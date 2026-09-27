from __future__ import annotations

import httpx
import pytest
import respx

from heimdall._contracts import FetchRequest
from heimdall._registry import ProviderRegistry
from heimdall.errors import ConfigError, RequestError, UpstreamError
from heimdall.providers.sec_form4 import SecForm4Provider
from heimdall.providers.sec_form4.provider import FORM4_TRANSACTIONS

_CIK = "0000320193"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{_CIK}.json"

_ACCESSION_A = "0001140361-26-037020"  # Newstead Jennifer
_ACCESSION_B = "0001140361-26-036226"  # Kondo Deirdre
_BASE_A = f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_A.replace('-', '')}"
_BASE_B = f"https://www.sec.gov/Archives/edgar/data/320193/{_ACCESSION_B.replace('-', '')}"

_TICKERS_JSON = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

_SUBMISSIONS_JSON = {
    "filings": {
        "recent": {
            "accessionNumber": [_ACCESSION_A, _ACCESSION_B],
            "filingDate": ["2026-09-17", "2026-09-10"],
            "form": ["4", "4"],
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


def _provider() -> SecForm4Provider:
    return SecForm4Provider(user_agent="test test@example.com")


def _mock_common(router: respx.MockRouter) -> None:
    router.get(_TICKERS_URL).mock(return_value=httpx.Response(200, json=_TICKERS_JSON))
    router.get(_SUBMISSIONS_URL).mock(return_value=httpx.Response(200, json=_SUBMISSIONS_JSON))


def _mock_filing(router: respx.MockRouter, base: str, xml_name: str, xml_text: str) -> None:
    router.get(f"{base}/index.json").mock(
        return_value=httpx.Response(200, json={"directory": {"item": [{"name": xml_name}]}})
    )
    router.get(f"{base}/{xml_name}").mock(return_value=httpx.Response(200, text=xml_text))


@respx.mock
def test_limit_mode_returns_flattened_rows() -> None:
    _mock_common(respx)
    _mock_filing(respx, _BASE_A, "form4.xml", _XML_A)

    result = _provider()._fetch(FetchRequest(resource="AAPL", params={"limit": 1}))

    assert result.provider_id == "sec_form4"
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
        SecForm4Provider()  # type: ignore[call-arg]


def test_first_use_without_config_raises_config_error(monkeypatch) -> None:
    monkeypatch.delenv("HEIMDALL_SEC_FORM4_USER_AGENT", raising=False)
    registry = ProviderRegistry()
    registry.register_lazy(SecForm4Provider.id, SecForm4Provider.from_env)

    with pytest.raises(ConfigError, match="HEIMDALL_SEC_FORM4_USER_AGENT"):
        registry.get("sec_form4")


@respx.mock
def test_first_use_with_env_var_set_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("HEIMDALL_SEC_FORM4_USER_AGENT", "test test@example.com")
    _mock_common(respx)
    _mock_filing(respx, _BASE_A, "form4.xml", _XML_A)

    registry = ProviderRegistry()
    registry.register_lazy(SecForm4Provider.id, SecForm4Provider.from_env)
    provider = registry.get("sec_form4")  # factory runs here, resolves the env var
    assert registry.get("sec_form4") is provider  # cached, factory doesn't re-run

    result = provider._fetch(FetchRequest(resource="AAPL", params={"limit": 1}))
    assert result.frame.height == 2
