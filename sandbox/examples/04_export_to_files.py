"""Fetch, print, and write the frame to parquet + CSV in sandbox/scratch/.

Needs `heimdall-mimird[fred]`.

    uv run python sandbox/examples/04_export_to_files.py
"""

from __future__ import annotations

import pathlib
import sys

import polars as pl

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sandbox._helpers import show, to_csv, to_parquet  # noqa: E402

import heimdall  # noqa: E402

result = heimdall.fetch("fred", "DGS2")
show(result, rows=5)

parquet_path = to_parquet(result)
to_csv(result)

print("\nread back:")
print(pl.read_parquet(parquet_path).tail(3))
