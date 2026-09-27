"""Tiny .env loader - deliberately not python-dotenv.

ponytail: hand-rolled KEY=VALUE parser only - no quoting, multi-line values,
or `export` prefixes. Swap for python-dotenv if a provider ever needs those.
Real environment variables always win; a .env file only fills gaps.
"""

from __future__ import annotations

import os
from pathlib import Path

_loaded = False


def load_dotenv_once() -> None:
    """Load ``.env`` (or ``$HEIMDALL_DOTENV_PATH``) into ``os.environ`` once
    per process. Existing environment variables are never overwritten.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    path = Path(os.environ.get("HEIMDALL_DOTENV_PATH", ".env"))
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
