from __future__ import annotations

from datetime import date
from typing import overload

from dateutil.relativedelta import relativedelta
import polars as pl
from ramonavocado_logger import get_log
import yfinance as yf

from config.folders import MARKET_DATA_ROOT_DIR
from core.providers.essential import (
    EssentialColumnCatalog,
    EssentialDataManifest,
    load_essential_data,
    load_essential_manifest,
    list_essential_columns,
)
from models.domain.columns import OHLCV, YFINANCE_COLUMNS
from models.enum import CacheDataTypes, EconomicDataSeries
from models.enum.time import TimeHorizon, TimeInterval


log_yfinance = get_log()


class YFinance:
    @overload
    @staticmethod
    def download_data(
        ticker: str,
        *,
        horizon: TimeHorizon,
        end: date = date.today(),
        interval: str = "1d",
    ) -> pl.DataFrame:
        pass

    @overload
    @staticmethod
    def download_data(
        ticker: str,
        *,
        start: date,
        end: date = date.today(),
        interval: str = "1d",
    ) -> pl.DataFrame:
        pass

    @staticmethod
    def download_data(
        ticker: str,
        start: date | None = None,
        horizon: TimeHorizon | None = None,
        end: date = date.today(),
        interval: str = "1d",
    ) -> pl.DataFrame:
        """
        Download OHLCV data from Yahoo Finance using yfinance
        and convert it into the schema expected by BaseStrategy.
        """
        if horizon:
            match horizon:
                case TimeHorizon.ONE_MONTH:
                    start = end - relativedelta(months=1)
                case TimeHorizon.ONE_YEAR:
                    start = end - relativedelta(year=1)
                case TimeHorizon.ALL:
                    start = date(year=1970, month=1, day=1)

        if start is None:
            log_yfinance.error("Something went wrong with the date", start=start)
            raise ValueError

        raw = yf.download(
            tickers=ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            interval=interval,
            auto_adjust=True,
            progress=False,
        )

        if raw is None or raw.empty:
            raise ValueError(f"No data downloaded for ticker: {ticker}")

        if hasattr(raw.columns, "nlevels") and raw.columns.nlevels > 1:
            raw.columns = raw.columns.get_level_values(0)

        raw = raw.reset_index()
        raw = raw.rename(columns=YFINANCE_COLUMNS.rename_map_to(OHLCV))

        data = pl.from_pandas(raw)
        cleaned = (
            data.with_columns(
                pl.lit(ticker).alias(OHLCV.ticker),
                pl.col(OHLCV.date).cast(pl.Datetime),
                pl.col(OHLCV.open).cast(pl.Float64),
                pl.col(OHLCV.high).cast(pl.Float64),
                pl.col(OHLCV.low).cast(pl.Float64),
                pl.col(OHLCV.close).cast(pl.Float64),
                pl.col(OHLCV.volume).cast(pl.Float64),
            )
            .select(
                OHLCV.date,
                OHLCV.ticker,
                OHLCV.open,
                OHLCV.high,
                OHLCV.low,
                OHLCV.close,
                OHLCV.volume,
            )
            .sort(OHLCV.date)
        )

        valid = cleaned.filter(
            pl.all_horizontal(
                pl.col(OHLCV.open).is_not_null(),
                pl.col(OHLCV.high).is_not_null(),
                pl.col(OHLCV.low).is_not_null(),
                pl.col(OHLCV.close).is_not_null(),
            )
        )

        dropped_rows = cleaned.height - valid.height
        if dropped_rows > 0:
            log_yfinance.warning(
                "Dropped rows with null OHLC values from downloaded market data",
                ticker=ticker,
                dropped_rows=dropped_rows,
            )

        if valid.is_empty():
            raise ValueError(f"No valid OHLC data downloaded for ticker: {ticker}")

        return valid

    @staticmethod
    def cache_data(
        tickers: list[str],
        horizon: TimeHorizon = TimeHorizon.ALL,
        end: date = date.today(),
        interval: TimeInterval = TimeInterval.ONE_DAY,
        *,
        is_essential: bool = False,
    ) -> None:
        for ticker in tickers:
            if is_essential:
                file_path = (
                    MARKET_DATA_ROOT_DIR
                    / "essential"
                    / ticker
                    / f"{interval.value}.parquet"
                )
            else:
                file_path = MARKET_DATA_ROOT_DIR / ticker / f"{interval.value}.parquet"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if file_path.exists():
                continue

            df = YFinance.download_data(
                ticker,
                horizon=horizon,
                end=end,
                interval=interval.value,
            )
            file_path.touch()
            df.write_parquet(file_path)

    @staticmethod
    def load_essential_data(
        series: EconomicDataSeries,
        *,
        cache_type: CacheDataTypes = CacheDataTypes.RAW,
    ) -> pl.DataFrame:
        return load_essential_data(series=series, cache_type=cache_type)

    @staticmethod
    def load_essential_manifest(series: EconomicDataSeries) -> EssentialDataManifest:
        return load_essential_manifest(series)

    @staticmethod
    def list_essential_columns(series: EconomicDataSeries) -> EssentialColumnCatalog:
        return list_essential_columns(series)
