"""Shared test fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from heimdall.contracts import FetchRequest, FetchResult
from heimdall.provider import Capabilities, Provider
from heimdall.schemas import OBSERVATIONS


class DummyProvider(Provider):
    """A minimal in-memory provider used across the test suite."""

    id = "dummy"
    capabilities = Capabilities(data_kinds=(OBSERVATIONS.name,), intervals=("1d",))

    def fetch(self, request: FetchRequest) -> FetchResult:
        frame = pl.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 1), datetime(2024, 1, 2)],
                "series_id": [request.resource, request.resource],
                "value": [1.0, 2.0],
            }
        ).with_columns(pl.col("timestamp").cast(pl.Datetime))
        return FetchResult(
            frame=frame,
            schema=OBSERVATIONS,
            provider_id=self.id,
            request=request,
            retrieved_at=datetime.now(UTC),
        )


@pytest.fixture
def dummy_provider() -> DummyProvider:
    return DummyProvider()


@pytest.fixture
def fresh_registry():
    from heimdall.registry import ProviderRegistry

    return ProviderRegistry()
