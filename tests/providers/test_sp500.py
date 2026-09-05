from __future__ import annotations

import httpx
import pytest
import respx

from heimdall.contracts import FetchRequest
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._sp500 import SP500Provider
from heimdall.schemas import GENERIC_TABLE
from heimdall.testing import ProviderContractTests

_CSV = (
    "Symbol,Security,GICS Sector,GICS Sub-Industry,Headquarters Location,Date added,CIK,Founded\n"
    'MMM,3M,Industrials,Industrial Conglomerates,"Saint Paul, Minnesota",1957-03-04,66740,1902\n'
    'AOS,A. O. Smith,Industrials,Building Products,"Milwaukee, Wisconsin",2017-07-26,91142,1916\n'
)
_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
)


@respx.mock
def test_fetch_parses_and_normalizes() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    result = SP500Provider().fetch("constituents")

    assert result.provider_id == "sp500"
    assert result.schema is GENERIC_TABLE
    GENERIC_TABLE.validate(result.frame)
    assert result.frame.columns == [
        "symbol",
        "security",
        "gics_sector",
        "gics_sub_industry",
        "headquarters_location",
        "date_added",
        "cik",
        "founded",
    ]
    assert result.frame.height == 2
    assert "MMM" in result.frame["symbol"].to_list()


def test_wrong_resource_rejected() -> None:
    # Rejected before any network call is made, so no respx mock is needed.
    with pytest.raises(RequestError):
        SP500Provider().fetch("AAPL")


@respx.mock
def test_http_error_becomes_upstream_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamError):
        SP500Provider().fetch("constituents")


class TestSP500Contract(ProviderContractTests):
    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> SP500Provider:
        return SP500Provider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="constituents")


@pytest.mark.network
def test_sp500_live() -> None:
    result = SP500Provider().fetch(FetchRequest(resource="constituents"))
    GENERIC_TABLE.validate(result.frame)
    assert result.frame.height > 400
