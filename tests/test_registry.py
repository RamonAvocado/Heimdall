from __future__ import annotations

import pytest

from heimdall.errors import ProviderError, ProviderNotFound
from heimdall.provider import Capabilities, Provider


class _P(Provider):
    id = "p"
    capabilities = Capabilities(data_kinds=("table.generic",))

    def fetch(self, request):  # pragma: no cover - not exercised here
        raise NotImplementedError


def test_register_class_instantiates(fresh_registry) -> None:
    inst = fresh_registry.register(_P)
    assert isinstance(inst, _P)
    assert fresh_registry.get("p") is inst
    assert fresh_registry.list() == ["p"]


def test_register_instance(fresh_registry) -> None:
    p = _P()
    fresh_registry.register(p)
    assert fresh_registry.get("p") is p


def test_register_instance_with_config_is_error(fresh_registry) -> None:
    with pytest.raises(ProviderError, match="config"):
        fresh_registry.register(_P(), config={"x": 1})


def test_duplicate_registration_rejected_unless_replace(fresh_registry) -> None:
    fresh_registry.register(_P)
    with pytest.raises(ProviderError, match="already registered"):
        fresh_registry.register(_P)
    fresh_registry.register(_P, replace=True)


def test_get_unknown_raises_provider_not_found(fresh_registry) -> None:
    with pytest.raises(ProviderNotFound):
        fresh_registry.get("nope")


def test_register_rejects_non_provider(fresh_registry) -> None:
    with pytest.raises(ProviderError):
        fresh_registry.register(object())  # type: ignore[arg-type]


def test_bundled_providers_present_in_default_registry() -> None:
    import heimdall

    assert {"fred", "yfinance"} <= set(heimdall.list_providers())
