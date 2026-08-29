from __future__ import annotations

from pathlib import Path


REPO_ROOT_DIR = Path(__file__).resolve().parents[4]


def resolve_storage_path(storage_path: str | Path) -> Path:
    path = Path(storage_path)
    if path.is_absolute():
        return path
    return REPO_ROOT_DIR / path
