from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from heimdall.contracts import (
    BatchResult,
    ColumnSpec,
    FetchRequest,
    FetchResult,
    SchemaSpec,
)
from heimdall.errors import RequestError, SchemaError
from heimdall.schemas import OBSERVATIONS


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


def _obs_result(series_id: str) -> FetchResult:
    frame = pl.DataFrame(
        {
            "timestamp": [datetime(2024, 1, 1), datetime(2024, 1, 2)],
            "series_id": [series_id, series_id],
            "value": [1.0, 2.0],
        }
    ).with_columns(pl.col("timestamp").cast(pl.Datetime))
    return FetchResult(
        frame=frame,
        schema=OBSERVATIONS,
        provider_id="dummy",
        request=FetchRequest(resource=series_id),
        retrieved_at=datetime.now(UTC),
    )


def test_batch_result_frame_concatenates_ok_frames() -> None:
    batch = BatchResult(ok={"A": _obs_result("A"), "B": _obs_result("B")}, failed={})
    assert bool(batch) and len(batch) == 2
    assert batch.frame.height == 4
    assert set(batch.frame["series_id"].unique().to_list()) == {"A", "B"}


def test_batch_result_frame_raises_when_all_failed() -> None:
    batch = BatchResult(ok={}, failed={"A": RequestError("nope")})
    assert not batch
    with pytest.raises(RequestError, match="no successful results"):
        _ = batch.frame
