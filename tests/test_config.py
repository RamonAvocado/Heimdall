from __future__ import annotations

import os

import pytest

import heimdall._config as config


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
