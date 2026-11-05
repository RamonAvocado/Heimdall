from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from heimdall._contracts import FetchRequest
from heimdall.errors import ConfigError, RequestError, UpstreamError
from heimdall.providers import ProviderRegistry
from heimdall.providers.sec import FORM4_TRANSACTIONS, SecProvider, parse_companyfacts
from heimdall.schemas import FUNDAMENTAL_FACTS
from heimdall.testing import ProviderContractTests

_CIK = "0000320193"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{_CIK}.json"

_ACCESSION_A = "0001140361-26-037020"  # Newstead Jennifer
_ACCESSION_B = "0001140361-26-036226"  # Kondo Deirdre
_BASE_A = (
    f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_A.replace('-', '')}"
)
_BASE_B = (
    f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_B.replace('-', '')}"
)

_TICKERS_JSON = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

_SUBMISSIONS_JSON = {
    "filings": {
        "recent": {
            "accessionNumber": [_ACCESSION_A, _ACCESSION_B],
            "filingDate": ["2026-09-17", "2026-09-10"],
            "form": ["4", "4"],
            "primaryDocument": ["xslF345X05/form4.xml", "xslF345X05/form4.xml"],
        }
    }
}

_XML_A = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Newstead Jennifer</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>false</isDirector>
      <isOfficer>true</isOfficer>
      <isTenPercentOwner>false</isTenPercentOwner>
      <isOther>false</isOther>
      <officerTitle>SVP, GC and Government Affairs</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-09-15</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1438</value></transactionShares>
        <transactionPricePerShare><value>330.19</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>32914</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
    <nonDerivativeHolding>
      <securityTitle><value>Common Stock</value></securityTitle>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>500</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>I</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeHolding>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Restricted Stock Unit</value></securityTitle>
      <transactionDate><value>2026-09-15</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>30104</value></transactionShares>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>180624</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </derivativeTransaction>
  </derivativeTable>
</ownershipDocument>
"""

_XML_B = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer>
    <issuerName>Apple Inc.</issuerName>
    <issuerTradingSymbol>AAPL</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Kondo Deirdre</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>false</isDirector>
      <isOfficer>true</isOfficer>
      <isTenPercentOwner>false</isTenPercentOwner>
      <isOther>false</isOther>
      <officerTitle>SVP, CFO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-09-08</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>317.23</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts>
        <sharesOwnedFollowingTransaction><value>10000</value></sharesOwnedFollowingTransaction>
      </postTransactionAmounts>
      <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>
"""


def _provider() -> SecProvider:
    return SecProvider(user_agent="test test@example.com")


def _mock_common(router: respx.MockRouter) -> None:
    router.get(_TICKERS_URL).mock(return_value=httpx.Response(200, json=_TICKERS_JSON))
    router.get(_SUBMISSIONS_URL).mock(
        return_value=httpx.Response(200, json=_SUBMISSIONS_JSON)
    )


def _mock_filing(
    router: respx.MockRouter, base: str, xml_name: str, xml_text: str
) -> None:
    # No index.json mock: the XML name comes from primaryDocument, and respx
    # rejects any unmocked request.
    router.get(f"{base}/{xml_name}").mock(
        return_value=httpx.Response(200, text=xml_text)
    )


@respx.mock
def test_falls_back_to_index_json_without_primary_document() -> None:
    submissions = {
        "filings": {
            "recent": {
                **_SUBMISSIONS_JSON["filings"]["recent"],
                "primaryDocument": ["", ""],
            }
        }
    }
    respx.get(_TICKERS_URL).mock(return_value=httpx.Response(200, json=_TICKERS_JSON))
    respx.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(200, json=submissions))
    respx.get(f"{_BASE_A}/index.json").mock(
        return_value=httpx.Response(
            200, json={"directory": {"item": [{"name": "other.xml"}]}}
        )
    )
    _mock_filing(respx, _BASE_A, "other.xml", _XML_A)

    result = _provider()._fetch(FetchRequest(resource="AAPL", params={"limit": 1}))

    assert result.metadata["filings_matched"] == 1


@respx.mock
def test_ticker_map_is_fetched_once() -> None:
    _mock_common(respx)
    _mock_filing(respx, _BASE_A, "form4.xml", _XML_A)
    tickers = respx.routes[0]
    provider = _provider()

    provider._fetch(FetchRequest(resource="AAPL", params={"limit": 1}))
    provider._fetch(FetchRequest(resource="AAPL", params={"limit": 1}))

    assert tickers.call_count == 1


@respx.mock
def test_limit_mode_returns_flattened_rows() -> None:
    _mock_common(respx)
    _mock_filing(respx, _BASE_A, "form4.xml", _XML_A)

    result = _provider()._fetch(FetchRequest(resource="AAPL", params={"limit": 1}))

    assert result.provider_id == "sec"
    assert result.schema is FORM4_TRANSACTIONS
    FORM4_TRANSACTIONS.validate(result.frame)
    assert set(result.frame.columns) == set(FORM4_TRANSACTIONS.column_names)
    # filing A has one non-derivative + one derivative transaction
    assert result.frame.height == 2
    assert result.frame["owner"].unique().to_list() == ["Newstead Jennifer"]
    assert result.frame["accession_number"].unique().to_list() == [_ACCESSION_A]


@respx.mock
def test_owner_mode_filters_by_exact_name() -> None:
    _mock_common(respx)
    _mock_filing(respx, _BASE_A, "form4.xml", _XML_A)
    _mock_filing(respx, _BASE_B, "form4.xml", _XML_B)

    result = _provider()._fetch(
        FetchRequest(resource="AAPL", params={"owner": "Newstead Jennifer"})
    )

    assert result.frame.height == 2
    assert result.frame["owner"].unique().to_list() == ["Newstead Jennifer"]
    assert result.frame["accession_number"].unique().to_list() == [_ACCESSION_A]


@respx.mock
def test_owner_mode_requires_exact_match() -> None:
    _mock_common(respx)
    _mock_filing(respx, _BASE_A, "form4.xml", _XML_A)
    _mock_filing(respx, _BASE_B, "form4.xml", _XML_B)

    with pytest.raises(RequestError):
        _provider()._fetch(FetchRequest(resource="AAPL", params={"owner": "Newstead"}))


def test_missing_limit_and_owner_raises_request_error() -> None:
    with pytest.raises(RequestError):
        _provider()._fetch(FetchRequest(resource="AAPL"))


@respx.mock
def test_unknown_ticker_raises_request_error() -> None:
    respx.get(_TICKERS_URL).mock(return_value=httpx.Response(200, json=_TICKERS_JSON))

    with pytest.raises(RequestError):
        _provider()._fetch(FetchRequest(resource="ZZZZ", params={"limit": 1}))


@respx.mock
def test_http_error_becomes_upstream_error() -> None:
    respx.get(_TICKERS_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(UpstreamError):
        _provider()._fetch(FetchRequest(resource="AAPL", params={"limit": 1}))


def test_user_agent_is_required() -> None:
    with pytest.raises(TypeError):
        SecProvider()  # type: ignore[call-arg]


def test_first_use_without_config_raises_config_error(monkeypatch) -> None:
    monkeypatch.delenv("HEIMDALL_SEC_USER_AGENT", raising=False)
    registry = ProviderRegistry()
    registry.register_lazy(SecProvider.id, SecProvider.from_env)

    with pytest.raises(ConfigError, match="HEIMDALL_SEC_USER_AGENT"):
        registry.get("sec")


@respx.mock
def test_first_use_with_env_var_set_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("HEIMDALL_SEC_USER_AGENT", "test test@example.com")
    _mock_common(respx)
    _mock_filing(respx, _BASE_A, "form4.xml", _XML_A)

    registry = ProviderRegistry()
    registry.register_lazy(SecProvider.id, SecProvider.from_env)
    provider = registry.get("sec")  # factory runs here, resolves the env var
    assert registry.get("sec") is provider  # cached, factory doesn't re-run

    result = provider._fetch(FetchRequest(resource="AAPL", params={"limit": 1}))
    assert result.frame.height == 2


def test_unknown_kind_is_a_request_error() -> None:
    with pytest.raises(RequestError, match="kind"):
        _provider().fetch("AAPL", kind="candles")


# --- fundamentals (XBRL companyfacts) ---

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


@respx.mock
def test_fetch_returns_fundamental_facts() -> None:
    respx.get(_TICKERS_URL).mock(return_value=httpx.Response(200, json=_TICKERS))
    route = respx.get(_FACTS_URL).mock(return_value=httpx.Response(200, json=_DOC))

    result = _provider().fetch("aapl", kind=FUNDAMENTAL_FACTS.name)

    FUNDAMENTAL_FACTS.validate(result.frame)
    assert result.frame.columns == [c.name for c in FUNDAMENTAL_FACTS.columns]
    assert set(result.frame["symbol"]) == {"aapl"}
    assert result.metadata["cik"] == "0000320193"
    assert route.calls.last.request.headers["User-Agent"] == "test test@example.com"


@respx.mock
def test_unknown_ticker_is_a_request_error() -> None:
    respx.get(_TICKERS_URL).mock(return_value=httpx.Response(200, json=_TICKERS))
    with pytest.raises(RequestError):
        _provider().fetch("NOPE", kind=FUNDAMENTAL_FACTS.name)


class TestSecFundamentalsContract(ProviderContractTests):
    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(_TICKERS_URL).mock(
            return_value=httpx.Response(200, json=_TICKERS)
        )
        self._router.get(_FACTS_URL).mock(return_value=httpx.Response(200, json=_DOC))
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> SecProvider:
        return _provider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="AAPL", kind=FUNDAMENTAL_FACTS.name)
