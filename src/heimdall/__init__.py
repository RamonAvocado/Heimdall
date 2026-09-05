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

import os
from collections.abc import Mapping
from importlib import import_module
from typing import Any

from heimdall import errors, schemas
from heimdall._time import utcnow
from heimdall.contracts import ColumnSpec, FetchRequest, FetchResult, SchemaSpec
from heimdall._provider import Capabilities, Provider, require_interval
from heimdall.registry import (
    ProviderRegistry,
    get_provider,
    list_providers,
    register,
    registry,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "fetch",
    "config_from_env",
    "utcnow",
    "FetchRequest",
    "FetchResult",
    "SchemaSpec",
    "ColumnSpec",
    "Provider",
    "Capabilities",
    "require_interval",
    "ProviderRegistry",
    "registry",
    "register",
    "get_provider",
    "list_providers",
    "errors",
    "schemas",
]

# Providers bundled with Heimdall. Each self-registers via a module-level
# ``_register(registry)`` hook, but only if its optional dependency is installed.
_BUNDLED = ("fred", "sp500", "yfinance")


def config_from_env(prefix: str, *, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Collect env vars starting with ``prefix`` into a config mapping.

    ``config_from_env("HEIMDALL_FRED_")`` with ``HEIMDALL_FRED_API_KEY=x`` set
    returns ``{"api_key": "x"}``. Providers never read the environment
    themselves; the caller builds config and passes it to
    :func:`register`.
    """
    src = os.environ if environ is None else environ
    return {
        key[len(prefix) :].lower(): value
        for key, value in src.items()
        if key.startswith(prefix) and len(key) > len(prefix)
    }


def fetch(provider_id: str, request: FetchRequest | str, /, **kwargs: Any) -> FetchResult:
    """Fetch from a registered provider.

    ``request`` may be a :class:`FetchRequest` or, as a shorthand, the resource
    string with the rest passed as keyword arguments::

        heimdall.fetch("yfinance", "AAPL", interval="1d")
    """
    if isinstance(request, str):
        request = FetchRequest(resource=request, **kwargs)
    elif kwargs:
        raise TypeError("pass keyword arguments only with the string shorthand")
    return get_provider(provider_id)._fetch(request)


def _load_bundled() -> None:
    for name in _BUNDLED:
        try:
            module = import_module(f"heimdall.providers._{name}")
        except ImportError:
            continue
        hook = getattr(module, "_register", None)
        if callable(hook):
            hook(registry)


_load_bundled()
