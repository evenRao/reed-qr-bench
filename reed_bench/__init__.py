"""REED QR Bench: measured operations, repeatable experiments, inspectable evidence."""

from pathlib import Path

__version__ = (Path(__file__).resolve().parents[1] / "VERSION").read_text("utf-8").strip()
