"""The process-wide provider registry.

Local providers register with `heimdall.register(MyProvider)`.  Third-party
packages published to PyPI expose theirs through `importlib.metadata` entry
points (group `heimdall.providers`); `ProviderRegistry.load_entry_points`
imports and registers them the first time the registry is queried.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points

from ramonavocado_logger import get_log

from heimdall.errors import ProviderError, ProviderNotFound
from heimdall.providers._base import Provider

__all__ = [
    "PROVIDER_ENTRY_POINT_GROUP",
    "PROVIDER_REGISTRY",
    "ProviderRegistry",
    "get_provider",
    "list_providers",
    "register",
]

_log = get_log(component="registry")

PROVIDER_ENTRY_POINT_GROUP = "heimdall.providers"


class ProviderRegistry:
    """Maps a provider id to its `Provider` instance.

    Parameters
    ----------
    entry_point_group:
        `importlib.metadata` group scanned on the first `get` / `list`.
    """

    def __init__(self, *, entry_point_group: str | None = None) -> None:
        self._entry_point_group = entry_point_group
        self._plugins_loaded = False
        self._providers: dict[str, Provider] = {}
        #: provider id -> a factory (typically `SomeProvider.from_env`) called
        #: on first `get`.  Lets a provider that needs config sit in the
        #: registry without crashing at registration time: the real
        #: `ConfigError` (if any) surfaces when someone actually asks for it.
        self._factories: dict[str, Callable[[], Provider]] = {}
        #: provider id -> why it is known but not usable (e.g. its extra failed
        #: to import).  Consulted by `get` to give an actionable error.
        self._unavailable: dict[str, str] = {}

    def register(
        self,
        provider: Provider | type[Provider],
        *,
        replace: bool = False,
    ) -> Provider:
        """Register a provider.  Returns the instance.

        Pass the class (`register(MyProvider)`) and it is instantiated with no
        arguments, so the provider's own `__init__` defaults apply.  Pass an
        already-built instance to use a non-default configuration:
        `register(MyProvider(timeout=10))`.
        """
        if isinstance(provider, Provider):
            instance = provider
        elif isinstance(provider, type) and issubclass(provider, Provider):
            instance = provider()
        else:
            raise ProviderError(
                f"expected a Provider instance or subclass, got {provider!r}"
            )

        pid = instance.id
        if (pid in self._providers or pid in self._factories) and not replace:
            raise ProviderError(
                f"provider id {pid!r} is already registered (pass replace=True)"
            )
        self._providers[pid] = instance
        self._factories.pop(pid, None)
        self._unavailable.pop(pid, None)
        _log.debug("registered", name=pid, cls=type(instance).__qualname__)
        return instance

    def register_lazy(self, provider_id: str, factory: Callable[[], Provider]) -> None:
        """Register a provider built on first use via `factory()` (typically
        `SomeProvider.from_env`).  `get(provider_id)` calls it, caches the
        result, and lets any `ConfigError` propagate as-is: missing config
        surfaces at first real use, not at import time.
        """
        if provider_id in self._providers or provider_id in self._factories:
            raise ProviderError(f"provider id {provider_id!r} is already registered")
        self._factories[provider_id] = factory

    def mark_unavailable(self, provider_id: str, reason: str) -> None:
        """Record that `provider_id` is known but cannot be used (its optional
        dependency failed to import, an entry point blew up, ...).  `get` turns
        this into an actionable error instead of a bare "not registered".
        """
        if provider_id not in self._providers:
            self._unavailable[provider_id] = reason

    def get(self, provider_id: str) -> Provider:
        """Return the provider registered under `provider_id` (loading plugins
        first), building it on first use if it was registered lazily."""
        self._load_plugins()
        if provider_id in self._providers:
            return self._providers[provider_id]
        factory = self._factories.get(provider_id)
        if factory is not None:
            instance = factory()  # a ConfigError here propagates as-is
            self._providers[provider_id] = instance
            del self._factories[provider_id]
            return instance
        raise ProviderNotFound(self._not_found_message(provider_id))

    def _not_found_message(self, provider_id: str) -> str:
        if provider_id in self._unavailable:
            return (
                f"provider {provider_id!r} is known to Heimdall but unavailable: "
                f"{self._unavailable[provider_id]}. If it is a bundled provider, "
                f"install its extra, e.g.  pip install heimdall-mimird[{provider_id}]"
            )
        if not self._providers and not self._factories:
            return (
                f"no provider registered for id {provider_id!r}, and the registry is "
                "empty - nothing has been registered yet. If you expected the "
                "bundled providers, make sure `import heimdall` ran (it "
                "self-registers them); if this is your own ProviderRegistry(), "
                "call .register(...) on it first."
            )
        return f"no provider registered for id {provider_id!r}; known: {self.list()}"

    def list(self) -> list[str]:
        """Sorted list of every registered id (loading plugins first)."""
        self._load_plugins()
        return sorted(set(self._providers) | set(self._factories))

    def unregister(self, provider_id: str) -> None:
        self._providers.pop(provider_id, None)
        self._factories.pop(provider_id, None)

    def _load_plugins(self) -> None:
        # Idempotent: the scan runs at most once per registry.
        if self._plugins_loaded:
            return
        self._plugins_loaded = True
        if self._entry_point_group is not None:
            self.load_entry_points(self._entry_point_group)

    def load_entry_points(self, group: str = PROVIDER_ENTRY_POINT_GROUP) -> None:
        """Discover and register providers advertised via `importlib.metadata`
        entry points.  The entry-point value may be a `Provider` class or
        instance, or a callable `fn(registry) -> None` registration hook.
        """
        for ep in entry_points(group=group):
            try:
                obj = ep.load()
                if (isinstance(obj, type) and issubclass(obj, Provider)) or isinstance(
                    obj, Provider
                ):
                    self.register(obj)
                elif callable(obj):
                    obj(self)
                else:
                    raise ProviderError(f"unsupported entry point target {obj!r}")
            except Exception as exc:  # one bad plugin must not break discovery
                _log.warning(
                    "plugin failed to load", entry_point=ep.name, error=str(exc)
                )
                self.mark_unavailable(ep.name, str(exc))


PROVIDER_REGISTRY = ProviderRegistry(entry_point_group=PROVIDER_ENTRY_POINT_GROUP)


def register(
    provider: Provider | type[Provider],
    *,
    replace: bool = False,
) -> Provider:
    """Register a provider in `PROVIDER_REGISTRY`."""
    return PROVIDER_REGISTRY.register(provider, replace=replace)


def get_provider(provider_id: str) -> Provider:
    """Look up a provider in `PROVIDER_REGISTRY`."""
    return PROVIDER_REGISTRY.get(provider_id)


def list_providers() -> list[str]:
    """List ids registered in `PROVIDER_REGISTRY`."""
    return PROVIDER_REGISTRY.list()
