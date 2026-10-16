"""Print Heimdall's catalog.json: every bundled provider.

The Mimird docs (Yggdrasil) render this file as the package's reference pages.
The release workflow attaches it to each GitHub release; see the "Package
catalogs" section of Yggdrasil's AGENTS.md for the schema. Every extra must be
installed so every provider imports:

    uv run --extra all scripts/export_catalog.py > catalog.json
"""

from __future__ import annotations

import inspect
import json
from dataclasses import asdict
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any

from heimdall import _BUNDLED, Provider

REPO = "https://github.com/RamonAvocado/Heimdall"
ROOT = Path(__file__).resolve().parent.parent


def _summary(obj: Any) -> str:
    """First paragraph of the docstring, on one line, with Markdown backticks."""
    # __doc__, not inspect.getdoc: a class must not inherit its base's docstring.
    doc = inspect.cleandoc(obj.__doc__ or "")
    return " ".join(doc.split("\n\n")[0].split()).replace("``", "`")


def _provider(name: str, cls: type[Provider]) -> dict[str, Any]:
    path = Path(inspect.getsourcefile(cls) or "").resolve().relative_to(ROOT)
    params = [
        {
            "name": p.name,
            "type": str(p.annotation) if p.annotation is not p.empty else "",
            "default": None if p.default is p.empty else repr(p.default),
            "description": "",
        }
        for p in inspect.signature(cls.__init__).parameters.values()
        if p.name != "self" and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]
    return {
        "id": cls.id,
        "name": cls.__name__,
        # Providers document themselves in the module docstring.
        "description": _summary(cls) or _summary(inspect.getmodule(cls)),
        "author": cls.author,
        "source": f"{path.as_posix()}#L{inspect.getsourcelines(cls)[1]}",
        "params": params,
        "facts": {"install": f"heimdall-mimird[{name}]", **asdict(cls.capabilities)},
    }


def build() -> dict[str, Any]:
    providers = []
    for name in _BUNDLED:
        module = import_module(f"heimdall.providers.{name}")
        providers += [
            _provider(name, obj)
            for obj in vars(module).values()
            if isinstance(obj, type) and issubclass(obj, Provider) and obj is not Provider
        ]
    return {
        "package": "heimdall",
        "version": version("heimdall-mimird"),
        "repo": REPO,
        "kinds": {"providers": providers},
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
