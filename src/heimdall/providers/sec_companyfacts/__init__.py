"""`sec_companyfacts`: point-in-time company fundamentals from SEC XBRL filings.

Needs a caller-supplied `user_agent` (SEC requires a real contact):

    heimdall.configure("sec_companyfacts", user_agent="Your Name your@email.com")

or `[tool.heimdall.sec_companyfacts]` in pyproject.toml, or
`HEIMDALL_SEC_COMPANYFACTS_USER_AGENT` (a `.env` file works too).
"""

from __future__ import annotations

from .provider import SecCompanyFactsProvider

__all__ = ["SecCompanyFactsProvider", "_register_lazy"]


def _register_lazy(registry: object) -> None:
    """Hook called by `heimdall._load_bundled` when the `sec_companyfacts` extra
    is installed. Config is resolved on first use, not at import time.
    """
    from heimdall.providers._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if SecCompanyFactsProvider.id not in registry.list():
        registry.register_lazy(
            SecCompanyFactsProvider.id, SecCompanyFactsProvider.from_env
        )
