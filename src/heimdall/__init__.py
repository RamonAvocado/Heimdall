"""Heimdall: a host-agnostic data-provider SDK.
Quick start::

    import heimdall

    result = heimdall.fetch("fred", "DGS10")          # str shorthand for FetchRequest
    result.schema.validate(result.frame)
    print(result.frame.head())

Write your own provider by subclassing :class:`heimdall.Provider` and calling
:func:`heimdall.register`. See ``docs/writing-a-provider.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from typing import Any

from heimdall import errors, schemas
from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall._provider import Capabilities, Provider, require_interval
from heimdall._registry import get_provider, list_providers, register, registry
from heimdall._time import utcnow

__version__ = "0.5.0"

# Only what a caller or a provider author actually touches. Schema types live in
# ``heimdall.schemas``; the registry object and ``get_provider`` stay importable
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
    "Capabilities",
    "require_interval",
    "register",
    "list_providers",
    "errors",
    "schemas",
]

# Providers bundled with Heimdall. Each self-registers via a module-level
# ``_register(registry)`` hook, but only if its optional dependency is installed.
_BUNDLED = ("fred", "sp500", "yfinance")


def fetch(
    provider_id: str,
    request: FetchRequest | str | Sequence[str],
    /,
    **kwargs: Any,
) -> FetchResult | BatchResult:
    """Fetch from a registered provider.

    ``request`` may be a :class:`FetchRequest`, or - the shorthand - a resource
    string (with the rest as keyword arguments), or a list of resource strings
    to fetch as a batch::

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
    """Async mirror of :func:`fetch` for a resource string or a list of them."""
    return await get_provider(provider_id).afetch(request, **kwargs)


def _load_bundled() -> None:
    for name in _BUNDLED:
        try:
            module = import_module(f"heimdall.providers._{name}")
        except ImportError as exc:
            # TODO: Think about this
            # Its extra isn't installed. Remember why, so a later
            # ``heimdall.fetch(name, ...)`` can say so instead of failing blank.
            registry.mark_unavailable(name, str(exc))
            continue
        hook = getattr(module, "_register", None)
        if callable(hook):
            hook(registry)


_load_bundled()
