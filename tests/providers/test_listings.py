from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from heimdall._contracts import FetchRequest
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers.listings import (
    PROVIDERS,
    CoinGeckoProvider,
    TreasuriesProvider,
    USListingsProvider,
    isin_from_cusip,
)
from heimdall.schemas import GENERIC_TABLE
from heimdall.testing import ProviderContractTests

_NASDAQ = (
    "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|"
    "Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares\n"
    "Y|AA|Alcoa Corporation Common Stock |N| |N|100|N||AA|AA|N\n"
    "Y|SPY|SPDR S&P 500 ETF Trust|P| |Y|100|N||SPY|SPY|N\n"
    "Y|BRK.B|Berkshire Hathaway Inc. Class B|N| |N|100|N||BRK.B|BRK.B|N\n"
    "Y|CECO|CECO Environmental Corp. Common Stock|F| |N|100|N||CECO|CECO|N\n"
    "Y|ZZZTX|TXSE Test Stk 5 Common Stock|F| |N|40|Y||ZZZTX|ZZZTX|N\n"
    "File Creation Time: 1104202612:13|||||\n"
)
_COINS = [
    {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "image": "https://x/btc.png",
        "market_cap_rank": 1,
    },
    {
        "id": "ethereum",
        "symbol": "eth",
        "name": "Ethereum",
        "image": None,
        "market_cap_rank": None,
    },
]
_TREASURIES = [
    # A reopening listed before its original issue: the original wins.
    {
        "cusip": "91282CRX1",
        "securityType": "Note",
        "securityTerm": "9-Year 10-Month",
        "originalSecurityTerm": "10-Year",
        "reopening": "Yes",
        "issueDate": "2027-01-15T00:00:00",
        "maturityDate": "2036-11-15T00:00:00",
        "interestRate": "4.125",
        "inflationProtected": "No",
        "floatingRate": "No",
    },
    {
        "cusip": "91282CRX1",
        "securityType": "Note",
        "securityTerm": "10-Year",
        "originalSecurityTerm": "10-Year",
        "reopening": "No",
        "issueDate": "2026-11-16T00:00:00",
        "maturityDate": "2036-11-15T00:00:00",
        "interestRate": "",
        "inflationProtected": "No",
        "floatingRate": "No",
    },
    {
        "cusip": "912797WE3",
        "securityType": "Bill",
        "securityTerm": "4-Week",
        "originalSecurityTerm": "17-Week",
        "reopening": "Yes",
        "issueDate": "2026-11-10T00:00:00",
        "maturityDate": "2026-12-08T00:00:00",
        "interestRate": "",
        "inflationProtected": "",
        "floatingRate": "",
    },
    {
        "cusip": "91282CRA1",
        "securityType": "Note",
        "securityTerm": "5-Year",
        "originalSecurityTerm": "5-Year",
        "reopening": "No",
        "issueDate": "2026-04-30T00:00:00",
        "maturityDate": "2031-04-15T00:00:00",
        "interestRate": "1.625",
        "inflationProtected": "Yes",
        "floatingRate": "No",
    },
]


def test_isin_from_cusip() -> None:
    assert isin_from_cusip("037833100") == "US0378331005"  # Apple
    assert isin_from_cusip("912810UY2") == "US912810UY28"


@respx.mock
def test_us_listings_parses() -> None:
    respx.get(USListingsProvider._URL).mock(
        return_value=httpx.Response(200, text=_NASDAQ)
    )
    frame = USListingsProvider().fetch().frame
    assert frame.columns == ["symbol", "name", "exchange_mic", "etf"]
    assert frame["symbol"].to_list() == [
        "AA",
        "SPY",
        "BRK.B",
        "CECO",
    ]  # test issue dropped
    assert frame["name"][0] == "Alcoa Corporation Common Stock"
    assert frame["exchange_mic"].to_list() == ["XNYS", "ARCX", "XNYS", None]
    assert frame["etf"].to_list() == [False, True, False, False]


@respx.mock
def test_us_listings_bad_shape() -> None:
    respx.get(USListingsProvider._URL).mock(
        return_value=httpx.Response(200, text="a|b\n1|2\n")
    )
    with pytest.raises(UpstreamError):
        USListingsProvider().fetch()


@respx.mock
def test_coingecko_pages() -> None:
    route = respx.get(CoinGeckoProvider._URL).mock(
        return_value=httpx.Response(200, json=_COINS)
    )
    frame = CoinGeckoProvider(pages="2").fetch().frame
    assert route.call_count == 2
    assert frame["symbol"].to_list() == ["BTC", "ETH", "BTC", "ETH"]
    assert frame["image"][1] is None


@respx.mock
def test_treasuries_dedupes_and_types() -> None:
    respx.get(TreasuriesProvider._URL).mock(
        return_value=httpx.Response(200, json=_TREASURIES)
    )
    frame = TreasuriesProvider().fetch().frame.sort("cusip")
    assert frame["cusip"].to_list() == ["912797WE3", "91282CRA1", "91282CRX1"]
    assert frame["security_type"].to_list() == ["Bill", "TIPS", "Note"]
    assert frame["term"].to_list() == ["17-Week", "5-Year", "10-Year"]
    assert frame["issue_date"][2] == date(2026, 11, 16)  # original, not the reopening
    assert frame["interest_rate"].to_list() == [None, 1.625, None]


@respx.mock
def test_upstream_error() -> None:
    respx.get(CoinGeckoProvider._URL).mock(return_value=httpx.Response(429))
    with pytest.raises(UpstreamError):
        CoinGeckoProvider().fetch()


def test_wrong_resource_rejected() -> None:
    with pytest.raises(RequestError):
        TreasuriesProvider().fetch("AAPL")


class TestListingsContract(ProviderContractTests):
    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(USListingsProvider._URL).mock(
            return_value=httpx.Response(200, text=_NASDAQ)
        )
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> USListingsProvider:
        return USListingsProvider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="listings")


@pytest.mark.network
@pytest.mark.parametrize("provider_cls", PROVIDERS, ids=lambda c: c.id)
def test_listings_live(provider_cls) -> None:
    frame = provider_cls().fetch().frame
    GENERIC_TABLE.validate(frame)
    assert frame.height >= 100
