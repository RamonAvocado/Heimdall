"""Provider registration and lookup.

The M1 path is explicit registration: ``heimdall.register(MyProvider)``.
:meth:`ProviderRegistry.load_entry_points` is implemented so that
``pip install``-and-go community packages become possible later, but nothing
calls it automatically yet.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from heimdall._logging import get_logger
from heimdall._provider import Provider
from heimdall.errors import ProviderError, ProviderNotFound

__all__ = ["ProviderRegistry", "registry", "register", "get_provider", "list_providers"]

_log = get_logger("registry")

ENTRY_POINT_GROUP = "heimdall.providers"


class ProviderRegistry:
    """A mapping of provider id -> :class:`~heimdall.provider.Provider` instance."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        #: provider id -> why it is known but not usable (e.g. its extra failed : to import). Consulted by :meth:`get` to give an actionable error.
        self._unavailable: dict[str, str] = {}

    def register(
        self,
        provider: Provider | type[Provider],
        *,
        replace: bool = False,
    ) -> Provider:
        """Register a provider. Returns the instance.

        Pass the class - ``register(MyProvider)`` - and it is instantiated with
        no arguments, so the provider's own ``__init__`` defaults apply. Pass an
        already-built instance to use a non-default configuration:
        ``register(MyProvider(timeout=10))``.
        """
        if isinstance(provider, Provider):
            instance = provider
        elif isinstance(provider, type) and issubclass(provider, Provider):
            instance = provider()
        else:
            raise ProviderError(f"expected a Provider instance or subclass, got {provider!r}")

        pid = instance.id
        if pid in self._providers and not replace:
            raise ProviderError(f"provider id {pid!r} is already registered (pass replace=True)")
        self._providers[pid] = instance
        self._unavailable.pop(pid, None)
        _log.debug("provider registered", provider_id=pid, cls=type(instance).__name__)
        return instance

    def mark_unavailable(self, provider_id: str, reason: str) -> None:
        """Record that ``provider_id`` is known but cannot be used (its optional
        dependency failed to import, an entry point blew up, ...). :meth:`get`
        turns this into an actionable error instead of a bare "not registered".
        """
        if provider_id not in self._providers:
            self._unavailable[provider_id] = reason

    def get(self, provider_id: str) -> Provider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ProviderNotFound(self._not_found_message(provider_id)) from None

    def _not_found_message(self, provider_id: str) -> str:
        if provider_id in self._unavailable:
            return (
                f"provider {provider_id!r} is known to Heimdall but unavailable: "
                f"{self._unavailable[provider_id]}. If it is a bundled provider, install its "
                f"extra, e.g.  pip install heimdall-mimird[{provider_id}]"
            )
        if not self._providers:
            return (
                f"no provider registered for id {provider_id!r}, and the registry is empty - "
                "nothing has been registered yet. If you expected the bundled providers, make "
                "sure `import heimdall` ran (it self-registers them); if this is your own "
                "ProviderRegistry(), call .register(...) on it first."
            )
        return (
            f"no provider registered for id {provider_id!r}; registered: {sorted(self._providers)}"
        )

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
                self.mark_unavailable(ep.name, str(exc))


registry = ProviderRegistry()


def register(
    provider: Provider | type[Provider],
    *,
    replace: bool = False,
) -> Provider:
    """Register a provider in the default registry."""
    return registry.register(provider, replace=replace)


def get_provider(provider_id: str) -> Provider:
    """Look up a provider in the default registry."""
    return registry.get(provider_id)


def list_providers() -> list[str]:
    """List ids registered in the default registry."""
    return registry.list()
