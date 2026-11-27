"""Provider-neutral authorized input reference; no filesystem path or ground truth."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Resource:
    id: str
    data: bytes
    mime: str
    width: int
    height: int
