from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[4] / "scripts" / "openclaw_hk_auto_push.py"
SPEC = importlib.util.spec_from_file_location("openclaw_hk_auto_push", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


DIGEST = """港股 Auto 选股 Top 10｜2026-06-18
扫描 2,763 只｜至少一项策略通过共 63 只

1. 0700.HK Tencent Holdings
   综合 80.0｜Pass｜策略 2/6｜RS 90.0｜Stage 2｜价格 600.00 HKD

Scan ID: scan-hk-0618
仅供研究，不构成投资建议。"""


def _payload(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_check_reports_ready(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        MODULE,
        "_run_digest",
        lambda *, market, strategy=None: SimpleNamespace(
            returncode=0, stdout=DIGEST, stderr=""
        ),
    )

    assert MODULE.main(["--state-file", str(tmp_path / "state.json"), "check"]) == 0

    payload = _payload(capsys)
    assert payload["status"] == "ready"
    assert payload["as_of_date"] == "2026-06-18"
    assert payload["scan_id"] == "scan-hk-0618"
    assert payload["message"] == DIGEST
    assert Path(payload["message_file"]).read_text(encoding="utf-8").strip() == DIGEST


def test_mark_sent_makes_followup_check_idempotent(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(
        MODULE,
        "_run_digest",
        lambda *, market, strategy=None: SimpleNamespace(
            returncode=0, stdout=DIGEST, stderr=""
        ),
    )

    assert MODULE.main(
        [
            "--state-file",
            str(state_file),
            "mark-sent",
            "--as-of-date",
            "2026-06-18",
            "--scan-id",
            "scan-hk-0618",
        ]
    ) == 0
    _payload(capsys)
    assert MODULE.main(["--state-file", str(state_file), "check"]) == 0

    assert _payload(capsys)["status"] == "already_sent"


def test_unavailable_digest_waits_until_final_check(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        MODULE,
        "_run_digest",
        lambda *, market, strategy=None: SimpleNamespace(
            returncode=2,
            stdout=(
                "港股 Auto 选股暂不可用：最近结果日期为 2026-06-17，"
                "最新交易日应为 2026-06-18。请先等待日度 pipeline 完成。"
            ),
            stderr="",
        ),
    )
    base = ["--state-file", str(tmp_path / "state.json"), "check"]

    assert MODULE.main(base) == 0
    assert _payload(capsys)["status"] == "waiting"
    assert MODULE.main([*base, "--final"]) == 0
    payload = _payload(capsys)
    assert payload["status"] == "failed"
    assert payload["expected_date"] == "2026-06-18"


def test_check_forwards_requested_strategy(monkeypatch, tmp_path, capsys):
    requested = []

    def fake_digest(*, market, strategy=None):
        requested.append((market, strategy))
        return SimpleNamespace(returncode=0, stdout=DIGEST, stderr="")

    monkeypatch.setattr(MODULE, "_run_digest", fake_digest)

    assert MODULE.main(
        [
            "--state-file",
            str(tmp_path / "state.json"),
            "check",
            "--strategy",
            "volume_breakthrough",
        ]
    ) == 0

    assert _payload(capsys)["status"] == "ready"
    assert requested == [("HK", "volume_breakthrough")]


def test_market_option_uses_separate_state_and_digest(monkeypatch, tmp_path, capsys):
    us_digest = DIGEST.replace("港股", "美股").replace("scan-hk-0618", "scan-us-0618")
    requested = []

    def fake_digest(*, market, strategy=None):
        requested.append((market, strategy))
        return SimpleNamespace(returncode=0, stdout=us_digest, stderr="")

    monkeypatch.setattr(MODULE, "_run_digest", fake_digest)
    monkeypatch.setattr(MODULE, "DEFAULT_STATE_DIR", tmp_path)

    assert MODULE.main(["--market", "US", "check"]) == 0

    payload = _payload(capsys)
    assert payload["status"] == "ready"
    assert payload["market"] == "US"
    assert payload["scan_id"] == "scan-us-0618"
    digest_hash = MODULE.hashlib.sha256("scan-us-0618".encode("utf-8")).hexdigest()[:16]
    assert payload["message_file"].endswith(f"/us-auto-pending-{digest_hash}.txt")
    assert requested == [("US", None)]


def test_deliver_sends_file_and_records_success(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "state.json"
    delivery_config = tmp_path / "delivery.json"
    delivery_config.write_text(
        json.dumps(
            {
                "channel": "openclaw-weixin",
                "account": "account-1",
                "target": "user@im.wechat",
            }
        )
    )
    monkeypatch.setattr(MODULE, "DEFAULT_DELIVERY_CONFIG", delivery_config)
    message_file = MODULE._pending_message_path(state_file, "scan-hk-0618")
    MODULE._write_private_text(message_file, DIGEST)
    sent = {}

    def fake_send(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"messageId": "weixin-message-1"}),
            stderr="",
        )

    monkeypatch.setattr(MODULE, "_send_message", fake_send)
    assert MODULE.main(
        [
            "--state-file",
            str(state_file),
            "deliver",
            "--as-of-date",
            "2026-06-18",
            "--scan-id",
            "scan-hk-0618",
            "--message-file",
            str(message_file),
        ]
    ) == 0

    payload = _payload(capsys)
    assert payload["status"] == "delivered"
    assert payload["message_id"] == "weixin-message-1"
    assert sent["message"] == DIGEST
    assert sent["channel"] == "openclaw-weixin"
    assert sent["account"] == "account-1"
    assert sent["target"] == "user@im.wechat"
    digest_hash = MODULE.hashlib.sha256(DIGEST.encode("utf-8")).hexdigest()[:16]
    assert sent["idempotency_key"] == f"stock-screener-hk:scan-hk-0618:{digest_hash}"
    assert sent["dry_run"] is False
    assert json.loads(state_file.read_text())["last_sent"]["scan_id"] == "scan-hk-0618"
    assert not message_file.exists()


def test_deliver_does_not_record_success_without_gateway_receipt(
    monkeypatch, tmp_path, capsys
):
    state_file = tmp_path / "state.json"
    delivery_config = tmp_path / "delivery.json"
    delivery_config.write_text(
        json.dumps(
            {
                "channel": "openclaw-weixin",
                "account": "account-1",
                "target": "user@im.wechat",
            }
        )
    )
    monkeypatch.setattr(MODULE, "DEFAULT_DELIVERY_CONFIG", delivery_config)
    message_file = MODULE._pending_message_path(state_file, "scan-hk-0618")
    MODULE._write_private_text(message_file, DIGEST)
    monkeypatch.setattr(
        MODULE,
        "_send_message",
        lambda **kwargs: SimpleNamespace(returncode=0, stdout="{}", stderr=""),
    )

    result = MODULE.main(
        [
            "--state-file",
            str(state_file),
            "deliver",
            "--as-of-date",
            "2026-06-18",
            "--scan-id",
            "scan-hk-0618",
            "--message-file",
            str(message_file),
        ]
    )

    assert result == 1
    assert _payload(capsys)["status"] == "error"
    assert not state_file.exists()
    assert message_file.exists()
