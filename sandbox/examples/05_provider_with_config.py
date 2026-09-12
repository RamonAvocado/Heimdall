"""Show how config / credentials reach a provider - and what happens without them.

Config is plain typed keyword arguments on the provider's ``__init__``. The
caller builds the values (here from the environment) and constructs the
provider; the provider never reads ``os.environ`` itself.

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
    capabilities = Capabilities(data_kinds=(GENERIC_TABLE.name,), requires_auth=True)

    def __init__(self, *, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ConfigError("token-echo: api_key must be a non-empty string")
        self._api_key = api_key
        self._timeout = timeout

    def _fetch(self, request: FetchRequest) -> FetchResult:
        frame = pl.DataFrame(
            {"resource": [request.resource], "api_key_seen": [self._api_key]}
        )
        return FetchResult(
            frame=frame,
            schema=GENERIC_TABLE,
            provider_id=self.id,
            request=request,
            retrieved_at=heimdall.utcnow(),
        )


# 1. Construct without the key -> the provider's own ConfigError, raised early.
try:
    TokenEcho(api_key="")
except ConfigError as exc:
    print(f"bad config -> {exc}\n")

# 2. Supply it. The caller reads the environment and passes a typed argument.
os.environ.setdefault("HEIMDALL_TOKENECHO_API_KEY", "sk-demo-123")
heimdall.register(TokenEcho(api_key=os.environ["HEIMDALL_TOKENECHO_API_KEY"]))

show(heimdall.fetch("token-echo", "hello"))
