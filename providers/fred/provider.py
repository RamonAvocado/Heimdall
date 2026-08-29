from __future__ import annotations

from io import StringIO

import httpx
import polars as pl

from core.providers.base import BaseDataProvider, require_dataset_field
from models.db import Dataset


class FredProvider(BaseDataProvider):
    provider_code = "fred"

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def fetch(self, dataset: Dataset) -> pl.DataFrame:
        if dataset.dataset_type != "essential":
            raise ValueError("FRED does not provide OHLCV market datasets.")

        series_id = require_dataset_field(dataset, "remote_identifier")
        response = httpx.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            params={"id": series_id},
            timeout=self._timeout,
        )
        response.raise_for_status()

        frame = pl.read_csv(StringIO(response.text))
        value_column = next(
            (
                column
                for column in frame.columns
                if column.lower() == series_id.lower()
            ),
            None,
        )
        if value_column is None:
            raise ValueError(f"FRED response is missing the series column: {series_id}")

        return (
            frame.rename(
                {
                    "DATE": "date",
                    value_column: "value",
                }
            )
            .with_columns(
                pl.col("date").alias("date"),
                pl.col("value").cast(pl.Float64, strict=False),
                pl.lit(_series_label(dataset)).alias("asset"),
                pl.lit(series_id).alias("symbol"),
                pl.lit(self.provider_code).alias("source"),
            )
            .drop_nulls(subset=["value"])
            .with_columns(
                pl.col("date").str.strptime(pl.Datetime, strict=False).alias("timestamp")
            )
            .select("date", "asset", "symbol", "source", "value", "timestamp")
            .sort("timestamp")
        )


def _series_label(dataset: Dataset) -> str:
    if dataset.code.startswith("essential."):
        return dataset.code.removeprefix("essential.").lower()
    return dataset.name.lower()
