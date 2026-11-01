from __future__ import annotations

import httpx
import pytest
import respx

from heimdall._contracts import FetchRequest
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers.indexes import (
    PROVIDERS,
    DAXProvider,
    HangSengProvider,
    Nasdaq100Provider,
    Nikkei225Provider,
)
from heimdall.schemas import GENERIC_TABLE
from heimdall.testing import ProviderContractTests

# Wikipedia shape: two-row header, an empty logo column, a footnote mark, a
# row-header <th>, a nested table, and a ragged (rowspan) row.
_DAX_HTML = """
<style>td { color: red }</style>
<table class="wikitable" id="history"><tr><th>Year</th></tr>
<tr><td>1990</td></tr></table>
<table class="wikitable sortable" id="constituents">
<tr><th>Ticker</th><th>Logo</th><th>Company</th><th>Prime Standard Sector[4]</th></tr>
<tr><th scope="row">ADS.DE</th><td><img src="x"/></td><td><a href="#">Adidas</a>[1]</td>
<td>Apparel</td></tr>
<tr><td>SAP.DE</td><td></td><td>SAP <table><tr><td>nested</td></tr></table></td>
<td>Software</td></tr>
<tr><td>Software</td></tr>
</table>
"""
_HSI_HTML = """
<table id="constituents"><tr><th>Ticker</th><th>Name</th><th>Sub-index</th></tr>
<tr><td>SEHK: 5</td><td>HSBC Holdings plc</td><td>Finance</td></tr>
<tr><td>SEHK: 700</td><td>Tencent</td><td>Commerce</td></tr></table>
"""
_NIKKEI_HTML = """
<h3 class="idx-section-subheading">Automobiles &amp; Auto parts</h3>
<table class="table"><tr><th>Code</th><th>Company Name</th></tr>
<tr><td>7203</td><td>TOYOTA MOTOR CORP.</td></tr></table>
<h3 class="idx-section-subheading">Electric Machinery</h3>
<table class="table"><tr><th>Code</th><th>Company Name</th></tr>
<tr><td>6758</td><td>SONY GROUP CORP.</td></tr>
<tr><td>285A</td><td>KIOXIA HOLDINGS CORP.</td></tr></table>
"""
_NASDAQ_JSON = {
    "data": {
        "data": {
            "rows": [
                {"symbol": "AAPL", "companyName": "Apple Inc.", "marketCap": "4,991"},
                {"symbol": "MSFT", "companyName": "Microsoft", "marketCap": ""},
            ]
        }
    }
}


def _mock(provider_cls, **response) -> None:
    respx.get(provider_cls._url).mock(return_value=httpx.Response(200, **response))


@respx.mock
def test_wikipedia_table_normalized() -> None:
    _mock(DAXProvider, text=_DAX_HTML)
    result = DAXProvider().fetch()

    GENERIC_TABLE.validate(result.frame)
    assert result.frame.columns == ["symbol", "name", "prime_standard_sector"]
    assert result.frame.rows() == [
        ("ADS.DE", "Adidas", "Apparel"),
        ("SAP.DE", "SAP nested", "Software"),  # nested table text joins its cell
    ]


@respx.mock
def test_hang_seng_codes_padded() -> None:
    _mock(HangSengProvider, text=_HSI_HTML)
    assert HangSengProvider().fetch().frame["symbol"].to_list() == ["0005", "0700"]


@respx.mock
def test_nikkei_tables_carry_sector() -> None:
    _mock(Nikkei225Provider, text=_NIKKEI_HTML)
    frame = Nikkei225Provider().fetch().frame
    assert frame.rows() == [
        ("7203", "TOYOTA MOTOR CORP.", "Automobiles & Auto parts"),
        ("6758", "SONY GROUP CORP.", "Electric Machinery"),
        ("285A", "KIOXIA HOLDINGS CORP.", "Electric Machinery"),
    ]


@respx.mock
def test_nasdaq100_json() -> None:
    _mock(Nasdaq100Provider, json=_NASDAQ_JSON)
    frame = Nasdaq100Provider().fetch().frame
    assert frame.rows() == [("AAPL", "Apple Inc.", 4991.0), ("MSFT", "Microsoft", None)]


@respx.mock
def test_missing_table_is_upstream_error() -> None:
    _mock(DAXProvider, text="<p>moved</p>")
    with pytest.raises(UpstreamError):
        DAXProvider().fetch()


@respx.mock
def test_http_error_is_upstream_error() -> None:
    respx.get(Nasdaq100Provider._url).mock(return_value=httpx.Response(403))
    with pytest.raises(UpstreamError):
        Nasdaq100Provider().fetch()


def test_wrong_resource_rejected() -> None:
    with pytest.raises(RequestError):
        DAXProvider().fetch("SAP")


class TestIndexContract(ProviderContractTests):
    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(DAXProvider._url).mock(
            return_value=httpx.Response(200, text=_DAX_HTML)
        )
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> DAXProvider:
        return DAXProvider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="constituents")


@pytest.mark.network
@pytest.mark.parametrize("provider_cls", PROVIDERS, ids=lambda c: c.id)
def test_index_live(provider_cls) -> None:
    frame = provider_cls().fetch().frame
    GENERIC_TABLE.validate(frame)
    assert frame.height >= 30
    assert frame["symbol"].n_unique() == frame.height
