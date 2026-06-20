"""Universe definition normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass

from ..markets.catalog import get_market_catalog
from ..markets.mic_aliases import mic_alias_registry
from .listing_tiers import listing_tier_registry


@dataclass(frozen=True, slots=True)
class NormalizedMarketScope:
    market: str
    mic: str | None = None
    listing_tier: str | None = None


@dataclass(frozen=True, slots=True)
class UniverseStorageProjection:
    label: str
    key: str
    type: str
    market: str | None = None
    exchange: str | None = None
    index: str | None = None
    symbols: list[str] | None = None


def parse_market_key_components(universe_key: str | None) -> dict[str, str]:
    if not isinstance(universe_key, str):
        return {}
    parts = [part.strip() for part in universe_key.split(":") if part.strip()]
    if len(parts) < 2 or parts[0].lower() != "market":
        return {}

    components: dict[str, str] = {"market": parts[1].upper()}
    for index in range(2, len(parts) - 1, 2):
        name = parts[index].lower()
        value = parts[index + 1]
        if name == "mic":
            components["mic"] = value.upper()
        elif name == "tier":
            components["tier"] = value
        elif name == "fresh":
            components["fresh"] = value.lower()
    return components


def normalize_market_scope(
    market: str,
    *,
    mic: str | None = None,
    exchange: str | None = None,
    listing_tier: str | None = None,
) -> NormalizedMarketScope:
    market_code = market.strip().upper()
    market_entry = get_market_catalog().get(market_code)
    normalized_mic = mic.strip().upper() if mic else None

    if normalized_mic is not None and normalized_mic not in market_entry.mics:
        supported = ", ".join(market_entry.mics)
        raise ValueError(
            f"Unsupported MIC {normalized_mic!r} for market {market_code}. "
            f"Supported: {supported}"
        )

    if exchange is not None:
        resolved = mic_alias_registry.resolve(market_code, exchange)
        if resolved is None:
            raise ValueError(
                f"Unsupported exchange alias {exchange!r} for market {market_code}"
            )
        if normalized_mic is not None and normalized_mic != resolved.mic:
            raise ValueError(
                f"MIC {normalized_mic!r} conflicts with exchange alias "
                f"{exchange!r} resolved MIC {resolved.mic!r}"
            )
        normalized_mic = resolved.mic

    normalized_tier = None
    if listing_tier is not None:
        normalized_tier = listing_tier_registry.normalize(
            market_code,
            listing_tier,
            mic=normalized_mic,
        )
        if normalized_tier is None:
            scope = f"{market_code}/{normalized_mic}" if normalized_mic else market_code
            raise ValueError(f"Unsupported listing_tier {listing_tier!r} for {scope}")

    return NormalizedMarketScope(
        market=market_code,
        mic=normalized_mic,
        listing_tier=normalized_tier,
    )


def validate_legacy_exchange_scope(
    exchange: str,
    *,
    market: str | None = None,
) -> None:
    if market is not None:
        market_code = market.strip().upper()
        if mic_alias_registry.resolve(market_code, exchange) is None:
            raise ValueError(
                f"Unsupported exchange alias {exchange!r} for market {market_code}"
            )
        return

    if mic_alias_registry.is_ambiguous(exchange):
        raise ValueError(f"Ambiguous exchange alias {exchange!r} requires market context")
    if mic_alias_registry.resolve_global(exchange) is None:
        raise ValueError(f"Unsupported exchange alias {exchange!r}")
