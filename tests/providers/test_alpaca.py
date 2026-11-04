from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import respx

from heimdall._contracts import FetchRequest
from heimdall.errors import RequestError
from heimdall.providers.alpaca import AlpacaProvider
from heimdall.schemas import OHLCV_BARS
from heimdall.testing import ProviderContractTests

_URL = "https://data.alpaca.markets/v2/stocks/AAPL/bars"


def _bar(day: int, close: float) -> dict[str, object]:
    return {
        "t": f"2024-01-0{day}T05:00:00Z",
        "o": 1,
        "h": 2,
        "l": 0.5,
        "c": close,
        "v": 100,
        "n": 3,
        "vw": 1.2,
    }


_PAGE = {"bars": [_bar(2, 1.5), _bar(3, 2)], "symbol": "AAPL", "next_page_token": None}


def _provider() -> AlpacaProvider:
    return AlpacaProvider(api_key_id="PKX", api_secret_key="secret")


def _request() -> FetchRequest:
    return FetchRequest(
        "AAPL", start=datetime(2024, 1, 1), end=datetime(2024, 1, 4), interval="1d"
    )


@respx.mock
def test_fetch_maps_bars_and_sends_auth() -> None:
    route = respx.get(_URL).mock(return_value=httpx.Response(200, json=_PAGE))

    result = _provider().fetch("AAPL", "1d", datetime(2024, 1, 1), datetime(2024, 1, 4))

    OHLCV_BARS.validate(result.frame)
    assert result.frame["close"].to_list() == [1.5, 2.0]
    assert result.frame["timestamp"][0] == datetime(2024, 1, 2, 5)
    sent = route.calls.last.request
    assert sent.headers["APCA-API-KEY-ID"] == "PKX"
    assert sent.headers["APCA-API-SECRET-KEY"] == "secret"
    assert dict(sent.url.params) == {
        "timeframe": "1Day",
        "start": "2024-01-01T00:00:00+00:00",
        "end": "2024-01-04T00:00:00+00:00",
        "feed": "iex",
        "adjustment": "all",
        "limit": "10000",
    }


@respx.mock
def test_follows_next_page_token() -> None:
    route = respx.get(_URL).mock(
        side_effect=[
            httpx.Response(200, json={"bars": [_bar(2, 1)], "next_page_token": "abc"}),
            httpx.Response(200, json={"bars": [_bar(3, 2)], "next_page_token": None}),
        ]
    )

    result = _provider().fetch("AAPL", "1d", datetime(2024, 1, 1))

    assert result.frame["close"].to_list() == [1.0, 2.0]
    assert "page_token" not in route.calls[0].request.url.params
    assert route.calls[1].request.url.params["page_token"] == "abc"


@respx.mock
def test_bad_symbol_is_a_request_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(422, json={"message": "x"}))
    with pytest.raises(RequestError):
        _provider().fetch("AAPL", "1d", datetime(2024, 1, 1))


def test_unsupported_interval_is_a_request_error() -> None:
    with pytest.raises(RequestError):
        _provider().fetch("AAPL", "3d")


class TestAlpacaContract(ProviderContractTests):
    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(_URL).mock(return_value=httpx.Response(200, json=_PAGE))
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> AlpacaProvider:
        return _provider()

    def sample_request(self) -> FetchRequest:
        return _request()
