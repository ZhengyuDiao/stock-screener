from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.domain.scanning.models import ResultPage, ScanResultItemDomain
from app.use_cases.scanning.build_auto_scan_digest import (
    AutoScanDigestStaleError,
    AutoScanDigestUnavailableError,
    build_auto_scan_digest,
    format_auto_scan_digest,
)


class FakeUow:
    def __init__(self, *, scans, feature_run, page, feature_runs=None):
        self.scans = SimpleNamespace(list_recent=lambda **_kwargs: scans)
        self.feature_runs = SimpleNamespace(
            get_run=lambda run_id: (feature_runs or {}).get(run_id, feature_run)
        )
        self.query_calls = []

        def query_run(run_id, query_spec, **kwargs):
            self.query_calls.append((run_id, query_spec, kwargs))
            return page

        self.feature_store = SimpleNamespace(query_run_as_scan_results=query_run)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _scan(**overrides):
    fields = {
        "scan_id": "scan-hk-auto",
        "status": "completed",
        "trigger_source": "auto",
        "feature_run_id": 42,
        "total_stocks": 2777,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _item(symbol="0700.HK", **extended):
    return ScanResultItemDomain(
        symbol=symbol,
        composite_score=86.4,
        rating="Strong Buy",
        current_price=420.5,
        screener_outputs={},
        screeners_run=["minervini", "canslim"],
        composite_method="weighted_average",
        screeners_passed=2,
        screeners_total=2,
        extended_fields={
            "company_name": "Tencent Holdings",
            "currency": "HKD",
            "rs_rating": 91.0,
            "stage": 2,
            "minervini_score": 94.0,
            **extended,
        },
    )


def test_builds_top_buy_digest_from_latest_completed_auto_scan():
    expected = date(2026, 6, 19)
    page = ResultPage(items=(_item(),), total=8, page=1, per_page=10)
    uow = FakeUow(
        scans=[_scan(), _scan(scan_id="manual", trigger_source="manual")],
        feature_run=SimpleNamespace(as_of_date=expected),
        page=page,
    )

    digest = build_auto_scan_digest(
        uow,
        market="hk",
        expected_date=expected,
        limit=10,
    )

    assert digest.market == "HK"
    assert digest.total_scanned == 2777
    assert digest.total_matches == 8
    assert digest.items[0].symbol == "0700.HK"
    assert digest.items[0].screeners_passed == 2
    run_id, query_spec, kwargs = uow.query_calls[0]
    assert run_id == 42
    assert query_spec.filters.range_filters[0].field == "passes_count"
    assert query_spec.filters.range_filters[0].min_value == 1
    assert query_spec.sort.field == "composite_score"
    assert query_spec.page.per_page == 10
    assert kwargs == {"include_sparklines": False, "include_setup_payload": False}


def test_rejects_stale_auto_scan_by_default():
    uow = FakeUow(
        scans=[_scan()],
        feature_run=SimpleNamespace(as_of_date=date(2026, 6, 16)),
        page=ResultPage(items=(), total=0, page=1, per_page=10),
    )

    with pytest.raises(AutoScanDigestStaleError) as exc_info:
        build_auto_scan_digest(
            uow,
            market="HK",
            expected_date=date(2026, 6, 19),
        )

    assert exc_info.value.actual_date == date(2026, 6, 16)
    assert uow.query_calls == []


def test_filters_and_ranks_by_requested_strategy():
    expected = date(2026, 6, 19)
    page = ResultPage(items=(_item(),), total=4, page=1, per_page=10)
    uow = FakeUow(
        scans=[_scan()],
        feature_run=SimpleNamespace(as_of_date=expected),
        page=page,
    )

    digest = build_auto_scan_digest(
        uow,
        market="HK",
        expected_date=expected,
        strategy="minervini",
    )

    _, query_spec, _ = uow.query_calls[0]
    assert digest.strategy == "minervini"
    assert digest.total_matches == 4
    assert digest.items[0].strategy_score == 94.0
    assert query_spec.filters.boolean_filters[0].field == "minervini_passes"
    assert query_spec.filters.boolean_filters[0].value is True
    assert query_spec.sort.field == "minervini_score"
    rendered = format_auto_scan_digest(digest)
    assert "港股 Minervini 选股 Top 10" in rendered
    assert "通过 Minervini 共 4 只" in rendered
    assert "Minervini 94.0｜综合 86.4" in rendered


def test_rejects_unknown_strategy():
    uow = FakeUow(
        scans=[_scan()],
        feature_run=SimpleNamespace(as_of_date=date(2026, 6, 19)),
        page=ResultPage(items=(), total=0, page=1, per_page=10),
    )

    with pytest.raises(ValueError, match="Unsupported strategy"):
        build_auto_scan_digest(
            uow,
            market="HK",
            expected_date=date(2026, 6, 19),
            strategy="unknown",
        )


def test_selects_newest_market_date_when_older_backfill_was_published_last():
    newest_date = date(2026, 6, 17)
    uow = FakeUow(
        scans=[_scan(feature_run_id=22), _scan(feature_run_id=20)],
        feature_run=None,
        feature_runs={
            22: SimpleNamespace(as_of_date=date(2026, 6, 15)),
            20: SimpleNamespace(as_of_date=newest_date),
        },
        page=ResultPage(items=(_item(),), total=1, page=1, per_page=10),
    )

    digest = build_auto_scan_digest(
        uow,
        market="HK",
        expected_date=newest_date,
    )

    assert digest.as_of_date == newest_date
    assert uow.query_calls[0][0] == 20


def test_allows_stale_scan_for_explicit_manual_inspection():
    uow = FakeUow(
        scans=[_scan()],
        feature_run=SimpleNamespace(as_of_date=date(2026, 6, 16)),
        page=ResultPage(items=(_item(),), total=1, page=1, per_page=10),
    )

    digest = build_auto_scan_digest(
        uow,
        market="HK",
        expected_date=date(2026, 6, 19),
        allow_stale=True,
    )

    assert digest.is_stale is True
    assert "最近一次历史结果" in format_auto_scan_digest(digest)
    assert "策略 2/2" in format_auto_scan_digest(digest)


def test_reports_when_no_completed_auto_scan_exists():
    uow = FakeUow(
        scans=[_scan(trigger_source="manual")],
        feature_run=None,
        page=ResultPage(items=(), total=0, page=1, per_page=10),
    )

    with pytest.raises(AutoScanDigestUnavailableError, match="No completed Auto scan"):
        build_auto_scan_digest(
            uow,
            market="HK",
            expected_date=date(2026, 6, 19),
        )


def test_formats_zero_match_digest_without_fabricating_rows():
    uow = FakeUow(
        scans=[_scan()],
        feature_run=SimpleNamespace(as_of_date=date(2026, 6, 19)),
        page=ResultPage(items=(), total=0, page=1, per_page=10),
    )
    digest = build_auto_scan_digest(
        uow,
        market="HK",
        expected_date=date(2026, 6, 19),
    )

    rendered = format_auto_scan_digest(digest)

    assert "Top 10" in rendered
    assert "没有任何股票通过底层扫描策略" in rendered
    assert "Scan ID: scan-hk-auto" in rendered
