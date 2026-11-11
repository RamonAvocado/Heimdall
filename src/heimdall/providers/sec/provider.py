"""`sec`: insider transactions and point-in-time fundamentals from SEC EDGAR."""

from __future__ import annotations

import threading
import time
from typing import Annotated, Any

import httpx
import polars as pl

from heimdall._contracts import FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._base import Capabilities, Provider, ProviderMetadata
from heimdall.schemas import FUNDAMENTAL_FACTS

from .companyfacts import parse_companyfacts
from .form4 import FORM4_TRANSACTIONS, parse_form4_xml

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_MIN_GAP = 0.1  # 10 req/s max, per SEC's fair-access policy

_lock = threading.Lock()
_last_call = 0.0


class SecProvider(Provider):
    """SEC EDGAR data for a ticker; `kind` picks which:

    - `"insider_trading"` (default): insider transactions, one row per
      Form 4 transaction line. Scope it with `FetchRequest.params`:
      `{"limit": n}` (the `n` most recent filings), `{"owner": "Newstead
      Jennifer"}` (exact match, every filing by that owner), `{"since":
      "2026-09-01"}` (only filings filed after that date), or any mix. Codes
      are not interpreted (e.g. "F" is tax withholding, not a discretionary
      sale): that judgment belongs to the consumer.
    - `"fundamentals"`: revenue, earnings, cash flow and balance-sheet
      facts from the XBRL `companyfacts` API, one row per (metric, period).
      Point-in-time: each value keeps the date it was first filed
      (`reported_at`). Missing quarters (Q4, YTD-only cash flow) are derived
      by differencing year-to-date figures.

    No API key, but SEC requires a real, contactable `User-Agent` (there is
    no safe shared default) and rate-limits fair use to ~10 req/s, enforced
    here with a process-wide lock. Only US SEC filers are covered.
    """

    metadata = ProviderMetadata(
        name="sec",
        description="Form 4 insider transactions and point-in-time XBRL "
        "fundamentals from SEC EDGAR.",
    )
    capabilities = Capabilities(
        data_kinds=(FORM4_TRANSACTIONS.name, FUNDAMENTAL_FACTS.name),
        supports_date_range=False,
    )

    def __init__(
        self,
        *,
        user_agent: Annotated[
            str, 'Contact SEC requires on every request, e.g. "Name you@mail.com".'
        ],
        timeout: Annotated[float, "HTTP timeout in seconds."] = 30.0,
    ) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self._ciks: dict[str, str] | None = None  # ticker -> CIK, fetched once

    def _fetch(self, request: FetchRequest) -> FetchResult:
        match request.kind:
            case FUNDAMENTAL_FACTS.name:
                return self._fetch_companyfacts(request)
        return self._fetch_form4(request)

    def _fetch_form4(self, request: FetchRequest) -> FetchResult:
        ticker = request.resource
        limit = request.params.get("limit")
        owner = request.params.get("owner")
        since = request.params.get("since")
        if limit is None and owner is None and since is None:
            raise RequestError(
                "sec form4 needs params={'limit': n}, {'owner': 'Exact Name'} "
                "and/or {'since': 'YYYY-MM-DD'}"
            )

        cik = self._resolve_cik(ticker)
        filings = self._list_form4_filings(cik)
        if since is not None:
            # ISO dates compare as strings; the filings list costs one request,
            # each skipped filing saves two.
            filings = [f for f in filings if f["filingDate"] > str(since)]
        to_scan = filings if owner is not None else filings[:limit]

        matched: list[dict[str, Any]] = []
        for entry in to_scan:
            filing = {**entry, **self._parse_filing(cik, entry)}
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

    def _fetch_companyfacts(self, request: FetchRequest) -> FetchResult:
        ticker = request.resource
        cik = self._resolve_cik(ticker)
        doc = self._get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        ).json()
        facts = parse_companyfacts(doc)
        if not facts:
            raise RequestError(f"no XBRL facts for {ticker!r}")

        frame = (
            pl.DataFrame(
                facts,
                schema={
                    "metric": pl.String,
                    "period_type": pl.String,
                    "period_end": pl.Date,
                    "value": pl.Float64,
                    "reported_at": pl.Date,
                },
                orient="row",
            )
            .select(pl.lit(ticker).alias("symbol"), pl.all())
            .sort("period_end")
        )
        FUNDAMENTAL_FACTS.validate(frame)
        return FetchResult(
            frame=frame,
            schema=FUNDAMENTAL_FACTS,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={"cik": cik, "rows": frame.height},
        )

    def _resolve_cik(self, ticker: str) -> str:
        if self._ciks is None:
            self._ciks = {
                row["ticker"].upper(): f"{row['cik_str']:010d}"
                for row in self._get(_TICKERS_URL).json().values()
            }
        if cik := self._ciks.get(ticker.upper()):
            return cik
        raise RequestError(f"ticker {ticker!r} not found in SEC's company_tickers.json")

    def _list_form4_filings(self, cik: str) -> list[dict[str, Any]]:
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        recent = self._get(url).json()["filings"]["recent"]
        columns = zip(*recent.values(), strict=True)
        rows = [dict(zip(recent.keys(), values, strict=True)) for values in columns]
        return [row for row in rows if row["form"] == "4"]

    def _parse_filing(self, cik: str, entry: dict[str, Any]) -> dict[str, Any]:
        accession_nodash = entry["accessionNumber"].replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}"
        # primaryDocument is the XSL-rendered path ("xslF345X05/x.xml"); its
        # basename is the raw XML, so no index.json round-trip is needed.
        xml_name = (entry.get("primaryDocument") or "").rsplit("/", 1)[-1]
        if not xml_name.endswith(".xml"):
            index = self._get(f"{base}/index.json").json()
            xml_name = next(
                item["name"]
                for item in index["directory"]["item"]
                if item["name"].endswith(".xml")
            )
        return parse_form4_xml(self._get(f"{base}/{xml_name}").text)

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
                raise UpstreamError(
                    f"SEC EDGAR request failed for {url}: {exc}"
                ) from exc
            finally:
                _last_call = time.monotonic()
        return response
