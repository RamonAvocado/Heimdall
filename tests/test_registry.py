from __future__ import annotations

import pytest

from heimdall.errors import ConfigError, ProviderError, ProviderNotFound
from heimdall.providers import Capabilities, Provider, ProviderMetadata


class _P(Provider):
    metadata = ProviderMetadata(name="p")
    capabilities = Capabilities(data_kinds=("table.generic",))

    def _fetch(self, request):  # pragma: no cover - not exercised here
        raise NotImplementedError


class _Configurable(Provider):
    metadata = ProviderMetadata(name="cfg")
    capabilities = Capabilities(data_kinds=("table.generic",))

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def _fetch(self, request):  # pragma: no cover - not exercised here
        raise NotImplementedError


class _NeedsToken(Provider):
    metadata = ProviderMetadata(name="needs_token")
    capabilities = Capabilities(data_kinds=("table.generic",))

    def __init__(self, *, token: str) -> None:
        self.token = token

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


def test_register_lazy_defers_construction(fresh_registry, monkeypatch) -> None:
    monkeypatch.setenv("HEIMDALL_NEEDS_TOKEN_TOKEN", "secret")
    calls = []

    def factory():
        calls.append(1)
        return _NeedsToken.from_env()

    fresh_registry.register_lazy("needs_token", factory)
    assert "needs_token" in fresh_registry.list()  # listed before it's built
    assert not calls

    first = fresh_registry.get("needs_token")
    second = fresh_registry.get("needs_token")

    assert first is second
    assert calls == [1]  # factory only ran once, result was cached
    assert first.token == "secret"


def test_register_lazy_propagates_config_error(fresh_registry, monkeypatch) -> None:
    monkeypatch.delenv("HEIMDALL_NEEDS_TOKEN_TOKEN", raising=False)
    fresh_registry.register_lazy("needs_token", _NeedsToken.from_env)

    with pytest.raises(ConfigError, match="HEIMDALL_NEEDS_TOKEN_TOKEN"):
        fresh_registry.get("needs_token")


def test_register_lazy_rejects_duplicate(fresh_registry) -> None:
    fresh_registry.register_lazy("needs_token", _NeedsToken.from_env)
    with pytest.raises(ProviderError, match="already registered"):
        fresh_registry.register_lazy("needs_token", _NeedsToken.from_env)


def test_eager_register_rejects_id_already_lazily_registered(fresh_registry) -> None:
    fresh_registry.register_lazy("p", _P)
    with pytest.raises(ProviderError, match="already registered"):
        fresh_registry.register(_P)
    fresh_registry.register(_P, replace=True)  # replace clears the pending factory
    assert fresh_registry.get("p") is not None
    assert "p" not in fresh_registry._factories


def test_entry_points_load_once_on_first_query(monkeypatch) -> None:
    from types import SimpleNamespace

    import heimdall.providers._registry as reg

    def _boom():
        raise ImportError("broken plugin")

    calls = []

    def fake_entry_points(group):
        calls.append(group)
        return [
            SimpleNamespace(name="p", load=lambda: _P),
            SimpleNamespace(name="bad", load=_boom),
        ]

    monkeypatch.setattr(reg, "entry_points", fake_entry_points)
    registry = reg.ProviderRegistry(entry_point_group="test.group")
    assert calls == []  # nothing scanned until queried
    assert registry.list() == ["p"]
    assert registry.get("p").id == "p"
    assert calls == ["test.group"]  # scanned once
    with pytest.raises(ProviderNotFound, match="broken plugin"):
        registry.get("bad")


def test_metadata_is_required() -> None:
    with pytest.raises(TypeError, match="metadata"):

        class _NoMeta(Provider):
            capabilities = Capabilities(data_kinds=("table.generic",))

            def _fetch(self, request):  # pragma: no cover
                raise NotImplementedError
