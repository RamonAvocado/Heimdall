"""Current constituents of major world stock indexes: `nasdaq100`, `dow30`,
`ftse100`, `dax`, `cac40`, `nikkei225`, `hang_seng`."""

from __future__ import annotations

from .provider import (
    CAC40Provider,
    DAXProvider,
    Dow30Provider,
    FTSE100Provider,
    HangSengProvider,
    Nasdaq100Provider,
    Nikkei225Provider,
)

PROVIDERS = (
    Nasdaq100Provider,
    Dow30Provider,
    FTSE100Provider,
    DAXProvider,
    CAC40Provider,
    Nikkei225Provider,
    HangSengProvider,
)

__all__ = [
    "CAC40Provider",
    "DAXProvider",
    "Dow30Provider",
    "FTSE100Provider",
    "HangSengProvider",
    "Nasdaq100Provider",
    "Nikkei225Provider",
    "_register_lazy",
]


def _register_lazy(registry: object) -> None:
    """Hook called by `heimdall._load_bundled` when httpx is installed."""
    from heimdall.providers._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    for cls in PROVIDERS:
        if cls.id not in registry.list():
            registry.register_lazy(cls.id, cls.from_env)
