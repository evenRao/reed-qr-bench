"""Independent Segno fixtures with evaluator-only answers and repeatable transforms."""

import hashlib
import io
import random
from dataclasses import dataclass

import segno
from PIL import Image, ImageEnhance, ImageFilter

SCENARIOS = {
    "clean": "Clean reference",
    "small": "Small code",
    "blur": "Soft focus",
    "rotated": "Rotated 18°",
    "low_light": "Low light",
    "compressed": "JPEG compression",
    "multiple": "Two distinct codes",
    "no_code": "No QR / negative control",
    "glare": "Glare across modules",
    "perspective": "Perspective skew",
    "numeric": "Numeric payload",
    "alphanumeric": "QR alphanumeric payload",
    "unicode": "UTF-8 / ECI payload",
    "no_quiet_zone": "Cropped quiet zone (out of specification)",
}


@dataclass(frozen=True)
class Fixture:
    scenario: str
    data: bytes
    expected: tuple[str, ...]
    digest: str


def png(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def build_fixture(scenario, seed=42, index=0):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario")
    rng = random.Random(f"reed-qr-fixture-v1:{seed}:{index}")
    values = ["rq-" + rng.randbytes(12).hex() for _ in range(2 if scenario == "multiple" else 1)]
    if scenario == "numeric":
        values = [str(int.from_bytes(rng.randbytes(16), "big"))]
    elif scenario == "alphanumeric":
        values = ["REED QR:" + values[0].upper().replace("RQ-", "")]
    elif scenario == "unicode":
        values = ["café / 東京 / 🙂 / " + values[0]]
    images = []
    for value in values:
        output = io.BytesIO()
        segno.make(
            value,
            micro=False,
            error="m",
            encoding="utf-8" if scenario == "unicode" else None,
            eci=scenario == "unicode",
        ).save(output, kind="png", scale=8, border=0 if scenario == "no_quiet_zone" else 4)
        images.append(Image.open(io.BytesIO(output.getvalue())).convert("RGB"))
    image = images[0]
    if scenario == "small":
        image = image.resize((112, 112), Image.Resampling.NEAREST)
    elif scenario == "blur":
        image = image.filter(ImageFilter.GaussianBlur(1.1))
    elif scenario == "rotated":
        image = image.rotate(18, expand=True, fillcolor="white")
    elif scenario == "low_light":
        image = ImageEnhance.Brightness(image).enhance(0.30)
    elif scenario == "compressed":
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=12)
        image = Image.open(io.BytesIO(output.getvalue())).convert("RGB")
    elif scenario == "multiple":
        canvas = Image.new("RGB", (image.width * 2 + 64, image.height + 32), "white")
        canvas.paste(image, (16, 16))
        canvas.paste(images[1], (image.width + 48, 16))
        image = canvas
    elif scenario == "no_code":
        image = Image.new("RGB", (400, 300), "#d6e1db")
        values = []
    elif scenario == "glare":
        from PIL import ImageDraw

        ImageDraw.Draw(image).rectangle(
            (image.width * 0.45, 0, image.width * 0.51, image.height), fill=(235, 235, 235)
        )
    elif scenario == "perspective":
        image = image.transform(
            image.size,
            Image.Transform.PERSPECTIVE,
            (1, 0.12, -12, 0.03, 1, 0, 0.0001, 0.0004),
            fillcolor="white",
        )
    data = png(image)
    return Fixture(scenario, data, tuple(values), hashlib.sha256(data).hexdigest())
