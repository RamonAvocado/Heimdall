# Heimdall

A host-agnostic **data-provider SDK**. Finance data first (Yahoo Finance OHLCV,
FRED economic series), built so that any data source - yours or the community's -
can plug in behind one small contract.

A provider takes a `FetchRequest` and returns a `FetchResult`: a
[Polars](https://pola.rs) frame, a `SchemaSpec` that describes and validates it,
and some metadata. That's the whole surface. Nothing in the core is
finance-specific; OHLCV bars and economic observations are just two predefined
schemas.

## Install

```bash
pip install heimdall-mimird[fred,yfinance]   # or: heimdall-mimird[all]
```

The core depends only on `polars` (plus a small logging shim). Each provider
pulls its own client library through an extra, so you install only what you use.

## Quick start

```python
import heimdall

# string shorthand -> FetchRequest(resource="DGS10")
result = heimdall.fetch("fred", "DGS10")
result.schema.validate(result.frame)  # raises SchemaError if it doesn't conform
print(result.frame.head())

bars = heimdall.fetch("yfinance", "AAPL", interval="1d")
print(bars.frame.tail())
print(bars.metadata)  # {"ticker": "AAPL", "interval": "1d", "rows": ...}
```

`heimdall.list_providers()` shows what's registered. Providers are registered
automatically when their extra is installed; register your own with
`heimdall.register(MyProvider)`.

## Writing a provider

Subclass `heimdall.Provider`, set `id` + `capabilities`, implement `fetch`. See
[docs/writing-a-provider.md](docs/writing-a-provider.md) for a full worked
example, and run `heimdall.testing.assert_provider_conformance(...)` to check it
against the contract.

## Status

Early. The provider contract and the two bundled providers are usable today. The
ingestion/storage layer, entry-point plugin discovery, and retry/rate-limit
middleware are on the [roadmap](ROADMAP.md).
