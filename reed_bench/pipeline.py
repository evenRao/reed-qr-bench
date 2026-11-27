"""Bounded latest-frame scheduling shared by camera, recordings, and fixtures."""

import asyncio
import time
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor

import reed_qr
from reed_qr_tools import QRTools, detection_status, serialize_detection

from .metrics import Meter


def opencv(data):
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    return opencv_pixels(image)


def opencv_pixels(image):
    import cv2

    detector = cv2.QRCodeDetector()
    ok, values, _, _ = detector.detectAndDecodeMulti(image)
    if not ok:
        value, _, _ = detector.detectAndDecode(image)
        values = [value] if value else []
    return {
        "status": "decoded" if any(values) else "not_found",
        "detections": [
            {"text": v, "payload_status": "text_only", "bytes_hex": None} for v in values if v
        ],
    }


class Decoder:
    def __init__(self, implementation, resolve, emit, workers=1):
        self.implementation = implementation
        self.tools = QRTools(resolve, emit=emit)
        self.tools_pool = [self.tools] + [QRTools(resolve, emit=emit) for _ in range(workers - 1)]
        self.next_tool = 0
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bench-baseline")

    async def native(self, function, *args):
        future = asyncio.get_running_loop().run_in_executor(self.executor, function, *args)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            await asyncio.shield(future)
            raise

    async def image(self, identifier, data):
        if self.implementation == "plugin":
            return await self.tools.decode_image(identifier)
        if self.implementation == "opencv":
            return await self.native(opencv, data)
        if self.implementation == "off":
            return {"status": "disabled", "detections": []}
        items = await self.native(reed_qr.decode_image, data)
        return {
            "status": detection_status(items),
            "detections": [serialize_detection(i) for i in items],
        }

    async def frame(self, frame, source_id, generation):
        if self.implementation == "plugin":
            tools = self.tools_pool[self.next_tool % len(self.tools_pool)]
            self.next_tool += 1
            return await tools.decode_frame(frame, source_id=source_id, generation=generation)
        if self.implementation == "off":
            return {"status": "disabled", "detections": []}
        if self.implementation == "opencv":
            import cv2
            import numpy as np

            image = np.frombuffer(frame.data, np.uint8).reshape(frame.height, frame.row_stride)
            image = image[:, : frame.width * 3].reshape(frame.height, frame.width, 3)
            return await self.native(opencv_pixels, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        items = await self.native(reed_qr.decode_frame, frame)
        return {
            "status": detection_status(items),
            "detections": [serialize_detection(i) for i in items],
        }

    async def close(self):
        await asyncio.gather(*(tools.aclose() for tools in self.tools_pool))
        self.executor.shutdown(wait=True, cancel_futures=True)


class FramePipeline:
    def __init__(self, decoder, emit, *, scan_hz=10, max_age_ms=1000):
        self.decoder, self.emit = decoder, emit
        self.period = 1 / scan_hz
        self.max_age = max_age_ms / 1000
        self.meter = Meter()
        self.sources = {}
        self.pending = {}
        self.last_sample = {}
        self.tasks = set()
        self.closed = False
        self.latest = None
        self.seen = deque(maxlen=256)
        self.seen_counts = Counter()
        self.fidelity_counts = Counter()
        self.text_unavailable = False
        self.generations_decoded = set()

    def activate(self, source, generation):
        self.sources[source] = generation
        if source in self.pending:
            del self.pending[source]
            self.meter.counts["retired_pending"] += 1
        self.last_sample.pop(source, None)
        self.emit("source_activated", {"source_id": source, "generation": generation})

    def retire(self, source):
        self.sources.pop(source, None)
        if self.pending.pop(source, None):
            self.meter.counts["retired_pending"] += 1
        self.emit("source_retired", {"source_id": source})

    def offer(self, source, generation, frame, received=None):
        now = time.perf_counter() if received is None else received
        self.meter.receive(now)
        if self.closed or self.sources.get(source) != generation:
            self.meter.counts["retired_frames"] += 1
            return
        if now - self.last_sample.get(source, -1e9) < self.period:
            self.meter.counts["sampled_out"] += 1
            return
        self.last_sample[source] = now
        if source in self.pending:
            self.meter.counts["replaced"] += 1
        self.pending[source] = (generation, frame, now)
        if not any(getattr(t, "source_id", None) == source for t in self.tasks):
            task = asyncio.create_task(self._drain(source))
            task.source_id = source
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def _drain(self, source):
        while source in self.pending and not self.closed:
            generation, frame, received = self.pending.pop(source)
            started = time.perf_counter()
            if started - received > self.max_age:
                self.meter.counts["stale"] += 1
                continue
            try:
                result = await self.decoder.frame(frame, source, generation)
            except Exception as error:
                self.meter.counts["errors"] += 1
                self.meter.complete(received, started, time.perf_counter(), False)
                self.emit("decode_error", {"type": type(error).__name__, "source_id": source})
                continue
            finished = time.perf_counter()
            accepted = self.sources.get(source) == generation and not self.closed
            if not accepted:
                self.meter.counts["late_rejected"] += 1
            if accepted and finished - received > self.max_age:
                accepted = False
                self.meter.counts["expired_results"] += 1
            self.meter.complete(received, started, finished, accepted and result.get("detections"))
            self.emit(
                "frame_completed",
                {
                    "source_id": source,
                    "generation": generation,
                    "received_s": received,
                    "started_s": started,
                    "finished_s": finished,
                    "latency_ms": (finished - received) * 1000,
                    "queue_ms": (started - received) * 1000,
                    "result": result,
                    "accepted": accepted,
                },
            )
            if not accepted:
                continue
            self.latest = result
            self.fidelity_counts.update(
                d.get("payload_status", "unspecified") for d in result.get("detections", [])
            )
            self.text_unavailable |= any(
                d.get("text") is None for d in result.get("detections", [])
            )
            self.generations_decoded.add((source, generation))
            for d in result.get("detections", []):
                if d.get("text") is not None and d["text"] not in self.seen:
                    if len(self.seen) == self.seen.maxlen:
                        self.seen_counts.pop(self.seen[0], None)
                    self.seen.append(d["text"])
            counts = Counter(
                d["text"] for d in result.get("detections", []) if d.get("text") is not None
            )
            for text, count in counts.items():
                self.seen_counts[text] = max(self.seen_counts[text], count)

    async def close(self):
        self.closed = True
        self.meter.counts["cancelled_pending"] += len(self.pending)
        self.pending.clear()
        await asyncio.gather(*self.tasks)
