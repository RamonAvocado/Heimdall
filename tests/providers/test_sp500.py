from __future__ import annotations

from datetime import date

import httpx
import polars as pl
import pytest
import respx

from heimdall._contracts import BatchResult, FetchRequest
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers.sp500 import SP500Provider
from heimdall.schemas import GENERIC_TABLE
from heimdall.testing import ProviderContractTests

_CSV = (
    "Symbol,Security,GICS Sector,GICS Sub-Industry,"
    "Headquarters Location,Date added,CIK,Founded\n"
    "MMM,3M,Industrials,Industrial Conglomerates,"
    '"Saint Paul, Minnesota",1957-03-04,66740,1902\n'
    "AOS,A. O. Smith,Industrials,Building Products,"
    '"Milwaukee, Wisconsin",2017-07-26,91142,1916\n'
)
_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
_CHANGES_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
_CHANGES_HTML = """
<table id="other"><tr><td>x</td></tr></table>
<table class="wikitable" id="changes">
<tr><th rowspan="2">Effective Date</th><th colspan="2">Added</th>
<th colspan="2">Removed</th><th rowspan="2">Reason</th><th>Refs</th></tr>
<tr><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th></tr>
<tr><td>October 6, 2026</td><td>TWLO</td><td>Twilio</td><td>WBD</td>
<td><a href="#">Warner Bros. Discovery</a></td><td>Acquired.</td><td>[2]</td></tr>
<tr><td>October 1, 2026</td><td>VYLR</td><td>Vylor</td><td></td><td></td>
<td>Spin-off.</td><td>[2]</td></tr>
<tr><td>March 1, 2020</td><td>X</td><td>X Corp</td><td>WBD</td>
<td>Discovery</td><td>Old removal.</td><td>[3]</td></tr>
<tr><td>March 1, 1999</td><td>Y</td><td>Y Corp</td><td>MMM</td>
<td>3M</td><td>Removed, later re-added.</td><td>[4]</td></tr>
</table>
"""


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


@respx.mock
def test_fetch_many_wraps_single_and_collects_bad_resource() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))

    batch = SP500Provider().fetch(["constituents", "AAPL"])

    assert isinstance(batch, BatchResult)
    assert list(batch.ok) == ["constituents"]
    assert list(batch.failed) == ["AAPL"]
    assert isinstance(batch.failed["AAPL"], RequestError)


@respx.mock
def test_pull_unlisted_appends_former_constituents() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    respx.get(_CHANGES_URL).mock(return_value=httpx.Response(200, text=_CHANGES_HTML))

    result = SP500Provider(pull_unlisted=True).fetch()
    frame = result.frame

    assert frame["symbol"].to_list() == ["MMM", "AOS", "WBD"]
    assert frame["listed"].to_list() == [True, True, False]
    wbd = frame.filter(pl.col("symbol") == "WBD").row(0, named=True)
    assert wbd["security"] == "Warner Bros. Discovery"
    assert wbd["date_removed"] == date(2026, 10, 6)  # latest removal wins
    assert wbd["gics_sector"] is None
    assert result.metadata["unlisted"] == 1


@respx.mock
def test_changes_page_without_table_is_upstream_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    respx.get(_CHANGES_URL).mock(return_value=httpx.Response(200, text="<p/>"))
    with pytest.raises(UpstreamError):
        SP500Provider(pull_unlisted=True).fetch()


def test_pull_unlisted_from_env_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEIMDALL_SP500_PULL_UNLISTED", "false")
    assert SP500Provider.from_env()._pull_unlisted is False
    monkeypatch.setenv("HEIMDALL_SP500_PULL_UNLISTED", "true")
    assert SP500Provider.from_env()._pull_unlisted is True


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
    result = SP500Provider().fetch("constituents")
    GENERIC_TABLE.validate(result.frame)
    assert result.frame.height > 400


@pytest.mark.network
def test_sp500_pull_unlisted_live() -> None:
    frame = SP500Provider(pull_unlisted=True).fetch().frame
    assert frame.height > 500
    assert not frame.filter(~pl.col("listed")).is_empty()
