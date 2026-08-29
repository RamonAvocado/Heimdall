"""Fetch OHLCV bars from Yahoo Finance via the ``yfinance`` library."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import yfinance as yf

from heimdall._logging import get_logger
from heimdall._time import utcnow
from heimdall.contracts import FetchRequest, FetchResult
from heimdall.errors import RequestError, UpstreamError
from heimdall.provider import Capabilities, Provider, require_interval
from heimdall.schemas import OHLCV_BARS

_log = get_logger("providers.yfinance")

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_RENAME = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Date": "timestamp",
    "Datetime": "timestamp",
    "index": "timestamp",
}
_PRICE_COLS = ("open", "high", "low", "close")


class YahooFinanceProvider(Provider):
    id = "yfinance"
    capabilities = Capabilities(
        data_kinds=(OHLCV_BARS.name,),
        intervals=("1d", "1h", "1wk", "1mo"),
        supports_date_range=True,
        requires_auth=False,
    )

    def fetch(self, request: FetchRequest) -> FetchResult:
        ticker = request.resource.strip()
        interval = require_interval(request, self.capabilities, default="1d")
        start = request.start or _EPOCH
        end = request.end or utcnow()

        try:
            raw = yf.download(
                tickers=ticker,
                start=start.date().isoformat(),
                end=end.date().isoformat(),
                interval=interval,
                auto_adjust=True,
                progress=False,
            )
        except Exception as exc:  # noqa: BLE001 - yfinance raises a grab-bag of types
            raise UpstreamError(f"yfinance download failed for {ticker!r}: {exc}") from exc

        if raw is None or raw.empty:
            raise RequestError(f"yfinance returned no data for {ticker!r}")

        if getattr(raw.columns, "nlevels", 1) > 1:
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.reset_index().rename(columns=_RENAME)

        frame = pl.from_pandas(raw)
        missing = {"timestamp", *_PRICE_COLS} - set(frame.columns)
        if missing:
            raise UpstreamError(
                f"yfinance frame for {ticker!r} is missing columns {sorted(missing)}"
            )

        exprs = [
            pl.col("timestamp").cast(pl.Datetime),
            pl.lit(ticker).alias("symbol"),
            *(pl.col(c).cast(pl.Float64) for c in _PRICE_COLS),
        ]
        if "volume" in frame.columns:
            exprs.append(pl.col("volume").cast(pl.Float64))
        else:
            exprs.append(pl.lit(None, dtype=pl.Float64).alias("volume"))

        frame = (
            frame.with_columns(exprs)
            .select("timestamp", "symbol", *_PRICE_COLS, "volume")
            .sort("timestamp")
        )

        valid = frame.filter(pl.all_horizontal(*(pl.col(c).is_not_null() for c in _PRICE_COLS)))
        dropped = frame.height - valid.height
        if dropped:
            _log.warning("dropped null OHLC rows", dropped=dropped, ticker=ticker)
        if valid.is_empty():
            raise RequestError(f"no valid OHLC rows for {ticker!r}")

        OHLCV_BARS.validate(valid)
        return FetchResult(
            frame=valid,
            schema=OHLCV_BARS,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={"ticker": ticker, "interval": interval, "rows": valid.height},
        )
