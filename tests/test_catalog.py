"""scripts/export_catalog.py produces what the docs expect."""

from __future__ import annotations

import runpy
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "export_catalog.py"


def test_catalog_lists_every_bundled_provider_once() -> None:
    from heimdall import _BUNDLED

    providers = runpy.run_path(str(SCRIPT))["build"]()["kinds"]["providers"]

    ids = [p["id"] for p in providers]
    assert sorted(ids) == sorted(_BUNDLED)
    for p in providers:
        assert p["name"] and p["author"] and p["description"]
        assert p["source"].startswith("src/heimdall/providers/")
