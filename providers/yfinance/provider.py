from __future__ import annotations

import polars as pl

from core.providers.base import BaseDataProvider, require_dataset_field
from models.db import Dataset
from models.enum.time import TimeHorizon

from .client import YFinance


class YahooFinanceProvider(BaseDataProvider):
    provider_code = "yfinance"

    def fetch(self, dataset: Dataset) -> pl.DataFrame:
        return YFinance.download_data(
            ticker=require_dataset_field(dataset, "remote_identifier"),
            horizon=TimeHorizon.ALL,
            interval=dataset.frequency,
        )
