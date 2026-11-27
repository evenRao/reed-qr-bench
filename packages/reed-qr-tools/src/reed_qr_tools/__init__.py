"""Public provider-neutral integration, independent of the benchmark application."""

__version__ = "0.2.0"

from .tools import EncodedQR, QRTools, detection_status, serialize_detection

__all__ = ["EncodedQR", "QRTools", "detection_status", "serialize_detection"]
