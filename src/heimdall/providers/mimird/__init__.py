"""`mimird`: daily OHLCV bars from a Mimird instance's prices API.

For self-hosted Mimird instances that pull candles from the hosted one (or any
other Mimird). Needs the instance's URL and an API key:

    heimdall.configure("mimird", base_url="https://...", api_key="mk_...")

or `HEIMDALL_MIMIRD_BASE_URL` / `HEIMDALL_MIMIRD_API_KEY` (a `.env` works too).
"""

from __future__ import annotations

from .provider import MimirdProvider

__all__ = ["MimirdProvider", "_register_lazy"]


def _register_lazy(registry: object) -> None:
    """Hook called by `heimdall._load_bundled` when the `mimird` extra is
    installed. Config is resolved on first use, so a missing key raises
    `ConfigError` from the first fetch, not at `import heimdall`.
    """
    from heimdall.providers._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if MimirdProvider.id not in registry.list():
        registry.register_lazy(MimirdProvider.id, MimirdProvider.from_env)
