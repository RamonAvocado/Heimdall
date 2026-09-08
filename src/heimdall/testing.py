"""A reusable conformance suite for providers.

Any provider package - first- or third-party - can prove it honours the
contract by either calling :func:`assert_provider_conformance` directly or
subclassing :class:`ProviderContractTests` in its pytest suite.

This module needs pytest. It is not pulled in by the base install; get it with
``pip install heimdall-mimird[testing]``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import polars as pl

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without the extra
    raise ModuleNotFoundError(
        "heimdall.testing requires pytest. Install it with:  pip install heimdall-mimird[testing]"
    ) from exc

from heimdall.contracts import BatchResult, FetchRequest, FetchResult
from heimdall.errors import ConfigError, RequestError
from heimdall._provider import Capabilities, Provider

__all__ = ["assert_provider_conformance", "ProviderContractTests"]


def assert_provider_conformance(provider: Provider, sample: FetchRequest) -> FetchResult:
    """Run every contract check against ``provider`` using ``sample`` as a
    known-good request. Returns the :class:`FetchResult` so callers can make
    extra provider-specific assertions.
    """
    assert isinstance(provider.id, str) and provider.id, "provider.id must be a non-empty string"
    assert isinstance(provider.capabilities, Capabilities), "capabilities must be a Capabilities"
    assert provider.capabilities.data_kinds, "capabilities.data_kinds must be non-empty"

    result = provider._fetch(sample)
    assert isinstance(result, FetchResult), "fetch() must return a FetchResult"
    assert isinstance(result.frame, pl.DataFrame) and result.frame.height > 0, (
        "result.frame must be a non-empty DataFrame"
    )
    assert result.provider_id == provider.id, "result.provider_id must equal provider.id"
    assert result.schema.name in provider.capabilities.data_kinds, (
        f"result.schema {result.schema.name!r} is not in capabilities.data_kinds"
    )

    # The frame must actually match the schema it claims.
    result.schema.validate(result.frame)

    assert isinstance(result.retrieved_at, datetime) and result.retrieved_at.tzinfo is not None, (
        "retrieved_at must be timezone-aware"
    )
    skew = abs((datetime.now(UTC) - result.retrieved_at).total_seconds())
    assert skew < 3600, "retrieved_at should be roughly now"

    # A second identical call yields the same shape.
    again = provider._fetch(sample)
    assert again.schema.name == result.schema.name
    assert set(again.frame.columns) == set(result.frame.columns)

    # An unsupported interval is a RequestError, not a bare ValueError/KeyError.
    if provider.capabilities.intervals:
        bad = replace(sample, interval="definitely-not-a-real-interval")
        with pytest.raises(RequestError):
            provider._fetch(bad)

    # A one-item list is a BatchResult carrying exactly that resource.
    batch = provider.fetch([sample.resource], sample.interval, sample.start, sample.end)
    assert isinstance(batch, BatchResult), "fetch([...]) must return a BatchResult"
    assert list(batch.ok) == [sample.resource] and not batch.failed, (
        f"a one-item batch should put exactly that resource in .ok, got {batch}"
    )
    assert batch.frame.height > 0, "BatchResult.frame must be non-empty"

    return result


class ProviderContractTests:
    """Mixin of parametrised contract tests.

    Subclass it in a provider's test module and implement :meth:`make_provider`
    and :meth:`sample_request`::

        class TestFredContract(ProviderContractTests):
            def make_provider(self):
                return FredProvider()

            def sample_request(self):
                return FetchRequest(resource="DGS10")
    """

    def make_provider(self) -> Provider:  # pragma: no cover - overridden
        raise NotImplementedError

    def sample_request(self) -> FetchRequest:  # pragma: no cover - overridden
        raise NotImplementedError

    def test_conformance(self) -> None:
        assert_provider_conformance(self.make_provider(), self.sample_request())

    def test_missing_required_config_raises(self) -> None:
        provider_cls = type(self.make_provider())
        required = provider_cls.capabilities.required_config
        if not required:
            pytest.skip("provider declares no required config")
        with pytest.raises(ConfigError):
            provider_cls({})

    def test_empty_resource_rejected(self) -> None:
        with pytest.raises((ValueError, RequestError)):
            FetchRequest(resource="   ")
