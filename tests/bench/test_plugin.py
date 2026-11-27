import asyncio
import threading
from types import SimpleNamespace as NS

import pytest
import reed_qr
from reed_qr_tools import QRTools

from reed_bench.fixtures import build_fixture
from reed_bench.pipeline import opencv
from reed_bench.worker import Events


def test_plugin_cancellation_retains_native_ownership(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocked(data):
        entered.set()
        release.wait(3)
        return ()

    monkeypatch.setattr(reed_qr, "decode_image", blocked)

    async def scenario():
        async with QRTools(lambda identifier: b"image") as tools:
            task = asyncio.create_task(tools.decode_image("authorized"))
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())


def test_plugin_preserves_partial_segments_without_claiming_a_full_payload(monkeypatch):
    detection = NS(
        text=None,
        payload_bytes=None,
        payload_status=reed_qr.PayloadStatus.UNSUPPORTED,
        byte_segments=(b"partial",),
        format="QR_CODE",
        landmarks=[],
    )
    monkeypatch.setattr(reed_qr, "decode_image", lambda data: (detection,))

    async def scenario():
        async with QRTools(lambda identifier: b"input") as tools:
            result = await tools.decode_image("authorized")
            assert result["status"] == "unsupported_payload"
            assert result["detections"][0]["bytes_hex"] is None
            assert result["detections"][0]["byte_segments_hex"] == [b"partial".hex()]

    asyncio.run(scenario())


def test_registered_encoding_publishes_an_opaque_artifact():
    async def scenario():
        artifacts = {}

        def publish(artifact):
            artifacts["qr-artifact"] = artifact.png
            return "qr-artifact"

        async with QRTools(lambda identifier: b"", publish_artifact=publish) as tools:
            assert [d["name"] for d in tools.declarations()] == [
                "decode_qr_image",
                "encode_qr_text",
            ]
            result = await tools.invoke(
                "encode_qr_text", {"text": "Opaque AI artifact", "correction": "M", "scale": 8}
            )
            assert result["artifact_id"] == "qr-artifact"
            assert opencv(artifacts["qr-artifact"])["detections"][0]["text"] == "Opaque AI artifact"
        async with QRTools(lambda identifier: b"") as tools:
            with pytest.raises(ValueError, match="not authorized"):
                await tools.invoke("encode_qr_text", {"text": "Denied"})

    asyncio.run(scenario())


@pytest.mark.parametrize("scenario", ["numeric", "alphanumeric", "unicode"])
def test_independent_payload_modes(scenario):
    fixture = build_fixture(scenario, 923, 1)
    assert [i.text for i in reed_qr.decode_image(fixture.data)] == list(fixture.expected)


def test_voice_scan_accepts_only_a_fresh_eligible_result():
    # Exercise routing without starting the telemetry writer or a paid voice agent.
    events = Events.__new__(Events)
    events.scan = None
    sent = []
    events.emit = lambda kind, detail=None: sent.append((kind, detail))
    events.request_scan("request-1")
    events.request_scan("request-2")
    assert sent[-1][1]["status"] == "busy"
    events.finish_scan({"status": "decoded", "detections": [{"text": "actual"}]})
    assert sent[-1][1]["request_id"] == "request-1"
    assert sent[-1][1]["worker_scan_ms"] >= 0
    assert events.scan is None
