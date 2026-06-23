#!/usr/bin/env python3
"""Check and persist delivery state for OpenClaw market Auto digests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = ROOT_DIR / "data" / "openclaw"
DEFAULT_STATE_FILE = DEFAULT_STATE_DIR / "hk-auto-push-state.json"
DEFAULT_DELIVERY_CONFIG = ROOT_DIR / "data" / "openclaw" / "hk-auto-delivery.json"
SUPPORTED_STRATEGIES = (
    "minervini",
    "canslim",
    "ipo",
    "custom",
    "volume_breakthrough",
    "setup_engine",
)
HEADER_RE = re.compile(r"^.+?选股 Top \d+｜(?P<date>\d{4}-\d{2}-\d{2})$")
SCAN_ID_RE = re.compile(r"^Scan ID: (?P<scan_id>\S+)$")
EXPECTED_DATE_RE = re.compile(r"最新交易日应为 (?P<date>\d{4}-\d{2}-\d{2})")


def _normalize_market(market: str) -> str:
    value = str(market or "").strip().upper()
    if not value:
        raise RuntimeError("Market is required")
    if not re.fullmatch(r"[A-Z0-9]{1,8}", value):
        raise RuntimeError(f"Invalid market code: {market}")
    return value


def _default_state_file(market: str) -> Path:
    return DEFAULT_STATE_DIR / f"{market.lower()}-auto-push-state.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--market",
        default="HK",
        help="Market code for the Auto digest (default: HK).",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Delivery state JSON path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check whether a digest is ready.")
    check.add_argument(
        "--final",
        action="store_true",
        help="Return failed instead of waiting when the digest is unavailable.",
    )
    check.add_argument(
        "--strategy",
        choices=SUPPORTED_STRATEGIES,
        help="Only deliver stocks passing this Auto-scan strategy.",
    )

    mark = subparsers.add_parser("mark-sent", help="Record a successful delivery.")
    mark.add_argument("--as-of-date", required=True)
    mark.add_argument("--scan-id", required=True)

    deliver = subparsers.add_parser(
        "deliver", help="Safely send a prepared digest and record delivery."
    )
    deliver.add_argument("--as-of-date", required=True)
    deliver.add_argument("--scan-id", required=True)
    deliver.add_argument("--message-file", type=Path, required=True)
    deliver.add_argument("--channel")
    deliver.add_argument("--account")
    deliver.add_argument("--target")
    deliver.add_argument("--dry-run", action="store_true")

    subparsers.add_parser("status", help="Show the current delivery state.")
    return parser


def _read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read delivery state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Delivery state {path} must contain a JSON object")
    return value


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _delivery_settings(
    *, channel: str | None, account: str | None, target: str | None
) -> tuple[str, str, str]:
    if channel and account and target:
        return channel, account, target
    try:
        config = json.loads(DEFAULT_DELIVERY_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not read delivery config {DEFAULT_DELIVERY_CONFIG}: {exc}"
        ) from exc
    values = (
        channel or config.get("channel"),
        account or config.get("account"),
        target or config.get("target"),
    )
    if not all(isinstance(value, str) and value for value in values):
        raise RuntimeError("Delivery config requires channel, account, and target")
    return values


def _pending_message_path(state_file: Path, scan_id: str, market: str = "HK") -> Path:
    digest = hashlib.sha256(scan_id.encode("utf-8")).hexdigest()[:16]
    return state_file.parent / f"{market.lower()}-auto-pending-{digest}.txt"


def _write_private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)


def _run_digest(
    *, market: str, strategy: str | None = None
) -> subprocess.CompletedProcess[str]:
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "app.scripts.daily_scan_digest",
        "--market",
        market,
        "--top",
        "10",
    ]
    if strategy:
        command.extend(["--strategy", strategy])
    return subprocess.run(
        command,
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )


def _send_message(
    *,
    channel: str | None,
    account: str | None,
    target: str | None,
    message: str,
    idempotency_key: str,
    dry_run: bool,
) -> subprocess.CompletedProcess[str]:
    if dry_run:
        command = [
            "openclaw",
            "message",
            "send",
            "--channel",
            channel,
            "--account",
            account,
            "--target",
            target,
            "--message",
            message,
            "--json",
            "--dry-run",
        ]
    else:
        params = json.dumps(
            {
                "to": target,
                "message": message,
                "channel": channel,
                "accountId": account,
                "idempotencyKey": idempotency_key,
            },
            ensure_ascii=False,
        )
        command = [
            "openclaw",
            "gateway",
            "call",
            "send",
            "--params",
            params,
            "--json",
            "--timeout",
            "30000",
        ]
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _gateway_message_id(output: str) -> str | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    message_id = payload.get("messageId")
    if not message_id and isinstance(payload.get("payload"), dict):
        message_id = payload["payload"].get("messageId")
    return message_id if isinstance(message_id, str) and message_id else None


def _parse_digest(output: str) -> tuple[str, str]:
    as_of_date = None
    scan_id = None
    for line in output.splitlines():
        if as_of_date is None:
            match = HEADER_RE.match(line.strip())
            if match:
                as_of_date = match.group("date")
        if scan_id is None:
            match = SCAN_ID_RE.match(line.strip())
            if match:
                scan_id = match.group("scan_id")
    if not as_of_date or not scan_id:
        raise RuntimeError("Digest output did not contain an as-of date and Scan ID")
    return as_of_date, scan_id


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _check(
    *, market: str, state_file: Path, final: bool, strategy: str | None = None
) -> int:
    result = _run_digest(market=market, strategy=strategy)
    output = result.stdout.strip()
    if result.returncode != 0:
        expected_match = EXPECTED_DATE_RE.search(output)
        payload = {
            "status": "failed" if final else "waiting",
            "market": market,
            "expected_date": expected_match.group("date") if expected_match else None,
            "reason": output or result.stderr.strip() or f"digest exited {result.returncode}",
        }
        _emit(payload)
        return 0

    try:
        as_of_date, scan_id = _parse_digest(output)
        state = _read_state(state_file)
    except RuntimeError as exc:
        _emit(
            {
                "status": "failed" if final else "waiting",
                "market": market,
                "reason": str(exc),
            }
        )
        return 0

    last_sent = state.get("last_sent") or {}
    if last_sent.get("as_of_date") == as_of_date or last_sent.get("scan_id") == scan_id:
        _emit(
            {
                "status": "already_sent",
                "market": market,
                "as_of_date": as_of_date,
                "scan_id": scan_id,
            }
        )
        return 0

    message_file = _pending_message_path(state_file, scan_id, market)
    _write_private_text(message_file, output)
    _emit(
        {
            "status": "ready",
            "market": market,
            "as_of_date": as_of_date,
            "scan_id": scan_id,
            "message": output,
            "message_file": str(message_file),
        }
    )
    return 0


def _mark_sent(*, market: str, state_file: Path, as_of_date: str, scan_id: str) -> int:
    date.fromisoformat(as_of_date)
    state = _read_state(state_file)
    state["last_sent"] = {"as_of_date": as_of_date, "scan_id": scan_id}
    _write_state(state_file, state)
    _emit({"status": "marked_sent", "market": market, **state["last_sent"]})
    return 0


def _deliver(
    *,
    market: str,
    state_file: Path,
    as_of_date: str,
    scan_id: str,
    message_file: Path,
    channel: str,
    account: str,
    target: str,
    dry_run: bool,
) -> int:
    date.fromisoformat(as_of_date)
    channel, account, target = _delivery_settings(
        channel=channel, account=account, target=target
    )
    expected_file = _pending_message_path(state_file, scan_id, market).resolve()
    if message_file.resolve() != expected_file:
        raise RuntimeError(f"Message file must be {expected_file}")
    message = message_file.read_text(encoding="utf-8").strip()
    if not message:
        raise RuntimeError("Prepared message is empty")

    result = _send_message(
        channel=channel,
        account=account,
        target=target,
        message=message,
        idempotency_key=(
            f"stock-screener-{market.lower()}:{scan_id}:"
            f"{hashlib.sha256(message.encode('utf-8')).hexdigest()[:16]}"
        ),
        dry_run=dry_run,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or "OpenClaw send failed"
        )
    message_id = None if dry_run else _gateway_message_id(result.stdout)
    if not dry_run and not message_id:
        raise RuntimeError("OpenClaw gateway returned no delivery message ID")
    if not dry_run:
        state = _read_state(state_file)
        state["last_sent"] = {"as_of_date": as_of_date, "scan_id": scan_id}
        _write_state(state_file, state)
        message_file.unlink(missing_ok=True)
    _emit(
        {
            "status": "dry_run" if dry_run else "delivered",
            "market": market,
            "as_of_date": as_of_date,
            "scan_id": scan_id,
            **({"message_id": message_id} if message_id else {}),
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        market = _normalize_market(args.market)
        state_file = args.state_file or _default_state_file(market)
        if args.command == "check":
            return _check(
                market=market,
                state_file=state_file,
                final=args.final,
                strategy=args.strategy,
            )
        if args.command == "mark-sent":
            return _mark_sent(
                market=market,
                state_file=state_file,
                as_of_date=args.as_of_date,
                scan_id=args.scan_id,
            )
        if args.command == "deliver":
            return _deliver(
                market=market,
                state_file=state_file,
                as_of_date=args.as_of_date,
                scan_id=args.scan_id,
                message_file=args.message_file,
                channel=args.channel,
                account=args.account,
                target=args.target,
                dry_run=args.dry_run,
            )
        _emit({"status": "ok", "market": market, "state": _read_state(state_file)})
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        _emit({"status": "error", "reason": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
