"""One isolated process per attempt; the evaluator alone owns expected answers."""

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import random
import secrets
import sys
import time
from collections import Counter
from datetime import UTC, datetime

import psutil

from .adapters import providers
from .config import protocol
from .evidence import environment, score
from .fixtures import build_fixture
from .metrics import observer_overhead, summarize
from .scoring import evaluate
from .transport import recording_preview

logger = logging.getLogger(__name__)


class Supervisor:
    def __init__(self, root, store, resources, livekit):
        self.root, self.store, self.resources, self.livekit = root, store, resources, livekit
        self.active = None
        self.task = None
        self.process = None
        self.stop_requested = False
        self.live = None
        self.series = []
        self.keys = {}
        self.recordings = {}
        self.corpora = {}
        self.replay_cases = None
        self.voice = None
        self.scan_future = None
        self.components = {}
        self.admission = asyncio.Lock()

    async def start(self, raw):
        async with self.admission:
            return await self._start(raw)

    async def _start(self, raw):
        if self.task and not self.task.done():
            raise ValueError("Stop the active run before starting another")
        config = protocol(raw)
        for identifier in config["image_ids"]:
            self.resources.get(identifier)
        if config["source"] == "recording" and config["recording_id"] not in self.recordings:
            raise ValueError("Choose an uploaded recording")
        if config["corpus_id"] and config["corpus_id"] not in self.corpora:
            raise ValueError("Choose an imported corpus")
        if config["corpus_id"]:
            count = sum(
                i["split"] == config["split"] for i in self.corpora[config["corpus_id"]]["items"]
            )
            if (
                count
                * config["repetitions"]
                * len(config["implementations"])
                * len(config["loads"])
                * len(config["telemetry_profiles"])
                > 2000
            ):
                raise ValueError("This corpus and protocol would exceed 2000 attempts")
        if config["source"] in ("video", "camera", "recording") and not config["voice"]:
            await self.livekit.start()
        identifier = secrets.token_hex(12)
        self.stop_requested = False
        self.live, self.series = None, []
        self.active = {
            "schema_version": 2,
            "id": identifier,
            "created": datetime.now(UTC).isoformat(),
            "status": "queued",
            "config": config,
            "environment": environment(),
            "attempts": [],
            "summary": [],
            "progress": {"completed": 0, "total": 0},
            "corpus": {
                "generator": "Segno independent encoder",
                "version": "synthetic-v1",
                "split": config["split"],
                "real_world": False,
            },
            "measurement": {
                "revision": 4,
                "clock": "worker monotonic; no browser/server clock subtraction",
                "cpu_scope": "isolated attempt worker; one core = 100%",
                "rss_scope": "worker sampled every 250 ms; peaks between samples may be missed",
                "rate_window_s": 5,
                "ground_truth": "evaluator only",
                "scoring_scope": (
                    "Exact text payload multisets. Raw bytes/fidelity are recorded in completion "
                    "events; binary correctness is not scored by text suites."
                ),
                "warmup": "same worker before measurement; cloud requests never warmed",
                "latency_reservoir": 20000,
            },
            "limitations": [
                "Synthetic fixtures alone do not establish field robustness. "
                "Import an independently labelled real-world corpus.",
                "Chat product transcripts are qualitative observations, not API timings.",
                "Provider internal execution, network-only time, and total billed cost "
                "are not observable.",
                "Direct SDK and plugin share the same decoder; this comparison measures "
                "integration overhead.",
                "Recorded video is normalized to 640×480 and replayed at the configured rate; "
                "it is not original-cadence playback.",
            ],
        }
        self.store.save(self.active)
        self.task = asyncio.create_task(self._run())
        return self.active

    def _cases(self, config):
        cases = []
        directory = self.store.directory(self.active["id"])
        inputs = directory / "inputs"
        inputs.mkdir(exist_ok=True)
        if self.replay_cases is not None:
            cases, self.replay_cases = self.replay_cases, None
            for case in cases:
                case["id"] = secrets.token_hex(8)
                # Use only the verified digest, never an arbitrary archived path.
                case["input_file"] = (
                    "inputs/"
                    + case["input_sha256"]
                    + (".jpg" if case["mime"] == "image/jpeg" else ".png")
                )
                (directory / case["input_file"]).write_bytes(case["data"])
            return cases
        if config["corpus_id"]:
            corpus = self.corpora[config["corpus_id"]]
            self.active["corpus"] = corpus["metadata"]
            (directory / "corpus.zip").write_bytes(corpus["archive"])
            selected = [i for i in corpus["items"] if i["split"] == config["split"]]
            if not selected:
                raise ValueError("This corpus has no cases in the selected split")
        else:
            selected = None
        for repetition in range(config["repetitions"]):
            source_cases = []
            if config["source"] == "recording":
                path = self.recordings[config["recording_id"]]
                source_cases = [
                    (
                        "recording",
                        recording_preview(path),
                        config["expected"],
                        "image/png",
                        config["recording_id"],
                    )
                ]
            elif selected is not None:
                source_cases = [
                    (i["scenario"], i["data"], i["expected"], i["mime"], i["id"]) for i in selected
                ]
            elif config["image_ids"]:
                source_cases = [
                    (
                        "uploaded",
                        self.resources.get(i).data,
                        config["expected"],
                        self.resources.get(i).mime,
                        i,
                    )
                    for i in config["image_ids"]
                ]
            else:
                for scenario in config["scenarios"]:
                    offset = 100000 if config["split"] == "held_out" else 0
                    fixture = build_fixture(scenario, config["seed"], repetition + offset)
                    source_cases.append(
                        (
                            scenario,
                            fixture.data,
                            list(fixture.expected),
                            "image/png",
                            f"{scenario}-{repetition}",
                        )
                    )
            for scenario, data, expected, mime, fixture_id in source_cases:
                if config["source"] == "encode":
                    expected = [config["text"]]
                elif config["source"] == "camera":
                    expected = None
                elif config["source"] == "recording":
                    expected = config["expected"]
                digest = hashlib.sha256(data).hexdigest()
                filename = digest + (".jpg" if mime == "image/jpeg" else ".png")
                (inputs / filename).write_bytes(data)
                for streams in config["loads"]:
                    for implementation in config["implementations"]:
                        cases.append(
                            {
                                "id": secrets.token_hex(8),
                                "implementation": implementation,
                                "model": config["models"].get(implementation.split(":")[0]),
                                "scenario": scenario,
                                "source": config["source"],
                                "streams": streams,
                                "repetition": repetition,
                                "fixture_id": fixture_id,
                                "input_sha256": digest,
                                "input_file": "inputs/" + filename,
                                "data": data,
                                "mime": mime,
                                "expected": expected,
                                "expected_positive": bool(expected),
                                "temperature": "warm"
                                if config["warmups"] and ":" not in implementation
                                else "cold",
                            }
                        )
        expanded = []
        for case in cases:
            for profile in config["telemetry_profiles"]:
                expanded.append(
                    {
                        **case,
                        "id": secrets.token_hex(8),
                        "telemetry_profile": profile,
                        "load_kind": config["load_kind"],
                        "workers": config["workers"],
                    }
                )
        cases = expanded
        if len(cases) > 2000:
            raise ValueError("Imported corpus would exceed 2000 attempts")
        random.Random(config["seed"]).shuffle(cases)
        return cases

    async def _run(self):
        run = self.active
        resource_task = asyncio.create_task(self._resources(run))
        try:
            cases = self._cases(run["config"])
            run["progress"]["total"] = len(cases)
            run["status"] = "running"
            self.store.save(run)
            for case in cases:
                if self.stop_requested:
                    break
                result = await self._attempt(case, run["config"])
                run["attempts"].append(result)
                run["progress"]["completed"] += 1
                run["summary"] = summarize(run["attempts"], run["config"]["targets"])
                run["observer_overhead"] = observer_overhead(run["attempts"])
                self.store.save(run)
            run["status"] = "cancelled" if self.stop_requested else "completed"
        except asyncio.CancelledError:
            run["status"] = "cancelled"
        except Exception as error:
            logger.exception("Benchmark run %s failed", run["id"])
            run["status"] = "error"
            run["error"] = (
                str(error)
                if isinstance(error, ValueError)
                else f"Run failed ({type(error).__name__})"
            )
        finally:
            terminal_status = run["status"]
            run["status"] = "finalizing"
            resource_task.cancel()
            await asyncio.gather(resource_task, return_exceptions=True)
            if run["config"]["voice"]:
                await self.voice.close()
            run["status"] = terminal_status
            run["finished"] = datetime.now(UTC).isoformat()
            self.store.save(run)

    async def _resources(self, run):
        processes = {}
        peaks = {}
        with (self.store.directory(run["id"]) / "components.events.ndjson").open(
            "w", encoding="utf-8"
        ) as file:
            while True:
                observed = {"control_plane": os.getpid()}
                if self.livekit.process and self.livekit.process.returncode is None:
                    observed["livekit_server"] = self.livekit.process.pid
                if self.voice and self.voice.process and self.voice.process.returncode is None:
                    observed["voice_agent"] = self.voice.process.pid
                samples = {}
                for name, pid in observed.items():
                    try:
                        process = processes.setdefault(pid, psutil.Process(pid))
                        samples[name] = {
                            "cpu_percent": process.cpu_percent(),
                            "rss_mb": process.memory_info().rss / 2**20,
                        }
                        peaks.setdefault(name, {"cpu_percent": 0, "rss_mb": 0})
                        for key, value in samples[name].items():
                            peaks[name][key] = max(peaks[name][key], value)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                self.components = samples
                run["component_resource_peaks"] = peaks
                file.write(
                    json.dumps({"monotonic_s": time.perf_counter(), "components": samples}) + "\n"
                )
                file.flush()
                await asyncio.sleep(0.25)

    async def _attempt(self, case, config):
        directory = self.store.directory(self.active["id"])
        identifier = case["id"]
        worker = {
            k: v
            for k, v in config.items()
            if k not in ("expected", "image_ids", "targets", "corpus_id")
        }
        worker.update(
            {
                "implementation": case["implementation"],
                "model": case["model"],
                "streams": case["streams"],
                "mime": case["mime"],
                "image_b64": base64.b64encode(case["data"]).decode(),
                "telemetry_profile": case.get("telemetry_profile", "full"),
            }
        )
        if ":" in case["implementation"]:
            worker["warmups"] = 0
        room = "bench-" + identifier
        if config["source"] in ("video", "camera", "recording"):
            if config["voice"]:
                worker["connection"] = await self.voice.start(room)
            else:
                worker["connection"] = self.livekit.connection(room)
                if config["load_kind"] == "rooms" and config["source"] == "video":
                    worker["connections"] = [
                        self.livekit.connection(f"{room}-{index}")
                        for index in range(case["streams"])
                    ]
        if config["source"] == "recording":
            recording = directory / "recording.video"
            if not recording.exists():
                recording.write_bytes(self.recordings[config["recording_id"]].read_bytes())
            worker["recording_path"] = str(recording)
            case["recording_sha256"] = hashlib.sha256(recording.read_bytes()).hexdigest()
        self.live = {
            "attempt_id": identifier,
            "implementation": case["implementation"],
            "scenario": case["scenario"],
            "streams": case["streams"],
            "workers": config["workers"],
            "load_kind": config["load_kind"],
            "source": config["source"],
            "state": "starting",
            "metrics": None,
            "events": [],
            "preview": "/api/runs/" + self.active["id"] + "/artifact/" + case["input_file"],
        }
        if config["source"] == "camera":
            self.live["camera"] = {
                "url": worker["connection"]["url"],
                "token": worker["connection"]["publisher_token"],
            }
        self.series = []
        env = os.environ.copy()
        env.update(
            {
                "OPENAI_API_KEY": self.keys.get("openai", env.get("OPENAI_API_KEY", "")),
                "GEMINI_API_KEY": self.keys.get("gemini", env.get("GEMINI_API_KEY", "")),
            }
        )
        for name, value in self.keys.items():
            env[providers()[name].key_env] = value
        start = time.perf_counter()
        result = None
        startup_ms, first_correct_ms, measurement_ms = None, None, None
        measurement_origin = None
        first_capture_ms, recovery_completed_ms, recovery_first_correct_ms = None, None, None
        first_correct_by_generation = {}
        host_to_first_payload_ms = None
        processed_by_source = {}
        clip_payloads = {}
        trace_path = directory / f"{identifier}.events.ndjson"
        with (
            (directory / f"{identifier}.stderr.log").open("wb") as stderr,
            trace_path.open("w", encoding="utf-8") as trace,
        ):
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "-m",
                "reed_bench.worker",
                cwd=self.root,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
                limit=4 * 1024 * 1024,
            )
            try:
                async with asyncio.timeout(
                    config["deadline_s"]
                    + (
                        config["duration_s"]
                        if config["source"] in ("video", "camera", "recording")
                        else 0
                    )
                ):
                    self.process.stdin.write((json.dumps(worker) + "\n").encode())
                    await self.process.stdin.drain()
                    while line := await self.process.stdout.readline():
                        trace.write(line.decode("utf-8"))
                        event = json.loads(line)
                        kind, detail = event["event"], event["detail"]
                        if kind == "worker_ready":
                            startup_ms = (time.perf_counter() - start) * 1000
                        if kind == "measurement_started":
                            measurement_ms = event["ms"]
                            measurement_origin = detail.get("origin_worker_s")
                        if kind == "first_frame_captured" and first_capture_ms is None:
                            first_capture_ms = event["ms"]
                        if kind == "frame_completed" and detail.get("source_id"):
                            source_id = detail["source_id"]
                            processed_by_source[source_id] = (
                                processed_by_source.get(source_id, 0) + 1
                            )
                        if kind == "recovery_completed":
                            recovery_completed_ms = event["ms"]
                        actual = [
                            i["text"]
                            for i in detail.get("result", {}).get("detections", [])
                            if i.get("text") is not None
                        ]
                        if (
                            kind == "frame_completed"
                            and detail.get("accepted", True)
                            and actual
                            and host_to_first_payload_ms is None
                        ):
                            host_to_first_payload_ms = (time.perf_counter() - start) * 1000
                            self.live["host_to_first_payload_ms"] = host_to_first_payload_ms
                        if (
                            kind == "frame_completed"
                            and config["source"] == "recording"
                            and detail.get("accepted", True)
                        ):
                            accumulated = clip_payloads.setdefault(detail["source_id"], Counter())
                            for text, count in Counter(actual).items():
                                accumulated[text] = max(accumulated[text], count)
                            actual = list(accumulated.elements())
                        if (
                            kind == "frame_completed"
                            and detail.get("accepted", True)
                            and score(actual, case["expected"]) == "correct"
                            and all(
                                i.get("text") is not None
                                for i in detail["result"].get("detections", [])
                            )
                            and case["expected"]
                        ):
                            first_correct_ms = (
                                first_correct_ms
                                if first_correct_ms is not None
                                else (detail["finished_s"] - measurement_origin) * 1000
                                if measurement_origin is not None
                                else event["ms"] - (measurement_ms or 0)
                            )
                            self.live["first_correct_ms"] = first_correct_ms
                            key = (
                                f"{detail.get('source_id', 'image')}:{detail.get('generation', 0)}"
                            )
                            first_correct_by_generation.setdefault(
                                key, event["ms"] - (measurement_ms or 0)
                            )
                            if (
                                recovery_completed_ms is not None
                                and recovery_first_correct_ms is None
                            ):
                                recovery_first_correct_ms = event["ms"] - recovery_completed_ms
                        if kind == "metrics":
                            self.live["metrics"] = detail
                            self.series.append(
                                {
                                    "t": detail["elapsed_s"],
                                    "received": detail["received_rate"],
                                    "processed": detail["processed_rate"],
                                    "p95": detail["p95_ms"],
                                    "rss_mb": detail["rss_mb"],
                                }
                            )
                            self.series = self.series[-240:]
                        elif kind == "scan_result" and self.scan_future:
                            request_id, future = self.scan_future
                            if detail.get("request_id") == request_id and not future.done():
                                future.set_result(detail)
                        elif kind == "voice_event":
                            self.live.setdefault("voice", []).append(detail)
                            self.live["voice"] = self.live["voice"][-40:]
                        elif kind == "model_stage":
                            self.live.setdefault("model_stages", {}).setdefault(
                                detail["stage"], detail["operation_ms"]
                            )
                            if detail["stage"] == "model_response_completed":
                                values = detail["detail"].get("payloads")
                                self.live["result"] = {
                                    "payloads": values,
                                    "score": score(values, case["expected"]),
                                    "status": "answer_available",
                                    "complete_answer_ms": detail["operation_ms"],
                                }
                                if values and host_to_first_payload_ms is None:
                                    host_to_first_payload_ms = (time.perf_counter() - start) * 1000
                                    self.live["host_to_first_payload_ms"] = host_to_first_payload_ms
                        else:
                            self.live["events"].append(
                                {
                                    "event": detail.get("stage", kind)
                                    if kind == "model_stage"
                                    else kind,
                                    "ms": event["ms"],
                                }
                            )
                            self.live["events"] = self.live["events"][-25:]
                        self.live["state"] = "running"
                        if kind == "finished":
                            result = detail
                    await self.process.wait()
            except TimeoutError:
                result = {
                    "status": "timeout",
                    "error": "Attempt exceeded the configured deadline",
                    "cleanup": "forced process boundary",
                }
            finally:
                if self.process.returncode is None:
                    self.process.kill()
                    await self.process.wait()
                exit_code = self.process.returncode
                self.process = None
        if config["voice"]:
            await self.voice.close()
        if self.stop_requested:
            result = {**(result or {}), "status": "cancelled", "error": "Stopped by the operator"}
        if result is None:
            result = {
                "status": "error",
                "error": f"Worker exited without a result (exit {exit_code})",
            }
        if result.get("artifact_b64"):
            path = directory / f"{identifier}.png"
            path.write_bytes(base64.b64decode(result.pop("artifact_b64")))
            result["artifact"] = path.name
        result.setdefault("metrics", dict(self.live.get("metrics") or {}))
        warning_count = (
            (directory / f"{identifier}.stderr.log")
            .read_text("utf-8", errors="replace")
            .count("Attempted to drop unknown FFI handle")
        )
        result["native_cleanup_warnings"] = warning_count
        if warning_count:
            result["cleanup"] = "completed with native FFI handle warnings; worker exited"
        result.setdefault("elapsed_ms", (time.perf_counter() - start) * 1000)
        result["metrics"].setdefault("first_result_ms", first_correct_ms)
        if result["status"] == "completed" and result.get("telemetry_dropped", 0):
            result["status"] = "incomplete_telemetry"
        result["resolved_model"] = result.get("model")
        result.update({k: v for k, v in case.items() if k != "data"})
        result.update(
            startup_ms=startup_ms,
            first_correct_ms=first_correct_ms,
            first_correct_by_generation=first_correct_by_generation,
            total_host_ms=(time.perf_counter() - start) * 1000,
            events_file=trace_path.name,
            first_capture_to_correct_ms=(
                first_correct_ms + (measurement_ms or 0) - first_capture_ms
            )
            if first_correct_ms is not None and first_capture_ms is not None
            else None,
            recovery_first_correct_ms=recovery_first_correct_ms,
            processed_by_source=processed_by_source,
            host_to_first_payload_ms=host_to_first_payload_ms,
            worker_exit_code=exit_code,
        )
        result["score"] = (
            evaluate(result, case["expected"])
            if result["status"] == "completed"
            else "execution_failure"
        )
        if case["implementation"] == "off":
            result["score"] = "unscored"
        if (
            config["source"] in ("video", "recording")
            and case["expected"] is not None
            and result["score"] == "correct"
        ):
            decoded_sources = {k.rsplit(":", 1)[0] for k in first_correct_by_generation}
            if len(decoded_sources if case["expected"] else processed_by_source) < case["streams"]:
                result["score"] = "capacity_failure"
        if (
            config["replace_track"]
            and case["expected"]
            and result["score"] == "correct"
            and recovery_first_correct_ms is None
        ):
            result["score"] = "recovery_failure"
        if ":" in case["implementation"]:
            result["cost"] = {
                "billed_total": None,
                "reason": "Provider invoice and all tool fees are not observable",
                "usage": result.get("usage"),
            }
        self.live["metrics"] = {**(self.live.get("metrics") or {}), **result["metrics"]}
        self.live["metrics"].update(
            cpu_percent=result.get("cpu_peak"),
            rss_mb=result.get("rss_peak_mb"),
        )
        self.series.append(
            {
                "t": result["metrics"].get("elapsed_s", 0),
                "received": result["metrics"].get("received_rate"),
                "processed": result["metrics"].get("processed_rate"),
                "p95": result["metrics"].get("p95_ms"),
                "rss_mb": result.get("rss_peak_mb", 0),
            }
        )
        self.live["result"] = {
            k: result.get(k)
            for k in (
                "payloads",
                "score",
                "status",
                "error",
                "artifact",
                "first_correct_ms",
                "first_token_ms",
                "tool_requested_ms",
                "tool_result_ms",
                "usage",
                "cost",
                "detections",
                "complete_answer_ms",
                "generation_after_first_output_ms",
                "provider_cleanup_ms",
                "qr_tool_used",
            )
        }
        self.live["state"] = result["status"]
        return result

    async def stop(self):
        if self.active and self.active["status"] == "finalizing" and self.task:
            await asyncio.shield(self.task)
            return
        self.stop_requested = True
        if self.active and self.task and not self.task.done():
            self.active["status"] = "cancelling"
        process = self.process
        if process is None and self.task and not self.task.done():
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
            if self.active["status"] in ("queued", "cancelling"):
                self.active["status"] = "cancelled"
                self.store.save(self.active)
            return
        if process and process.returncode is None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError, TimeoutError):
                process.stdin.write(b"stop\n")
                await asyncio.wait_for(process.stdin.drain(), 1)
            try:
                await asyncio.wait_for(asyncio.shield(self.task), 4)
            except TimeoutError:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                await self.task

    async def scan(self):
        if self.scan_future is not None:
            return {"status": "busy", "detections": []}
        if (
            not self.process
            or self.process.returncode is not None
            or not self.active
            or not self.active["config"]["voice"]
        ):
            return {"status": "no_camera", "detections": []}
        identifier = secrets.token_hex(8)
        future = asyncio.get_running_loop().create_future()
        self.scan_future = (identifier, future)
        try:
            self.process.stdin.write((json.dumps({"scan_request": identifier}) + "\n").encode())
            await self.process.stdin.drain()
            result = await asyncio.wait_for(future, 6)
            # Keep exact bytes and geometry outside model context.
            result["detections"] = [
                {"text": d.get("text"), "payload_status": d.get("payload_status")}
                for d in result.get("detections", [])
            ]
            return result
        except (TimeoutError, BrokenPipeError, ConnectionResetError):
            return {"status": "cancelled", "detections": []}
        finally:
            self.scan_future = None

    async def close(self):
        await self.stop()
        if self.task:
            await self.task
        await self.livekit.close()
        if self.voice:
            await self.voice.close()
