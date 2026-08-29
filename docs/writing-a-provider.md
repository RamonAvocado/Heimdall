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
from heimdall.contracts import ColumnSpec, SchemaSpec
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

    def fetch(self, request: FetchRequest) -> FetchResult:
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

## Register and use it

```python
import heimdall

heimdall.register(CsvUrlProvider)
result = heimdall.fetch("csv-url", "https://example.com/rates.csv")
```

For config/secrets, declare `required_config` in `Capabilities` and pass values
at registration - never read the environment inside the provider:

```python
heimdall.register(MyProvider, config=heimdall.config_from_env("HEIMDALL_MYPROVIDER_"))
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
- Missing `required_config` raises `ConfigError` at construction.
