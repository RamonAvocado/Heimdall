"""Fetch a FRED series and print it.  Needs `heimdall-mimird[fred]`.

uv run python sandbox/examples/01_fred_to_terminal.py
"""

from __future__ import annotations

import pathlib
import sys

# Run-by-path bootstrap: put the repo root on sys.path so `import sandbox` works.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from sandbox._helpers import show

import heimdall

result = heimdall.fetch("fred", "DGS10")
show(result)
