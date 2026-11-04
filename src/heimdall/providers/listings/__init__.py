"""Instrument listings: `us_listings` (all US-listed securities), `coingecko`
(top crypto by market cap), `treasuries` (outstanding US Treasuries)."""

from __future__ import annotations

from .provider import (
    CoinGeckoProvider,
    TreasuriesProvider,
    USListingsProvider,
    isin_from_cusip,
)

PROVIDERS = (USListingsProvider, CoinGeckoProvider, TreasuriesProvider)

__all__ = [
    "CoinGeckoProvider",
    "TreasuriesProvider",
    "USListingsProvider",
    "_register_lazy",
    "isin_from_cusip",
]


def _register_lazy(registry: object) -> None:
    """Hook called by `heimdall._load_bundled` when httpx is installed."""
    from heimdall.providers._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    for cls in PROVIDERS:
        if cls.id not in registry.list():
            registry.register_lazy(cls.id, cls.from_env)
