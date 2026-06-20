"""
Universe resolver — centralized symbol resolution for scan universes.

Replaces inline symbol resolution in create_scan() with a single service
that maps UniverseDefinition → list of stock symbols. Used by the API,
Celery tasks, and any future scan triggers.
"""
import logging
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from ..schemas.universe import UniverseDefinition, UniverseType
from ..services.price_history_coverage import classify_price_history
from ..wiring.bootstrap import get_market_calendar_service, get_stock_universe_service
from ..services.universe_compat_adapter import resolve_scan_universe_request

logger = logging.getLogger(__name__)


def normalize_universe_definition(universe_def: Any) -> UniverseDefinition:
    """Coerce legacy or serialized universe payloads to UniverseDefinition."""
    if isinstance(universe_def, UniverseDefinition):
        return universe_def

    if isinstance(universe_def, str):
        legacy = universe_def.strip()
        if legacy.lower() == "active":
            return UniverseDefinition(type=UniverseType.ALL)
        return resolve_scan_universe_request(
            universe_def=None,
            legacy_universe=legacy,
            legacy_symbols=None,
        ).universe_def

    if isinstance(universe_def, dict):
        if "type" in universe_def:
            return UniverseDefinition.model_validate(universe_def)

        for key in ("name", "universe", "value"):
            legacy = universe_def.get(key)
            if isinstance(legacy, str):
                symbols = universe_def.get("symbols")
                symbols_list = symbols if isinstance(symbols, list) else None
                return resolve_scan_universe_request(
                    universe_def=None,
                    legacy_universe=legacy,
                    legacy_symbols=symbols_list,
                ).universe_def

        raise ValueError(
            "Unsupported universe definition dict; expected {'type': ...} "
            "or a legacy name field like {'name': 'active'}"
        )

    raise ValueError(
        f"Unsupported universe definition type: {type(universe_def).__name__}"
    )


def resolve_symbols(
    db: Session,
    universe_def: Any,
    limit: Optional[int] = None,
) -> List[str]:
    """
    Resolve a UniverseDefinition to a list of stock symbols.

    Args:
        db: Database session
        universe_def: Typed or normalized universe definition
        limit: Optional max number of symbols to return

    Returns:
        List of uppercase stock symbol strings
    """
    universe_def = normalize_universe_definition(universe_def)
    t = universe_def.type

    if t == UniverseType.ALL:
        return get_stock_universe_service().get_active_symbols(
            db, market=None, exchange=None, sp500_only=False, limit=limit
        )

    elif t == UniverseType.MARKET:
        service_limit = None if universe_def.fresh_only else limit
        kwargs = {
            "market": universe_def.market.value,
            "exchange": universe_def.mic,
            "sp500_only": False,
            "limit": service_limit,
        }
        if universe_def.listing_tier is not None:
            kwargs["listing_tier"] = universe_def.listing_tier
        symbols = get_stock_universe_service().get_active_symbols(db, **kwargs)
        if not universe_def.fresh_only:
            return symbols

        market = universe_def.market.value
        expected_date = get_market_calendar_service().last_completed_trading_day(market)
        coverage = classify_price_history(
            db,
            symbols=symbols,
            as_of_date=expected_date,
        )
        fresh_symbols = list(coverage.fresh)
        logger.info(
            "Fresh-only universe resolved %d/%d symbols for market=%s as_of=%s",
            len(fresh_symbols),
            len(symbols),
            market,
            expected_date,
        )
        return fresh_symbols[:limit] if limit is not None else fresh_symbols

    elif t == UniverseType.EXCHANGE:
        return get_stock_universe_service().get_active_symbols(
            db,
            market=universe_def.market.value if universe_def.market else None,
            exchange=universe_def.exchange.value,
            sp500_only=False,
            limit=limit,
        )

    elif t == UniverseType.INDEX:
        # Dispatch by the requested index name. SP500 keeps using the
        # legacy ``is_sp500`` column; HSI/NIKKEI225/TAIEX resolve via
        # ``stock_universe_index_membership``.
        return get_stock_universe_service().get_active_symbols(
            db,
            market=None,
            exchange=None,
            index_name=universe_def.index.value,
            limit=limit,
        )

    elif t in (UniverseType.CUSTOM, UniverseType.TEST):
        symbols = universe_def.symbols
        if not universe_def.allow_inactive_symbols:
            stock_universe_service = get_stock_universe_service()
            filtered = stock_universe_service.filter_active_symbols(db, symbols)
            filtered_set = set(filtered)
            dropped = [symbol for symbol in symbols if symbol not in filtered_set]
            if dropped:
                logger.warning(
                    "Dropped %d inactive or unknown symbols from %s universe: %s",
                    len(dropped),
                    t.value,
                    ", ".join(dropped[:10]),
                )
            symbols = filtered
        if limit is not None:
            return symbols[:limit]
        return symbols

    else:
        raise ValueError(f"Unknown universe type: {t}")


def resolve_count(
    db: Session,
    universe_def: Any,
) -> int:
    """
    Get the count of symbols in a universe without fetching the full list.

    For CUSTOM/TEST, this is cheap (len of symbols list).
    For ALL/EXCHANGE/INDEX, this queries the DB.

    Args:
        db: Database session
        universe_def: Typed or normalized universe definition

    Returns:
        Number of symbols in the universe
    """
    universe_def = normalize_universe_definition(universe_def)
    if universe_def.type in (UniverseType.CUSTOM, UniverseType.TEST):
        return len(resolve_symbols(db, universe_def))
    return len(resolve_symbols(db, universe_def))
