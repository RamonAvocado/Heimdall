from __future__ import annotations

import asyncio
from datetime import datetime

import polars as pl
import pytest

from heimdall._contracts import FetchRequest, FetchResult
from heimdall._time import utcnow
from heimdall.errors import RequestError
from heimdall.providers import Capabilities, Provider, ProviderMetadata
from heimdall.schemas import GENERIC_TABLE, OBSERVATIONS


def test_instance_fetch_takes_a_request_with_params(dummy_provider) -> None:
    request = FetchRequest("X", params={"limit": 3})

    assert dummy_provider.fetch(request).request.params == {"limit": 3}
    assert asyncio.run(dummy_provider.afetch(request)).request.params == {"limit": 3}

    day = datetime(2024, 1, 1)
    with pytest.raises(RequestError):  # validated like the string form
        dummy_provider.fetch(FetchRequest("X", start=day, end=day))
    with pytest.raises(TypeError):
        dummy_provider.fetch(request, interval="1d")


class _TwoKinds(Provider):
    metadata = ProviderMetadata(name="two_kinds")
    capabilities = Capabilities(data_kinds=(OBSERVATIONS.name, GENERIC_TABLE.name))

    def _fetch(self, request: FetchRequest) -> FetchResult:
        match request.kind:
            case GENERIC_TABLE.name:
                schema = GENERIC_TABLE
            case _:
                schema = OBSERVATIONS
        return FetchResult(pl.DataFrame({"x": [1]}), schema, self.id, request, utcnow())


def test_kind_defaults_to_the_first_data_kind() -> None:
    result = _TwoKinds().fetch("X")
    assert result.request.kind == OBSERVATIONS.name
    assert result.schema is OBSERVATIONS


def test_kind_routes_to_its_branch_in_every_form() -> None:
    p = _TwoKinds()
    assert p.fetch("X", kind=GENERIC_TABLE.name).schema is GENERIC_TABLE
    assert p.fetch(FetchRequest("X", kind=GENERIC_TABLE.name)).schema is GENERIC_TABLE
    batch = p.fetch(["X", "Y"], kind=GENERIC_TABLE.name)
    assert {r.schema.name for r in batch.ok.values()} == {GENERIC_TABLE.name}
    abatch = asyncio.run(p.afetch(["X", "Y"], kind=GENERIC_TABLE.name))
    assert {r.schema.name for r in abatch.ok.values()} == {GENERIC_TABLE.name}


def test_unknown_kind_is_a_request_error() -> None:
    with pytest.raises(RequestError, match="candles"):
        _TwoKinds().fetch("X", kind="candles")
