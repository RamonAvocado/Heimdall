"""Define a provider inline, register it, fetch from it, and conformance-check it.

No network needed.  The conformance call needs `heimdall-mimird[testing]`.

    uv run python sandbox/examples/03_custom_provider.py
"""

from __future__ import annotations

import math
import pathlib
import sys
from datetime import datetime, timedelta

import polars as pl

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sandbox._helpers import show  # noqa: E402

import heimdall  # noqa: E402
from heimdall import Capabilities, FetchRequest, FetchResult, Provider  # noqa: E402
from heimdall.schemas import OBSERVATIONS  # noqa: E402
from heimdall.testing import assert_provider_conformance  # noqa: E402


class SineProvider(Provider):
    """Emits a deterministic sine wave as `timeseries.observations`."""

    id = "sine"
    capabilities = Capabilities(data_kinds=(OBSERVATIONS.name,))

    def fetch(self, request: FetchRequest) -> FetchResult:
        n = int(request.params.get("n", 30))
        base = datetime(2024, 1, 1)
        frame = pl.DataFrame(
            {
                "timestamp": [base + timedelta(days=i) for i in range(n)],
                "series_id": [request.resource] * n,
                "value": [round(math.sin(i / 3), 4) for i in range(n)],
            }
        ).with_columns(pl.col("timestamp").cast(pl.Datetime))
        OBSERVATIONS.validate(frame)
        return FetchResult(
            frame=frame,
            schema=OBSERVATIONS,
            provider_id=self.id,
            request=request,
            retrieved_at=heimdall.utcnow(),
        )


heimdall.register(SineProvider)
show(heimdall.fetch("sine", "demo"))

assert_provider_conformance(SineProvider(), FetchRequest(resource="demo"))
print("conformance : OK")
