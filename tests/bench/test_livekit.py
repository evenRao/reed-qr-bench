"""Opt-in integration tests use only the owned local LiveKit server and synthetic frames."""

import asyncio
import io
import os

import cv2
import numpy as np
import pytest
from PIL import Image

from reed_bench.fixtures import build_fixture
from reed_bench.resources import Resources
from reed_bench.server import ROOT
from reed_bench.store import Store
from reed_bench.supervisor import Supervisor
from reed_bench.transport import LiveKitService


@pytest.mark.skipif(
    os.getenv("REED_BENCH_RTC_TEST") != "1",
    reason="Set REED_BENCH_RTC_TEST=1 for local RTC integration",
)
def test_actual_rtc_processing_negative_control_and_replacement(tmp_path):
    async def scenario():
        store = Store(tmp_path)
        supervisor = Supervisor(ROOT, store, Resources(), LiveKitService(ROOT))
        try:
            run = await supervisor.start(
                {
                    "source": "video",
                    "scenarios": ["clean", "no_code"],
                    "implementations": ["plugin", "sdk", "opencv", "off"],
                    "repetitions": 1,
                    "duration_s": 3,
                    "replace_track": True,
                }
            )
            await supervisor.task
            assert run["status"] == "completed", run.get("error")
            for item in run["attempts"]:
                assert item["status"] == "completed", item
                assert item["metrics"]["counts"]["received"] > 10
                assert item["metrics"]["counts"]["processed"] > 5
                assert item["metrics"]["p95_ms"] > 0
                if item["implementation"] != "off":
                    assert item["score"] == "correct", item
                    if item["scenario"] == "clean":
                        assert any(k.endswith(":2") for k in item["first_correct_by_generation"])
            for extra in (
                {"loads": [4], "workers": 2},
                {"loads": [2], "load_kind": "rooms"},
                {"replace_track": True, "recovery_action": "reconnect"},
                {"replace_track": True, "recovery_action": "pause"},
            ):
                run = await supervisor.start(
                    {
                        "source": "video",
                        "implementations": ["plugin"],
                        "repetitions": 1,
                        "duration_s": 4,
                        **extra,
                    }
                )
                await supervisor.task
                item = run["attempts"][0]
                assert item["status"] == "completed", item
                assert item["score"] == "correct", item
                assert len(item["processed_by_source"]) >= extra.get("loads", [1])[0]
                if extra.get("replace_track"):
                    assert item["recovery_first_correct_ms"] is not None
            fixture = build_fixture("clean", 175)
            image = Image.open(io.BytesIO(fixture.data)).convert("RGB")
            canvas = Image.new("RGB", (640, 480), "white")
            canvas.paste(image, ((640 - image.width) // 2, (480 - image.height) // 2))
            recording = tmp_path / "recording.avi"
            writer = cv2.VideoWriter(
                str(recording), cv2.VideoWriter_fourcc(*"MJPG"), 15, (640, 480)
            )
            assert writer.isOpened()
            for _ in range(30):
                writer.write(cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR))
            writer.release()
            supervisor.recordings["test"] = recording
            run = await supervisor.start(
                {
                    "source": "recording",
                    "recording_id": "test",
                    "expected": list(fixture.expected),
                    "implementations": ["plugin"],
                    "repetitions": 1,
                    "duration_s": 3,
                }
            )
            await supervisor.task
            assert run["attempts"][0]["score"] == "correct", run["attempts"][0]
        finally:
            await supervisor.close()
            assert supervisor.livekit.process is None
            store.close()

    asyncio.run(scenario())
