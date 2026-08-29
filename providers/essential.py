from __future__ import annotations

from pathlib import Path

import polars as pl
from pydantic import BaseModel, ConfigDict

from core.providers.base import require_dataset_field
from core.providers.storage import resolve_storage_path
from models.db import Dataset
from models.enum import CacheDataTypes, EconomicDataSeries


class EssentialDatasetDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: str
    category: str
    source: str
    remote_identifier: str
    frequency: str
    primary_column: str
    storage_path: str | None = None

    def get_dir_path(self) -> Path:
        if self.storage_path is not None:
            return resolve_storage_path(self.storage_path)
        return EconomicDataSeries[self.series].get_dir_path()

    def get_path(self, cache_type: CacheDataTypes) -> Path:
        return self.get_dir_path() / cache_type.file_name

    def get_manifest_path(self) -> Path:
        return self.get_dir_path() / "manifest.json"


class EssentialDataManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: str
    category: str
    source: str
    remote_identifier: str | None = None
    frequency: str
    primary_column: str
    raw_file: str
    transformed_file: str
    fast_render_file: str
    raw_columns: list[str]
    transformed_columns: list[str]
    fast_render_columns: list[str]
    transforms: list[str]


class EssentialColumnCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    series: EconomicDataSeries
    raw_columns: list[str]
    transformed_columns: list[str]
    fast_render_columns: list[str]

    @property
    def available_columns(self) -> list[str]:
        seen: dict[str, None] = {}
        for column in [
            *self.raw_columns,
            *self.transformed_columns,
            *self.fast_render_columns,
        ]:
            if column == "timestamp":
                continue
            seen.setdefault(column, None)
        return list(seen)


TRANSFORM_NAMES = [
    "diff_1",
    "pct_change_1",
    "sma_20",
    "sma_50",
]


DEFAULT_ESSENTIAL_DATASETS: dict[EconomicDataSeries, EssentialDatasetDefinition] = {
    series: EssentialDatasetDefinition(
        series=series.name,
        category=category,
        source=source,
        remote_identifier=remote_identifier,
        frequency="1d",
        primary_column=primary_column,
    )
    for series, category, source, remote_identifier, primary_column in [
        (EconomicDataSeries.COPPER, "futures", "yfinance", "HG=F", "close"),
        (EconomicDataSeries.GOLD, "futures", "yfinance", "GC=F", "close"),
        (EconomicDataSeries.NATURAL_GAS, "futures", "yfinance", "NG=F", "close"),
        (EconomicDataSeries.OIL, "futures", "yfinance", "CL=F", "close"),
        (EconomicDataSeries.SILVER, "futures", "yfinance", "SI=F", "close"),
        (EconomicDataSeries.NASDAQ100, "market", "yfinance", "^NDX", "close"),
        (
            EconomicDataSeries.NASDAQ_COMPOSITE,
            "market",
            "yfinance",
            "^IXIC",
            "close",
        ),
        (EconomicDataSeries.RUSSELL2000, "market", "yfinance", "^RUT", "close"),
        (EconomicDataSeries.SP500, "market", "yfinance", "^GSPC", "close"),
        (
            EconomicDataSeries.US_DOLLAR_INDEX,
            "market",
            "yfinance",
            "DX-Y.NYB",
            "close",
        ),
        (EconomicDataSeries.VIX, "market", "yfinance", "^VIX", "close"),
        (EconomicDataSeries.VVIX, "market", "yfinance", "^VVIX", "close"),
        (EconomicDataSeries.US_10Y, "yield", "fred", "DGS10", "value"),
        (EconomicDataSeries.US_2Y, "yield", "fred", "DGS2", "value"),
        (EconomicDataSeries.US_30Y, "yield", "fred", "DGS30", "value"),
    ]
}


def get_default_essential_dataset_definition(
    series: EconomicDataSeries,
) -> EssentialDatasetDefinition:
    return DEFAULT_ESSENTIAL_DATASETS[series]


def build_essential_dataset_definition(dataset: Dataset) -> EssentialDatasetDefinition:
    if dataset.dataset_type != "essential":
        raise ValueError(f"Dataset is not an essential dataset: {dataset.code}")

    return EssentialDatasetDefinition(
        series=_series_name_from_dataset(dataset),
        category=dataset.category,
        source=dataset.provider_code,
        remote_identifier=require_dataset_field(dataset, "remote_identifier"),
        frequency=dataset.frequency,
        primary_column=require_dataset_field(dataset, "primary_column"),
        storage_path=dataset.storage_path,
    )


def migrate_all_essential_data() -> None:
    for series in EconomicDataSeries:
        migrate_essential_dataset(get_default_essential_dataset_definition(series))


def migrate_essential_dataset(definition: EssentialDatasetDefinition) -> None:
    legacy_path = _resolve_legacy_path(definition)
    raw_frame = _load_legacy_frame(legacy_path)
    materialize_essential_dataset(definition, raw_frame)


def materialize_essential_dataset(
    definition: EssentialDatasetDefinition,
    raw_frame: pl.DataFrame,
) -> None:
    raw_frame = _normalize_raw_frame(raw_frame)
    transformed = _build_transformed_frame(raw_frame, definition.primary_column)
    fast_render = _build_fast_render_frame(raw_frame, definition.primary_column)

    definition.get_dir_path().mkdir(parents=True, exist_ok=True)
    raw_frame.write_parquet(definition.get_path(CacheDataTypes.RAW))
    transformed.write_parquet(definition.get_path(CacheDataTypes.TRANSFORMED))
    fast_render.write_parquet(definition.get_path(CacheDataTypes.FAST_RENDER))

    manifest = EssentialDataManifest(
        series=definition.series,
        category=definition.category,
        source=definition.source,
        remote_identifier=definition.remote_identifier,
        frequency=definition.frequency,
        primary_column=definition.primary_column,
        raw_file=CacheDataTypes.RAW.file_name,
        transformed_file=CacheDataTypes.TRANSFORMED.file_name,
        fast_render_file=CacheDataTypes.FAST_RENDER.file_name,
        raw_columns=raw_frame.columns,
        transformed_columns=transformed.columns,
        fast_render_columns=fast_render.columns,
        transforms=TRANSFORM_NAMES,
    )
    definition.get_manifest_path().write_text(
        manifest.model_dump_json(indent=2) + "\n"
    )


def load_essential_manifest(series: EconomicDataSeries) -> EssentialDataManifest:
    manifest_path = series.get_manifest_path()
    if not manifest_path.exists():
        raise FileNotFoundError(f"Essential data manifest not found: {manifest_path}")
    return EssentialDataManifest.model_validate_json(manifest_path.read_text())


def list_essential_columns(series: EconomicDataSeries) -> EssentialColumnCatalog:
    manifest = load_essential_manifest(series)
    return EssentialColumnCatalog(
        series=series,
        raw_columns=manifest.raw_columns,
        transformed_columns=manifest.transformed_columns,
        fast_render_columns=manifest.fast_render_columns,
    )


def load_essential_data(
    series: EconomicDataSeries,
    cache_type: CacheDataTypes = CacheDataTypes.RAW,
) -> pl.DataFrame:
    file_path = series.get_path(cache_type)
    if not file_path.exists():
        raise FileNotFoundError(f"Essential data file not found: {file_path}")

    frame = pl.read_parquet(file_path)
    return _normalize_essential_frame(frame)


def _series_name_from_dataset(dataset: Dataset) -> str:
    if dataset.code.startswith("essential."):
        return dataset.code.removeprefix("essential.").upper()
    return dataset.name


def _resolve_legacy_path(definition: EssentialDatasetDefinition) -> Path:
    series_dir = definition.get_dir_path()
    legacy_daily_path = series_dir / "1d.parquet"
    legacy_flat_path = series_dir.with_suffix(".parquet")
    if legacy_daily_path.exists():
        return legacy_daily_path
    if legacy_flat_path.exists():
        return legacy_flat_path
    if series_dir.is_file():
        return series_dir
    raise FileNotFoundError(f"Legacy essential dataset not found for {definition.series}")


def _load_legacy_frame(path: Path) -> pl.DataFrame:
    return _normalize_raw_frame(pl.read_parquet(path))


def _normalize_raw_frame(frame: pl.DataFrame) -> pl.DataFrame:
    if "date" in frame.columns and "timestamp" not in frame.columns:
        frame = frame.with_columns(
            pl.col("date").str.strptime(pl.Datetime, strict=False).alias("timestamp")
        )
    elif "timestamp" in frame.columns:
        frame = frame.with_columns(pl.col("timestamp").cast(pl.Datetime))
    else:
        raise ValueError("Essential dataset missing date/timestamp column.")
    return frame.sort("timestamp")


def _build_transformed_frame(raw_frame: pl.DataFrame, primary_column: str) -> pl.DataFrame:
    base_name = primary_column.lower()
    if primary_column not in raw_frame.columns:
        raise ValueError(f"Primary column '{primary_column}' not found in raw dataset.")

    return raw_frame.with_columns(
        pl.col(primary_column).cast(pl.Float64),
        pl.col(primary_column).diff().alias(f"{base_name}_diff_1"),
        pl.col(primary_column).pct_change().alias(f"{base_name}_pct_change_1"),
        pl.col(primary_column).rolling_mean(20).alias(f"{base_name}_sma_20"),
        pl.col(primary_column).rolling_mean(50).alias(f"{base_name}_sma_50"),
    )


def _build_fast_render_frame(raw_frame: pl.DataFrame, primary_column: str) -> pl.DataFrame:
    if primary_column not in raw_frame.columns:
        raise ValueError(f"Primary column '{primary_column}' not found in raw dataset.")

    return raw_frame.select(
        "timestamp",
        pl.col(primary_column).cast(pl.Float64).alias("display_value"),
        pl.col(primary_column).cast(pl.Float64).pct_change().alias("pct_change"),
    )


def _normalize_essential_frame(frame: pl.DataFrame) -> pl.DataFrame:
    normalized = frame
    if "date" in normalized.columns and "timestamp" not in normalized.columns:
        normalized = normalized.with_columns(
            pl.col("date").str.strptime(pl.Datetime, strict=False).alias("timestamp")
        )
    if "timestamp" in normalized.columns:
        normalized = normalized.with_columns(pl.col("timestamp").cast(pl.Datetime))
        return normalized.sort("timestamp")
    raise ValueError("Essential dataset must include a timestamp-compatible column.")
