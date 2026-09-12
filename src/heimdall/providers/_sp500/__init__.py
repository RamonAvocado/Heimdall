"""S&P 500 constituents provider."""

from __future__ import annotations

from .provider import SP500Provider

__all__ = ["SP500Provider", "_register"]


def _register(registry: object) -> None:
    """Hook called by :func:`heimdall._load_bundled` when the ``sp500`` extra is installed."""
    from heimdall._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if SP500Provider.id not in registry.list():
        registry.register(SP500Provider)
