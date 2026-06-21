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
        lambda strategy=None: SimpleNamespace(returncode=0, stdout=DIGEST, stderr=""),
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
        lambda strategy=None: SimpleNamespace(returncode=0, stdout=DIGEST, stderr=""),
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
        lambda strategy=None: SimpleNamespace(
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

    def fake_digest(strategy=None):
        requested.append(strategy)
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
    assert requested == ["volume_breakthrough"]


def test_deliver_sends_file_and_records_success(monkeypatch, tmp_path, capsys):
    state_file = tmp_path / "state.json"
    message_file = MODULE._pending_message_path(state_file, "scan-hk-0618")
    MODULE._write_private_text(message_file, DIGEST)
    sent = {}

    def fake_send(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

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
            "--channel",
            "openclaw-weixin",
            "--account",
            "account-1",
            "--target",
            "user@im.wechat",
        ]
    ) == 0

    assert _payload(capsys)["status"] == "delivered"
    assert sent["message"] == DIGEST
    assert sent["dry_run"] is False
    assert json.loads(state_file.read_text())["last_sent"]["scan_id"] == "scan-hk-0618"
    assert not message_file.exists()
