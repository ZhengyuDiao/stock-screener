"""CLI for rendering a market's latest automatic scan as an IM digest."""

from __future__ import annotations

import argparse
import io
from contextlib import redirect_stderr, redirect_stdout

from app.use_cases.scanning.build_auto_scan_digest import (
    AutoScanDigestStaleError,
    AutoScanDigestUnavailableError,
    build_auto_scan_digest,
    format_auto_scan_digest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render top stocks passing at least one strategy in the latest Auto scan.",
    )
    parser.add_argument("--market", default="HK", help="Market code (default: HK)")
    parser.add_argument("--top", type=int, default=10, help="Maximum rows (default: 10)")
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Render the latest historical scan even when it is not current.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    market = str(args.market).strip().upper()
    # Runtime bootstrap prints migration and screener registration chatter.
    # Keep stdout reserved for the IM-ready digest contract.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        from app.database import SessionLocal
        from app.infra.db.uow import SqlUnitOfWork
        from app.scripts._runtime import prepare_runtime
        from app.wiring.bootstrap import get_market_calendar_service

        prepare_runtime()
    expected_date = get_market_calendar_service().last_completed_trading_day(market)

    try:
        digest = build_auto_scan_digest(
            SqlUnitOfWork(SessionLocal),
            market=market,
            expected_date=expected_date,
            limit=args.top,
            allow_stale=args.allow_stale,
        )
    except AutoScanDigestStaleError as exc:
        print(
            "港股 Auto 选股暂不可用："
            f"最近结果日期为 {exc.actual_date.isoformat()}，"
            f"最新交易日应为 {exc.expected_date.isoformat()}。请先等待日度 pipeline 完成。"
        )
        return 2
    except AutoScanDigestUnavailableError as exc:
        print(f"港股 Auto 选股暂不可用：{exc}")
        return 2

    print(format_auto_scan_digest(digest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
