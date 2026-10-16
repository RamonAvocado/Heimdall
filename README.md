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
pip install heimdall-mimird[fred,yfinance,sp500]   # or: heimdall-mimird[all]
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

sp500 = heimdall.fetch("sp500", "constituents")
print(sp500.frame.select("symbol", "security", "gics_sector").head())

# a list of resources -> BatchResult(.ok / .failed keyed by resource, + combined .frame)
batch = heimdall.fetch("yfinance", ["AAPL", "MSFT", "NVDA"], interval="1d")
print(batch.frame.height, list(batch.failed))

# afetch() is the async mirror of both forms
result = await heimdall.afetch("fred", ["DGS10", "GDP"])
```

`heimdall.list_providers()` shows what's registered. Providers are registered
automatically when their extra is installed; register your own with
`heimdall.register(MyProvider)` (pass a constructed instance,
`heimdall.register(MyProvider(timeout=10))`, to override its `__init__`
defaults). Asking `heimdall.fetch(...)` for a provider whose extra is missing
raises `ProviderNotFound` telling you which extra to install, rather than
failing blank.

## Writing a provider

Subclass `heimdall.Provider`, set `metadata` + `capabilities`, implement
`_fetch` (one resource - batch, async, and failure collection come for free).
See [CONTRIBUTING.md](CONTRIBUTING.md) for a full worked example, and run
`heimdall.testing.assert_provider_conformance(...)` to check it against the
contract. Third-party packages register through the `heimdall.providers`
entry-point group, picked up automatically on first use.

## Explore the catalog

`heimdall.catalog()` describes every bundled provider (whose extra is installed)
as JSON-safe data: id, description, author, source, `__init__` parameters and
capabilities. The Mimird docs are built from it, and an MCP server can call it
on the installed package:

```bash
uv run --extra all python -m heimdall > catalog.json
```

## Status

Early. The provider contract and the bundled providers are usable today. The
ingestion/storage layer and retry/rate-limit middleware are on the
[roadmap](ROADMAP.md).
