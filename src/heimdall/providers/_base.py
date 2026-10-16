"""The provider contract.

A provider turns a `FetchRequest` into a `FetchResult`.  Subclass `Provider`,
set `metadata` and `capabilities`, and implement `_fetch` for one resource;
`fetch` / `afetch` handle lists, batching and async for the caller.  Its own
configuration (timeouts, credentials, ...) is typed keyword arguments on
`__init__`, each annotated `Annotated[type, "description"]` for the docs.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from types import UnionType
from typing import Any, ClassVar, get_args

from ramonavocado_logger import get_log

from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall.errors import ConfigError, HeimdallError, RequestError

__all__ = ["Capabilities", "Provider", "ProviderMetadata", "require_interval"]

_PACKAGE = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ProviderMetadata:
    """Who a provider is: the docs and the registry read these fields."""

    #: Registry and catalog id, snake_case (`"fred"`); also its extra's name.
    name: str
    #: One line on what it fetches; the docs' headline for it.
    description: str = ""
    #: The provider's own version, bumped when its output changes.
    version: str = "0.1.0"
    #: GitHub handle of a community contributor; the docs credit them.
    author: str = "mimird"


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a provider can do, so a host can route and validate before calling.

    `data_kinds` holds `SchemaSpec.name` values the provider may emit.  An
    empty `intervals` means the provider is not interval-based (e.g. a daily
    economic series) or accepts anything.  `requires_auth` /
    `rate_limit_per_min` are here because a host reads them *before*
    constructing the provider, to route and pace calls.
    """

    data_kinds: tuple[str, ...]
    intervals: tuple[str, ...] = ()
    supports_date_range: bool = True
    requires_auth: bool = False
    rate_limit_per_min: int | None = None


def summary(obj: Any) -> str:
    """First paragraph of `obj`'s own docstring, on one line."""
    # __doc__, not inspect.getdoc: a class must not inherit its base's docstring.
    doc = inspect.cleandoc(obj.__doc__ or "")
    return " ".join(doc.split("\n\n")[0].split())


def source(obj: Any) -> str:
    """`src/heimdall/<file>#L<line>` for heimdall's own code, the module name
    otherwise."""
    obj = inspect.unwrap(obj)
    path = Path(inspect.getsourcefile(obj) or "").resolve()
    if not path.is_relative_to(_PACKAGE):
        return str(obj.__module__)
    rel = path.relative_to(_PACKAGE).as_posix()
    return f"src/heimdall/{rel}#L{inspect.getsourcelines(obj)[1]}"


def type_name(annotation: Any) -> str:
    """`int`, `str | None`: an annotation as a reader would write it."""
    if isinstance(annotation, str):
        return annotation
    if isinstance(annotation, UnionType):
        return " | ".join(type_name(arg) for arg in get_args(annotation))
    return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))


class Provider(ABC):
    """Fetches one kind of data from one upstream.

    Subclass it, set `metadata` and `capabilities`, implement `_fetch`, then
    call `fetch()`.  `_fetch` must stay pure: make the upstream call, parse,
    normalise, return.  No disk writes, no caching, no retry loops: those are
    host concerns (see `heimdall._retry`).
    """

    metadata: ClassVar[ProviderMetadata]
    capabilities: ClassVar[Capabilities]
    #: `metadata.name`, set for every subclass; what `FetchResult.provider_id`
    #: and the registry use.
    id: ClassVar[str]
    _log: ClassVar[Any]

    #: Set to `True` and override `_fetch_many` when the upstream can serve
    #: several resources in one call (e.g. yfinance).  Leave `False` and the
    #: base class fetches a list one resource at a time.
    native_batch: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if getattr(cls, "__abstractmethods__", None):
            return
        meta = getattr(cls, "metadata", None)
        if not isinstance(meta, ProviderMetadata) or not meta.name:
            raise TypeError(f"{cls.__name__} must set 'metadata' to a ProviderMetadata with a name")
        if not isinstance(getattr(cls, "capabilities", None), Capabilities):
            raise TypeError(f"{cls.__name__} must set 'capabilities' to a Capabilities instance")
        cls.id = meta.name
        cls._log = get_log(component="provider", name=meta.name)

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
        """Fetch one resource (returns `FetchResult`) or a list of them
        (returns `BatchResult`).  `interval` / `start` / `end` apply to every
        resource in a list.
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
        """Async mirror of `fetch`.  The blocking work runs in a worker thread;
        a list of resources on a non-`native_batch` provider is fanned out
        concurrently, one thread per resource.
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
        """Fetch several resources.  The default fetches them one at a time and
        collects failures; override (with `native_batch = True`) when the
        upstream takes many resources in a single call.
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
        """Fetch data for `request` and return a `FetchResult`."""
        raise NotImplementedError

    @classmethod
    def from_env(cls, **overrides: Any) -> Provider:
        """Build an instance, resolving required `__init__` config from the
        environment (or a loaded `.env` file) via `HEIMDALL_<id>_<param>` env
        vars (e.g. `user_agent` on `sec_form4` ->
        `HEIMDALL_SEC_FORM4_USER_AGENT`).  `overrides` wins over the
        environment.  Raises `ConfigError` naming exactly what's missing.
        """
        # ponytail: env values are always strings; a provider needing a required
        # non-str param must cast in its own __init__ or pass it via `overrides`.
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
            detail = "\n".join(f"  - {name}: set {env}=..." for name, env in missing)
            names = ", ".join(name for name, _ in missing)
            raise ConfigError(
                f"{cls.id!r} needs configuration to construct - set the following "
                f"environment variable(s) (a .env file works too), or construct it "
                f"yourself, e.g. {cls.__name__}({names}=...):\n{detail}"
            )
        return cls(**kwargs)

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """JSON-safe description: `id`, `name`, `description`, `author`,
        `source`, `params` (name, type, default, description) and `facts`."""
        meta = cls.metadata
        return {
            "id": meta.name,
            "name": cls.__name__,
            "description": meta.description or summary(cls),
            "author": meta.author,
            "source": source(cls),
            "params": _init_params(cls),
            "facts": {
                "version": meta.version,
                "install": f"heimdall-mimird[{meta.name}]",
                **asdict(cls.capabilities),
            },
        }


def _init_params(cls: type[Provider]) -> list[dict[str, Any]]:
    # Descriptions come from `Annotated[type, "description"]`.
    init = cls.__init__
    if init is object.__init__:
        return []
    hints = inspect.get_annotations(init, eval_str=True)
    params = []
    for p in inspect.signature(init).parameters.values():
        if p.name == "self" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        hint = hints.get(p.name)
        meta = getattr(hint, "__metadata__", ())
        params.append(
            {
                "name": p.name,
                "type": type_name(hint.__origin__ if meta else hint) if hint else "",
                "default": None if p.default is p.empty else repr(p.default),
                "description": meta[0] if meta else "",
            }
        )
    return params


def require_interval(request: FetchRequest, capabilities: Capabilities, *, default: str) -> str:
    """Resolve and validate `request.interval` against `capabilities`.

    Returns `default` when the request leaves it unset.  Raises `RequestError`
    for an unsupported value.
    """
    interval = request.interval or default
    if capabilities.intervals and interval not in capabilities.intervals:
        raise RequestError(
            f"interval {interval!r} not supported; choose one of {list(capabilities.intervals)}"
        )
    return interval
