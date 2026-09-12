"""Shared display + file-sink helpers for the sandbox scripts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from heimdall import FetchResult

SCRATCH = Path(__file__).resolve().parent / "scratch"


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", text).strip("-")
    return cleaned or "resource"


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def show(result: FetchResult, *, rows: int = 10) -> None:
    """Print a FetchResult to the terminal: header, schema check, then the frame."""
    frame = result.frame
    print(f"provider   : {result.provider_id}")
    print(f"resource   : {result.request.resource}")
    if result.request.interval:
        print(f"interval   : {result.request.interval}")
    print(f"schema     : {result.schema.name}")
    print(f"shape      : {frame.height} rows x {frame.width} cols")
    print(f"retrieved  : {result.retrieved_at:%Y-%m-%d %H:%M:%SZ}")
    print(f"metadata   : {dict(result.metadata)}")
    try:
        result.schema.validate(frame)
        print("validate   : OK")
    except Exception as exc:  # noqa: BLE001 - sandbox: surface whatever went wrong
        print(f"validate   : FAIL - {exc}")
    print()
    with pl.Config(tbl_rows=rows, tbl_width_chars=120):
        print(frame.head(rows))
        if frame.height > rows:
            print(f"... {frame.height - rows} more rows ...")
            print(frame.tail(3))


def _target(result: FetchResult, ext: str) -> Path:
    SCRATCH.mkdir(exist_ok=True)
    name = f"{result.provider_id}_{_slug(result.request.resource)}_{_stamp()}.{ext}"
    return SCRATCH / name


def to_parquet(result: FetchResult) -> Path:
    """Write ``result.frame`` to ``sandbox/scratch/`` as parquet; return the path."""
    path = _target(result, "parquet")
    result.frame.write_parquet(path)
    print(f"wrote {result.frame.height} rows -> {path}")
    return path


def to_csv(result: FetchResult) -> Path:
    """Write ``result.frame`` to ``sandbox/scratch/`` as CSV; return the path."""
    path = _target(result, "csv")
    result.frame.write_csv(path)
    print(f"wrote {result.frame.height} rows -> {path}")
    return path


# --- Database sink (not wired yet) -----------------------------------------------
# Heimdall keeps `fetch()` pure and leaves persistence to the host. To push a
# FetchResult into a real database from the sandbox:
#
#   1. add a dependency group in pyproject.toml, e.g.
#        [dependency-groups]
#        sandbox = ["sqlalchemy>=2"]                          # SQLite (driver is stdlib)
#        # sandbox = ["sqlalchemy>=2", "psycopg[binary]>=3"]  # PostgreSQL
#      then:  uv sync --group sandbox
#   2. set HEIMDALL_SANDBOX_DB_URL, e.g. sqlite:///sandbox/scratch/heimdall.db
#   3. uncomment:
#
# import os
#
# def to_database(
#     result: FetchResult, *, url: str | None = None, table: str | None = None
# ) -> None:
#     url = url or os.environ.get(
#         "HEIMDALL_SANDBOX_DB_URL", "sqlite:///sandbox/scratch/heimdall.db"
#     )
#     table = table or f"{result.provider_id}_{_slug(result.request.resource)}"
#     result.frame.write_database(table, url, if_table_exists="replace")
#     print(f"wrote {result.frame.height} rows -> {table} @ {url}")
