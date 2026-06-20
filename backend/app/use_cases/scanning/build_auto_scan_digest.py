"""Build a compact digest from the latest completed automatic market scan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.domain.common.query import (
    FilterSpec,
    PageSpec,
    QuerySpec,
    SortOrder,
    SortSpec,
)
from app.domain.common.uow import UnitOfWork


class AutoScanDigestUnavailableError(RuntimeError):
    """Raised when no completed automatic scan can produce a digest."""


class AutoScanDigestStaleError(AutoScanDigestUnavailableError):
    """Raised when the latest automatic scan is not for the expected session."""

    def __init__(self, *, market: str, actual_date: date, expected_date: date) -> None:
        self.market = market
        self.actual_date = actual_date
        self.expected_date = expected_date
        super().__init__(
            f"{market} latest Auto scan is dated {actual_date.isoformat()}, "
            f"expected {expected_date.isoformat()}."
        )


@dataclass(frozen=True)
class AutoScanDigestItem:
    symbol: str
    company_name: str | None
    composite_score: float | None
    rating: str
    current_price: float | None
    currency: str | None
    rs_rating: float | None
    stage: int | None
    screeners_passed: int
    screeners_total: int


@dataclass(frozen=True)
class AutoScanDigest:
    market: str
    scan_id: str
    as_of_date: date
    expected_date: date
    total_scanned: int
    total_matches: int
    requested_limit: int
    items: tuple[AutoScanDigestItem, ...]

    @property
    def is_stale(self) -> bool:
        return self.as_of_date != self.expected_date


def build_auto_scan_digest(
    uow: UnitOfWork,
    *,
    market: str,
    expected_date: date,
    limit: int = 10,
    allow_stale: bool = False,
) -> AutoScanDigest:
    """Return top-ranked stocks that passed at least one Auto-scan strategy."""
    market_code = str(market).strip().upper()
    if not market_code:
        raise ValueError("market is required")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    with uow:
        scans = [
            candidate
            for candidate in uow.scans.list_recent(limit=100, market=market_code)
            if candidate.status == "completed"
            and candidate.trigger_source == "auto"
            and candidate.feature_run_id is not None
        ]
        if not scans:
            raise AutoScanDigestUnavailableError(
                f"No completed Auto scan is available for {market_code}."
            )

        scans_with_runs = [
            (candidate, uow.feature_runs.get_run(candidate.feature_run_id))
            for candidate in scans
        ]
        scans_with_runs = [pair for pair in scans_with_runs if pair[1] is not None]
        if not scans_with_runs:
            raise AutoScanDigestUnavailableError(
                f"No feature run is available for completed Auto scans in {market_code}."
            )
        scan, feature_run = max(
            scans_with_runs,
            key=lambda pair: pair[1].as_of_date,
        )

        as_of_date = feature_run.as_of_date
        if as_of_date != expected_date and not allow_stale:
            raise AutoScanDigestStaleError(
                market=market_code,
                actual_date=as_of_date,
                expected_date=expected_date,
            )

        filters = FilterSpec().add_range("passes_count", min_value=1)
        page = uow.feature_store.query_run_as_scan_results(
            scan.feature_run_id,
            QuerySpec(
                filters=filters,
                sort=SortSpec(field="composite_score", order=SortOrder.DESC),
                page=PageSpec(page=1, per_page=limit),
            ),
            include_sparklines=False,
            include_setup_payload=False,
        )

        items = tuple(
            AutoScanDigestItem(
                symbol=str(item.symbol),
                company_name=item.extended_fields.get("company_name"),
                composite_score=item.composite_score,
                rating=item.rating,
                current_price=item.current_price,
                currency=item.extended_fields.get("currency"),
                rs_rating=item.extended_fields.get("rs_rating"),
                stage=item.extended_fields.get("stage"),
                screeners_passed=item.screeners_passed,
                screeners_total=item.screeners_total,
            )
            for item in page.items
        )

        return AutoScanDigest(
            market=market_code,
            scan_id=scan.scan_id,
            as_of_date=as_of_date,
            expected_date=expected_date,
            total_scanned=int(scan.total_stocks or 0),
            total_matches=page.total,
            requested_limit=limit,
            items=items,
        )


def _format_decimal(value: float | None, *, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def format_auto_scan_digest(digest: AutoScanDigest) -> str:
    """Render a concise Chinese digest suitable for an IM message."""
    market_labels = {"HK": "港股"}
    market_label = market_labels.get(digest.market, digest.market)
    lines = [
        f"{market_label} Auto 选股 Top {digest.requested_limit}｜{digest.as_of_date.isoformat()}"
    ]
    if digest.is_stale:
        lines.append(
            f"注意：这是最近一次历史结果，最新交易日应为 {digest.expected_date.isoformat()}。"
        )
    lines.extend(
        [
            f"扫描 {digest.total_scanned:,} 只｜至少一项策略通过共 {digest.total_matches} 只",
            "",
        ]
    )

    if not digest.items:
        lines.append("本次没有任何股票通过底层扫描策略。")
    else:
        for index, item in enumerate(digest.items, start=1):
            name = f" {item.company_name}" if item.company_name else ""
            price = _format_decimal(item.current_price, digits=2)
            currency = f" {item.currency}" if item.currency else ""
            lines.extend(
                [
                    f"{index}. {item.symbol}{name}",
                    "   "
                    f"综合 {_format_decimal(item.composite_score)}｜{item.rating}"
                    f"｜策略 {item.screeners_passed}/{item.screeners_total}"
                    f"｜RS {_format_decimal(item.rs_rating)}｜Stage {item.stage or '-'}"
                    f"｜价格 {price}{currency}",
                ]
            )

    lines.extend(
        [
            "",
            f"Scan ID: {digest.scan_id}",
            "仅供研究，不构成投资建议。",
        ]
    )
    return "\n".join(lines)
