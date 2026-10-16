"""`heimdall.catalog()` produces what the docs (and MCP servers) expect."""

from __future__ import annotations

from heimdall import _BUNDLED, catalog


def test_catalog_entries_are_complete_and_unique() -> None:
    providers = catalog()["kinds"]["providers"]
    ids = [entry["id"] for entry in providers]
    assert sorted(ids) == sorted(_BUNDLED), "every bundled provider, once"
    for entry in providers:
        assert entry["name"]
        assert entry["author"]
        assert entry["source"].startswith("src/heimdall/providers/")
        assert entry["description"], f"{entry['id']}: add a docstring"
        for param in entry["params"]:
            assert param["type"], f"{entry['id']}.{param['name']}: annotate it"
            assert param["description"], (
                f'{entry["id"]}.{param["name"]}: describe it (Annotated[type, "..."])'
            )
