"""Schema vocabulary: the :class:`SchemaSpec` / :class:`ColumnSpec` types plus
the canonical spec values.

Two finance shapes plus a catch-all. A provider is free to define its own with
``SchemaSpec`` / ``ColumnSpec``; these exist so common cases share a vocabulary
and the conformance kit can make stronger assertions.
"""

from __future__ import annotations

import polars as pl

from heimdall._contracts import ColumnSpec, SchemaSpec

__all__ = [
    "SchemaSpec",
    "ColumnSpec",
    "OHLCV_BARS",
    "OBSERVATIONS",
    "GENERIC_TABLE",
    "KNOWN_SCHEMAS",
]


OHLCV_BARS = SchemaSpec(
    name="ohlcv.bars",
    columns=(
        ColumnSpec("timestamp", pl.Datetime, nullable=False, description="Bar open time"),
        ColumnSpec("symbol", pl.String, nullable=False, description="Instrument identifier"),
        ColumnSpec("open", pl.Float64, nullable=False),
        ColumnSpec("high", pl.Float64, nullable=False),
        ColumnSpec("low", pl.Float64, nullable=False),
        ColumnSpec("close", pl.Float64, nullable=False),
        ColumnSpec("volume", pl.Float64, nullable=True),
    ),
    time_column="timestamp",
    primary_key=("timestamp", "symbol"),
)


OBSERVATIONS = SchemaSpec(
    name="timeseries.observations",
    columns=(
        ColumnSpec("timestamp", pl.Datetime, nullable=False, description="Observation date"),
        ColumnSpec("series_id", pl.String, nullable=False, description="Upstream series id"),
        ColumnSpec("value", pl.Float64, nullable=False),
    ),
    time_column="timestamp",
    primary_key=("timestamp", "series_id"),
)


GENERIC_TABLE = SchemaSpec(name="table.generic", columns=())


KNOWN_SCHEMAS: dict[str, SchemaSpec] = {
    s.name: s for s in (OHLCV_BARS, OBSERVATIONS, GENERIC_TABLE)
}
