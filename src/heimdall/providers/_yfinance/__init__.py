"""Yahoo Finance OHLCV provider."""

from __future__ import annotations

from .provider import YahooFinanceProvider

__all__ = ["YahooFinanceProvider", "_register"]


def _register(registry: object) -> None:
    """Hook called by :func:`heimdall._load_bundled` when the ``yfinance`` extra is installed."""
    from heimdall.registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if YahooFinanceProvider.id not in registry.list():
        registry.register(YahooFinanceProvider)
