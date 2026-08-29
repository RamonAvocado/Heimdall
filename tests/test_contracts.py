from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from heimdall.contracts import ColumnSpec, FetchRequest, SchemaSpec
from heimdall.errors import SchemaError


def test_fetch_request_rejects_empty_resource() -> None:
    with pytest.raises(ValueError):
        FetchRequest(resource="")
    with pytest.raises(ValueError):
        FetchRequest(resource="   ")


def test_fetch_request_is_frozen() -> None:
    req = FetchRequest(resource="AAPL")
    with pytest.raises(AttributeError):
        req.resource = "MSFT"  # type: ignore[misc]


_SPEC = SchemaSpec(
    name="demo",
    columns=(
        ColumnSpec("timestamp", pl.Datetime, nullable=False),
        ColumnSpec("key", pl.String, nullable=False),
        ColumnSpec("value", pl.Float64, nullable=True),
    ),
    time_column="timestamp",
    primary_key=("timestamp", "key"),
)


def _good_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [datetime(2024, 1, 1), datetime(2024, 1, 2)],
            "key": ["a", "a"],
            "value": [1.0, None],
        }
    ).with_columns(pl.col("timestamp").cast(pl.Datetime))


def test_validate_accepts_conforming_frame() -> None:
    _SPEC.validate(_good_frame())


def test_validate_allows_extra_columns() -> None:
    _SPEC.validate(_good_frame().with_columns(pl.lit("x").alias("extra")))


def test_validate_rejects_missing_column() -> None:
    with pytest.raises(SchemaError, match="missing columns"):
        _SPEC.validate(_good_frame().drop("value"))


def test_validate_rejects_wrong_dtype() -> None:
    bad = _good_frame().with_columns(pl.col("value").cast(pl.Int64))
    with pytest.raises(SchemaError, match="dtype"):
        _SPEC.validate(bad)


def test_validate_rejects_nulls_in_non_nullable() -> None:
    bad = _good_frame().with_columns(
        pl.when(pl.col("key") == "a").then(None).otherwise(pl.col("key")).alias("key")
    )
    with pytest.raises(SchemaError, match="non-nullable"):
        _SPEC.validate(bad)


def test_validate_rejects_unsorted_time_column() -> None:
    bad = _good_frame().reverse()
    with pytest.raises(SchemaError, match="not sorted"):
        _SPEC.validate(bad)


def test_validate_rejects_duplicate_primary_key() -> None:
    bad = pl.DataFrame(
        {
            "timestamp": [datetime(2024, 1, 1), datetime(2024, 1, 1)],
            "key": ["a", "a"],
            "value": [1.0, 2.0],
        }
    ).with_columns(pl.col("timestamp").cast(pl.Datetime))
    with pytest.raises(SchemaError, match="primary key"):
        _SPEC.validate(bad)


def test_generic_table_only_checks_non_empty() -> None:
    from heimdall.schemas import GENERIC_TABLE

    GENERIC_TABLE.validate(pl.DataFrame({"anything": [1]}))
    with pytest.raises(SchemaError, match="no rows"):
        GENERIC_TABLE.validate(pl.DataFrame({"anything": []}))
