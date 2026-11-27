"""Run with a clean environment's Python after installing the tools wheel and SDK."""

import asyncio
import importlib.metadata
import json

from reed_qr import encode_text
from reed_qr_tools import QRTools


async def verify():
    installed = {}
    for name in ("reed-qr", "reed-qr-tools"):
        distribution = importlib.metadata.distribution(name)
        source = json.loads(distribution.read_text("direct_url.json") or "{}")
        if source.get("dir_info", {}).get("editable"):
            raise RuntimeError(f"{name} is editable; this check requires installed wheels")
        installed[name] = distribution.version
    images = {}
    async with QRTools(images.__getitem__) as tools:
        await tools.warmup()
        artifact = await tools.encode_text("Installed SDK and plugin verification")
        images["authorized-input"] = artifact.png
        result = await tools.invoke("decode_qr_image", {"image_id": "authorized-input"})
        assert result["detections"][0]["text"] == "Installed SDK and plugin verification"
        frame = encode_text("Installed frame operation").as_frame()
        result = await tools.decode_frame(frame, source_id="authorized-camera", generation=2)
        assert result["source_id"] == "authorized-camera"
        assert result["generation"] == 2
        assert result["detections"][0]["text"] == "Installed frame operation"
    print(
        json.dumps(
            {
                "installed_wheels": installed,
                "round_trip": "passed",
                "scope": "Packaging smoke check, not an independent accuracy benchmark",
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(verify())
