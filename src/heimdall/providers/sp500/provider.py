"""`sp500`: the current S&P 500 constituent list, optionally with former
constituents."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from html.parser import HTMLParser
from io import StringIO
from typing import Annotated

import httpx
import polars as pl

from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._base import Capabilities, Provider, ProviderMetadata
from heimdall.schemas import GENERIC_TABLE

_CSV_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
_RESOURCE = "constituents"
_CHANGES_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"


class SP500Provider(Provider):
    """Who is in the S&P 500 today: one row per constituent, with its sector.

    Source: the community-maintained CSV mirror at
    github.com/datasets/s-and-p-500-companies.  A snapshot, not point-in-time
    history, and not parameterized by ticker or date: the whole list is the
    resource, so `"constituents"` is the only accepted value (and the default).

    With `pull_unlisted=True`, companies that have left the index are appended
    (`listed=False`, plus `date_removed` / `removal_reason`), taken from the
    changes table on Wikipedia's "Historical components of the S&P 500".
    Current rows get `listed=True`; columns only one side has are null.
    """

    metadata = ProviderMetadata(
        name="sp500",
        description=(
            "The current S&P 500 constituent list, optionally with former constituents."
        ),
    )
    capabilities = Capabilities(
        data_kinds=(GENERIC_TABLE.name,),
        intervals=(),
        supports_date_range=False,
        requires_auth=False,
    )

    def __init__(
        self,
        *,
        timeout: Annotated[float, "HTTP timeout in seconds."] = 30.0,
        pull_unlisted: Annotated[
            bool, "Also return former constituents (Wikipedia changes table)."
        ] = False,
    ) -> None:
        self._timeout = float(timeout)
        # `from_env` hands env values over as strings.
        self._pull_unlisted = str(pull_unlisted).lower() in ("1", "true", "yes")

    def fetch(
        self,
        resource: str | Sequence[str] = _RESOURCE,
        interval: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> FetchResult | BatchResult:
        """Only one resource exists here, so default it - callers shouldn't
        have to know the sentinel string just to get the list."""
        return super().fetch(resource, interval, start, end)

    def _fetch(self, request: FetchRequest) -> FetchResult:
        resource = request.resource.lower()
        if resource != _RESOURCE:
            raise RequestError(
                f"sp500: resource must be {_RESOURCE!r}, got {request.resource!r}"
            )

        try:
            response = httpx.get(_CSV_URL, timeout=self._timeout, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(f"S&P 500 constituents request failed: {exc}") from exc

        frame = pl.read_csv(StringIO(response.text))
        if frame.is_empty() or not any(c.lower() == "symbol" for c in frame.columns):
            raise UpstreamError(
                f"unexpected S&P 500 CSV shape: columns {frame.columns}"
            )

        frame = frame.rename(
            {
                c: c.strip().lower().replace(" ", "_").replace("-", "_")
                for c in frame.columns
            }
        )
        before = frame.height
        frame = frame.drop_nulls(subset=["symbol"])
        if dropped := before - frame.height:
            self._log.warning("dropped rows with null symbol", dropped=dropped)

        if frame.is_empty():
            raise RequestError("S&P 500 constituents source returned no rows")

        metadata: dict[str, object] = {"source": _CSV_URL}
        if self._pull_unlisted:
            unlisted = self._fetch_unlisted(set(frame["symbol"].to_list()))
            metadata |= {"unlisted_source": _CHANGES_URL, "unlisted": unlisted.height}
            frame = pl.concat(
                [frame.with_columns(listed=pl.lit(True)), unlisted],
                how="diagonal_relaxed",
            )
        metadata["rows"] = frame.height

        GENERIC_TABLE.validate(frame)
        return FetchResult(
            frame=frame,
            schema=GENERIC_TABLE,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata=metadata,
        )

    def _fetch_unlisted(self, current: set[str]) -> pl.DataFrame:
        """Former constituents: every ticker removed per the changes table that
        is not in the index today, with its latest removal."""
        # ponytail: Wikipedia's table is "selected" changes (~400 rows back to
        # 1976), not full point-in-time membership; swap in a dedicated
        # historical dataset if completeness matters.
        try:
            response = httpx.get(
                _CHANGES_URL,
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "heimdall-mimird"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(f"S&P 500 changes request failed: {exc}") from exc

        parser = _ChangesTableParser()
        parser.feed(response.text)
        rows = [r for r in parser.rows if len(r) >= 6 and r[3]]
        if not rows:
            raise UpstreamError("S&P 500 changes table not found or empty")

        return (
            pl.DataFrame(
                {
                    "symbol": [r[3] for r in rows],
                    "security": [r[4] for r in rows],
                    "date_removed": [
                        datetime.strptime(r[0], "%B %d, %Y").date() for r in rows
                    ],
                    "removal_reason": [r[5] for r in rows],
                }
            )
            .filter(~pl.col("symbol").is_in(list(current)))
            .sort("date_removed", descending=True)
            .unique(subset=["symbol"], keep="first", maintain_order=True)
            .with_columns(listed=pl.lit(False))
        )


class _ChangesTableParser(HTMLParser):
    """Collects the `<td>` texts of each row in `<table id="changes">`."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._depth = 0  # table nesting depth, counted from the changes table
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and (self._depth or ("id", "changes") in attrs):
            self._depth += 1
        elif self._depth == 1 and tag == "tr":
            self.rows.append([])
        elif self._depth == 1 and tag == "td" and self.rows:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._depth:
            self._depth -= 1
        elif tag == "td" and self._cell is not None:
            self.rows[-1].append("".join(self._cell).strip())
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)
