# Writing a provider

A provider is one class: it turns a `FetchRequest` into a `FetchResult`. You can
keep it inside your own project or publish it - Heimdall imposes nothing beyond
the contract.

## Package layout (bundled providers)

Each bundled provider is one folder under `src/heimdall/providers/<name>/`
(no leading underscore - that's reserved for the internal `_template`
package), containing `provider.py` (the class) and an `__init__.py` that
re-exports it and defines a `_register_lazy(registry)` hook (see "Register and
use it" below for what that hook does). The canonical import is direct, by
name:

```python
from heimdall.providers.fred import FredProvider
```

There's no flat re-export from `heimdall.providers` itself - at scale that
would eagerly import every provider (and try to pull in every optional
dependency) just to reach one class. Add the provider's `id` to `_BUNDLED` in
`src/heimdall/__init__.py` so it self-registers when its extra is installed,
and give it its own extra in `pyproject.toml`'s
`[project.optional-dependencies]`, named to match the folder.

## The contract

```python
FetchRequest(resource, interval=None, start=None, end=None, params={})
FetchResult(frame, schema, provider_id, request, retrieved_at, metadata={})
```

- **`resource`** is provider-specific: a ticker, a series id, an endpoint key.
- **`frame`** is a `polars.DataFrame`.
- **`schema`** is a `SchemaSpec` that must actually validate `frame`. Reuse
  `heimdall.schemas.OHLCV_BARS` / `OBSERVATIONS`, or define your own - only do
  the latter when the output shape is genuinely new. A `SchemaSpec` is shared
  vocabulary, not a per-provider class.

## Starting point

Copy `src/heimdall/providers/_template/provider.py`: rename the class, change
`id`, and replace the body of `_fetch` with a real upstream call - see
`heimdall.providers.fred` or `heimdall.providers.yfinance` for one that does
real HTTP. The template stays in-memory so you can read it (and its test,
`tests/providers/test_template.py`) without any network mocking getting in the
way.

You implement `_fetch` (one resource). The base `Provider` wraps it:

- `provider.fetch("X")` / `heimdall.fetch("template", "X")` - one resource, returns `FetchResult`.
- `provider.fetch(["X", "Y"])` - a list, returns a `BatchResult` (`.ok` /
  `.failed` dicts keyed by resource, plus a combined `.frame`). A resource that
  raises a `HeimdallError` lands in `.failed`; the batch never raises for it.
- `provider.afetch(...)` / `heimdall.afetch(...)` - async mirror of both. The
  blocking `_fetch` runs in a worker thread; a list is fanned out concurrently.

You get all of that for free. Only override `_fetch_many(self, requests)` (and
set `native_batch = True`) if the upstream can serve several resources in one
call - see `heimdall.providers.yfinance` for an example.

## Register and use it

```python
import heimdall
from your_package.provider import MyProvider

heimdall.register(MyProvider)
result = heimdall.fetch("mine", "some-resource")
```

For config/secrets, add typed keyword arguments to your provider's `__init__` -
never read the environment inside the provider itself:

```python
class MyProvider(Provider):
    id = "mine"
    capabilities = Capabilities(data_kinds=(MY_SCHEMA.name,), requires_auth=True)

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout
```

`heimdall.register(MyProvider)` instantiates the class with no arguments, so a
provider with everything defaulted (like `fred`) works as-is. A provider with
a *required* argument (no default - like `api_key` above) needs one of:

- **Resolve it from the environment** with `Provider.from_env()`, which every
  provider gets for free. It reads `HEIMDALL_<ID>_<PARAM>` (upper-cased) for
  each `__init__` parameter with no default - `api_key` on a provider whose
  `id` is `"mine"` becomes `HEIMDALL_MINE_API_KEY`. A `.env` file in the
  working directory is loaded once at `import heimdall` (real env vars always
  win over it - see `.env.example` at the repo root). Missing config raises
  `heimdall.errors.ConfigError` naming exactly which variable(s) to set:

  ```python
  heimdall.register(MyProvider.from_env())
  # or, for a bundled provider that already registered lazily (see below):
  heimdall.fetch("mine", "some-resource")  # raises ConfigError if unset
  ```

- **Construct it yourself**, bypassing the environment entirely:

  ```python
  heimdall.register(MyProvider(api_key="..."))
  ```

For a *bundled* provider with required config, register it lazily instead of
eagerly, so `import heimdall` never crashes for lack of config - the
`ConfigError` (if any) surfaces the first time the provider is actually
fetched from, not at import time:

```python
# your_package/__init__.py
def _register_lazy(registry: object) -> None:
    from heimdall._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if MyProvider.id not in registry.list():
        registry.register_lazy(MyProvider.id, MyProvider.from_env)
```

(add `MyProvider`'s id to `_BUNDLED` in `src/heimdall/__init__.py`, and list
its required env var(s) in `.env.example`, if it ships with Heimdall itself.)

## Prove it conforms

`heimdall.testing` needs pytest, which the base install does not pull in:

```bash
pip install heimdall-mimird[testing]
```

```python
from heimdall.testing import assert_provider_conformance
from heimdall import FetchRequest

assert_provider_conformance(MyProvider(), FetchRequest(resource="some-resource"))
```

Or in a pytest suite, subclass `heimdall.testing.ProviderContractTests` and
implement `make_provider()` / `sample_request()`.

## Rules the conformance kit enforces

- `id` is a non-empty string; `capabilities.data_kinds` is non-empty.
- `fetch()` returns a `FetchResult` with a non-empty frame that passes
  `schema.validate()`.
- `result.provider_id == self.id`; `retrieved_at` is timezone-aware.
- Two identical requests return the same schema and columns.
- An unsupported `interval` raises `RequestError` (not a bare exception).
