"""SEC Form 4 (insider transaction) provider.

Needs a caller-supplied ``user_agent`` (SEC requires a real contact; there's
no safe shared default). Set it once via environment variable and it's
resolved automatically on first use::

    export HEIMDALL_SEC_FORM4_USER_AGENT="Your Name your@email.com"

(a ``.env`` file works too - see ``.env.example``). Or construct it
yourself for a one-off / non-default ``timeout``::

    import heimdall
    from heimdall.providers.sec_form4 import SecForm4Provider

    heimdall.register(SecForm4Provider(user_agent="Your Name your@email.com"))
"""

from __future__ import annotations

from .provider import SecForm4Provider

__all__ = ["SecForm4Provider", "_register_lazy"]


def _register_lazy(registry: object) -> None:
    """Hook called by :func:`heimdall._load_bundled` when the ``sec_form4``
    extra is installed. Resolves ``user_agent`` from the environment on first
    use, not at import time - so a missing/unset value raises
    :class:`~heimdall.errors.ConfigError` from the first real
    ``heimdall.fetch("sec_form4", ...)`` call, not a crash at ``import heimdall``.
    """
    from heimdall._registry import ProviderRegistry

    assert isinstance(registry, ProviderRegistry)
    if SecForm4Provider.id not in registry.list():
        registry.register_lazy(SecForm4Provider.id, SecForm4Provider.from_env)
