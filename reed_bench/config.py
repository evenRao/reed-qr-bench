"""Versioned run protocol with bounded work and explicit cloud opt-in."""

import math

from .adapters import providers
from .fixtures import SCENARIOS

MODES = ["plugin", "sdk", "opencv", "off"]
AI_MODES = [f"{p}:{m}" for p, spec in providers().items() for m in spec.modes]
SUITES = {
    "calibration": {
        "title": "Observer overhead",
        "source": "image",
        "scenarios": ["clean"],
        "repetitions": 10,
        "operations": 100,
        "implementations": ["plugin", "sdk"],
        "telemetry_profiles": ["minimal", "full"],
    },
    "smoke": {
        "title": "Smoke check",
        "source": "image",
        "scenarios": ["clean", "no_code"],
        "repetitions": 2,
    },
    "performance": {
        "title": "SDK performance",
        "source": "image",
        "scenarios": ["clean"],
        "repetitions": 30,
    },
    "robustness": {
        "title": "Robustness",
        "source": "image",
        "scenarios": list(SCENARIOS),
        "repetitions": 3,
    },
    "video": {
        "title": "LiveKit pipeline",
        "source": "video",
        "scenarios": ["clean", "no_code"],
        "repetitions": 3,
    },
    "recovery": {
        "title": "Track replacement",
        "source": "video",
        "scenarios": ["clean"],
        "repetitions": 3,
        "replace_track": True,
    },
    "load": {
        "title": "Concurrent streams",
        "source": "video",
        "scenarios": ["clean"],
        "repetitions": 3,
        "loads": [1, 2, 4, 8],
    },
    "endurance": {
        "title": "Sustained operation",
        "source": "video",
        "scenarios": ["clean"],
        "repetitions": 1,
        "duration_s": 120,
    },
    "ai": {
        "title": "AI image workflow",
        "source": "image",
        "scenarios": ["clean", "no_code"],
        "repetitions": 3,
        "implementations": ["openai:vision", "openai:code", "openai:reed"],
    },
    "encoding": {
        "title": "Encoding round trip",
        "source": "encode",
        "scenarios": ["clean"],
        "repetitions": 30,
        "implementations": ["plugin", "sdk"],
    },
}


def protocol(raw):
    if not isinstance(raw, dict):
        raise ValueError("Supply a configuration object")
    source = raw.get("source", "image")
    if source not in ("image", "video", "camera", "encode", "recording"):
        raise ValueError("Unknown source")
    modes = raw.get("implementations", ["plugin", "sdk", "opencv"])
    allowed = MODES + (AI_MODES if source == "image" else [])
    if (
        not isinstance(modes, list)
        or not 1 <= len(modes) <= 9
        or any(m not in allowed for m in modes)
        or len(set(modes)) != len(modes)
    ):
        raise ValueError("Choose distinct supported implementations")
    if source == "encode" and any(m not in ("plugin", "sdk") for m in modes):
        raise ValueError("Encoding supports the plugin and direct SDK")
    if source == "camera" and len(modes) != 1:
        raise ValueError("A camera session uses one implementation")

    def number(key, default, lo, hi, integer=False):
        v = raw.get(key, default)
        if (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or not lo <= v <= hi
            or (integer and type(v) is not int)
        ):
            raise ValueError(
                f"{key} must be {'an integer' if integer else 'a number'} between {lo} and {hi}"
            )
        return v

    scenarios = raw.get("scenarios", ["clean"])
    if (
        not isinstance(scenarios, list)
        or not scenarios
        or any(s not in SCENARIOS for s in scenarios)
    ):
        raise ValueError("Choose supported scenarios")
    config = {
        "schema_version": 2,
        "source": source,
        "implementations": modes,
        "scenarios": scenarios,
        "repetitions": number("repetitions", 3, 1, 100, True),
        "seed": number("seed", 42, 0, 2**31 - 1, True),
        "duration_s": number("duration_s", 5, 2, 3600),
        "scan_hz": number("scan_hz", 10, 0.5, 60),
        "input_hz": number("input_hz", 15, 1, 60),
        "deadline_s": number("deadline_s", 90, 2, 3700),
        "warmups": number("warmups", 1, 0, 10, True),
        "operations": number("operations", 1, 1, 10000, True),
        "max_queue_age_ms": number("max_queue_age_ms", 1000, 1, 10000),
        "workers": number("workers", 1, 1, 8, True),
        "replace_track": raw.get("replace_track") is True,
        "recovery_action": raw.get("recovery_action", "replace_track"),
        "load_kind": raw.get("load_kind", "streams"),
        "models": raw.get("models", {}),
        "forced_tool": raw.get("forced_tool") is True,
        "allow_cloud": raw.get("allow_cloud") is True,
        "targets": raw.get("targets", {}),
        "suite": str(raw.get("suite", "custom"))[:64],
        "loads": raw.get("loads", [1]),
        "split": raw.get("split", "development"),
        "image_ids": raw.get("image_ids", []),
        "expected": raw.get("expected"),
        "recording_id": raw.get("recording_id"),
        "corpus_id": raw.get("corpus_id"),
        "text": raw.get("text", "REED QR / exact round trip"),
        "correction": raw.get("correction", "M"),
        "scale": number("scale", 8, 2, 12, True),
        "voice": raw.get("voice") is True,
        "telemetry_profiles": raw.get("telemetry_profiles", ["full"]),
    }
    if raw.get("schema_version", 2) != 2:
        raise ValueError("Unsupported protocol schema version")
    unknown = set(raw) - (set(config) | {"attempt_limit"})
    if unknown:
        raise ValueError("Unknown protocol fields: " + ", ".join(sorted(map(str, unknown))))
    if len(scenarios) != len(set(scenarios)):
        raise ValueError("Scenarios must be distinct")
    if config["split"] not in ("development", "held_out"):
        raise ValueError("Unknown corpus split")
    if source == "camera" and (
        config["repetitions"] != 1 or len(scenarios) != 1 or config["loads"] != [1]
    ):
        raise ValueError("Camera sessions use one attempt, one scene, and one stream")
    if source not in ("video", "camera", "recording") and config["workers"] != 1:
        raise ValueError(
            "Worker parallelism is configured for video sources; image attempts are serial"
        )
    if config["recovery_action"] not in ("replace_track", "reconnect", "pause"):
        raise ValueError("Unknown recovery action")
    if config["load_kind"] not in ("streams", "rooms"):
        raise ValueError("Load kind must be streams or rooms")
    if config["telemetry_profiles"] not in (["full"], ["minimal", "full"]):
        raise ValueError("Choose full telemetry, or paired minimal/full calibration")
    if len(config["telemetry_profiles"]) > 1 and (
        source != "image" or any(":" in m for m in modes)
    ):
        raise ValueError("Observer calibration supports local image decoding")
    if (
        not isinstance(config["loads"], list)
        or not config["loads"]
        or any(type(n) is not int or n not in (1, 2, 4, 8) for n in config["loads"])
    ):
        raise ValueError("Stream counts must be 1, 2, 4, or 8")
    if len(config["loads"]) != len(set(config["loads"])):
        raise ValueError("Load counts must be distinct")
    if config["correction"] not in ("L", "M", "Q", "H"):
        raise ValueError("Unknown error correction level")
    if config["voice"] and (source != "camera" or modes != ["plugin"] or not config["allow_cloud"]):
        raise ValueError(
            "Voice requires a camera test with the REED QR plugin and explicit paid cloud access"
        )
    if not isinstance(config["text"], str) or not 1 <= len(config["text"].encode()) <= 2900:
        raise ValueError("Text must contain 1–2900 UTF-8 bytes")
    if (
        not isinstance(config["image_ids"], list)
        or len(config["image_ids"]) > 48
        or any(not isinstance(i, str) for i in config["image_ids"])
    ):
        raise ValueError("Choose at most 48 authorized images")
    if config["expected"] is not None and (
        not isinstance(config["expected"], list)
        or any(not isinstance(i, str) for i in config["expected"])
    ):
        raise ValueError("Expected payloads must be a list of strings, or null for unscored")
    if config["expected"] is not None and (
        len(config["expected"]) > 64 or sum(len(v.encode()) for v in config["expected"]) > 65536
    ):
        raise ValueError("Expected labels exceed 64 payloads or 64 KiB")
    if not isinstance(config["models"], dict) or any(
        not isinstance(v, str) for v in config["models"].values()
    ):
        raise ValueError("Model IDs must be text")
    if any(m in AI_MODES for m in modes) and not config["allow_cloud"]:
        raise ValueError("Enable paid cloud requests explicitly to run AI comparisons")
    if not isinstance(config["targets"], dict):
        raise ValueError("Targets must be an object")
    bounds = {
        "min_accuracy": (0, 1),
        "max_false_detections": (0, 10000),
        "max_p95_ms": (0, 1e6),
        "min_rate": (0, 1e6),
        "max_rss_mb": (1, 1e6),
        "max_cpu_percent": (0, 100000),
        "max_queue_p95_ms": (0, 100000),
        "max_recovery_ms": (0, 1e6),
    }
    for key, value in config["targets"].items():
        if (
            key not in bounds
            or isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            or not bounds[key][0] <= value <= bounds[key][1]
        ):
            raise ValueError(f"Invalid target: {key}")
    attempts = (
        len(modes)
        * len(scenarios)
        * config["repetitions"]
        * len(config["loads"])
        * max(1, len(config["image_ids"]))
        * len(config["telemetry_profiles"])
    )
    if attempts > 2000:
        raise ValueError("Limit each run to 2000 independent attempts")
    config["attempt_limit"] = attempts
    return config
