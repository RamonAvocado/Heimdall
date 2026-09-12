from __future__ import annotations

import pytest

from heimdall._provider import Capabilities, Provider
from heimdall.errors import ProviderError, ProviderNotFound


class _P(Provider):
    id = "p"
    capabilities = Capabilities(data_kinds=("table.generic",))

    def _fetch(self, request):  # pragma: no cover - not exercised here
        raise NotImplementedError


class _Configurable(Provider):
    id = "cfg"
    capabilities = Capabilities(data_kinds=("table.generic",))

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def _fetch(self, request):  # pragma: no cover - not exercised here
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


def test_register_class_uses_provider_defaults(fresh_registry) -> None:
    inst = fresh_registry.register(_Configurable)
    assert inst.timeout == 30.0


def test_register_configured_instance(fresh_registry) -> None:
    fresh_registry.register(_Configurable(timeout=5.0))
    assert fresh_registry.get("cfg").timeout == 5.0


def test_duplicate_registration_rejected_unless_replace(fresh_registry) -> None:
    fresh_registry.register(_P)
    with pytest.raises(ProviderError, match="already registered"):
        fresh_registry.register(_P)
    fresh_registry.register(_P, replace=True)


def test_get_unknown_raises_provider_not_found(fresh_registry) -> None:
    with pytest.raises(ProviderNotFound):
        fresh_registry.get("nope")


def test_get_on_empty_registry_says_so(fresh_registry) -> None:
    with pytest.raises(ProviderNotFound, match="registry is empty"):
        fresh_registry.get("fred")


def test_get_unavailable_provider_points_at_the_extra(fresh_registry) -> None:
    fresh_registry.mark_unavailable("yfinance", "No module named 'yfinance'")
    with pytest.raises(ProviderNotFound, match=r"heimdall-mimird\[yfinance\]"):
        fresh_registry.get("yfinance")


def test_register_clears_unavailable(fresh_registry) -> None:
    fresh_registry.mark_unavailable("p", "boom")
    fresh_registry.register(_P)
    assert fresh_registry.get("p").id == "p"


def test_register_rejects_non_provider(fresh_registry) -> None:
    with pytest.raises(ProviderError):
        fresh_registry.register(object())  # type: ignore[arg-type]


def test_bundled_providers_present_in_default_registry() -> None:
    import heimdall

    assert {"fred", "yfinance"} <= set(heimdall.list_providers())
