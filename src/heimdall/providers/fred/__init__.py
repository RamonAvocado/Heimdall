"""FRED (Federal Reserve Economic Data) provider."""

from __future__ import annotations

from .provider import FredProvider

__all__ = ["FredProvider", "_register_lazy"]


def _register_lazy(registry: object) -> None:
    """Hook called by :func:`heimdall._load_bundled` when the ``fred`` extra is
    installed. Resolves config (none required today) from the environment on
    first use, not at import time.
    """
    from heimdall._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if FredProvider.id not in registry.list():
        registry.register_lazy(FredProvider.id, FredProvider.from_env)
