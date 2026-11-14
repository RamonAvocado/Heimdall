"""`sec`: SEC EDGAR data in one provider. Form 4 insider transactions
(`kind="insider_trading"`, the default) and point-in-time XBRL
fundamentals (`kind="fundamentals"`).

Needs a caller-supplied `user_agent` (SEC requires a real contact; there's
no safe shared default). Set it once and it's resolved on first use:

    heimdall.configure("sec", user_agent="Your Name your@email.com")
    heimdall.fetch("sec", "AAPL", kind="fundamentals")

or `[tool.heimdall.sec]` `user_agent = "..."` in pyproject.toml, or
`HEIMDALL_SEC_USER_AGENT` (a `.env` file works too). Or construct it yourself:

    from heimdall import FetchRequest
    from heimdall.providers.sec import SecProvider
    from heimdall.schemas import Kind

    sec = SecProvider(user_agent="Your Name your@email.com")
    sec.fetch(FetchRequest("AAPL", kind=Kind.INSIDER_TRADING, params={"limit": 5}))
"""

from __future__ import annotations

from .companyfacts import parse_companyfacts
from .form4 import FORM4_TRANSACTIONS
from .form13f import FORM13F_FILERS, FORM13F_HOLDINGS
from .provider import SecProvider

__all__ = [
    "FORM4_TRANSACTIONS",
    "FORM13F_FILERS",
    "FORM13F_HOLDINGS",
    "SecProvider",
    "_register_lazy",
    "parse_companyfacts",
]


def _register_lazy(registry: object) -> None:
    """Hook called by `heimdall._load_bundled` when the `sec` extra is
    installed. Resolves `user_agent` on first use, not at import time, so a
    missing value raises `ConfigError` from the first real
    `heimdall.fetch("sec", ...)` call, not a crash at `import heimdall`.
    """
    from heimdall.providers._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if SecProvider.id not in registry.list():
        registry.register_lazy(SecProvider.id, SecProvider.from_env)
