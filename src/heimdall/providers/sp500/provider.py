"""`sp500`: the current S&P 500 constituent list."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from io import StringIO
from typing import Annotated

import httpx
import polars as pl

from heimdall._contracts import BatchResult, FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._base import Capabilities, Provider, ProviderMetadata
from heimdall.schemas import GENERIC_TABLE

_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
)
_RESOURCE = "constituents"


class SP500Provider(Provider):
    """Who is in the S&P 500 today: one row per constituent, with its sector.

    Source: the community-maintained CSV mirror at
    github.com/datasets/s-and-p-500-companies.  A snapshot, not point-in-time
    history, and not parameterized by ticker or date: the whole list is the
    resource, so `"constituents"` is the only accepted value (and the default).
    """

    metadata = ProviderMetadata(
        name="sp500",
        description="The current S&P 500 constituent list.",
    )
    capabilities = Capabilities(
        data_kinds=(GENERIC_TABLE.name,),
        intervals=(),
        supports_date_range=False,
        requires_auth=False,
    )

    def __init__(self, *, timeout: Annotated[float, "HTTP timeout in seconds."] = 30.0) -> None:
        self._timeout = timeout

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
            raise RequestError(f"sp500: resource must be {_RESOURCE!r}, got {request.resource!r}")

        try:
            response = httpx.get(_CSV_URL, timeout=self._timeout, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError(f"S&P 500 constituents request failed: {exc}") from exc

        frame = pl.read_csv(StringIO(response.text))
        if frame.is_empty() or not any(c.lower() == "symbol" for c in frame.columns):
            raise UpstreamError(f"unexpected S&P 500 CSV shape: columns {frame.columns}")

        frame = frame.rename(
            {c: c.strip().lower().replace(" ", "_").replace("-", "_") for c in frame.columns}
        )
        before = frame.height
        frame = frame.drop_nulls(subset=["symbol"])
        if dropped := before - frame.height:
            self._log.warning("dropped rows with null symbol", dropped=dropped)

        if frame.is_empty():
            raise RequestError("S&P 500 constituents source returned no rows")

        GENERIC_TABLE.validate(frame)
        return FetchResult(
            frame=frame,
            schema=GENERIC_TABLE,
            provider_id=self.id,
            request=request,
            retrieved_at=utcnow(),
            metadata={"source": _CSV_URL, "rows": frame.height},
        )
