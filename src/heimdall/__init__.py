"""heimdall -- a host-agnostic data-provider SDK.

- `heimdall.providers`: the provider contract, registry and bundled providers
- `heimdall.schemas`  : shared `SchemaSpec` values (`OHLCV_BARS`, ...)
- `heimdall.errors`   : the exception hierarchy

Fetch by provider id:

    import heimdall

    result = heimdall.fetch("fred", "DGS10")  # str shorthand for FetchRequest
    result.schema.validate(result.frame)
    print(result.frame.head())

Write your own provider by subclassing `heimdall.Provider` and calling
`heimdall.register`; see CONTRIBUTING.md.  Third-party providers register
through the `heimdall.providers` entry-point group.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from importlib.metadata import version
from typing import Any

from heimdall import errors, schemas
from heimdall._config import load_dotenv_once
from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.catalog import catalog
from heimdall.providers import (
    PROVIDER_REGISTRY,
    Capabilities,
    Provider,
    ProviderMetadata,
    get_provider,
    list_providers,
    register,
    require_interval,
)

__version__ = version("heimdall-mimird")

# Only what a caller or a provider author actually touches. Schema types live in
# `heimdall.schemas`; `PROVIDER_REGISTRY` and `get_provider` stay importable
# but off the blessed surface.
__all__ = [
    "__version__",
    "fetch",
    "afetch",
    "utcnow",
    "FetchRequest",
    "FetchResult",
    "BatchResult",
    "Provider",
    "ProviderMetadata",
    "Capabilities",
    "require_interval",
    "catalog",
    "register",
    "list_providers",
    "errors",
    "schemas",
]

# Providers bundled with Heimdall. Each self-registers lazily (see
# `Provider.from_env`) via a module-level `_register_lazy(registry)` hook, but
# only if its optional dependency is installed.
_BUNDLED = ("fred", "sp500", "yfinance", "sec_form4")


def fetch(
    provider_id: str,
    request: FetchRequest | str | Sequence[str],
    /,
    **kwargs: Any,
) -> FetchResult | BatchResult:
    """Fetch from a registered provider.

    `request` may be a `FetchRequest`, or (the shorthand) a resource string
    with the rest as keyword arguments, or a list of resource strings to fetch
    as a batch:

        heimdall.fetch("yfinance", "AAPL", interval="1d")
        heimdall.fetch("yfinance", ["AAPL", "MSFT"], interval="1d")  # -> BatchResult
    """
    provider = get_provider(provider_id)
    if isinstance(request, FetchRequest):
        if kwargs:
            raise TypeError("pass keyword arguments only with the string shorthand")
        return provider._fetch(request)
    return provider.fetch(request, **kwargs)


async def afetch(
    provider_id: str,
    request: str | Sequence[str],
    /,
    **kwargs: Any,
) -> FetchResult | BatchResult:
    """Async mirror of `fetch` for a resource string or a list of them."""
    return await get_provider(provider_id).afetch(request, **kwargs)


def _load_bundled() -> None:
    for name in _BUNDLED:
        try:
            module = import_module(f"heimdall.providers.{name}")
        except ImportError as exc:
            # TODO: Think about this
            # Its extra isn't installed. Remember why, so a later
            # `heimdall.fetch(name, ...)` can say so instead of failing blank.
            PROVIDER_REGISTRY.mark_unavailable(name, str(exc))
            continue
        hook = getattr(module, "_register_lazy", None)
        if callable(hook):
            hook(PROVIDER_REGISTRY)


load_dotenv_once()
_load_bundled()
