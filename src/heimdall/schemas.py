"""Schema vocabulary: the `SchemaSpec` / `ColumnSpec` types plus
the canonical spec values.

Two finance shapes plus a catch-all. A provider is free to define its own with
`SchemaSpec` / `ColumnSpec`; these exist so common cases share a vocabulary
and the conformance kit can make stronger assertions.
"""

from __future__ import annotations

from enum import StrEnum

import polars as pl

from heimdall._contracts import ColumnSpec, SchemaSpec

__all__ = [
    "FUNDAMENTAL_FACTS",
    "GENERIC_TABLE",
    "KNOWN_SCHEMAS",
    "OBSERVATIONS",
    "OHLCV_BARS",
    "ColumnSpec",
    "Kind",
    "SchemaSpec",
]


class Kind(StrEnum):
    """Every kind of data a bundled provider can return; pass one as
    `fetch(..., kind=...)`. Each is a `str`, so `kind="candles"` works too.
    The kind is the returned `SchemaSpec.name`: same kind, same columns, from
    any provider. A third-party provider may use its own plain-string kinds.
    """

    CANDLES = "candles"  # OHLCV bars
    OBSERVATIONS = "observations"  # one value per date (FRED series)
    FUNDAMENTALS = "fundamentals"  # point-in-time normalized metrics (SEC XBRL)
    FINANCIAL_STATEMENTS = "financial_statements"  # raw statement line items
    ANALYST_RATINGS = "analyst_ratings"
    INSIDER_TRADING = "insider_trading"  # Form 4 transactions
    HOLDINGS_13F = "13f_holdings"  # institutional holdings per quarter (SEC 13F-HR)
    FILERS_13F = "13f_filers"  # who filed a 13F-HR in a quarter
    TABLE = "table"  # anything else: constituents, listings, ...


OHLCV_BARS = SchemaSpec(
    name=Kind.CANDLES.value,
    columns=(
        ColumnSpec(
            "timestamp", pl.Datetime, nullable=False, description="Bar open time"
        ),
        ColumnSpec(
            "symbol", pl.String, nullable=False, description="Instrument identifier"
        ),
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
    name=Kind.OBSERVATIONS.value,
    columns=(
        ColumnSpec(
            "timestamp", pl.Datetime, nullable=False, description="Observation date"
        ),
        ColumnSpec(
            "series_id", pl.String, nullable=False, description="Upstream series id"
        ),
        ColumnSpec("value", pl.Float64, nullable=False),
    ),
    time_column="timestamp",
    primary_key=("timestamp", "series_id"),
)


FUNDAMENTAL_FACTS = SchemaSpec(
    name=Kind.FUNDAMENTALS.value,
    columns=(
        ColumnSpec("symbol", pl.String, nullable=False),
        ColumnSpec(
            "metric",
            pl.String,
            nullable=False,
            description="revenue, net_income, eps_diluted, cash, debt, shares_out, ...",
        ),
        ColumnSpec(
            "period_type",
            pl.String,
            nullable=False,
            description="Q = quarter, FY = fiscal year, I = instant (balance sheet)",
        ),
        ColumnSpec("period_end", pl.Date, nullable=False),
        ColumnSpec("value", pl.Float64, nullable=False),
        ColumnSpec(
            "reported_at",
            pl.Date,
            nullable=False,
            description="When it became public (first filing), for point-in-time use",
        ),
    ),
    time_column="period_end",
    primary_key=("symbol", "metric", "period_type", "period_end"),
)


GENERIC_TABLE = SchemaSpec(name=Kind.TABLE.value, columns=())


KNOWN_SCHEMAS: dict[str, SchemaSpec] = {
    s.name: s for s in (OHLCV_BARS, OBSERVATIONS, FUNDAMENTAL_FACTS, GENERIC_TABLE)
}
