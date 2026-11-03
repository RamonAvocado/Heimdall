"""`sec_companyfacts`: point-in-time fundamentals from SEC XBRL `companyfacts`."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date
from itertools import pairwise
from typing import Annotated, Any

import httpx
import polars as pl

from heimdall._contracts import FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._base import Capabilities, Provider, ProviderMetadata
from heimdall.schemas import FUNDAMENTAL_FACTS

#: Our metric -> us-gaap concepts. Companies switch concepts over the years
#: (Revenues -> RevenueFromContract...), so the first concept wins per period and
#: the later ones fill the gaps.
_DURATION = {
    "eps_diluted": ("EarningsPerShareDiluted",),
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss",),
    "operating_income": ("OperatingIncomeLoss",),
    "d_and_a": (
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
    ),
    "operating_cf": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
}
# ponytail: LongTermDebt only (incl. current portion when the filer reports it);
# add short-term borrowings / commercial paper if EV needs to be exact.
_INSTANT = {
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "debt": ("LongTermDebt", "LongTermDebtNoncurrent"),
}
_UNITS = {"eps_diluted": "USD/shares"}

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_MIN_GAP = 0.1  # 10 req/s max, per SEC's fair-access policy

_lock = threading.Lock()
_last_call = 0.0

#: (metric, period_type, period_end, value, reported_at)
Fact = tuple[str, str, date, float, date]


class SecCompanyFactsProvider(Provider):
    """Revenue, earnings, cash flow and balance-sheet facts for a ticker, one row
    per (metric, period), from SEC's XBRL `companyfacts` API.

    Point-in-time: each value keeps the date it was first filed (`reported_at`),
    so a backtest on day D only sees what was public on D. Quarters missing from
    the filings (Q4, YTD-only cash flow) are derived by differencing year-to-date
    figures. Only US SEC filers are covered.
    """

    metadata = ProviderMetadata(
        name="sec_companyfacts",
        description="Point-in-time company fundamentals from SEC XBRL filings.",
    )
    capabilities = Capabilities(
        data_kinds=(FUNDAMENTAL_FACTS.name,), supports_date_range=False
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

    def _fetch(self, request: FetchRequest) -> FetchResult:
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
        data = self._get(_TICKERS_URL).json()
        for row in data.values():
            if row["ticker"].upper() == ticker.upper():
                return f"{row['cik_str']:010d}"
        raise RequestError(f"ticker {ticker!r} not found in SEC's company_tickers.json")

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


def _concept_facts(
    doc: dict[str, Any], taxonomy: str, concepts: tuple[str, ...], unit: str
) -> dict[tuple[str | None, str], tuple[float, date]]:
    """(start, end) -> (value, filed), earliest filing per period (that's what was
    public first; later 10-Ks repeat it as a comparative)."""
    merged: dict[tuple[str | None, str], tuple[float, date]] = {}
    for concept in concepts:
        own: dict[tuple[str | None, str], tuple[float, date]] = {}
        units = doc["facts"].get(taxonomy, {}).get(concept, {}).get("units", {})
        for f in units.get(unit, []):
            key = (f.get("start"), f["end"])
            filed = date.fromisoformat(f["filed"])
            if key not in own or filed < own[key][1]:
                own[key] = (float(f["val"]), filed)
        for key, value in own.items():
            merged.setdefault(key, value)
    return merged


def _duration_facts(
    metric: str, facts: dict[tuple[str | None, str], tuple[float, date]]
) -> list[Fact]:
    """3-month (Q) and ~1-year (FY) values. 10-Qs often only state cash-flow lines
    year-to-date, and no filing states Q4 at all, so consecutive YTD figures
    sharing a start date are differenced: 6mo-3mo, 9mo-6mo, FY-9mo."""
    rows: dict[tuple[str, date], tuple[float, date]] = {}
    by_start: dict[date, list[tuple[date, float, date]]] = defaultdict(list)
    for (start, end), (value, filed) in facts.items():
        if start is None:
            continue
        s, e = date.fromisoformat(start), date.fromisoformat(end)
        days = (e - s).days
        if 80 <= days <= 100:
            rows[("Q", e)] = (value, filed)
        elif 350 <= days <= 380:
            rows[("FY", e)] = (value, filed)
        by_start[s].append((e, value, filed))

    # ponytail: differenced EPS is approximate (share count moves within the year);
    # pull the 8-K earnings release if exact quarterly EPS matters.
    for items in by_start.values():
        items.sort()
        for (e0, v0, f0), (e1, v1, f1) in pairwise(items):
            if 80 <= (e1 - e0).days <= 100 and ("Q", e1) not in rows:
                rows[("Q", e1)] = (v1 - v0, max(f0, f1))
    return [(metric, pt, end, v, filed) for (pt, end), (v, filed) in rows.items()]


def parse_companyfacts(doc: dict[str, Any]) -> list[Fact]:
    """SEC XBRL `companyfacts` JSON -> point-in-time facts."""
    out: list[Fact] = []
    for metric, concepts in _DURATION.items():
        facts = _concept_facts(doc, "us-gaap", concepts, _UNITS.get(metric, "USD"))
        out += _duration_facts(metric, facts)
    instants = {
        m: _concept_facts(doc, "us-gaap", c, "USD") for m, c in _INSTANT.items()
    }
    instants["shares_out"] = _concept_facts(
        doc, "dei", ("EntityCommonStockSharesOutstanding",), "shares"
    )
    for metric, facts in instants.items():
        out += [
            (metric, "I", date.fromisoformat(end), v, filed)
            for (_, end), (v, filed) in facts.items()
        ]
    return out
