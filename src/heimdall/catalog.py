"""Every provider heimdall bundles, described as data.

The Mimird docs (Yggdrasil) render this as the package's reference pages; the
publish workflow attaches it to each GitHub release as `catalog.json` (schema:
"Package catalogs" in Yggdrasil's AGENTS.md).  An MCP server or any other tool
can call `catalog()` on the installed package to explore it.  A provider whose
extra is not installed is left out, so install them all for the full list:

    uv run --extra all python -m heimdall > catalog.json
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import version
from typing import Any

from heimdall.providers import Provider

__all__ = ["catalog"]

REPO = "https://github.com/RamonAvocado/Heimdall"


def _providers() -> list[dict[str, Any]]:
    import heimdall

    entries = []
    for name in heimdall._BUNDLED:
        try:
            module = import_module(f"heimdall.providers.{name}")
        except ImportError:
            continue
        objs = (getattr(module, n) for n in module.__all__)
        entries += [
            o.describe()
            for o in objs
            if isinstance(o, type) and issubclass(o, Provider) and o is not Provider
        ]
    return entries


def catalog() -> dict[str, Any]:
    """Every bundled provider whose extra is installed, as JSON-safe dicts.

    Each entry has `id`, `name`, `description`, `author`, `source` (a path in
    the repo), `params` (name, type, default, description) and `facts`.
    """
    return {
        "package": "heimdall",
        "version": version("heimdall-mimird"),
        "repo": REPO,
        "kinds": {"providers": _providers()},
    }
