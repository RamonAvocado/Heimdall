from __future__ import annotations

from datetime import datetime

import httpx
import pytest
import respx

from heimdall._contracts import FetchRequest
from heimdall.errors import RequestError
from heimdall.providers.mimird import MimirdProvider
from heimdall.schemas import OHLCV_BARS
from heimdall.testing import ProviderContractTests

_URL = "https://mimird.test/api/v1/i/prices"
_CANDLES = [
    {
        "timestamp": "2024-01-02T00:00:00",
        "open": 1,
        "high": 2,
        "low": 0.5,
        "close": 1.5,
        "volume": 10,
    },
    {
        "timestamp": "2024-01-03T00:00:00",
        "open": 1.5,
        "high": 2.5,
        "low": 1,
        "close": 2,
        "volume": None,
    },
]


def _provider() -> MimirdProvider:
    return MimirdProvider(base_url="https://mimird.test/", api_key="mk_x")


def _request() -> FetchRequest:
    return FetchRequest(
        "BRK.B", start=datetime(2024, 1, 1), end=datetime(2024, 1, 4), interval="1d"
    )


@respx.mock
def test_fetch_maps_candles_to_ohlcv_bars() -> None:
    route = respx.get(_URL).mock(return_value=httpx.Response(200, json=_CANDLES))

    result = _provider().fetch(
        "BRK.B", "1d", datetime(2024, 1, 1), datetime(2024, 1, 4)
    )

    OHLCV_BARS.validate(result.frame)
    assert result.frame["symbol"].to_list() == ["BRK.B", "BRK.B"]
    assert result.frame["close"].to_list() == [1.5, 2.0]
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer mk_x"
    assert dict(sent.url.params) == {
        "symbol": "BRK.B",
        "start": "2024-01-01",
        "end": "2024-01-04",
        "interval": "1d",
    }


@respx.mock
def test_unknown_symbol_is_a_request_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(404, json={"detail": "x"}))
    with pytest.raises(RequestError):
        _provider().fetch("BRK.B", "1d", datetime(2024, 1, 1), datetime(2024, 1, 4))


class TestMimirdContract(ProviderContractTests):
    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(_URL).mock(return_value=httpx.Response(200, json=_CANDLES))
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> MimirdProvider:
        return _provider()

    def sample_request(self) -> FetchRequest:
        return _request()
