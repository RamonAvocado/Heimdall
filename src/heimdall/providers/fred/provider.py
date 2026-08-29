"""Fetch economic series from FRED.

This uses the public ``fredgraph.csv`` download endpoint, which needs no API
key. The official ``api.stlouisfed.org`` JSON API (vintages, metadata,
pagination) needs ``FRED_API_KEY`` and is the eventual upgrade path - flip
``requires_auth`` / ``required_config`` in :attr:`FredProvider.capabilities`
when that lands.
"""

from __future__ import annotations

from datetime import datetime
from io import StringIO

import httpx
import polars as pl

from heimdall._logging import get_logger
from heimdall._time import utcnow
from heimdall.contracts import FetchRequest, FetchResult
from heimdall.errors import RequestError, UpstreamError
from heimdall.provider import Capabilities, Provider
from heimdall.schemas import OBSERVATIONS

_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_log = get_logger("providers.fred")


class FredProvider(Provider):
    id = "fred"
    capabilities = Capabilities(
        data_kinds=(OBSERVATIONS.name,),
        intervals=(),
        supports_date_range=True,
        requires_auth=False,
    )

    def __init__(self, config: dict | None = None, *, timeout: float = 30.0) -> None:
        super().__init__(config)
        self._timeout = float(self.config("timeout", timeout))

    def fetch(self, request: FetchRequest) -> FetchResult:
        series_id = request.resource.strip()

        try:
            response = httpx.get(
                _CSV_URL,
                params={"id": series_id},
                timeout=self._timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(f"FRED request failed for {series_id!r}: {exc}") from exc

        frame = pl.read_csv(StringIO(response.text), null_values=[".", ""])
        if frame.width < 2:
            raise UpstreamError(f"unexpected FRED CSV for {series_id!r}: columns {frame.columns}")

        date_col = frame.columns[0]
        value_col = next(
            (c for c in frame.columns[1:] if c.lower() == series_id.lower()),
            frame.columns[1],
        )

        normalized = (
            frame.select(
                pl.col(date_col)
                .cast(pl.String)
                .str.strptime(pl.Datetime, strict=False)
                .alias("timestamp"),
                pl.lit(series_id).alias("series_id"),
                pl.col(value_col).cast(pl.Float64, strict=False).alias("value"),
            )
            .drop_nulls(subset=["timestamp", "value"])
            .sort("timestamp")
        )
        normalized = _apply_date_range(normalized, request.start, request.end)

        if normalized.is_empty():
            raise RequestError(
                f"FRED returned no observations for {series_id!r} in the requested range"
            )

        OBSERVATIONS.validate(normalized)
        return FetchResult(
            frame=normalized,
            schema=OBSERVATIONS,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={"source": "fredgraph.csv", "series_id": series_id, "rows": normalized.height},
        )


def _apply_date_range(
    frame: pl.DataFrame, start: datetime | None, end: datetime | None
) -> pl.DataFrame:
    if start is not None:
        frame = frame.filter(pl.col("timestamp") >= pl.lit(start))
    if end is not None:
        frame = frame.filter(pl.col("timestamp") <= pl.lit(end))
    return frame
