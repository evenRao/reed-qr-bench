"""Bounded host-owned artifacts; never expose arbitrary paths to tools."""

import io
import secrets
from collections import OrderedDict

from PIL import Image, UnidentifiedImageError

from .contracts import Resource


class Resources:
    def __init__(self, limit=48, max_bytes=64 * 1024 * 1024):
        self.items = OrderedDict()
        self.limit = limit
        self.max_bytes = max_bytes

    def add(self, data):
        if not data or len(data) > 16 * 1024 * 1024:
            raise ValueError("Upload a PNG or JPEG no larger than 16 MiB")
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ("PNG", "JPEG"):
                    raise ValueError("Only PNG and JPEG images are supported")
                if (
                    image.width > 4096
                    or image.height > 4096
                    or image.width * image.height > 2190400
                ):
                    raise ValueError("Image exceeds the scanner limit of 2,190,400 pixels")
                image.verify()
                width, height, fmt = image.width, image.height, image.format
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError("This file is not a valid supported image") from error
        while self.items and (
            len(self.items) >= self.limit
            or sum(len(r.data) for r in self.items.values()) + len(data) > self.max_bytes
        ):
            self.items.popitem(last=False)
        resource = Resource(
            secrets.token_hex(16),
            data,
            "image/png" if fmt == "PNG" else "image/jpeg",
            width,
            height,
        )
        self.items[resource.id] = resource
        return resource

    def get(self, identifier):
        try:
            return self.items[identifier]
        except (KeyError, TypeError) as error:
            raise ValueError("Image reference expired or is not authorized") from error

    def resolve(self, identifier):
        return self.get(identifier).data
