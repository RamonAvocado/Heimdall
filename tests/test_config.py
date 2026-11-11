from __future__ import annotations

import os

import pytest

import heimdall._config as config
from heimdall.providers import Capabilities, Provider, ProviderMetadata


class _NeedsToken(Provider):
    metadata = ProviderMetadata(name="needs_token")
    capabilities = Capabilities(data_kinds=("table",))

    def __init__(self, *, token: str) -> None:
        self.token = token

    def _fetch(self, request):  # pragma: no cover - not exercised here
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _reset_loaded_flag():
    config._loaded = False
    yield
    config._loaded = False


def test_loads_dotenv_into_environ(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text('FOO=bar\nQUOTED="baz"\n# a comment\n\nSPACED = spaced \n')
    monkeypatch.setenv("HEIMDALL_DOTENV_PATH", str(dotenv))
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    monkeypatch.delenv("SPACED", raising=False)

    config.load_dotenv_once()

    assert os.environ["FOO"] == "bar"
    assert os.environ["QUOTED"] == "baz"
    assert os.environ["SPACED"] == "spaced"


def test_real_env_var_wins_over_dotenv(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("FOO=from_dotenv\n")
    monkeypatch.setenv("HEIMDALL_DOTENV_PATH", str(dotenv))
    monkeypatch.setenv("FOO", "from_real_env")

    config.load_dotenv_once()

    assert os.environ["FOO"] == "from_real_env"


def test_missing_dotenv_file_is_a_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HEIMDALL_DOTENV_PATH", str(tmp_path / "does-not-exist.env"))

    config.load_dotenv_once()  # must not raise


def test_only_loads_once_per_process(tmp_path, monkeypatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("FOO=first\n")
    monkeypatch.setenv("HEIMDALL_DOTENV_PATH", str(dotenv))
    monkeypatch.delenv("FOO", raising=False)

    config.load_dotenv_once()
    dotenv.write_text("FOO=second\n")
    config.load_dotenv_once()

    assert os.environ["FOO"] == "first"


def test_from_env_precedence_configure_env_pyproject(tmp_path, monkeypatch) -> None:
    pyproject = '[tool.heimdall.needs_token]\ntoken = "toml"\n'
    (tmp_path / "pyproject.toml").write_text(pyproject)
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path / "sub")  # found by walking up
    monkeypatch.delenv("HEIMDALL_NEEDS_TOKEN_TOKEN", raising=False)
    monkeypatch.setattr(config, "configured", {})
    config.pyproject_settings.cache_clear()
    try:
        assert _NeedsToken.from_env().token == "toml"
        monkeypatch.setenv("HEIMDALL_NEEDS_TOKEN_TOKEN", "env")
        assert _NeedsToken.from_env().token == "env"
        config.configured["needs_token"] = {"token": "code"}
        assert _NeedsToken.from_env().token == "code"
        assert _NeedsToken.from_env(token="override").token == "override"
    finally:
        config.pyproject_settings.cache_clear()


def test_configure_rebuilds_a_lazily_built_provider(monkeypatch) -> None:
    import heimdall
    from heimdall.providers import PROVIDER_REGISTRY

    monkeypatch.setattr(config, "configured", {})
    PROVIDER_REGISTRY.register_lazy("needs_token", _NeedsToken.from_env)
    try:
        heimdall.configure("needs_token", token="a")
        assert PROVIDER_REGISTRY.get("needs_token").token == "a"
        heimdall.configure("needs_token", token="b")
        assert PROVIDER_REGISTRY.get("needs_token").token == "b"
    finally:
        PROVIDER_REGISTRY.unregister("needs_token")


def test_from_env_builds_a_provider_without_its_own_init() -> None:
    # object.__init__'s *args/**kwargs aren't config (yfinance has no __init__).
    class _NoInit(Provider):
        metadata = ProviderMetadata(name="no_init")
        capabilities = Capabilities(data_kinds=("table",))

        def _fetch(self, request):  # pragma: no cover - not exercised here
            raise NotImplementedError

    assert isinstance(_NoInit.from_env(), _NoInit)
