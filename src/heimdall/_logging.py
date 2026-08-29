"""Logging helpers.

Heimdall logs through ``ramonavocado_logger`` (structlog). It never configures
handlers or levels itself - the host application calls
``ramonavocado_logger.configure_logging`` if it wants output.
"""

from __future__ import annotations

from typing import Any

from ramonavocado_logger import get_log

_ROOT = "heimdall"


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger namespaced under ``heimdall``.

    ``get_logger("providers.fred")`` binds ``logger="heimdall.providers.fred"``.
    """
    scope = _ROOT if not name else f"{_ROOT}.{name}"
    return get_log(component=scope)
