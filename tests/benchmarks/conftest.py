"""Write a compact, readable summary next to each saved benchmark run.

pytest-benchmark's own JSON (`.benchmarks/`) holds every raw sample, which
`--benchmark-compare` needs. Alongside it, every run that saves
(`--benchmark-autosave` or `--benchmark-json`) also writes
`.benchmarks/summary/<datetime>_<commit>.json`, one file per run, for
external trackers (Skuld) to read.
"""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

_SUMMARY_DIR = Path(__file__).resolve().parents[2] / ".benchmarks" / "summary"


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 4)


def pytest_benchmark_update_json(config, benchmarks, output_json) -> None:
    commit = output_json.get("commit_info", {})
    machine = output_json.get("machine_info", {})
    summary = {
        "package": "heimdall-mimird",
        "version": version("heimdall-mimird"),
        "datetime": output_json["datetime"],
        "commit": commit.get("id"),
        "dirty": commit.get("dirty"),
        "python": machine.get("python_version"),
        "cpu": machine.get("cpu", {}).get("brand_raw"),
        "unit": "ms",
        "results": [
            {
                "name": b["name"],
                "mean": _ms(b["stats"]["mean"]),
                "median": _ms(b["stats"]["median"]),
                "min": _ms(b["stats"]["min"]),
                "max": _ms(b["stats"]["max"]),
                "stddev": _ms(b["stats"]["stddev"]),
                "ops_per_sec": round(b["stats"]["ops"], 2),
                "rounds": b["stats"]["rounds"],
            }
            for b in output_json["benchmarks"]
        ],
    }
    stamp = summary["datetime"][:19].replace(":", "-")
    path = _SUMMARY_DIR / f"{stamp}_{(summary['commit'] or 'nogit')[:7]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2) + "\n")
