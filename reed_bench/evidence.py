"""Clocked, bounded execution traces and exact scoring independent of providers."""

import hashlib
import importlib.metadata
import importlib.util
import json
import math
import platform
import statistics
import time
from collections import Counter
from pathlib import Path

from . import __version__


def _backend_fingerprint():
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parent
    for path in sorted(root.glob("*.py")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


# Capture at import, rather than claiming newly edited files are already loaded.
BACKEND_FINGERPRINT = _backend_fingerprint()


class Trace:
    def __init__(self, capacity=256):
        self.started = time.perf_counter_ns()
        self.events = []
        self.capacity = capacity
        self.dropped = 0

    def emit(self, kind, value=None):
        if len(self.events) >= self.capacity:
            self.dropped += 1
            return
        self.events.append({"event": kind, "ms": self.ms(), "detail": value or {}})

    def ms(self):
        return round((time.perf_counter_ns() - self.started) / 1e6, 4)

    def first(self, event):
        return next((item["ms"] for item in self.events if item["event"] == event), None)

    def export(self):
        return {
            "clock": "host-perf-counter",
            "complete": self.dropped == 0,
            "events_dropped": self.dropped,
            "events": self.events,
        }


def payloads(result):
    return [
        item["text"] for item in result.get("detections", []) if isinstance(item.get("text"), str)
    ]


def parse_answer(text):
    """Require a complete machine-readable answer, not a matching URL substring."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        stripped = "\n".join(stripped.splitlines()[1:-1]).strip()
    try:
        value = json.loads(stripped)
        if not isinstance(value, dict) or not isinstance(value.get("payloads"), list):
            return None
        if any(not isinstance(item, str) for item in value["payloads"]):
            return None
        return value["payloads"]
    except (ValueError, TypeError):
        return None


def score(actual, expected):
    if expected is None:
        return "unscored"
    if actual is None:
        return "invalid_response"
    if Counter(actual) == Counter(expected):
        return "correct"
    if not actual and expected:
        return "missed"
    if actual and not expected:
        return "false_detection"
    return "incorrect"


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lo, hi = math.floor(rank), math.ceil(rank)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo), 4)


def summarize(attempts):
    groups = {}
    for item in attempts:
        key = (item["implementation"], item.get("model"))
        groups.setdefault(key, []).append(item)
    rows = []
    for (implementation, model), items in groups.items():
        correct = [item for item in items if item.get("score") == "correct"]
        latencies = [
            item.get("time_to_correct_payload_ms") or item["elapsed_ms"] for item in correct
        ]
        rows.append(
            {
                "implementation": implementation,
                "model": model,
                "attempts": len(items),
                "correct": len(correct),
                "scored": sum(
                    i.get("score")
                    in ("correct", "missed", "incorrect", "false_detection", "invalid_response")
                    for i in items
                ),
                "qr_tool_invocations": sum(i.get("qr_tool_used", False) for i in items),
                "code_tools_observed": sum(i.get("code_tool_used", False) for i in items),
                "outcomes": dict(Counter(i.get("score", "unscored") for i in items)),
                "execution": dict(Counter(i["status"] for i in items)),
                "median_correct_ms": round(statistics.median(latencies), 4) if latencies else None,
                "p95_correct_ms": percentile(latencies, 0.95),
                "latency_scope": "Successful exact answers only; all failures retained in counts",
            }
        )
    return rows


def package_info(name):
    try:
        dist = importlib.metadata.distribution(name)
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        editable = direct.get("dir_info", {}).get("editable", False)
        hashes = hashlib.sha256()
        recorded = set()
        for entry in sorted(dist.files or [], key=str):
            if str(entry).endswith((".py", ".pyd", ".so")) and ".." not in entry.parts:
                path = Path(dist.locate_file(entry))
                if path.is_file():
                    hashes.update(path.read_bytes())
                    recorded.add(path.resolve())
        if editable and name == "reed-qr":
            spec = importlib.util.find_spec("reed_qr")
            for directory in spec.submodule_search_locations or []:
                for path in sorted(Path(directory).rglob("*")):
                    if path.suffix in (".py", ".pyd", ".so") and path.resolve() not in recorded:
                        hashes.update(path.read_bytes())
                        recorded.add(path.resolve())
        return {
            "version": dist.version,
            "editable": editable,
            "fingerprint": hashes.hexdigest() if recorded else None,
            "fingerprinted_files": len(recorded),
            "installed": True,
        }
    except importlib.metadata.PackageNotFoundError:
        return {"installed": False, "version": None, "editable": None}


def environment():
    return {
        "application": {
            "name": "reed-qr-bench",
            "version": __version__,
            "measurement_revision": 4,
            "backend_fingerprint": BACKEND_FINGERPRINT,
        },
        "os": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "packages": {
            name: package_info(name)
            for name in ("reed-qr", "reed-qr-tools", "opencv-python-headless", "pillow", "livekit")
        },
        "evidence": "development" if package_info("reed-qr").get("editable") else "installed-sdk",
        "scope": "Local host metrics; provider-internal hardware/timing is not observable",
    }
