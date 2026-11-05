"""Benchmarks of heimdall's own work (parsing, batching), network mocked out.

Off by default (`--benchmark-disable` runs each once, as a test). Measure with:
    uv run pytest tests/benchmarks --benchmark-enable --no-cov --benchmark-autosave
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx
import respx

from heimdall.providers.fred import FredProvider
from heimdall.providers.sec_companyfacts.provider import parse_companyfacts

_SYMBOLS = [f"S{i}" for i in range(100)]
_DAYS = [date(1990, 1, 1) + timedelta(days=i) for i in range(10_000)]
_FRED_CSV = "observation_date,DGS10\n" + "".join(
    f"{d},{i % 500 / 100}\n" for i, d in enumerate(_DAYS)
)


def _quarters(n: int) -> list[dict]:
    # n fiscal quarters as 10-Qs report them, plus each one re-filed a year later.
    out = []
    for q in range(n):
        start = date(1990 + q // 4, 1 + 3 * (q % 4), 1)
        end = start + timedelta(days=89)
        f = {"start": str(start), "end": str(end), "val": float(q)}
        out.append({**f, "filed": str(end + timedelta(days=30))})
        out.append({**f, "filed": str(end + timedelta(days=395))})
    return out


_SEC_DOC = {
    "facts": {
        "us-gaap": {
            concept: {"units": {"USD": _quarters(140)}}
            for concept in (
                "Revenues",
                "NetIncomeLoss",
                "OperatingIncomeLoss",
                "NetCashProvidedByUsedInOperatingActivities",
            )
        }
    }
}


def test_fetch_overhead(benchmark, dummy_provider) -> None:
    benchmark(dummy_provider.fetch, "X")


def test_fetch_batch_100(benchmark, dummy_provider) -> None:
    result = benchmark(dummy_provider.fetch, _SYMBOLS)
    assert len(result.ok) == 100


def test_afetch_fanout_100(benchmark, dummy_provider) -> None:
    result = benchmark(lambda: asyncio.run(dummy_provider.afetch(_SYMBOLS)))
    assert len(result.ok) == 100


@respx.mock
def test_fred_parse_10k_rows(benchmark) -> None:
    respx.get("https://fred.stlouisfed.org/graph/fredgraph.csv").mock(
        return_value=httpx.Response(200, text=_FRED_CSV)
    )
    result = benchmark(FredProvider().fetch, "DGS10")
    assert result.frame.height == 10_000


def test_sec_companyfacts_parse(benchmark) -> None:
    # The pure parser: fetch() also sleeps for SEC's 10 req/s rate limit.
    assert benchmark(parse_companyfacts, _SEC_DOC)
