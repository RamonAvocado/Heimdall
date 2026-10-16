# Contributing to heimdall

## Ground rules

- A provider is one class: it turns a `FetchRequest` into a `FetchResult`. You
  implement `_fetch` for one resource; the base `Provider` gives you `fetch`
  for lists (`BatchResult`), `afetch`, and failure collection.
- `frame` is a Polars `DataFrame` that must pass its `schema.validate()`. Reuse
  `heimdall.schemas.OHLCV_BARS` / `OBSERVATIONS` / `GENERIC_TABLE`. Define your
  own `SchemaSpec` only when the output shape is genuinely new.
- `_fetch` stays pure: call the upstream, parse, normalise, return. No disk
  writes, no caching, no retry loops (those are host concerns).
- Config (timeouts, credentials) is typed keyword arguments on `__init__`,
  never read from the environment inside the provider.
- Raise `heimdall.errors` (`RequestError`, `UpstreamError`, `ConfigError`, ...),
  never bare `ValueError` / `KeyError`; they all derive from `HeimdallError`.
- Log through `self._log` (bound to `component="provider", name=<id>`), or
  `ramonavocado_logger.get_log(...)` outside a provider.
- `uv run pytest -m "not network"`, `uv run ruff check .`,
  `uv run ruff format --check .` and `uv run mypy` must all pass. Run
  `uv run pytest -m network` (real FRED / Yahoo / SEC) before a release.

Dev setup: `uv sync --extra all --group dev`.

## Writing a provider

```python
from typing import Annotated

import polars as pl
from heimdall import Capabilities, FetchRequest, FetchResult, Provider, ProviderMetadata
from heimdall import utcnow
from heimdall.schemas import OBSERVATIONS


class MyProvider(Provider):
    """One line on what it fetches. This becomes its description in the docs."""

    metadata = ProviderMetadata(name="mine", version="0.1.0", author="your-handle")
    capabilities = Capabilities(data_kinds=(OBSERVATIONS.name,), requires_auth=True)

    def __init__(
        self,
        *,
        api_key: Annotated[str, "Key from the upstream's dashboard."],
        timeout: Annotated[float, "HTTP timeout in seconds."] = 30.0,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def _fetch(self, request: FetchRequest) -> FetchResult:
        frame = ...  # call the upstream, build the OBSERVATIONS columns
        OBSERVATIONS.validate(frame)
        return FetchResult(
            frame=frame,
            schema=OBSERVATIONS,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
        )
```

Start from `src/heimdall/providers/_template/provider.py`. It stays in memory,
so it and its test (`tests/providers/test_template.py`) need no network
mocking. See `fred` for a provider that does real HTTP. Override
`_fetch_many(self, requests)` and set `native_batch = True` only when the
upstream serves several resources in one call, as `yfinance` does.

### Register and configure it

```python
import heimdall

heimdall.register(MyProvider(api_key="..."))  # or register(MyProvider) if all defaulted
result = heimdall.fetch("mine", "some-resource")
```

`Provider.from_env()` builds it from `HEIMDALL_<ID>_<PARAM>` env vars, one for
each `__init__` parameter without a default. For example, `api_key` on `mine`
reads `HEIMDALL_MINE_API_KEY`. A `.env` file in the working directory is loaded
once at `import heimdall`, and real env vars always win over it (see
`.env.example`). Missing config raises `ConfigError` naming exactly which
variable to set.

### Prove it conforms

Subclass `heimdall.testing.ProviderContractTests` and implement
`make_provider()` / `sample_request()`, or call
`assert_provider_conformance(MyProvider(...), FetchRequest("some-resource"))`.
It checks that:

- `capabilities.data_kinds` is non-empty, and `result.schema.name` is in it.
- `_fetch` returns a non-empty frame that passes `schema.validate()`.
- `result.provider_id == self.id` and `retrieved_at` is timezone-aware.
- Two identical requests give the same schema and columns.
- An unsupported `interval` raises `RequestError`.
- A one-item list returns a `BatchResult` holding exactly that resource.

`heimdall.testing` needs pytest. Out-of-tree packages get it with
`pip install heimdall-mimird[testing]`.

## Publishing as a plugin

A third-party package registers without any change to heimdall. In your
`pyproject.toml`:

```toml
[project.entry-points."heimdall.providers"]
mine = "my_pkg.provider:MyProvider"
```

The entry-point value may be a `Provider` class or instance, or a callable
`fn(registry) -> None` registration hook. A hook is the way to go for a
provider with required config:
`registry.register_lazy(MyProvider.id, MyProvider.from_env)`. heimdall scans the
group the first time `PROVIDER_REGISTRY` is queried. A plugin that fails to
import is logged and skipped, not fatal: `heimdall.fetch("mine", ...)` then
says why. Depend on `heimdall-mimird` and you are done.

## Adding a provider by pull request

The core (`providers/_base.py`, `providers/_registry.py`, `_contracts.py`,
`schemas.py`) is kept small and reviewed carefully. Providers are where the
community grows heimdall.

1. Add a folder `src/heimdall/providers/<name>/` with `provider.py` (the class)
   and an `__init__.py` that exports it in `__all__` and defines a
   `_register_lazy(registry)` hook (copy one from `fred/__init__.py`).
   `<name>` is `metadata.name`.
2. Add `<name>` to `_BUNDLED` in `src/heimdall/__init__.py`. Add a matching
   extra in `pyproject.toml`'s `[project.optional-dependencies]` with the
   provider's client library, so `import heimdall` still works without it. List
   any required env var in `.env.example`.
3. Add `tests/providers/test_<name>.py` subclassing `ProviderContractTests`
   (mock the HTTP with `respx`), plus a `@pytest.mark.network` smoke test.
4. Set `author`, write a class docstring or `description`, and annotate every
   `__init__` keyword as `Annotated[type, "description"]`;
   `tests/test_catalog.py` fails otherwise.
5. Open a PR. CI runs lint, types and tests; a maintainer reviews and merges.
   On the next release your provider appears in the docs.

## Getting credited in the docs

Every bundled provider is listed in the Mimird docs, generated from
`heimdall.catalog()` on each release. When you contribute one, put your GitHub
handle on it so the docs credit you:

```python
metadata = ProviderMetadata(name="mine", author="your-handle")
```

The docs show `metadata.description` (or the first paragraph of the class
docstring), each `__init__` keyword with its `Annotated` description, and the
`Capabilities`. Check what will be published with
`uv run --extra all python -m heimdall`.
