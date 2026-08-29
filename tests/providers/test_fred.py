from __future__ import annotations

from datetime import datetime

import httpx
import polars as pl
import pytest
import respx

from heimdall.contracts import FetchRequest
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers.fred import FredProvider
from heimdall.schemas import OBSERVATIONS
from heimdall.testing import ProviderContractTests

_CSV = "observation_date,DGS10\n2024-01-02,3.95\n2024-01-03,3.91\n2024-01-04,.\n2024-01-05,4.02\n"
_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@respx.mock
def test_fetch_parses_and_normalizes() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    result = FredProvider().fetch(FetchRequest(resource="DGS10"))

    assert result.provider_id == "fred"
    assert result.schema is OBSERVATIONS
    OBSERVATIONS.validate(result.frame)
    assert result.frame.columns == ["timestamp", "series_id", "value"]
    # the "." observation is dropped
    assert result.frame.height == 3
    assert result.frame["series_id"].unique().to_list() == ["DGS10"]
    assert result.frame["value"].dtype == pl.Float64


@respx.mock
def test_date_range_filter() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    result = FredProvider().fetch(
        FetchRequest(resource="DGS10", start=datetime(2024, 1, 3), end=datetime(2024, 1, 3))
    )
    assert result.frame["timestamp"].to_list() == [datetime(2024, 1, 3)]


@respx.mock
def test_empty_range_raises_request_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    with pytest.raises(RequestError):
        FredProvider().fetch(FetchRequest(resource="DGS10", start=datetime(2030, 1, 1)))


@respx.mock
def test_http_error_becomes_upstream_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(UpstreamError):
        FredProvider().fetch(FetchRequest(resource="NOPE"))


class TestFredContract(ProviderContractTests):
    _csv_route = None

    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> FredProvider:
        return FredProvider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="DGS10")


@pytest.mark.network
def test_fred_live() -> None:
    result = FredProvider().fetch(FetchRequest(resource="DGS10"))
    OBSERVATIONS.validate(result.frame)
    assert result.frame.height > 100
