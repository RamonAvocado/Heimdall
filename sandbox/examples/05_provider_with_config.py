"""Show how config / credentials reach a provider - and what happens without them.

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

    id = "token-echo"
    capabilities = Capabilities(data_kinds=(GENERIC_TABLE.name,), required_config=("api_key",))

    def fetch(self, request: FetchRequest) -> FetchResult:
        frame = pl.DataFrame(
            {"resource": [request.resource], "api_key_seen": [self.config("api_key")]}
        )
        return FetchResult(
            frame=frame,
            schema=GENERIC_TABLE,
            provider_id=self.id,
            request=request,
            retrieved_at=heimdall.utcnow(),
        )


# 1. Construct without the required key -> ConfigError, raised early.
try:
    TokenEcho()
except ConfigError as exc:
    print(f"no config -> {exc}\n")

# 2. Supply it. The caller builds the config; the provider never reads os.environ.
os.environ.setdefault("HEIMDALL_TOKENECHO_API_KEY", "sk-demo-123")
config = heimdall.config_from_env("HEIMDALL_TOKENECHO_")
heimdall.register(TokenEcho, config=config)

show(heimdall.fetch("token-echo", "hello"))
