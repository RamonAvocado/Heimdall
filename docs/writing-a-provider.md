# Writing a provider

A provider is one class: it turns a `FetchRequest` into a `FetchResult`. You can
keep it inside your own project or publish it - Heimdall imposes nothing beyond
the contract.

## The contract

```python
FetchRequest(resource, interval=None, start=None, end=None, params={})
FetchResult(frame, schema, provider_id, request, retrieved_at, metadata={})
```

- **`resource`** is provider-specific: a ticker, a series id, an endpoint key.
- **`frame`** is a `polars.DataFrame`.
- **`schema`** is a `SchemaSpec` that must actually validate `frame`. Reuse
  `heimdall.schemas.OHLCV_BARS` / `OBSERVATIONS`, or define your own.

## A minimal example

A provider that pulls a CSV with `date,value` columns from a URL:

```python
from datetime import datetime
from io import StringIO

import httpx
import polars as pl

import heimdall
from heimdall import Capabilities, FetchRequest, FetchResult, Provider
from heimdall.schemas import ColumnSpec, SchemaSpec
from heimdall.errors import RequestError, UpstreamError

CSV_SERIES = SchemaSpec(
    name="csv.series",
    columns=(
        ColumnSpec("timestamp", pl.Datetime, nullable=False),
        ColumnSpec("value", pl.Float64, nullable=False),
    ),
    time_column="timestamp",
    primary_key=("timestamp",),
)


class CsvUrlProvider(Provider):
    id = "csv-url"
    capabilities = Capabilities(data_kinds=(CSV_SERIES.name,))

    def _fetch(self, request: FetchRequest) -> FetchResult:
        url = request.params.get("url") or request.resource
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(f"could not fetch {url}: {exc}") from exc

        frame = (
            pl.read_csv(StringIO(resp.text))
            .rename({"date": "timestamp", "value": "value"})
            .with_columns(
                pl.col("timestamp").str.strptime(pl.Datetime, strict=False),
                pl.col("value").cast(pl.Float64, strict=False),
            )
            .drop_nulls()
            .sort("timestamp")
        )
        if frame.is_empty():
            raise RequestError(f"no rows returned from {url}")

        CSV_SERIES.validate(frame)
        return FetchResult(
            frame=frame,
            schema=CSV_SERIES,
            provider_id=self.id,
            request=request,
            retrieved_at=heimdall.utcnow(),
        )
```

You implement `_fetch` (one resource). The base `Provider` wraps it:

- `provider.fetch("X")` / `heimdall.fetch("csv-url", "X")` - one resource, returns `FetchResult`.
- `provider.fetch(["X", "Y"])` - a list, returns a `BatchResult` (`.ok` /
  `.failed` dicts keyed by resource, plus a combined `.frame`). A resource that
  raises a `HeimdallError` lands in `.failed`; the batch never raises for it.
- `provider.afetch(...)` / `heimdall.afetch(...)` - async mirror of both. The
  blocking `_fetch` runs in a worker thread; a list is fanned out concurrently.

You get all of that for free. Only override `_fetch_many(self, requests)` (and
set `native_batch = True`) if the upstream can serve several resources in one
call - see `heimdall.providers._yfinance` for an example.

## Register and use it

```python
import heimdall

heimdall.register(CsvUrlProvider)
result = heimdall.fetch("csv-url", "https://example.com/rates.csv")
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

assert_provider_conformance(
    CsvUrlProvider(), FetchRequest(resource="https://example.com/rates.csv")
)
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
