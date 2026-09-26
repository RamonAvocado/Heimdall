"""Fetch OHLCV bars from Yahoo Finance via the ``yfinance`` library."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import polars as pl
import yfinance as yf

from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall._logging import get_logger
from heimdall._provider import Capabilities, Provider, require_interval
from heimdall._time import utcnow
from heimdall.errors import HeimdallError, RequestError, UpstreamError
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
    native_batch = True
    capabilities = Capabilities(
        data_kinds=(OHLCV_BARS.name,),
        intervals=("1d", "1h", "1wk", "1mo"),
        supports_date_range=True,
        requires_auth=False,
    )

    def _fetch(self, request: FetchRequest) -> FetchResult:
        ticker = request.resource
        interval = require_interval(request, self.capabilities, default="1d")

        try:
            raw = yf.download(
                tickers=ticker,
                start=(request.start or _EPOCH).date().isoformat(),
                end=(request.end or utcnow()).date().isoformat(),
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
        return self._normalize(raw, ticker, interval, request)

    def _fetch_many(self, requests: list[FetchRequest]) -> BatchResult:
        if len(requests) == 1:  # no need for a multi-ticker download / column slicing
            req = requests[0]
            try:
                return BatchResult({req.resource: self._fetch(req)}, {})
            except HeimdallError as exc:
                return BatchResult({}, {req.resource: exc})

        tickers = [r.resource for r in requests]
        interval = require_interval(requests[0], self.capabilities, default="1d")
        start = min((r.start for r in requests if r.start is not None), default=_EPOCH)
        end = max((r.end for r in requests if r.end is not None), default=utcnow())

        try:
            raw = yf.download(
                tickers=" ".join(tickers),
                start=start.date().isoformat(),
                end=end.date().isoformat(),
                interval=interval,
                auto_adjust=True,
                progress=False,
                group_by="ticker",
            )
        except Exception as exc:  # noqa: BLE001 - yfinance raises a grab-bag of types
            raise UpstreamError(f"yfinance batch download failed for {tickers}: {exc}") from exc

        ok: dict[str, FetchResult] = {}
        failed: dict[str, Exception] = {}
        for request in requests:
            ticker = request.resource
            sub = _slice_ticker(raw, ticker)
            if sub is None or sub.empty or sub.dropna(how="all").empty:
                failed[ticker] = RequestError(f"yfinance returned no data for {ticker!r}")
                continue
            try:
                ok[ticker] = self._normalize(sub, ticker, interval, request)
            except HeimdallError as exc:
                failed[ticker] = exc
        return BatchResult(ok, failed)

    def _normalize(
        self, raw: Any, ticker: str, interval: str, request: FetchRequest
    ) -> FetchResult:
        """Turn a single-ticker pandas frame (OHLCV columns, datetime index)
        into a schema-valid :class:`FetchResult`.
        """
        pdf = raw.reset_index().rename(columns=_RENAME)
        frame = pl.from_pandas(pdf)

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


def _slice_ticker(raw: Any, ticker: str) -> Any | None:
    """Pull one ticker's sub-frame out of a multi-ticker download. Handles
    either column-MultiIndex order ((ticker, field) or (field, ticker)).
    Returns ``None`` if the ticker is absent.
    """
    columns = getattr(raw, "columns", None)
    if columns is None:
        return None
    if getattr(columns, "nlevels", 1) == 1:
        return raw  # single ticker: yfinance did not build a MultiIndex
    for level in range(columns.nlevels):
        if ticker in columns.get_level_values(level):
            return raw.xs(ticker, axis=1, level=level)
    return None
