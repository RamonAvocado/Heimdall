"""Provider contract and registry.

Typical use goes through the top-level helpers:

    import heimdall

    result = heimdall.fetch("fred", "DGS10")

Import a bundled provider by its own package when you need the class itself:

    from heimdall.providers.fred import FredProvider

    result = FredProvider(timeout=10).fetch("DGS10")

The bundled providers are not re-exported here: each needs its own optional
extra, and importing them all would pull in every one.
"""

from __future__ import annotations

from heimdall.providers._base import (
    Capabilities,
    Provider,
    ProviderMetadata,
    require_interval,
)
from heimdall.providers._registry import (
    PROVIDER_ENTRY_POINT_GROUP,
    PROVIDER_REGISTRY,
    ProviderRegistry,
    get_provider,
    list_providers,
    register,
)

__all__ = [
    "PROVIDER_ENTRY_POINT_GROUP",
    "PROVIDER_REGISTRY",
    "Capabilities",
    "Provider",
    "ProviderMetadata",
    "ProviderRegistry",
    "get_provider",
    "list_providers",
    "register",
    "require_interval",
]
