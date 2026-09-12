from __future__ import annotations

from datetime import datetime

import httpx
import polars as pl
import pytest
import respx

from heimdall._contracts import BatchResult, FetchRequest
from heimdall.errors import RequestError, UpstreamError
from heimdall.providers._fred import FredProvider
from heimdall.schemas import OBSERVATIONS
from heimdall.testing import ProviderContractTests

_CSV = "observation_date,DGS10\n2024-01-02,3.95\n2024-01-03,3.91\n2024-01-04,.\n2024-01-05,4.02\n"
_GDP_CSV = "observation_date,GDP\n2024-01-01,27000.0\n2024-04-01,27500.0\n"
_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


@respx.mock
def test_fetch_parses_and_normalizes() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    result = FredProvider().fetch("DGS10")

    assert result.provider_id == "fred"
    assert result.schema is OBSERVATIONS
    OBSERVATIONS.validate(result.frame)
    assert result.frame.columns == ["timestamp", "series_id", "value"]
    # the "." observation is dropped
    assert result.frame.height == 3
    assert result.frame["series_id"].unique().to_list() == ["DGS10"]
    assert result.frame["value"].dtype == pl.Float64


@respx.mock
def test_date_range_filter() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    result = FredProvider().fetch(
        "DGS10", start=datetime(2024, 1, 3), end=datetime(2024, 1, 4)
    )
    assert result.frame["timestamp"].to_list() == [datetime(2024, 1, 3)]


def test_timeout_is_a_typed_init_arg() -> None:
    assert FredProvider()._timeout == 30.0
    assert FredProvider(timeout=5.0)._timeout == 5.0


@respx.mock
def test_empty_range_raises_request_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
    with pytest.raises(RequestError):
        FredProvider().fetch("DGS10", start=datetime(2030, 1, 1))


@respx.mock
def test_http_error_becomes_upstream_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(UpstreamError):
        FredProvider().fetch("NOPE")


class TestFredContract(ProviderContractTests):
    _csv_route = None

    def setup_method(self) -> None:
        self._router = respx.mock(assert_all_called=False)
        self._router.get(_URL).mock(return_value=httpx.Response(200, text=_CSV))
        self._router.start()

    def teardown_method(self) -> None:
        self._router.stop()

    def make_provider(self) -> FredProvider:
        return FredProvider()

    def sample_request(self) -> FetchRequest:
        return FetchRequest(resource="DGS10")


@respx.mock
def test_fetch_many_returns_batch_result() -> None:
    respx.get(_URL, params={"id": "DGS10"}).mock(return_value=httpx.Response(200, text=_CSV))
    respx.get(_URL, params={"id": "GDP"}).mock(return_value=httpx.Response(200, text=_GDP_CSV))

    batch = FredProvider().fetch(["DGS10", "GDP"])

    assert isinstance(batch, BatchResult)
    assert set(batch.ok) == {"DGS10", "GDP"}
    assert not batch.failed
    # combined frame stacks both series, distinguishable by series_id
    assert set(batch.frame["series_id"].unique().to_list()) == {"DGS10", "GDP"}
    assert batch.frame.height == batch.ok["DGS10"].frame.height + batch.ok["GDP"].frame.height


@respx.mock
def test_fetch_many_collects_failures() -> None:
    respx.get(_URL, params={"id": "DGS10"}).mock(return_value=httpx.Response(200, text=_CSV))
    respx.get(_URL, params={"id": "NOPE"}).mock(return_value=httpx.Response(404))

    batch = FredProvider().fetch(["DGS10", "NOPE"])

    assert list(batch.ok) == ["DGS10"]
    assert list(batch.failed) == ["NOPE"]
    assert isinstance(batch.failed["NOPE"], UpstreamError)


@pytest.mark.network
def test_fred_live() -> None:
    result = FredProvider().fetch("DGS10")
    OBSERVATIONS.validate(result.frame)
    assert result.frame.height > 100
