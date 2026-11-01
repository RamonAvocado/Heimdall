"""Current constituents of major world stock indexes, one provider per index."""

from __future__ import annotations

import json
import re
from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

import httpx
import polars as pl

from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._base import Capabilities, Provider, ProviderMetadata
from heimdall.providers._html import Table, parse_tables
from heimdall.schemas import GENERIC_TABLE

_RESOURCE = "constituents"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; heimdall-mimird)"}
_ALIASES = {
    "ticker": "symbol",
    "code": "symbol",
    "company": "name",
    "company_name": "name",
    "security": "name",
}


class _IndexProvider(Provider):
    """Shared base: GET `_url`, parse it with `_parse`, return one row per
    constituent with at least `symbol` and `name` (strings, as published).

    A snapshot, not point-in-time history. `"constituents"` is the only
    resource (and the default). The default `_parse` reads the page's
    `<table id="constituents">`, the Wikipedia convention.
    """

    capabilities = Capabilities(
        data_kinds=(GENERIC_TABLE.name,),
        intervals=(),
        supports_date_range=False,
        requires_auth=False,
    )

    @property
    @abstractmethod
    def _url(self) -> str: ...

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
    ) -> FetchResult | BatchResult:
        """Only one resource exists here, so default it."""
        return super().fetch(resource, interval, start, end)

    def _fetch(self, request: FetchRequest) -> FetchResult:
        if request.resource.lower() != _RESOURCE:
            raise RequestError(
                f"{self.id}: resource must be {_RESOURCE!r}, got {request.resource!r}"
            )
        try:
            response = httpx.get(
                self._url,
                timeout=self._timeout,
                follow_redirects=True,
                headers=_HEADERS,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"{self.id} constituents request failed: {exc}"
            ) from exc

        frame = self._parse(response.text)
        if not {"symbol", "name"} <= set(frame.columns):
            raise UpstreamError(
                f"{self.id}: unexpected page shape, columns {frame.columns}"
            )
        frame = frame.select("symbol", "name", pl.exclude("symbol", "name")).filter(
            pl.col("symbol").is_not_null() & (pl.col("symbol") != "")
        )
        if frame.is_empty():
            raise UpstreamError(f"{self.id}: no constituents found at {self._url}")

        GENERIC_TABLE.validate(frame)
        return FetchResult(
            frame=frame,
            schema=GENERIC_TABLE,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={"source": self._url, "rows": frame.height},
        )

    def _parse(self, text: str) -> pl.DataFrame:
        tables = [t for t in parse_tables(text) if t.id == "constituents"]
        if not tables:
            raise UpstreamError(f"{self.id}: no constituents table at {self._url}")
        return self._table_frame(tables[0])

    def _table_frame(self, table: Table) -> pl.DataFrame:
        """A table as a frame: snake_case headers (`Ticker` / `Code` ->
        `symbol`, `Company` -> `name`), ragged rows dropped, all-empty columns
        (logos) dropped."""
        columns = [_ALIASES.get(c, c) for c in map(_snake, table.header)]
        rows = [r for r in table.rows if len(r) == len(columns)]
        if dropped := len(table.rows) - len(rows):
            self._log.warning("dropped ragged rows", dropped=dropped)
        frame = pl.DataFrame(rows, schema=columns, orient="row")
        return frame.select(c for c in frame.columns if (frame[c] != "").any())


class Nasdaq100Provider(_IndexProvider):
    """The Nasdaq-100: symbol, name and market cap from Nasdaq's own API."""

    metadata = ProviderMetadata(
        name="nasdaq100", description="Current Nasdaq-100 constituents."
    )
    _url = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"

    def _parse(self, text: str) -> pl.DataFrame:
        try:
            rows = json.loads(text)["data"]["data"]["rows"]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamError(f"nasdaq100: unexpected API response: {exc}") from exc
        if not rows:
            return pl.DataFrame()
        return pl.DataFrame(rows).select(
            pl.col("symbol").cast(pl.String),
            pl.col("companyName").cast(pl.String).alias("name"),
            pl.col("marketCap")
            .cast(pl.String)
            .str.replace_all(",", "")
            .cast(pl.Float64, strict=False)
            .alias("market_cap"),
        )


class Dow30Provider(_IndexProvider):
    """The Dow Jones Industrial Average's 30 companies, from Wikipedia."""

    metadata = ProviderMetadata(
        name="dow30", description="Current Dow Jones Industrial Average constituents."
    )
    _url = (
        "https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies"
    )


class FTSE100Provider(_IndexProvider):
    """The FTSE 100 (London), from Wikipedia."""

    metadata = ProviderMetadata(
        name="ftse100", description="Current FTSE 100 constituents."
    )
    _url = "https://en.wikipedia.org/wiki/FTSE_100_Index"


class DAXProvider(_IndexProvider):
    """The DAX 40 (Frankfurt), from Wikipedia. Tickers are Yahoo-style
    (`ADS.DE`)."""

    metadata = ProviderMetadata(name="dax", description="Current DAX constituents.")
    _url = "https://en.wikipedia.org/wiki/DAX"


class CAC40Provider(_IndexProvider):
    """The CAC 40 (Paris), from Wikipedia. Tickers are Yahoo-style (`AC.PA`)."""

    metadata = ProviderMetadata(
        name="cac40", description="Current CAC 40 constituents."
    )
    _url = "https://en.wikipedia.org/wiki/CAC_40"


class HangSengProvider(_IndexProvider):
    """The Hang Seng Index (Hong Kong), from Wikipedia. `symbol` is the
    4-digit HKEX code (`0005`)."""

    metadata = ProviderMetadata(
        name="hang_seng", description="Current Hang Seng Index constituents."
    )
    _url = "https://en.wikipedia.org/wiki/Hang_Seng_Index"

    def _parse(self, text: str) -> pl.DataFrame:
        return (
            super()
            ._parse(text)
            .with_columns(pl.col("symbol").str.replace(r"^SEHK:\s*", "").str.zfill(4))
        )


class Nikkei225Provider(_IndexProvider):
    """The Nikkei 225 (Tokyo), from Nikkei's official component page:
    `symbol` (TSE code), `name` and `sector`."""

    metadata = ProviderMetadata(
        name="nikkei225", description="Current Nikkei 225 constituents."
    )
    _url = "https://indexes.nikkei.co.jp/en/nkave/index/component?idx=nk225"

    def _parse(self, text: str) -> pl.DataFrame:
        # One table per sector, each under an <h3> naming it.
        tables = [
            t for t in parse_tables(text) if t.header[:2] == ["Code", "Company Name"]
        ]
        if not tables:
            raise UpstreamError(f"nikkei225: no component tables at {self._url}")
        return pl.concat(
            self._table_frame(t).with_columns(sector=pl.lit(t.heading)) for t in tables
        )


def _snake(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_")
