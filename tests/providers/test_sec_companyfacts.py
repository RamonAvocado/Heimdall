from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from heimdall._contracts import FetchRequest
from heimdall.errors import RequestError
from heimdall.providers.sec_companyfacts import SecCompanyFactsProvider
from heimdall.providers.sec_companyfacts.provider import parse_companyfacts
from heimdall.schemas import FUNDAMENTAL_FACTS
from heimdall.testing import ProviderContractTests

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"


def _f(start, end, val, filed):
    return {"start": start, "end": end, "val": val, "filed": filed}


# Fiscal year starting 2024-01-01: 10-Qs state Q1-Q3 directly, the 10-K only FY.
_EPS = [
    _f("2024-01-01", "2024-03-31", 1.0, "2024-04-25"),
    _f("2024-04-01", "2024-06-30", 1.5, "2024-07-25"),
    _f("2024-07-01", "2024-09-30", 2.0, "2024-10-25"),
    _f("2024-01-01", "2024-06-30", 2.5, "2024-07-25"),
    _f("2024-01-01", "2024-09-30", 4.5, "2024-10-25"),
    _f("2024-01-01", "2024-12-31", 7.0, "2025-02-01"),
    # Same FY repeated as a comparative in next year's 10-K: keep the first filing.
    _f("2024-01-01", "2024-12-31", 7.0, "2026-02-01"),
]
_DOC = {
    "facts": {
        "us-gaap": {
            "EarningsPerShareDiluted": {"units": {"USD/shares": _EPS}},
            # Cash flow: YTD only, as 10-Qs report it.
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {
                    "USD": [
                        _f("2024-01-01", "2024-03-31", 10.0, "2024-04-25"),
                        _f("2024-01-01", "2024-06-30", 25.0, "2024-07-25"),
                    ]
                }
            },
            "Revenues": {
                "units": {"USD": [_f("2024-01-01", "2024-03-31", 99.0, "2024-04-25")]}
            },
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [_f("2024-01-01", "2024-03-31", 100.0, "2024-04-25")]}
            },
            "LongTermDebt": {
                "units": {
                    "USD": [{"end": "2024-12-31", "val": 50.0, "filed": "2025-02-01"}]
                }
            },
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        {"end": "2025-01-20", "val": 10.0, "filed": "2025-02-01"}
                    ]
                }
            }
        },
    }
}


def _by(facts, metric, period_type):
    return {f[2]: f for f in facts if f[0] == metric and f[1] == period_type}


def test_parse_companyfacts_is_point_in_time() -> None:
    facts = parse_companyfacts(_DOC)
    eps_q = _by(facts, "eps_diluted", "Q")

    # Q4 = FY - 9mo YTD
    assert [f[3] for _, f in sorted(eps_q.items())] == [1.0, 1.5, 2.0, 2.5]
    assert eps_q[date(2024, 12, 31)][4] == date(2025, 2, 1)
    assert _by(facts, "eps_diluted", "FY")[date(2024, 12, 31)][4] == date(2025, 2, 1)
    assert _by(facts, "operating_cf", "Q")[date(2024, 6, 30)][3] == 15.0
    assert _by(facts, "revenue", "Q")[date(2024, 3, 31)][3] == 100.0  # first concept
    assert _by(facts, "debt", "I")[date(2024, 12, 31)][3] == 50.0
    assert _by(facts, "shares_out", "I")[date(2025, 1, 20)][3] == 10.0


def _provider() -> SecCompanyFactsProvider:
    return SecCompanyFactsProvider(user_agent="Test t@example.com")


@respx.mock
def test_fetch_returns_fundamental_facts() -> None:
    respx.get(_TICKERS_URL).mock(return_value=httpx.Response(200, json=_TICKERS))
    route = respx.get(_FACTS_URL).mock(return_value=httpx.Response(200, json=_DOC))

    result = _provider().fetch("aapl")

    FUNDAMENTAL_FACTS.validate(result.frame)
    assert result.frame.columns == [c.name for c in FUNDAMENTAL_FACTS.columns]
    assert set(result.frame["symbol"]) == {"aapl"}
    assert result.metadata["cik"] == "0000320193"
    assert route.calls.last.request.headers["User-Agent"] == "Test t@example.com"


@respx.mock
def test_unknown_ticker_is_a_request_error() -> None:
    respx.get(_TICKERS_URL).mock(return_value=httpx.Response(200, json=_TICKERS))
    with pytest.raises(RequestError):
        _provider().fetch("NOPE")


class TestSecCompanyFactsContract(ProviderContractTests):
    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(_TICKERS_URL).mock(
            return_value=httpx.Response(200, json=_TICKERS)
        )
        self._router.get(_FACTS_URL).mock(return_value=httpx.Response(200, json=_DOC))
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> SecCompanyFactsProvider:
        return _provider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="AAPL")
