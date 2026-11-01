"""Provider config sources: `heimdall.configure`, `.env`, and pyproject.toml.

Tiny .env loader - deliberately not python-dotenv.

ponytail: hand-rolled KEY=VALUE parser only - no quoting, multi-line values,
or `export` prefixes. Swap for python-dotenv if a provider ever needs those.
Real environment variables always win; a .env file only fills gaps.
"""

from __future__ import annotations

import os
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

_loaded = False

#: `{provider_id: {param: value}}` set in code by `heimdall.configure`.
configured: dict[str, dict[str, Any]] = {}


@cache
def pyproject_settings() -> dict[str, dict[str, Any]]:
    """`[tool.heimdall.<provider_id>]` tables from the nearest pyproject.toml
    at or above the working directory (read once per process)."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        path = directory / "pyproject.toml"
        if path.is_file():
            return tomllib.loads(path.read_text()).get("tool", {}).get("heimdall", {})
    return {}


def load_dotenv_once() -> None:
    """Load `.env` (or `$HEIMDALL_DOTENV_PATH`) into `os.environ` once
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
