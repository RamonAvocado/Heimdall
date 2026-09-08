from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

import heimdall
from heimdall.contracts import BatchResult, FetchResult
from heimdall.providers._fred import FredProvider

_CSV = "observation_date,DGS10\n2024-01-02,3.95\n2024-01-03,3.91\n"
_GDP_CSV = "observation_date,GDP\n2024-01-01,27000.0\n2024-04-01,27500.0\n"
_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@respx.mock
def test_afetch_single_returns_fetch_result() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    result = asyncio.run(FredProvider().afetch("DGS10"))
    assert isinstance(result, FetchResult)
    assert result.frame["series_id"].unique().to_list() == ["DGS10"]


@respx.mock
def test_afetch_list_fans_out_and_collects_failure() -> None:
    respx.get(_URL, params={"id": "DGS10"}).mock(return_value=httpx.Response(200, text=_CSV))
    respx.get(_URL, params={"id": "GDP"}).mock(return_value=httpx.Response(200, text=_GDP_CSV))
    respx.get(_URL, params={"id": "NOPE"}).mock(return_value=httpx.Response(404))

    batch = asyncio.run(FredProvider().afetch(["DGS10", "GDP", "NOPE"]))

    assert isinstance(batch, BatchResult)
    assert set(batch.ok) == {"DGS10", "GDP"}
    assert list(batch.failed) == ["NOPE"]
    assert set(batch.frame["series_id"].unique().to_list()) == {"DGS10", "GDP"}


@respx.mock
def test_module_afetch_delegates_to_provider() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    result = asyncio.run(heimdall.afetch("fred", "DGS10"))
    assert isinstance(result, FetchResult)


@respx.mock
def test_afetch_list_native_batch_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    # A native_batch provider takes the single-thread path, not per-item fan-out.
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    provider = FredProvider()
    monkeypatch.setattr(type(provider), "native_batch", True)

    batch = asyncio.run(provider.afetch(["DGS10"]))
    assert isinstance(batch, BatchResult)
    assert list(batch.ok) == ["DGS10"]
