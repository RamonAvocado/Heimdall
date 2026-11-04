"""`alpaca`: OHLCV bars from Alpaca's market-data API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

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

_TIMEFRAMES = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "1h": "1Hour",
    "1d": "1Day",
    "1wk": "1Week",
    "1mo": "1Month",
}
_COLUMNS = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
# Alpaca's stock history starts in 2016; its own default start is "today".
_HISTORY_START = "2016-01-01T00:00:00Z"


class AlpacaProvider(Provider):
    """Stock bars for a ticker (`AAPL`) from `GET /v2/stocks/{symbol}/bars`.

    Follows `next_page_token` until the range is exhausted. `feed="iex"` works
    on free accounts; `"sip"` needs a paid data subscription.
    """

    metadata = ProviderMetadata(
        name="alpaca",
        description="OHLCV stock bars from Alpaca's market-data API.",
    )
    capabilities = Capabilities(
        data_kinds=(OHLCV_BARS.name,),
        intervals=tuple(_TIMEFRAMES),
        supports_date_range=True,
        requires_auth=True,
        rate_limit_per_min=200,
    )

    def __init__(
        self,
        *,
        api_key_id: Annotated[str, "Alpaca API key id (APCA-API-KEY-ID)."],
        api_secret_key: Annotated[str, "Alpaca API secret (APCA-API-SECRET-KEY)."],
        feed: Annotated[str, "Data feed: 'iex' (free), 'sip' or 'otc'."] = "iex",
        adjustment: Annotated[
            str, "Corporate-action adjustment: raw, split, dividend or all."
        ] = "all",
        base_url: Annotated[str, "Market-data API root."] = (
            "https://data.alpaca.markets"
        ),
        timeout: Annotated[float, "HTTP timeout in seconds."] = 30.0,
    ) -> None:
        self._headers = {
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret_key,
        }
        self._feed = feed
        self._adjustment = adjustment
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout)

    def _fetch(self, request: FetchRequest) -> FetchResult:
        symbol = request.resource
        interval = require_interval(request, self.capabilities, default="1d")
        params: dict[str, Any] = {
            "timeframe": _TIMEFRAMES[interval],
            "start": _rfc3339(request.start) if request.start else _HISTORY_START,
            "feed": self._feed,
            "adjustment": self._adjustment,
            "limit": 10000,
        }
        if request.end is not None:
            params["end"] = _rfc3339(request.end)

        bars: list[dict[str, Any]] = []
        with httpx.Client(headers=self._headers, timeout=self._timeout) as client:
            while True:
                page = self._get(client, symbol, params)
                bars.extend(page.get("bars") or [])
                token = page.get("next_page_token")
                if not token:
                    break
                params["page_token"] = token

        if not bars:
            raise RequestError(f"Alpaca has no bars for {symbol!r} in the range")

        frame = pl.DataFrame(bars).select(
            pl.col("t")
            .str.to_datetime(time_zone="UTC")
            .dt.replace_time_zone(None)
            .alias("timestamp"),
            pl.lit(symbol).alias("symbol"),
            *(pl.col(k).cast(pl.Float64).alias(v) for k, v in _COLUMNS.items()),
        )
        OHLCV_BARS.validate(frame)
        return FetchResult(
            frame=frame,
            schema=OHLCV_BARS,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={
                "symbol": symbol,
                "interval": interval,
                "feed": self._feed,
                "rows": frame.height,
            },
        )

    def _get(
        self, client: httpx.Client, symbol: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = client.get(
                f"{self._base_url}/v2/stocks/{symbol}/bars", params=params
            )
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Alpaca request failed for {symbol!r}: {exc}") from exc
        if response.status_code in (400, 404, 422):
            raise RequestError(f"Alpaca rejected {symbol!r}: {response.text[:200]}")
        if response.is_error:
            raise UpstreamError(
                f"Alpaca returned {response.status_code} for {symbol!r}: "
                f"{response.text[:200]}"
            )
        data: dict[str, Any] = response.json()
        return data


def _rfc3339(value: datetime) -> str:
    """Alpaca wants an offset on every timestamp; a naive one is taken as UTC."""
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
