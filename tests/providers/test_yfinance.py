from __future__ import annotations

from datetime import datetime

import pandas as pd
import polars as pl
import pytest
import yfinance as yf

from heimdall.contracts import BatchResult, FetchRequest
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._yfinance import YahooFinanceProvider
from heimdall.schemas import OHLCV_BARS
from heimdall.testing import ProviderContractTests


def _fake_frame(ticker: str = "AAPL", rows: int = 5) -> pd.DataFrame:
    index = pd.DatetimeIndex([datetime(2024, 1, 1 + i) for i in range(rows)], name="Date")
    columns = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], [ticker]])
    data = [[10.0 + i, 11.0 + i, 9.0 + i, 10.5 + i, 1000 + i] for i in range(rows)]
    return pd.DataFrame(data, index=index, columns=columns)


def _fake_multi_frame(tickers: tuple[str, ...] = ("AAPL", "MSFT"), rows: int = 5) -> pd.DataFrame:
    """Shape of ``yf.download(..., group_by="ticker")`` for several tickers:
    a ``(ticker, field)`` column MultiIndex."""
    index = pd.DatetimeIndex([datetime(2024, 1, 1 + i) for i in range(rows)], name="Date")
    fields = ["Open", "High", "Low", "Close", "Volume"]
    columns = pd.MultiIndex.from_product([list(tickers), fields])
    data = [[10.0 + i + j for j in range(len(fields) * len(tickers))] for i in range(rows)]
    return pd.DataFrame(data, index=index, columns=columns)


@pytest.fixture
def patched_download(monkeypatch: pytest.MonkeyPatch):
    def _install(frame: pd.DataFrame) -> None:
        monkeypatch.setattr(yf, "download", lambda *a, **k: frame)

    return _install


def test_fetch_normalizes_to_ohlcv(patched_download) -> None:
    patched_download(_fake_frame())
    result = YahooFinanceProvider().fetch("AAPL")

    assert result.provider_id == "yfinance"
    assert result.schema is OHLCV_BARS
    OHLCV_BARS.validate(result.frame)
    assert result.frame.columns == ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
    assert result.frame["symbol"].unique().to_list() == ["AAPL"]
    assert result.frame["close"].dtype == pl.Float64
    assert result.metadata["interval"] == "1d"


def test_unsupported_interval_raises_request_error(patched_download) -> None:
    patched_download(_fake_frame())
    with pytest.raises(RequestError):
        YahooFinanceProvider().fetch("AAPL", interval="3s")


def test_empty_download_raises_request_error(patched_download) -> None:
    patched_download(pd.DataFrame())
    with pytest.raises(RequestError):
        YahooFinanceProvider().fetch("AAPL")


def test_download_exception_becomes_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(yf, "download", boom)
    with pytest.raises(UpstreamError):
        YahooFinanceProvider().fetch("AAPL")


def test_null_ohlc_rows_dropped(patched_download) -> None:
    frame = _fake_frame(rows=4)
    frame.iloc[1, frame.columns.get_loc(("Open", "AAPL"))] = None
    patched_download(frame)
    result = YahooFinanceProvider().fetch("AAPL")
    assert result.frame.height == 3


def test_fetch_many_uses_native_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yf, "download", lambda *a, **k: _fake_multi_frame(("AAPL", "MSFT")))

    batch = YahooFinanceProvider().fetch(["AAPL", "MSFT"], interval="1d")

    assert isinstance(batch, BatchResult)
    assert set(batch.ok) == {"AAPL", "MSFT"}
    assert not batch.failed
    assert set(batch.frame["symbol"].unique().to_list()) == {"AAPL", "MSFT"}
    # each per-ticker frame is individually schema-valid
    for result in batch.ok.values():
        OHLCV_BARS.validate(result.frame)


def test_fetch_many_collects_missing_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yf, "download", lambda *a, **k: _fake_multi_frame(("AAPL",)))

    batch = YahooFinanceProvider().fetch(["AAPL", "BADX"], interval="1d")

    assert list(batch.ok) == ["AAPL"]
    assert list(batch.failed) == ["BADX"]
    assert isinstance(batch.failed["BADX"], RequestError)


class TestYFinanceContract(ProviderContractTests):
    @pytest.fixture(autouse=True)
    def _patch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(yf, "download", lambda *a, **k: _fake_frame())

    def make_provider(self) -> YahooFinanceProvider:
        return YahooFinanceProvider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="AAPL")


@pytest.mark.network
def test_yfinance_live() -> None:
    result = YahooFinanceProvider().fetch("^GSPC", interval="1d")
    OHLCV_BARS.validate(result.frame)
    assert result.frame.height > 100
