"""First-party providers bundled with Heimdall.

Each submodule guards its third-party import so ``import heimdall`` works with
no extras installed. Install what you need::

    pip install heimdall-mimird[fred]        # FRED economic series
    pip install heimdall-mimird[yfinance]    # Yahoo Finance OHLCV
    pip install heimdall-mimird[all]
"""
