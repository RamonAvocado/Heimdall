"""S&P 500 constituents provider."""

from __future__ import annotations

from .provider import SP500Provider

__all__ = ["SP500Provider", "_register_lazy"]


def _register_lazy(registry: object) -> None:
    """Hook called by :func:`heimdall._load_bundled` when the ``sp500`` extra
    is installed. Resolves config (none required today) from the environment
    on first use, not at import time.
    """
    from heimdall._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if SP500Provider.id not in registry.list():
        registry.register_lazy(SP500Provider.id, SP500Provider.from_env)
