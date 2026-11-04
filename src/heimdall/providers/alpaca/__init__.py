"""`alpaca`: OHLCV bars from Alpaca's market-data API.

Needs an Alpaca API key pair (paper or live, both work for market data):

    heimdall.configure("alpaca", api_key_id="PK...", api_secret_key="...")

or `HEIMDALL_ALPACA_API_KEY_ID` / `HEIMDALL_ALPACA_API_SECRET_KEY` (a `.env`
works too).
"""

from __future__ import annotations

from .provider import AlpacaProvider

__all__ = ["AlpacaProvider", "_register_lazy"]


def _register_lazy(registry: object) -> None:
    """Hook called by `heimdall._load_bundled` when the `alpaca` extra is
    installed. Config is resolved on first use, so a missing key raises
    `ConfigError` from the first fetch, not at `import heimdall`.
    """
    from heimdall.providers._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if AlpacaProvider.id not in registry.list():
        registry.register_lazy(AlpacaProvider.id, AlpacaProvider.from_env)
