"""`mimird`: daily OHLCV bars from a Mimird instance's prices API."""

from __future__ import annotations

from typing import Annotated

import httpx
import polars as pl

from heimdall._contracts import FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._base import (
    Capabilities,
    Provider,
    ProviderMetadata,
    require_interval,
)
from heimdall.schemas import OHLCV_BARS


class MimirdProvider(Provider):
    """Daily bars for a ticker (`AAPL`, `BRK.B`) from a Mimird instance.

    Calls `GET /api/v1/i/prices?symbol=...`, which serves what that instance
    has already stored, so the range is whatever it has ingested.
    """

    metadata = ProviderMetadata(
        name="mimird",
        description="Daily OHLCV bars from a Mimird instance's prices API.",
    )
    capabilities = Capabilities(
        data_kinds=(OHLCV_BARS.name,),
        intervals=("1d",),
        supports_date_range=True,
        requires_auth=True,
    )

    def __init__(
        self,
        *,
        base_url: Annotated[str, "The Mimird instance, e.g. https://mimird.example."],
        api_key: Annotated[str, "A Mimird API key (Settings -> API keys)."],
        timeout: Annotated[float, "HTTP timeout in seconds."] = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _fetch(self, request: FetchRequest) -> FetchResult:
        symbol = request.resource
        interval = require_interval(request, self.capabilities, default="1d")
        if request.start is None or request.end is None:
            raise RequestError("mimird needs both start and end")

        try:
            response = httpx.get(
                f"{self._base_url}/api/v1/i/prices",
                params={
                    "symbol": symbol,
                    "start": request.start.date().isoformat(),
                    "end": request.end.date().isoformat(),
                    "interval": interval,
                },
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Mimird request failed for {symbol!r}: {exc}") from exc
        if response.status_code in (404, 409):
            raise RequestError(f"Mimird has no unique instrument {symbol!r}")
        if response.is_error:
            raise UpstreamError(
                f"Mimird returned {response.status_code} for {symbol!r}: "
                f"{response.text[:200]}"
            )

        candles = response.json()
        if not candles:
            raise RequestError(
                f"Mimird has no bars for {symbol!r} in the requested range"
            )

        frame = pl.DataFrame(candles).select(
            pl.col("timestamp").str.to_datetime(),
            pl.lit(symbol).alias("symbol"),
            *(
                pl.col(c).cast(pl.Float64)
                for c in ("open", "high", "low", "close", "volume")
            ),
        )
        OHLCV_BARS.validate(frame)
        return FetchResult(
            frame=frame,
            schema=OHLCV_BARS,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={"source": self._base_url, "rows": frame.height},
        )
