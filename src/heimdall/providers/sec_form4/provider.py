"""Fetch SEC Form 4 (insider transaction) filings.

Two ways to scope a request via ``FetchRequest.params`` (``resource`` is the
issuer's ticker):

- ``{"limit": n}`` - the ``n`` most recent Form 4 filings for the ticker.
- ``{"owner": "Newstead Jennifer"}`` (exact match) - every filing by that
  reporting owner, for the ticker.
- Both together - the ``n`` most recent filings by that owner.

This provider only fetches and flattens filings into rows; it does not
interpret transaction codes (e.g. that "F" is forced tax withholding, not a
discretionary sale) - that judgment belongs to the consumer.

Talks to SEC EDGAR's public JSON/XML endpoints. No API key, but SEC requires a
real, contactable ``User-Agent`` (pass your own via the constructor - there is
no safe shared default) and rate-limits fair use to ~10 req/s, enforced here
with a process-wide lock.
"""

from __future__ import annotations

import threading
import time
from xml.etree import ElementTree

import httpx
import polars as pl

from heimdall._contracts import ColumnSpec, FetchRequest, FetchResult, SchemaSpec
from heimdall._provider import Capabilities, Provider
from heimdall._time import utcnow
from heimdall.errors import RequestError, UpstreamError

FORM4_TRANSACTIONS = SchemaSpec(
    name="sec.form4_transactions",
    columns=(
        ColumnSpec("accession_number", pl.String, nullable=False),
        ColumnSpec("filing_date", pl.Date, nullable=False),
        ColumnSpec("issuer", pl.String, nullable=False),
        ColumnSpec("ticker", pl.String, nullable=False),
        ColumnSpec("owner", pl.String, nullable=False),
        ColumnSpec("position", pl.String),
        ColumnSpec("kind", pl.String, nullable=False, description="derivative or non-derivative"),
        ColumnSpec("security", pl.String),
        ColumnSpec("transaction_date", pl.Date, nullable=False),
        ColumnSpec("code", pl.String, description="raw SEC transaction code, e.g. S/P/A/M/F/G/C/X"),
        ColumnSpec("shares", pl.Float64),
        ColumnSpec("price", pl.Float64, description="per-share price; often null for grants"),
        ColumnSpec("acquired_disposed", pl.String, description="A = acquired, D = disposed"),
        ColumnSpec("shares_owned_after", pl.Float64),
        ColumnSpec("ownership", pl.String, description="D = direct, I = indirect"),
    ),
    time_column="transaction_date",
)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_MIN_GAP = 0.1  # 10 req/s max, per SEC's fair-access policy

_lock = threading.Lock()
_last_call = 0.0


class SecForm4Provider(Provider):
    id = "sec_form4"
    capabilities = Capabilities(data_kinds=(FORM4_TRANSACTIONS.name,), requires_auth=False)

    def __init__(self, *, user_agent: str, timeout: float = 30.0) -> None:
        self._user_agent = user_agent
        self._timeout = timeout

    def _fetch(self, request: FetchRequest) -> FetchResult:
        ticker = request.resource
        limit = request.params.get("limit")
        owner = request.params.get("owner")
        if limit is None and owner is None:
            raise RequestError(
                "sec_form4 needs params={'limit': n} and/or params={'owner': 'Exact Name'}"
            )

        cik = self._resolve_cik(ticker)
        filings = self._list_form4_filings(cik)
        to_scan = filings if owner is not None else filings[:limit]

        matched: list[dict] = []
        for entry in to_scan:
            parsed = self._parse_filing(cik, entry)
            filing = {**entry, **parsed}
            if owner is not None and filing["owner"] != owner:
                continue
            matched.append(filing)
            if limit is not None and len(matched) >= limit:
                break

        rows = [
            {
                "accession_number": filing["accessionNumber"],
                "filing_date": filing["filingDate"],
                "issuer": filing["issuer"],
                "ticker": filing["ticker"] or ticker,
                "owner": filing["owner"],
                "position": filing["position"],
                "kind": txn["kind"],
                "security": txn["security"],
                "transaction_date": txn["date"],
                "code": txn["code"],
                "shares": txn["shares"],
                "price": txn["price"],
                "acquired_disposed": txn["acquired_disposed"],
                "shares_owned_after": txn["shares_owned_after"],
                "ownership": txn["ownership"],
            }
            for filing in matched
            for txn in filing["transactions"]
        ]
        if not rows:
            raise RequestError(f"no Form 4 transactions matched for {ticker!r}")

        frame = (
            pl.DataFrame(rows)
            .with_columns(
                pl.col("filing_date").str.strptime(pl.Date, strict=False),
                pl.col("transaction_date").str.strptime(pl.Date, strict=False),
                pl.col("shares").cast(pl.Float64, strict=False),
                pl.col("price").cast(pl.Float64, strict=False),
                pl.col("shares_owned_after").cast(pl.Float64, strict=False),
            )
            .sort("transaction_date")
        )
        FORM4_TRANSACTIONS.validate(frame)
        return FetchResult(
            frame=frame,
            schema=FORM4_TRANSACTIONS,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={"cik": cik, "filings_matched": len(matched)},
        )

    def _resolve_cik(self, ticker: str) -> str:
        data = self._get(_TICKERS_URL).json()
        for row in data.values():
            if row["ticker"].upper() == ticker.upper():
                return f"{row['cik_str']:010d}"
        raise RequestError(f"ticker {ticker!r} not found in SEC's company_tickers.json")

    def _list_form4_filings(self, cik: str) -> list[dict]:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        recent = self._get(url).json()["filings"]["recent"]
        columns = zip(*recent.values(), strict=True)
        rows = [dict(zip(recent.keys(), values, strict=True)) for values in columns]
        return [row for row in rows if row["form"] == "4"]

    def _parse_filing(self, cik: str, entry: dict) -> dict:
        accession_nodash = entry["accessionNumber"].replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}"
        index = self._get(f"{base}/index.json").json()
        xml_name = next(
            item["name"] for item in index["directory"]["item"] if item["name"].endswith(".xml")
        )
        xml_text = self._get(f"{base}/{xml_name}").text
        return _parse_form4_xml(xml_text)

    def _get(self, url: str) -> httpx.Response:
        global _last_call
        with _lock:
            wait = _last_call + _MIN_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                response = httpx.get(
                    url, headers={"User-Agent": self._user_agent}, timeout=self._timeout
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise UpstreamError(f"SEC EDGAR request failed for {url}: {exc}") from exc
            finally:
                _last_call = time.monotonic()
        return response


def _val(el: ElementTree.Element, tag: str) -> str | None:
    """Most Form 4 leaf fields are ``<tag><value>...</value></tag>``; a missing
    value (e.g. no price on a grant) leaves whitespace, not "" - strip it.
    """
    for candidate in (el.findtext(f"{tag}/value"), el.findtext(tag)):
        if candidate is not None and candidate.strip():
            return candidate.strip()
    return None


def _parse_form4_xml(xml_text: str) -> dict:
    root = ElementTree.fromstring(xml_text)
    owner_el = root.find("reportingOwner")
    relationship = owner_el.find("reportingOwnerRelationship") if owner_el is not None else None

    tables = (("nonDerivativeTable", "non-derivative"), ("derivativeTable", "derivative"))
    transactions = []
    for table, kind in tables:
        table_el = root.find(table)
        if table_el is None:
            continue
        for txn in table_el:
            transactions.append(
                {
                    "kind": kind,
                    "security": _val(txn, "securityTitle"),
                    "date": _val(txn, "transactionDate"),
                    "code": _val(txn, "transactionCoding/transactionCode"),
                    "shares": _val(txn, "transactionAmounts/transactionShares"),
                    "price": _val(txn, "transactionAmounts/transactionPricePerShare"),
                    "acquired_disposed": _val(
                        txn, "transactionAmounts/transactionAcquiredDisposedCode"
                    ),
                    "shares_owned_after": _val(
                        txn, "postTransactionAmounts/sharesOwnedFollowingTransaction"
                    ),
                    "ownership": _val(txn, "ownershipNature/directOrIndirectOwnership"),
                }
            )

    def _flag(tag: str) -> bool:
        return relationship is not None and relationship.findtext(tag) == "true"

    roles = []
    if _flag("isDirector"):
        roles.append("director")
    if _flag("isOfficer"):
        title = relationship.findtext("officerTitle") if relationship is not None else None
        roles.append(f"officer ({title})" if title else "officer")
    if _flag("isTenPercentOwner"):
        roles.append("10% owner")
    if _flag("isOther"):
        roles.append("other")

    return {
        "issuer": root.findtext("issuer/issuerName"),
        "ticker": root.findtext("issuer/issuerTradingSymbol"),
        "owner": (
            owner_el.findtext("reportingOwnerId/rptOwnerName") if owner_el is not None else None
        ),
        "position": ", ".join(roles) if roles else "unknown",
        "transactions": transactions,
    }
