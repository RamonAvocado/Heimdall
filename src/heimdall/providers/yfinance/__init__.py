"""Yahoo Finance OHLCV provider."""

from __future__ import annotations

from .provider import YahooFinanceProvider

__all__ = ["YahooFinanceProvider", "_register_lazy"]


def _register_lazy(registry: object) -> None:
    """Hook called by :func:`heimdall._load_bundled` when the ``yfinance``
    extra is installed. Resolves config (none required today) from the
    environment on first use, not at import time.
    """
    from heimdall._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if YahooFinanceProvider.id not in registry.list():
        registry.register_lazy(YahooFinanceProvider.id, YahooFinanceProvider.from_env)
