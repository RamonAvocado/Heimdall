"""Show how config / credentials reach a provider - and what happens without them.

Config is plain typed keyword arguments on the provider's ``__init__``.
``Provider.from_env()`` resolves them from ``HEIMDALL_<ID>_<PARAM>``
environment variables (a ``.env`` file works too - see ``.env.example``) and
raises :class:`~heimdall.errors.ConfigError` naming exactly what's missing -
the provider itself never reads ``os.environ``.

No network needed.

    uv run python sandbox/examples/05_provider_with_config.py
"""

from __future__ import annotations

import os
import pathlib
import sys

import polars as pl

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sandbox._helpers import show  # noqa: E402

import heimdall  # noqa: E402
from heimdall import Capabilities, FetchRequest, FetchResult, Provider  # noqa: E402
from heimdall.errors import ConfigError  # noqa: E402
from heimdall.schemas import GENERIC_TABLE  # noqa: E402


class TokenEcho(Provider):
    """Trivial provider that just proves it received its api_key."""

    id = "token_echo"
    capabilities = Capabilities(data_kinds=(GENERIC_TABLE.name,), requires_auth=True)

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def _fetch(self, request: FetchRequest) -> FetchResult:
        frame = pl.DataFrame({"resource": [request.resource], "api_key_seen": [self._api_key]})
        return FetchResult(
            frame=frame,
            schema=GENERIC_TABLE,
            provider_id=self.id,
            request=request,
            retrieved_at=heimdall.utcnow(),
        )


# 1. Ask for it without the env var set -> ConfigError names exactly what to set.
os.environ.pop("HEIMDALL_TOKEN_ECHO_API_KEY", None)
try:
    TokenEcho.from_env()
except ConfigError as exc:
    print(f"missing config -> {exc}\n")

# 2. Set it (a .env file works too) and it resolves automatically.
os.environ["HEIMDALL_TOKEN_ECHO_API_KEY"] = "sk-demo-123"
heimdall.register(TokenEcho.from_env())

show(heimdall.fetch("token_echo", "hello"))
