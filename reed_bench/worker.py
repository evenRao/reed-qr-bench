"""Disposable attempt process. NDJSON telemetry contains every completion, not just detections."""

import asyncio
import base64
import contextlib
import json
import queue
import sys
import threading
import time

import aiohttp
import psutil
import reed_qr

from .adapters import create_provider
from .contracts import Resource
from .evidence import Trace
from .metrics import Meter
from .pipeline import Decoder, FramePipeline
from .providers import ProviderError


class Events:
    def __init__(self):
        self.queue = queue.Queue(maxsize=2048)
        self.dropped = 0
        self.started = time.perf_counter()
        self.scan = None
        self.cancel_requested = False
        self.profile = "full"
        self.thread = threading.Thread(target=self._write, daemon=True)
        self.thread.start()

    def _write(self):
        while True:
            item = self.queue.get()
            if item is None:
                return
            sys.stdout.write(json.dumps(item, ensure_ascii=True, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def emit(self, kind, detail=None):
        if self.profile == "minimal" and kind in (
            "frame_completed",
            "qr_operation_started",
            "qr_operation_completed",
        ):
            return
        if (
            self.scan
            and kind == "frame_completed"
            and detail.get("accepted", True)
            and detail["received_s"] >= self.scan[1]
            and detail["result"].get("detections")
        ):
            self.finish_scan(detail["result"])
        item = {
            "worker_s": time.perf_counter(),
            "event": kind,
            "ms": (time.perf_counter() - self.started) * 1000,
            "detail": detail or {},
        }
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def request_scan(self, identifier):
        if self.scan:
            self.emit("scan_result", {"request_id": identifier, "status": "busy", "detections": []})
        else:
            self.scan = (identifier, time.perf_counter())

    def finish_scan(self, result):
        if self.scan is None:
            return
        identifier, started = self.scan
        self.scan = None
        self.emit(
            "scan_result",
            {
                "request_id": identifier,
                "worker_scan_ms": (time.perf_counter() - started) * 1000,
                **result,
            },
        )

    def finish(self, result):
        result["telemetry_dropped"] = self.dropped
        self.queue.put(
            {
                "event": "finished",
                "ms": (time.perf_counter() - self.started) * 1000,
                "detail": result,
            }
        )
        self.queue.put(None)
        self.thread.join(timeout=5)


class LiveTrace(Trace):
    def __init__(self, emit):
        super().__init__(capacity=1024)
        self.forward = emit

    def emit(self, kind, value=None):
        super().emit(kind, value)
        self.forward(
            "model_stage", {"stage": kind, "detail": value or {}, "operation_ms": self.ms()}
        )


async def attempt(config, events, stop):
    data = base64.b64decode(config.get("image_b64", ""))
    resource = Resource("input", data, config.get("mime", "image/png"), 0, 0)

    def resolve(identifier):
        if identifier != "input":
            raise ValueError("Unauthorized image")
        return data

    decoder = Decoder(
        config["implementation"], resolve, events.emit, workers=config.get("workers", 1)
    )
    pipeline = FramePipeline(
        decoder, events.emit, scan_hz=config["scan_hz"], max_age_ms=config["max_queue_age_ms"]
    )
    process = psutil.Process()
    process.cpu_percent()
    resources = {"cpu_peak": 0, "rss_peak_mb": 0}
    resource_samples = []
    done = asyncio.Event()

    async def telemetry():
        while not done.is_set():
            if events.scan and time.perf_counter() - events.scan[1] >= 5:
                events.finish_scan({"status": "not_found", "detections": []})
            sample = {
                "cpu_percent": process.cpu_percent(),
                "rss_mb": process.memory_info().rss / 2**20,
            }
            resources["cpu_peak"] = max(resources["cpu_peak"], sample["cpu_percent"])
            resources["rss_peak_mb"] = max(resources["rss_peak_mb"], sample["rss_mb"])
            resource_samples.append((time.perf_counter(), sample["rss_mb"]))
            if len(resource_samples) > 14400:
                del resource_samples[:7200]
            events.emit(
                "metrics",
                {
                    **pipeline.meter.snapshot(),
                    **sample,
                    "scope": "isolated attempt worker; CPU 100% = one logical core",
                    "latest": pipeline.latest,
                },
            )
            await asyncio.sleep(0.25)

    task = None
    result = {"status": "completed", "payloads": [], "usage": None}
    encoded_outputs = []
    try:
        # Warmup executes in this same owned process, excluded from measured scope.
        warm_started = time.perf_counter()
        for _ in range(config["warmups"]):
            if config["source"] == "encode":
                await decoder.tools.encode_text("warmup")
            elif data and ":" not in config["implementation"]:
                if config["implementation"] == "plugin":
                    await asyncio.gather(
                        *(tools.decode_image("input") for tools in decoder.tools_pool)
                    )
                else:
                    await asyncio.gather(
                        *(decoder.image("input", data) for _ in range(config.get("workers", 1)))
                    )
        events.emit(
            "warmup_completed",
            {"count": config["warmups"], "elapsed_ms": (time.perf_counter() - warm_started) * 1000},
        )
        process.cpu_percent()
        pipeline.meter = Meter()
        task = asyncio.create_task(telemetry())
        events.emit(
            "measurement_started",
            {
                "clock": "worker perf_counter",
                "origin_worker_s": pipeline.meter.started,
                "latency_scope": (
                    "received frame to completed decode; image admission to completion"
                ),
            },
        )
        if config["source"] in ("video", "camera", "recording"):
            from .transport import run_video

            if config.get("connections"):
                await asyncio.gather(
                    *(
                        run_video(
                            {**config, "connection": connection, "streams": 1},
                            data,
                            pipeline,
                            stop,
                            events.emit,
                            close_pipeline=False,
                        )
                        for connection in config["connections"]
                    )
                )
            else:
                await run_video(config, data, pipeline, stop, events.emit)
            result["payloads"] = list(pipeline.seen_counts.elements())
            result["generations_decoded"] = sorted([list(i) for i in pipeline.generations_decoded])
        else:
            for _ in range(config["operations"]):
                if stop.is_set():
                    break
                start = time.perf_counter()
                pipeline.meter.receive(start)
                if config["source"] == "encode":
                    if config["implementation"] == "plugin":
                        image = await decoder.tools.encode_text(
                            config["text"], correction=config["correction"], scale=config["scale"]
                        )
                        png = image.png
                    else:
                        image = await decoder.native(
                            lambda: reed_qr.encode_text(
                                config["text"],
                                options=reed_qr.EncodeOptions(
                                    error_correction=config["correction"],
                                    pixels_per_module=config["scale"],
                                ),
                            )
                        )
                        png = image.to_png()
                    finished = time.perf_counter()
                    encoded_outputs.append(png)
                    decoded = {"status": "encoded", "detections": []}
                    result["artifact_b64"] = base64.b64encode(png).decode()
                    result["artifact_bytes"] = len(png)
                elif ":" in config["implementation"]:
                    name, mode = config["implementation"].split(":")
                    trace = LiveTrace(events.emit)
                    async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=config["deadline_s"])
                    ) as session:
                        answer = await create_provider(name, session).run(
                            resource,
                            mode,
                            config["model"],
                            decoder.tools,
                            trace,
                            forced=config["forced_tool"],
                        )
                    answer_completed = trace.first("model_response_completed")
                    finished = (
                        trace.started / 1e9 + answer_completed / 1000
                        if answer_completed is not None
                        else time.perf_counter()
                    )
                    result.update(answer)
                    result["provider_cleanup_ms"] = max(0, (time.perf_counter() - finished) * 1000)
                    result["complete_answer_ms"] = (finished - start) * 1000
                    result["trace"] = trace.export()
                    result["first_token_ms"] = trace.first("first_model_output")
                    result["generation_after_first_output_ms"] = (
                        answer_completed - result["first_token_ms"]
                        if answer_completed is not None and result["first_token_ms"] is not None
                        else None
                    )
                    result["tool_requested_ms"] = trace.first("tool_requested")
                    result["tool_result_ms"] = trace.first("tool_result_available")
                    result["qr_tool_used"] = trace.first("tool_result_available") is not None
                    result["code_tool_observed"] = trace.first("code_tool_observed") is not None
                    decoded = {"detections": [{"text": v} for v in (answer.get("payloads") or [])]}
                else:
                    decoded = await decoder.image("input", data)
                    finished = time.perf_counter()
                if decoded.get("status") == "scanner_error":
                    result["status"] = "scanner_error"
                    result["error"] = "The QR plugin returned a scanner error"
                pipeline.latest = decoded
                pipeline.fidelity_counts.update(
                    d.get("payload_status", "model_text") for d in decoded.get("detections", [])
                )
                pipeline.text_unavailable |= any(
                    d.get("text") is None for d in decoded.get("detections", [])
                )
                pipeline.meter.complete(start, start, finished, decoded.get("detections"))
                if ":" not in config["implementation"]:
                    result["payloads"] = [
                        d["text"]
                        for d in decoded.get("detections", [])
                        if d.get("text") is not None
                    ]
                events.emit(
                    "frame_completed",
                    {
                        "received_s": start,
                        "started_s": start,
                        "finished_s": finished,
                        "latency_ms": (finished - start) * 1000,
                        "queue_ms": 0,
                        "result": decoded,
                    },
                )
                await asyncio.sleep(0)
        result["elapsed_ms"] = (time.perf_counter() - pipeline.meter.started) * 1000
        if (
            ":" in config["implementation"]
            and config["operations"] == 1
            and result.get("complete_answer_ms") is not None
        ):
            result["elapsed_ms"] = result["complete_answer_ms"]
        result["metrics"] = pipeline.meter.snapshot()
        result["detections"] = (pipeline.latest or {}).get("detections", [])
        result["fidelity_counts"] = dict(pipeline.fidelity_counts)
        result["text_unavailable"] = pipeline.text_unavailable
        if encoded_outputs:
            from .pipeline import opencv

            verify_start = time.perf_counter()
            verified = [await decoder.native(opencv, png) for png in encoded_outputs]
            result["verification_ms"] = (time.perf_counter() - verify_start) * 1000
            result["round_trips_verified"] = len(verified)
            matching = all(
                [d.get("text") for d in item["detections"]] == [config["text"]] for item in verified
            )
            result["payloads"] = [config["text"]] if matching else []
        if events.cancel_requested:
            result["status"] = "cancelled"
    except ProviderError as error:
        result.update(status=error.category, error=str(error))
    except Exception as error:
        result.update(status="error", error=f"Operation failed ({type(error).__name__})")
        events.emit("worker_error", {"type": type(error).__name__})
    finally:
        events.finish_scan({"status": "cancelled", "detections": []})
        done.set()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await pipeline.close()
        await decoder.close()
        result.setdefault("elapsed_ms", (time.perf_counter() - pipeline.meter.started) * 1000)
        result.setdefault("metrics", pipeline.meter.snapshot())
        if ":" in config["implementation"] and "trace" in locals():
            result["trace"] = trace.export()
        resources["rss_peak_mb"] = max(resources["rss_peak_mb"], process.memory_info().rss / 2**20)
        result.update(resources)
        result["cpu_final"] = process.cpu_percent()
        result["cpu_peak"] = max(result["cpu_peak"], result["cpu_final"])
        if len(resource_samples) >= 2:
            seconds = resource_samples[-1][0] - resource_samples[0][0]
            result["memory_endpoint_slope_mb_min"] = (
                (resource_samples[-1][1] - resource_samples[0][1]) / seconds * 60
                if seconds
                else None
            )
        result["cleanup"] = "completed"
        events.emit("cleanup_completed", {})
    return result


async def main():
    config = json.loads(sys.stdin.readline())
    # Windows native DLL bootstrap must run before the telemetry/control threads.
    # Loading OpenCV on an executor thread can deadlock during module shutdown.
    if config["implementation"] == "opencv" or config["source"] in ("encode", "recording"):
        import cv2  # noqa: F401
    if config["source"] in ("video", "camera", "recording"):
        from .transport import run_video  # noqa: F401

    events = Events()
    events.profile = config.get("telemetry_profile", "full")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def controls():
        for line in sys.stdin:
            if line.strip() == "stop":
                events.cancel_requested = True
                loop.call_soon_threadsafe(stop.set)
                return
            try:
                command = json.loads(line)
                if command.get("scan_request"):
                    loop.call_soon_threadsafe(events.request_scan, command["scan_request"])
            except ValueError:
                continue

    threading.Thread(target=controls, daemon=True).start()
    events.emit("worker_ready", {})
    result = await attempt(config, events, stop)
    events.finish(result)


if __name__ == "__main__":
    asyncio.run(main())
