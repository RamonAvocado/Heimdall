"""The provider contract: what goes in (:class:`FetchRequest`) and what comes
out (:class:`FetchResult`), plus the :class:`SchemaSpec` that describes and
validates a returned frame.

These types are deliberately domain-agnostic. Finance shapes (OHLCV bars,
economic observations) are ordinary :class:`SchemaSpec` values defined in
:mod:`heimdall.schemas`; a non-finance provider just defines its own.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import polars as pl

from heimdall.errors import SchemaError

__all__ = [
    "FetchRequest",
    "ColumnSpec",
    "SchemaSpec",
    "FetchResult",
]


@dataclass(frozen=True, slots=True)
class FetchRequest:
    """A request for data from a single provider.

    ``resource`` is provider-specific: a ticker for yfinance, a series id for
    FRED, an endpoint key for something else. Everything else is optional and
    the provider decides whether it is meaningful; unknown knobs go in
    ``params``.
    """

    resource: str
    interval: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.resource, str) or not self.resource.strip():
            raise ValueError("FetchRequest.resource must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One column in a :class:`SchemaSpec`."""

    name: str
    dtype: pl.DataType | type[pl.DataType]
    nullable: bool = True
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SchemaSpec:
    """A named, validatable description of a tabular result.

    ``validate`` is intentionally strict about the things downstream code
    relies on (columns exist, dtypes line up, keys are unique, the time axis is
    ordered) and silent about everything else (extra columns are fine).
    """

    name: str
    columns: tuple[ColumnSpec, ...]
    time_column: str | None = None
    primary_key: tuple[str, ...] = ()

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def validate(self, frame: pl.DataFrame) -> None:
        """Raise :class:`~heimdall.errors.SchemaError` if ``frame`` does not
        conform. ``GENERIC_TABLE`` (no declared columns) only checks that the
        frame is non-empty.
        """
        if not isinstance(frame, pl.DataFrame):
            raise SchemaError(f"{self.name}: expected a polars DataFrame, got {type(frame)!r}")

        if not self.columns:
            if frame.height == 0:
                raise SchemaError(f"{self.name}: frame has no rows")
            return

        actual = frame.schema
        missing = [c.name for c in self.columns if c.name not in actual]
        if missing:
            raise SchemaError(f"{self.name}: frame is missing columns {missing}")

        for col in self.columns:
            if not _dtype_matches(actual[col.name], col.dtype):
                raise SchemaError(
                    f"{self.name}: column {col.name!r} has dtype {actual[col.name]}, "
                    f"expected {col.dtype}"
                )
            if not col.nullable and frame[col.name].null_count() > 0:
                raise SchemaError(f"{self.name}: non-nullable column {col.name!r} contains nulls")

        if self.time_column is not None:
            series = frame[self.time_column]
            if series.null_count() > 0:
                raise SchemaError(f"{self.name}: time column {self.time_column!r} contains nulls")
            if not series.is_sorted():
                raise SchemaError(
                    f"{self.name}: time column {self.time_column!r} is not sorted ascending"
                )

        if self.primary_key:
            keys = list(self.primary_key)
            if frame.n_unique(subset=keys) != frame.height:
                raise SchemaError(f"{self.name}: primary key {keys} is not unique")


@dataclass(frozen=True, slots=True)
class FetchResult:
    """What every :meth:`~heimdall.provider.Provider.fetch` returns."""

    frame: pl.DataFrame
    schema: SchemaSpec
    provider_id: str
    request: FetchRequest
    retrieved_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _dtype_matches(
    actual: pl.DataType,
    expected: pl.DataType | type[pl.DataType],
) -> bool:
    try:
        if actual == expected:
            return True
    except (TypeError, ValueError):
        pass
    try:
        expected_base = expected if isinstance(expected, type) else expected.base_type()
        return actual.base_type() == expected_base
    except (TypeError, ValueError, AttributeError):
        return False
