"""Provider registration and lookup.

The M1 path is explicit registration: ``heimdall.register(MyProvider)``.
:meth:`ProviderRegistry.load_entry_points` is implemented so that
``pip install``-and-go community packages become possible later, but nothing
calls it automatically yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import entry_points
from typing import Any

from heimdall._logging import get_logger
from heimdall.errors import ProviderError, ProviderNotFound
from heimdall._provider import Provider

__all__ = ["ProviderRegistry", "registry", "register", "get_provider", "list_providers"]

_log = get_logger("registry")

ENTRY_POINT_GROUP = "heimdall.providers"


class ProviderRegistry:
    """A mapping of provider id -> :class:`~heimdall.provider.Provider` instance."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(
        self,
        provider: Provider | type[Provider],
        *,
        config: Mapping[str, Any] | None = None,
        replace: bool = False,
    ) -> Provider:
        """Register a provider instance or class. Returns the instance.

        A class is instantiated with ``config``. Passing ``config`` alongside an
        already-built instance is an error.
        """
        if isinstance(provider, Provider):
            if config is not None:
                raise ProviderError("config may only be passed when registering a class")
            instance = provider
        elif isinstance(provider, type) and issubclass(provider, Provider):
            instance = provider(config)
        else:
            raise ProviderError(f"expected a Provider instance or subclass, got {provider!r}")

        pid = instance.id
        if pid in self._providers and not replace:
            raise ProviderError(f"provider id {pid!r} is already registered (pass replace=True)")
        self._providers[pid] = instance
        _log.debug("provider registered", provider_id=pid, cls=type(instance).__name__)
        return instance

    def get(self, provider_id: str) -> Provider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ProviderNotFound(
                f"no provider registered for id {provider_id!r}; "
                f"registered: {sorted(self._providers)}"
            ) from None

    def list(self) -> list[str]:
        return sorted(self._providers)

    def unregister(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)

    def load_entry_points(self, group: str = ENTRY_POINT_GROUP) -> None:
        """Discover and register providers advertised via ``importlib.metadata``
        entry points. Opt-in: a host must call this explicitly.
        """
        for ep in entry_points(group=group):
            try:
                obj = ep.load()
                if isinstance(obj, type) and issubclass(obj, Provider) or isinstance(obj, Provider):
                    self.register(obj)
                elif callable(obj):
                    obj(self)  # a registration hook: fn(registry) -> None
                else:
                    raise ProviderError(f"unsupported entry point target {obj!r}")
            except Exception as exc:  # noqa: BLE001 - one bad plugin must not break discovery
                _log.warning("entry point skipped", entry_point=ep.name, error=str(exc))


registry = ProviderRegistry()


def register(
    provider: Provider | type[Provider],
    *,
    config: Mapping[str, Any] | None = None,
    replace: bool = False,
) -> Provider:
    """Register a provider in the default registry."""
    return registry.register(provider, config=config, replace=replace)


def get_provider(provider_id: str) -> Provider:
    """Look up a provider in the default registry."""
    return registry.get(provider_id)


def list_providers() -> list[str]:
    """List ids registered in the default registry."""
    return registry.list()
