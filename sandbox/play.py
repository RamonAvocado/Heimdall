"""A tiny runner for poking at providers from the terminal.

uv run python -m sandbox --list
uv run python -m sandbox fred DGS10
uv run python -m sandbox yfinance AAPL --interval 1d --to-parquet --rows 5
"""

from __future__ import annotations

import argparse
from datetime import datetime

import heimdall
from heimdall.errors import HeimdallError
from sandbox._helpers import show, to_csv, to_parquet


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m sandbox", description=__doc__)
    parser.add_argument("provider", nargs="?", help="registered provider id (e.g. fred, yfinance)")
    parser.add_argument("resource", nargs="?", help="what to fetch: a ticker, a series id, ...")
    parser.add_argument("--list", action="store_true", help="list registered providers and exit")
    parser.add_argument("--interval", help="bar interval, provider-specific (e.g. 1d)")
    parser.add_argument("--start", type=_parse_date, metavar="YYYY-MM-DD")
    parser.add_argument("--end", type=_parse_date, metavar="YYYY-MM-DD")
    parser.add_argument("--rows", type=int, default=10, help="rows to print (default: 10)")
    parser.add_argument("--to-parquet", action="store_true", help="also write parquet to scratch/")
    parser.add_argument("--to-csv", action="store_true", help="also write csv to scratch/")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list or not args.provider:
        print("registered providers:")
        for pid in heimdall.list_providers():
            print(f"  {pid}")
        return 0

    if not args.resource:
        print("error: a resource is required, e.g.  fred DGS10")
        return 2

    try:
        result = heimdall.fetch(
            args.provider,
            args.resource,
            interval=args.interval,
            start=args.start,
            end=args.end,
        )
    except HeimdallError as exc:
        print(f"error: {type(exc).__name__}: {exc}")
        return 1

    show(result, rows=args.rows)
    if args.to_parquet:
        to_parquet(result)
    if args.to_csv:
        to_csv(result)
    return 0
