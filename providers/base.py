from __future__ import annotations

from abc import ABC, abstractmethod

import polars as pl

from models.db import Dataset


class BaseDataProvider(ABC):
    provider_code: str

    @abstractmethod
    def fetch(self, dataset: Dataset) -> pl.DataFrame:
        raise NotImplementedError


def require_dataset_field(dataset: Dataset, field_name: str) -> str:
    value = getattr(dataset, field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(
        f"Dataset {dataset.code!r} is missing required provider metadata: {field_name}"
    )
