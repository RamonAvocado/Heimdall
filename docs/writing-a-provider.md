# Writing a provider

A provider is one class: it turns a `FetchRequest` into a `FetchResult`. You can
keep it inside your own project or publish it - Heimdall imposes nothing beyond
the contract.

## Package layout (bundled providers)

Each bundled provider is one folder under `src/heimdall/providers/<name>/`
(no leading underscore - that's reserved for the internal `_template`
package), containing `provider.py` (the class) and an `__init__.py` that
re-exports it and defines a `_register(registry)` hook. The canonical import
is direct, by name:

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
never read the environment inside the provider. `heimdall.register(MyProvider)`
instantiates the class with no arguments, so those defaults apply; to override
one, register a constructed instance:

```python
class MyProvider(Provider):
    id = "mine"
    capabilities = Capabilities(data_kinds=(MY_SCHEMA.name,), requires_auth=True)

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout


heimdall.register(MyProvider(api_key=os.environ["MYPROVIDER_API_KEY"]))
```

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
