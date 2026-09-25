# Roadmap

Legend: `[x]` shipped · `[~]` partially built · `[ ]` planned

## Shipped

- [x] **Core SDK** - `FetchRequest` / `FetchResult` / `SchemaSpec` contract,
      `Provider` base + `Capabilities`, `ProviderRegistry` with explicit
      registration, error hierarchy, `heimdall.fetch(...)`.
- [x] **Bundled providers** - `fred` (public `fredgraph.csv` endpoint, no key)
      and `yfinance` (OHLCV via the `yfinance` library), each behind an extra.
- [x] **Provider conformance kit** - `heimdall.testing.assert_provider_conformance`
  - `ProviderContractTests`, behind the `testing` extra. This is the "testing
    harness for provider authors" - third parties prove their provider fits the
    spec by running it.
- [x] **Tooling** - ruff, mypy, pytest (with a `network` marker), GitHub Actions CI.
- [x] **Dev sandbox** - `sandbox/` with a `python -m sandbox` runner and example
      scripts; results print to the terminal and can be dumped to parquet / CSV.
- [x] **Batch + async fetch** - `fetch()` / `heimdall.fetch()` take one resource
      or a list (a list returns a `BatchResult` that collects per-resource
      failures); `afetch()` is the async mirror (blocking work in a worker thread,
      lists fanned out concurrently). Providers still implement only `_fetch`;
      `_fetch_many` + `native_batch` is an opt-in override for upstreams with a real
      multi-resource endpoint (yfinance uses it).

## Planned (next)

- [ ] **Conformance kit polish** - recorded-fixture helpers so third parties can
      write offline contract tests without hand-rolling mocks.
- [ ] **Docs** - expand `docs/writing-a-provider.md` with a schema-authoring
      section.

## Candidate ideas (evaluated, not yet scheduled)

- [~] **Entry-point plugin discovery** - `ProviderRegistry.load_entry_points()`
  already works; wire a documented `heimdall.providers` entry-point group and add
  a `@heimdall.provider` decorator so `pip install heimdall-stripe` auto-registers
  with the core package. Single biggest driver of ecosystem growth (cf. dlt,
  pytest, SQLAlchemy dialects).
- [~] **Config & credentials layer** - providers take typed keyword args on their
  own `__init__`. Add `.env` loading and a pluggable secret-source hook
  (env / file / secret manager) so provider authors don't reinvent it.
- [~] **Finer error taxonomy** - split `UpstreamError` into `ProviderAuthError` /
  `ProviderRateLimitError` / `ProviderTransientError` so orchestration code can
  react generically: retry vs fail vs backoff.
- [ ] **Rate limiting / backpressure** - a shared limiter providers opt into;
      make `Capabilities.rate_limit_per_min` enforced rather than advisory. Part of a
      middleware stack that wraps `fetch()` host-side (retry + rate-limit + cache).
- [ ] **State / checkpoint store** - a pluggable interface (file / DB / redis) for
      "last synced cursor", so incremental sync is usable in production. Needs a
      cursor concept in the contract (`FetchRequest.cursor` + a next-cursor on
      `FetchResult`). Larger design item.
- [ ] **Observability hooks** - a logging/metrics callback protocol (records
      fetched, latency, errors) that plugs into whatever monitoring the host already
      runs. Overlaps the middleware work.
- [ ] **`create-provider` scaffolder** - a `heimdall new-provider <name>` command
      or a cookiecutter template that emits a provider package skeleton plus its
      conformance test. Directly lowers the bar for third-party contributors.
- [ ] **`heimdall.ingest`** - persist `FetchResult`s: parquet tiers + a JSON
      manifest, plus the transform set (`diff_1`, `pct_change_1`, `sma_20`, `sma_50`).
      Starting point is parked at `docs/legacy/essential.py`.
- [ ] **FRED official API** - swap/augment the CSV endpoint with
      `api.stlouisfed.org` (needs `FRED_API_KEY` -> an `api_key` keyword on
      `FredProvider.__init__`), giving vintages, metadata, and pagination.
- [ ] **Packaging split** - break `heimdall-core` and each provider into separate
      distributions, if the boundaries hold up.


## NEW PROVIDERS

- [ ] **ADD SEC INSIDER TRADING PROVIDER**

- [ ] **ADD OWN MIMIRD PROVIDER**
