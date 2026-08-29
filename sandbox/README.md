# sandbox/

A dev-only playground for exercising Heimdall providers by hand. **Not shipped** -
the package build only includes `src/heimdall`.

- **Committed** (`play.py`, `_helpers.py`, `examples/`) - reference material, kept
  tidy and lint-clean.
- **`scratch/`** - git-ignored. Put your own throwaway scripts and any generated
  `.parquet` / `.csv` / `.db` files here.

Run everything from the repo root, after `uv sync --extra all --group dev`.

## The runner

```bash
uv run python -m sandbox --list
uv run python -m sandbox fred DGS10
uv run python -m sandbox yfinance AAPL --interval 1d --rows 5
uv run python -m sandbox fred DGS10 --start 2020-01-01 --to-parquet --to-csv
```

It calls `heimdall.fetch(provider, resource, ...)`, prints a header + schema
check + the frame via `_helpers.show()`, and optionally writes the frame to
`sandbox/scratch/`. Provider errors print as one line, no traceback.

## The examples

```bash
uv run python sandbox/examples/01_fred_to_terminal.py
uv run python sandbox/examples/03_custom_provider.py      # no network
```

| file | shows |
|---|---|
| `01_fred_to_terminal.py` | fetch a FRED series, print it |
| `02_yfinance_to_terminal.py` | fetch OHLCV bars, print them |
| `03_custom_provider.py` | define + register a provider inline, then conformance-check it |
| `04_export_to_files.py` | fetch, write parquet + CSV to `scratch/`, read back |
| `05_provider_with_config.py` | `required_config`, `config_from_env`, and the `ConfigError` when a key is missing |

## Exporting to a real database

The file sinks (`to_parquet`, `to_csv`) work out of the box. `_helpers.py` has a
commented `to_database()` using `polars.DataFrame.write_database`; enable it by
adding a `sandbox` dependency group (`sqlalchemy>=2` + a driver) and setting
`HEIMDALL_SANDBOX_DB_URL`. Details are in the comment block.
