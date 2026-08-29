# Roadmap

## Done

- **Core SDK.** `FetchRequest` / `FetchResult` / `SchemaSpec` contract,
  `Provider` base + `Capabilities`, `ProviderRegistry` with explicit
  registration, error hierarchy, `heimdall.fetch(...)`.
- **Bundled providers.** `fred` (public `fredgraph.csv` endpoint, no key) and
  `yfinance` (OHLCV via the `yfinance` library), each behind an extra.
- **Conformance kit.** `heimdall.testing.assert_provider_conformance` +
  `ProviderContractTests`.
- Tooling: ruff, mypy, pytest (with a `network` marker), GitHub Actions CI.

## Next

- **Conformance kit polish.** Recorded-fixture helpers so third parties can
  write offline contract tests without hand-rolling mocks.
- **Docs.** Expand `docs/writing-a-provider.md` with a schema-authoring section.

## Later (deferred by design)

- **Entry-point discovery.** `ProviderRegistry.load_entry_points` already works;
  wire it into a documented `heimdall.providers` entry-point group so a
  `pip install`ed community package auto-registers.
- **Middleware.** Promote `heimdall._retry` into a small composable stack:
  retry, rate limiting (`Capabilities.rate_limit_per_min` is the hint), response
  caching. `fetch()` stays pure; these wrap it host-side.
- **`heimdall.ingest`.** A separate package that persists `FetchResult`s:
  RAW / TRANSFORMED / FAST_RENDER parquet tiers + a JSON manifest, plus the
  transform set (`diff_1`, `pct_change_1`, `sma_20`, `sma_50`). Starting point is
  parked at `docs/legacy/essential.py`.
- **FRED official API.** Swap/augment the CSV endpoint with
  `api.stlouisfed.org` (needs `FRED_API_KEY` -> `Capabilities.required_config`),
  giving vintages, metadata, and pagination.
- **CLI.** `heimdall fetch <provider> <resource>` writing parquet/CSV.
- **Packaging split.** If the boundaries hold up, break `heimdall-core` and each
  provider into separate distributions.
