"""Measurements use one worker monotonic clock; missing values remain missing."""

import math
import random
import statistics
import time
from collections import Counter, deque


def quantile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def wilson(correct, total):
    if not total:
        return None
    z = 1.95996398454
    p = correct / total
    d = 1 + z * z / total
    mid = (p + z * z / (2 * total)) / d
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total**2)) / d
    return [max(0, mid - half), min(1, mid + half)]


def bootstrap_median(values, seed=42):
    if len(values) < 3:
        return None
    rng = random.Random(seed)
    estimates = [statistics.median(rng.choices(values, k=len(values))) for _ in range(1000)]
    return [quantile(estimates, 0.025), quantile(estimates, 0.975)]


class Meter:
    """Five-second rolling view and bounded full-attempt latency reservoir.

    Event counts are exact. Percentiles use the most recent 20,000 completions;
    raw completion events remain in the evidence stream for offline analysis.
    """

    def __init__(self, clock=time.perf_counter, window=5):
        self.clock = clock
        self.window = window
        self.started = clock()
        self.received = deque(maxlen=40000)
        self.completed = deque(maxlen=40000)
        self.latencies = deque(maxlen=20000)
        self.queue_ages = deque(maxlen=20000)
        self.latency_timeline = deque(maxlen=20000)
        self.counts = Counter()
        self.first_result_ms = None

    def receive(self, now=None):
        now = self.clock() if now is None else now
        self.counts["received"] += 1
        self.received.append(now)

    def complete(self, received, started, finished, found):
        self.counts["processed"] += 1
        self.counts["positive_frames"] += bool(found)
        self.completed.append(finished)
        self.latencies.append((finished - received) * 1000)
        self.latency_timeline.append((finished, (finished - received) * 1000))
        self.queue_ages.append((started - received) * 1000)
        if found and self.first_result_ms is None:
            self.first_result_ms = (finished - self.started) * 1000

    def snapshot(self, now=None):
        now = self.clock() if now is None else now
        elapsed = max(0, now - self.started)
        for queue in (self.received, self.completed):
            while queue and queue[0] < now - self.window:
                queue.popleft()
        span = min(elapsed, self.window)
        mid = (
            (self.latency_timeline[0][0] + self.latency_timeline[-1][0]) / 2
            if self.latency_timeline
            else 0
        )
        first_half = quantile([v for t, v in self.latency_timeline if t <= mid], 0.95)
        second_half = quantile([v for t, v in self.latency_timeline if t > mid], 0.95)
        return {
            "elapsed_s": elapsed,
            "received_rate": len(self.received) / span if span else None,
            "processed_rate": len(self.completed) / span if span else None,
            "window_s": span,
            "counts": dict(self.counts),
            "p50_ms": quantile(self.latencies, 0.5),
            "p95_ms": quantile(self.latencies, 0.95),
            "p99_ms": quantile(self.latencies, 0.99),
            "latency_samples": len(self.latencies),
            "queue_p95_ms": quantile(self.queue_ages, 0.95),
            "first_result_ms": self.first_result_ms,
            "retained_first_half_p95_ms": first_half,
            "retained_second_half_p95_ms": second_half,
            "p95_drift_ms": second_half - first_half
            if first_half is not None and second_half is not None
            else None,
            "percentile_scope": "most recent 20000 completions in this attempt",
        }


def summarize(attempts, targets):
    groups = {}
    for item in attempts:
        # Never pool scenario, source, cold/warm, negative/positive, model, or load.
        key = tuple(
            item.get(k)
            for k in (
                "implementation",
                "model",
                "scenario",
                "source",
                "temperature",
                "streams",
                "telemetry_profile",
                "load_kind",
                "workers",
            )
        )
        groups.setdefault(key, []).append(item)
    rows = []
    for key, items in groups.items():
        completed = [i for i in items if i["status"] == "completed"]
        scored = [
            i for i in items if i.get("expected") is not None and i.get("score") != "unscored"
        ]
        correct = [i for i in scored if i.get("score") == "correct"]
        input_groups = {}
        for index, item in enumerate(scored):
            identity = (
                ("encode", tuple(item.get("expected", [])))
                if item.get("source") == "encode"
                else (item.get("input_sha256", item.get("id", index)), item.get("recording_sha256"))
            )
            input_groups.setdefault(identity, []).append(item)
        consistent = sum(
            all(i.get("score") == "correct" for i in group) for group in input_groups.values()
        )
        positive = [
            i["first_correct_ms"]
            for i in correct
            if i.get("expected_positive") and i.get("first_correct_ms") is not None
        ]
        durations = [i["elapsed_ms"] for i in completed]
        row = dict(
            zip(
                (
                    "implementation",
                    "model",
                    "scenario",
                    "source",
                    "temperature",
                    "streams",
                    "telemetry_profile",
                    "load_kind",
                    "workers",
                ),
                key,
                strict=True,
            )
        )
        row.update(
            {
                "attempts": len(items),
                "completed": len(completed),
                "correct": len(correct),
                "scored": len(scored),
                "unique_inputs": len(input_groups),
                "consistent_inputs": consistent,
                "accuracy_ci95": wilson(consistent, len(input_groups)),
                "outcomes": dict(Counter(i.get("score", "unscored") for i in items)),
                "statuses": dict(Counter(i["status"] for i in items)),
                "qr_tool_invocations": sum(bool(i.get("qr_tool_used")) for i in items),
                "code_tools_observed": sum(bool(i.get("code_tool_observed")) for i in items),
                "first_result_p50_ms": quantile(positive, 0.5),
                "first_result_p95_ms": quantile(positive, 0.95),
                "first_result_median_ci95": bootstrap_median(positive),
                "attempt_duration_p50_ms": quantile(durations, 0.5),
                "duration_median_ci95": bootstrap_median(durations),
                "frame_p95_ms": quantile(
                    [
                        i["metrics"]["p95_ms"]
                        for i in completed
                        if i["metrics"].get("p95_ms") is not None
                    ],
                    0.5,
                ),
                "processed_rate": quantile(
                    [
                        i["metrics"]["processed_rate"]
                        for i in completed
                        if i["metrics"].get("processed_rate") is not None
                    ],
                    0.5,
                ),
                "cpu_percent": quantile([i.get("cpu_peak", 0) for i in completed], 0.5),
                "rss_peak_mb": max(
                    (i["rss_peak_mb"] for i in items if i.get("rss_peak_mb") is not None),
                    default=None,
                ),
                "sample_warning": "Exploratory: fewer than 30 independent inputs/attempts"
                if len(items) < 30 or (scored and len(input_groups) < 30)
                else None,
            }
        )
        checks = {}
        if "min_accuracy" in targets and scored:
            checks["accuracy"] = len(correct) / len(scored) >= targets["min_accuracy"]
        if "max_false_detections" in targets and scored:
            checks["false_detections"] = (
                sum(i.get("score") == "false_detection" for i in items)
                <= targets["max_false_detections"]
            )
        if (
            "max_p95_ms" in targets
            and completed
            and all(i["metrics"].get("p95_ms") is not None for i in completed)
        ):
            checks["latency"] = all(
                i["metrics"].get("p95_ms", 0) <= targets["max_p95_ms"] for i in completed
            )
        if (
            "min_rate" in targets
            and completed
            and all(i["metrics"].get("processed_rate") is not None for i in completed)
        ):
            checks["throughput"] = all(
                i["metrics"].get("processed_rate", 0) >= targets["min_rate"] for i in completed
            )
        if "max_rss_mb" in targets and row["rss_peak_mb"] is not None:
            checks["memory"] = row["rss_peak_mb"] <= targets["max_rss_mb"]
        for target, key, nested in (
            ("max_cpu_percent", "cpu_peak", False),
            ("max_queue_p95_ms", "queue_p95_ms", True),
            ("max_recovery_ms", "recovery_first_correct_ms", False),
        ):
            observed = [(i["metrics"] if nested else i).get(key) for i in items]
            if target in targets and all(v is not None for v in observed):
                checks[target] = all(v <= targets[target] for v in observed)
        row["checks"] = checks
        row["verdict"] = (
            "unrated"
            if not targets
            else "fail"
            if not all(checks.values()) or len(completed) != len(items)
            else "inconclusive"
            if len(checks) < len(targets)
            else "pass"
        )
        rows.append(row)
    return rows


def observer_overhead(attempts):
    pairs = {}
    for item in attempts:
        if item["status"] != "completed":
            continue
        key = (item["implementation"], item["input_sha256"], item["repetition"])
        pairs.setdefault(key, {})[item.get("telemetry_profile", "full")] = item
    ratios = {}
    for (implementation, _, _), pair in pairs.items():
        if set(pair) == {"full", "minimal"} and pair["minimal"]["elapsed_ms"] > 0:
            ratio = (pair["full"]["elapsed_ms"] / pair["minimal"]["elapsed_ms"] - 1) * 100
            ratios.setdefault(implementation, []).append(ratio)
    return [
        {
            "implementation": mode,
            "pairs": len(values),
            "median_overhead_percent": statistics.median(values),
            "median_ci95": bootstrap_median(values),
            "scope": (
                "Per-operation trace generation + writer contention; both profiles retain "
                "4 Hz resource sampling. Process scheduling and OS noise remain."
            ),
        }
        for mode, values in ratios.items()
    ]
