# Contributing

## Dev setup

```bash
uv sync --extra all --group dev
```

## Checks (what CI runs)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/heimdall
uv run pytest -m "not network"      # offline suite
uv run pytest -m network            # hits real FRED / Yahoo; run before releases
```

## Adding a provider

First-party providers live under `src/heimdall/providers/<name>/` and are
registered by a module-level `_register(registry)` hook (see the `fred` and
`yfinance` packages). Their client library goes in a matching
`[project.optional-dependencies]` extra so `import heimdall` still works without
it.

Every provider must:

1. Subclass `heimdall.Provider`, set a stable `id` and a `Capabilities`.
2. Return a `FetchResult` whose `frame` passes `schema.validate()` - reuse
   `heimdall.schemas.OHLCV_BARS` / `OBSERVATIONS` or define your own `SchemaSpec`.
3. Raise `heimdall.errors.*` (`RequestError`, `UpstreamError`, `ConfigError`),
   never bare `ValueError` / `KeyError`.
4. Pass the conformance suite. Add a test module that subclasses
   `heimdall.testing.ProviderContractTests` plus a `@pytest.mark.network`
   smoke test.

`heimdall.testing` needs pytest. It is not part of the base install - an
out-of-tree provider package gets it with `pip install heimdall-mimird[testing]`.
Heimdall's own `dev` group already includes pytest.

See `docs/writing-a-provider.md` for a full example.
