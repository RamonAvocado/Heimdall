"""The :class:`Provider` base class and its :class:`Capabilities` declaration."""

from __future__ import annotations

import asyncio
import inspect
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall.errors import ConfigError, HeimdallError, RequestError

__all__ = ["Capabilities", "Provider", "require_interval"]


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a provider can do, so a host can route and validate before calling.

    ``data_kinds`` holds :attr:`~heimdall._contracts.SchemaSpec.name` values the
    provider may emit. An empty ``intervals`` means the provider is not
    interval-based (e.g. a daily economic series) or accepts anything.

    This is capability metadata only. A provider's own configuration (timeouts,
    credentials, ...) is declared as typed keyword arguments on its ``__init__``,
    not here. ``requires_auth`` / ``rate_limit_per_min`` stay because a host reads
    them *before* constructing the provider, to route and pace calls.
    """

    data_kinds: tuple[str, ...]
    intervals: tuple[str, ...] = ()
    supports_date_range: bool = True
    requires_auth: bool = False
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

    #: Set to ``True`` and override :meth:`_fetch_many` when the upstream can
    #: serve several resources in one call (e.g. yfinance). Leave ``False`` and
    #: the base class fetches a list one resource at a time.
    native_batch: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        if not isinstance(getattr(cls, "id", None), str) or not cls.id:
            raise TypeError(f"{cls.__name__} must set a non-empty string class attribute 'id'")
        if not isinstance(getattr(cls, "capabilities", None), Capabilities):
            raise TypeError(f"{cls.__name__} must set 'capabilities' to a Capabilities instance")

    def _validate_request(self, request: FetchRequest) -> None:
        if not request.resource:
            raise RequestError("resource cannot be empty")

        if request.start is not None and request.end is not None and request.start >= request.end:
            raise RequestError("start must be before end")

    def fetch(
        self,
        resource: str | Sequence[str],
        interval: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> FetchResult | BatchResult:
        """Fetch one resource (returns :class:`FetchResult`) or a list of them
        (returns :class:`BatchResult`). ``interval`` / ``start`` / ``end`` apply
        to every resource in a list.
        """
        if isinstance(resource, str):
            request = FetchRequest(resource, interval, start, end)
            self._validate_request(request)
            return self._fetch(request)

        requests = [FetchRequest(r, interval, start, end) for r in resource]
        for request in requests:
            self._validate_request(request)
        return self._fetch_many(requests)

    async def afetch(
        self,
        resource: str | Sequence[str],
        interval: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> FetchResult | BatchResult:
        """Async mirror of :meth:`fetch`. The blocking work runs in a worker
        thread; a list of resources on a non-:attr:`native_batch` provider is
        fanned out concurrently, one thread per resource.
        """
        if isinstance(resource, str) or self.native_batch:
            return await asyncio.to_thread(self.fetch, resource, interval, start, end)

        resources = list(resource)
        results = await asyncio.gather(
            *(self.afetch(r, interval, start, end) for r in resources),
            return_exceptions=True,
        )
        ok: dict[str, FetchResult] = {}
        failed: dict[str, Exception] = {}
        for r, res in zip(resources, results, strict=True):
            if isinstance(res, BaseException):
                if not isinstance(res, Exception):
                    raise res
                failed[r] = res
            else:
                assert isinstance(res, FetchResult)
                ok[r] = res
        return BatchResult(ok, failed)

    def _fetch_many(self, requests: list[FetchRequest]) -> BatchResult:
        """Fetch several resources. The default fetches them one at a time and
        collects failures; override (with :attr:`native_batch` = ``True``) when
        the upstream takes many resources in a single call.
        """
        ok: dict[str, FetchResult] = {}
        failed: dict[str, Exception] = {}
        for request in requests:
            try:
                ok[request.resource] = self._fetch(request)
            except HeimdallError as exc:
                failed[request.resource] = exc
        return BatchResult(ok, failed)

    @abstractmethod
    def _fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch data for ``request`` and return a :class:`FetchResult`."""
        raise NotImplementedError

    @classmethod
    def from_env(cls, **overrides: Any) -> Provider:
        """Build an instance, resolving required ``__init__`` config from the
        environment (or a loaded ``.env`` file) via ``HEIMDALL_<id>_<param>``
        env vars (e.g. ``user_agent`` on ``sec_form4`` -> ``HEIMDALL_SEC_FORM4_USER_AGENT``).
        ``overrides`` wins over the environment. Raises
        :class:`~heimdall.errors.ConfigError` naming exactly what's missing.

        # ponytail: env values are always strings; a provider needing a
        # required non-str param must cast in its own __init__ or pass it via
        # `overrides` - add real type coercion here if that's ever needed.
        """
        params = inspect.signature(cls.__init__).parameters
        kwargs: dict[str, Any] = {}
        missing: list[tuple[str, str]] = []
        for name, param in params.items():
            if name == "self":
                continue
            if name in overrides:
                kwargs[name] = overrides[name]
                continue
            env_name = f"HEIMDALL_{cls.id.upper()}_{name.upper()}"
            value = os.environ.get(env_name)
            if value is not None:
                kwargs[name] = value
            elif param.default is inspect.Parameter.empty:
                missing.append((name, env_name))
        if missing:
            detail = "\n".join(f"  - {name}: set {env_name}=..." for name, env_name in missing)
            names = ", ".join(name for name, _ in missing)
            raise ConfigError(
                f"{cls.id!r} needs configuration to construct - set the following "
                f"environment variable(s) (a .env file works too), or construct it "
                f"yourself, e.g. {cls.__name__}({names}=...):\n{detail}"
            )
        return cls(**kwargs)


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
