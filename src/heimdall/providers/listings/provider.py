"""Instrument listings: what exists to trade, one provider per asset family.

All three are snapshots (no history, no date range) with a single resource,
`"listings"` (also the default), returning GENERIC_TABLE rows.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime
from io import StringIO
from typing import Annotated, Any

import httpx
import polars as pl

from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._base import Capabilities, Provider, ProviderMetadata
from heimdall.schemas import GENERIC_TABLE

_RESOURCE = "listings"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; heimdall-mimird)"}


class _ListingProvider(Provider):
    """Shared base: validate the resource, call `_rows`, wrap the frame."""

    capabilities = Capabilities(
        data_kinds=(GENERIC_TABLE.name,),
        intervals=(),
        supports_date_range=False,
        requires_auth=False,
    )

    def __init__(
        self, *, timeout: Annotated[float, "HTTP timeout in seconds."] = 30.0
    ) -> None:
        self._timeout = float(timeout)

    def fetch(
        self,
        resource: str | Sequence[str] = _RESOURCE,
        interval: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        kind: str | None = None,
    ) -> FetchResult | BatchResult:
        """Only one resource exists here, so default it."""
        return super().fetch(resource, interval, start, end, kind)

    def _fetch(self, request: FetchRequest) -> FetchResult:
        if request.resource.lower() != _RESOURCE:
            raise RequestError(
                f"{self.id}: resource must be {_RESOURCE!r}, got {request.resource!r}"
            )
        frame = self._rows()
        if frame.is_empty():
            raise UpstreamError(f"{self.id}: upstream returned no listings")
        GENERIC_TABLE.validate(frame)
        return FetchResult(
            frame=frame,
            schema=GENERIC_TABLE,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={"rows": frame.height},
        )

    def _get(self, url: str, **params: Any) -> httpx.Response:
        try:
            response = httpx.get(
                url,
                params=params,
                timeout=self._timeout,
                follow_redirects=True,
                headers=_HEADERS,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(f"{self.id} request failed: {exc}") from exc
        return response

    @abstractmethod
    def _rows(self) -> pl.DataFrame: ...


# Nasdaq Trader "Listing Exchange" code -> ISO 10383 MIC. Unknown codes -> null.
_NASDAQ_MICS = {
    "Q": "XNAS",
    "N": "XNYS",
    "P": "ARCX",
    "Z": "BATS",
    "A": "XASE",
    "V": "IEXG",
    "M": "XCHI",
}


class USListingsProvider(_ListingProvider):
    """Every security traded on US exchanges (stocks, ETFs, preferreds,
    warrants, units), from Nasdaq Trader's symbol directory.

    Columns: `symbol` (CQS/Nasdaq style, e.g. `BRK.B`, `ABR$D`), `name`,
    `exchange_mic` (null for venues not in the map), `etf` (bool).
    Test issues are dropped.
    """

    metadata = ProviderMetadata(
        name="us_listings",
        description="All US-listed securities, from Nasdaq Trader's symbol directory.",
    )
    _URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"

    def _rows(self) -> pl.DataFrame:
        text = self._get(self._URL).text
        # The last line is a "File Creation Time: ..." footer, not a row.
        body = "\n".join(
            line for line in text.splitlines() if not line.startswith("File Creation")
        )
        raw = pl.read_csv(StringIO(body), separator="|", infer_schema=False)
        if not {"Symbol", "Security Name", "ETF", "Test Issue"} <= set(raw.columns):
            raise UpstreamError(f"{self.id}: unexpected columns {raw.columns}")
        return raw.filter(
            (pl.col("Test Issue") != "Y") & pl.col("Symbol").is_not_null()
        ).select(
            symbol=pl.col("Symbol"),
            name=pl.col("Security Name").str.strip_chars(),
            exchange_mic=pl.col("Listing Exchange").replace_strict(
                _NASDAQ_MICS, default=None
            ),
            etf=pl.col("ETF") == "Y",
        )


class CoinGeckoProvider(_ListingProvider):
    """Top crypto assets by market cap, from CoinGecko's public markets endpoint.

    Columns: `symbol` (upper-cased, e.g. `BTC`), `name`, `coingecko_id`,
    `image` (logo URL), `market_cap_rank`. 250 coins per page.
    """

    metadata = ProviderMetadata(
        name="coingecko",
        description="Top crypto assets by market cap (with logos), from CoinGecko.",
    )
    _URL = "https://api.coingecko.com/api/v3/coins/markets"

    def __init__(
        self,
        *,
        timeout: Annotated[float, "HTTP timeout in seconds."] = 30.0,
        pages: Annotated[int, "Pages of 250 coins to fetch."] = 1,
    ) -> None:
        super().__init__(timeout=timeout)
        self._pages = int(pages)  # from_env hands strings over

    def _rows(self) -> pl.DataFrame:
        # ponytail: keyless tier allows ~30 req/min, fine for a handful of pages;
        # add an api-key param if we ever want the full ~15k coin list.
        coins = [
            coin
            for page in range(1, self._pages + 1)
            for coin in self._get(
                self._URL,
                vs_currency="usd",
                order="market_cap_desc",
                per_page=250,
                page=page,
            ).json()
        ]
        return pl.DataFrame(
            {
                "symbol": [c["symbol"].upper() for c in coins],
                "name": [c["name"] for c in coins],
                "coingecko_id": [c["id"] for c in coins],
                "image": [c.get("image") for c in coins],
                "market_cap_rank": [c.get("market_cap_rank") for c in coins],
            },
            schema_overrides={"market_cap_rank": pl.Int64},
        )


def isin_from_cusip(cusip: str, country: str = "US") -> str:
    """ISIN = country + CUSIP + Luhn check digit over the digit-expanded string."""
    base = country + cusip
    digits = "".join(str(int(c, 36)) for c in base)
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return base + str((10 - total % 10) % 10)


class TreasuriesProvider(_ListingProvider):
    """Outstanding US Treasury marketable securities (Bills, Notes, Bonds,
    TIPS, FRNs), including announced-but-not-yet-issued ones, from
    TreasuryDirect's auction data.

    One row per CUSIP (reopenings collapsed). Columns: `cusip`, `isin`,
    `security_type` (Bill/Note/Bond/TIPS/FRN), `term` (original term, e.g.
    `10-Year`), `issue_date`, `maturity_date`, `interest_rate` (percent; null
    for bills and for coupons not yet auctioned).
    """

    metadata = ProviderMetadata(
        name="treasuries",
        description="Outstanding US Treasury securities, from TreasuryDirect.",
    )
    _URL = "https://www.treasurydirect.gov/TA_WS/securities/search"

    def _rows(self) -> pl.DataFrame:
        today = utcnow().date()
        records = self._get(
            self._URL,
            format="json",
            dateFieldName="maturityDate",
            startDate=today.isoformat(),
            endDate=today.replace(year=today.year + 31).isoformat(),
        ).json()
        by_cusip: dict[str, dict[str, Any]] = {}
        for r in records:
            # Original issue first: a reopening carries the same CUSIP and coupon.
            if r["cusip"] not in by_cusip or r.get("reopening") == "No":
                by_cusip[r["cusip"]] = r
        rows = by_cusip.values()

        def kind(r: dict[str, Any]) -> str:
            if r.get("inflationProtected") == "Yes":
                return "TIPS"
            if r.get("floatingRate") == "Yes":
                return "FRN"
            return str(r["securityType"])

        return pl.DataFrame(
            {
                "cusip": [r["cusip"] for r in rows],
                "isin": [isin_from_cusip(r["cusip"]) for r in rows],
                "security_type": [kind(r) for r in rows],
                "term": [
                    r.get("originalSecurityTerm") or r["securityTerm"] for r in rows
                ],
                "issue_date": [r["issueDate"][:10] for r in rows],
                "maturity_date": [r["maturityDate"][:10] for r in rows],
                "interest_rate": [
                    float(r["interestRate"]) if r.get("interestRate") else None
                    for r in rows
                ],
            },
            schema_overrides={"interest_rate": pl.Float64},
        ).with_columns(pl.col("issue_date", "maturity_date").str.to_date())
