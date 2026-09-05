"""The :class:`Provider` base class and its :class:`Capabilities` declaration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from heimdall.contracts import FetchRequest, FetchResult
from heimdall.errors import ConfigError, RequestError

__all__ = ["Capabilities", "Provider", "require_interval"]


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a provider can do, so a host can route and validate before calling.

    ``data_kinds`` holds :attr:`~heimdall.contracts.SchemaSpec.name` values the
    provider may emit. An empty ``intervals`` means the provider is not
    interval-based (e.g. a daily economic series) or accepts anything.
    """

    data_kinds: tuple[str, ...]
    intervals: tuple[str, ...] = ()
    supports_date_range: bool = True
    requires_auth: bool = False
    required_config: tuple[str, ...] = ()
    rate_limit_per_min: int | None = None


class Provider(ABC):
    """Base class for every data provider.

    Subclasses set the class attributes :attr:`id` and :attr:`capabilities`,
    and implement :meth:`fetch`. ``fetch`` must stay pure: make the upstream
    call, parse, normalise, return. No disk writes, no caching, no retry loops
    - those are host concerns (see :mod:`heimdall._retry`).
    """

    id: ClassVar[str]
    capabilities: ClassVar[Capabilities]

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = dict(config or {})
        missing = [k for k in self.capabilities.required_config if k not in self._config]
        if missing:
            raise ConfigError(f"{self.id}: missing required config keys: {missing}")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        if not isinstance(getattr(cls, "id", None), str) or not cls.id:
            raise TypeError(f"{cls.__name__} must set a non-empty string class attribute 'id'")
        if not isinstance(getattr(cls, "capabilities", None), Capabilities):
            raise TypeError(f"{cls.__name__} must set 'capabilities' to a Capabilities instance")

    def config(self, key: str, default: Any = None) -> Any:
        """Read a configuration value supplied at construction time."""
        return self._config.get(key, default)

    def _validate_request(self, request: FetchRequest) -> None:
        if not request.resource:
            raise RequestError("resource cannot be empty")

        if request.start is not None and request.end is not None and request.start >= request.end:
            raise RequestError("start must be before end")

    def fetch(
        self,
        resource: str,
        interval: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> FetchResult:
        request = FetchRequest(resource, interval, start, end)
        self._validate_request(request)
        return self._fetch(request)

    @abstractmethod
    def _fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch data for ``request`` and return a :class:`FetchResult`."""
        raise NotImplementedError


def require_interval(request: FetchRequest, capabilities: Capabilities, *, default: str) -> str:
    """Resolve and validate ``request.interval`` against ``capabilities``.

    Returns ``default`` when the request leaves it unset. Raises
    :class:`~heimdall.errors.RequestError` for an unsupported value.
    """
    interval = request.interval or default
    if capabilities.intervals and interval not in capabilities.intervals:
        raise RequestError(
            f"interval {interval!r} not supported; choose one of {list(capabilities.intervals)}"
        )
    return interval
