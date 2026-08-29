"""Fetch OHLCV bars from Yahoo Finance and print them.  Needs `heimdall-mimird[yfinance]`.

uv run python sandbox/examples/02_yfinance_to_terminal.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sandbox._helpers import show  # noqa: E402

import heimdall  # noqa: E402

result = heimdall.fetch("yfinance", "AAPL", interval="1d")
show(result, rows=8)
