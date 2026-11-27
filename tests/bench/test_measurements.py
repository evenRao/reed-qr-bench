import asyncio

import pytest

from reed_bench.config import protocol
from reed_bench.metrics import Meter, wilson
from reed_bench.pipeline import FramePipeline


def test_counts_and_clocked_latency_include_misses():
    meter = Meter(clock=lambda: 0)
    for index in range(100):
        received = index / 20
        meter.receive(received)
        meter.complete(received, received + 0.003, received + 0.023, False)
    snapshot = meter.snapshot(5)
    assert snapshot["counts"]["received"] == 100
    assert snapshot["counts"]["processed"] == 100
    assert snapshot["received_rate"] == 20
    assert snapshot["p95_ms"] == pytest.approx(23)
    assert snapshot["queue_p95_ms"] == pytest.approx(3)
    assert snapshot["first_result_ms"] is None


def test_no_data_is_not_zero_and_config_is_bounded():
    assert Meter(clock=lambda: 0).snapshot()["p95_ms"] is None
    for raw in (
        {"scan_hz": float("nan")},
        {"repetitions": True},
        {"source": "video", "implementations": ["openai:reed"]},
    ):
        with pytest.raises(ValueError):
            protocol(raw)
    assert wilson(0, 0) is None


def test_latest_frame_replacement_and_retired_results():
    async def scenario():
        gate = asyncio.Event()

        class Decoder:
            async def frame(self, frame, source, generation):
                await gate.wait()
                return {"detections": [{"text": "old"}]}

        events = []
        pipeline = FramePipeline(Decoder(), lambda *args: events.append(args), scan_hz=10000)
        pipeline.activate("camera", 1)
        pipeline.offer("camera", 1, object())
        await asyncio.sleep(0.001)
        pipeline.offer("camera", 1, object())
        await asyncio.sleep(0.001)
        pipeline.offer("camera", 1, object())
        pipeline.retire("camera")
        pipeline.activate("camera", 2)
        gate.set()
        await asyncio.sleep(0.01)
        await pipeline.close()
        assert pipeline.meter.counts["replaced"] == 1
        assert pipeline.meter.counts["late_rejected"] == 1
        completions = [detail for kind, detail in events if kind == "frame_completed"]
        assert len(completions) == 1
        assert completions[0]["accepted"] is False
        assert pipeline.meter.counts["processed"] == 1

    asyncio.run(scenario())
