"""FRED (Federal Reserve Economic Data) provider."""

from __future__ import annotations

from heimdall.providers.fred.provider import FredProvider

__all__ = ["FredProvider", "_register"]


def _register(registry: object) -> None:
    """Hook called by :func:`heimdall._load_bundled` when the ``fred`` extra is installed."""
    from heimdall.registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if FredProvider.id not in registry.list():
        registry.register(FredProvider)
