"""Distinguish detection, recoverable text, unsupported payloads, and true negatives."""

from collections import Counter

from .evidence import score


def evaluate(result, expected):
    if expected is None:
        return "unscored"
    detections = result.get("detections", [])
    fidelity = result.get("fidelity_counts", {})
    found = bool(detections) or bool(fidelity)
    unavailable = result.get("text_unavailable", False) or any(
        d.get("text") is None for d in detections
    )
    actual = result.get("payloads")
    if not expected and found:
        return "false_detection"
    outcome = score(actual, expected)
    if unavailable and not (Counter(actual or []) - Counter(expected)):
        return "unsupported_payload"
    return outcome
