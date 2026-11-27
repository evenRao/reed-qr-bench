"""Owned LiveKit service and public RTC source adapters; no legacy UI imports."""

import asyncio
import contextlib
import io
import os
import secrets
import time
from datetime import timedelta
from pathlib import Path

from livekit import api, rtc
from PIL import Image
from reed_qr import Frame, PixelFormat


def recording_preview(path):
    import cv2

    capture = cv2.VideoCapture(str(path))
    try:
        ok, pixels = capture.read()
        if not ok:
            raise ValueError("Recording contains no readable frames")
        ok, encoded = cv2.imencode(".png", cv2.resize(pixels, (640, 480)))
        if not ok:
            raise ValueError("Could not prepare the recording preview")
        return encoded.tobytes()
    finally:
        capture.release()


class LiveKitService:
    def __init__(self, root):
        self.root = Path(root)
        self.process = None
        self.log = None
        self.key = "bench-" + secrets.token_hex(8)
        self.secret = secrets.token_urlsafe(36)
        self.url = "ws://127.0.0.1:7880"
        self.lock = asyncio.Lock()

    async def start(self):
        async with self.lock:
            if self.process and self.process.returncode is None:
                return
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", 7880)
            except OSError:
                pass
            else:
                writer.close()
                await writer.wait_closed()
                raise ValueError(
                    "Port 7880 is occupied. Stop that LiveKit service before starting Bench."
                )
            executable = self.root / ".cache/livekit/1.13.10/livekit-server.exe"
            if not executable.exists():
                raise ValueError(
                    "Install the pinned LiveKit service with scripts/setup-livekit-demo.ps1"
                )
            logs = self.root / ".cache/bench-v2"
            logs.mkdir(parents=True, exist_ok=True)
            self.log = (logs / "livekit.log").open("ab")
            # Secret configuration travels only in the owned child's environment.
            env = os.environ.copy()
            env["LIVEKIT_CONFIG"] = (
                "port: 7880\nbind_addresses: [127.0.0.1]\n"
                "rtc:\n  tcp_port: 7881\n  udp_port: 7882\n  use_external_ip: false\n"
                f"keys:\n  {self.key}: {self.secret}\n"
                "logging:\n  level: warn\n"
            )
            self.process = await asyncio.create_subprocess_exec(
                str(executable),
                "--node-ip",
                "127.0.0.1",
                env=env,
                stdout=self.log,
                stderr=self.log,
            )
            try:
                for _ in range(100):
                    if self.process.returncode is not None:
                        raise ValueError(
                            "LiveKit failed to start; inspect .cache/bench-v2/livekit.log"
                        )
                    try:
                        _, writer = await asyncio.open_connection("127.0.0.1", 7880)
                        writer.close()
                        await writer.wait_closed()
                        return
                    except OSError:
                        await asyncio.sleep(0.1)
                raise ValueError("LiveKit startup exceeded 10 seconds")
            except BaseException:
                await self.close()
                raise

    def token(self, room, identity, publish=True):
        return (
            api.AccessToken(self.key, self.secret)
            .with_identity(identity)
            .with_ttl(timedelta(hours=2))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room,
                    can_publish=publish,
                    can_subscribe=True,
                    can_publish_data=False,
                )
            )
            .to_jwt()
        )

    def connection(self, room):
        return {
            "url": self.url,
            "receiver_token": self.token(room, "bench-receiver", False),
            "publisher_token": self.token(room, "bench-publisher"),
            "room": room,
        }

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None
        if self.log:
            self.log.close()
            self.log = None


async def receive(room, pipeline, stop, emit):
    """Reconcile subscriptions even when the old track produces no more frames."""
    readers = {}
    generations = {}

    def on_data(packet):
        if (
            packet.topic != "reed_bench.voice"
            or packet.participant is None
            or packet.participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
            or len(packet.data) > 15000
        ):
            return
        try:
            event = __import__("json").loads(packet.data)
            if isinstance(event, dict) and event.get("type") in (
                "status",
                "transcript",
                "tool_requested",
                "tool_completed",
            ):
                emit("voice_event", event)
        except (ValueError, TypeError):
            pass

    room.on("data_received", on_data)

    async def consume(key, track, generation):
        reader = rtc.VideoStream.from_track(
            track=track, capacity=1, format=rtc.VideoBufferType.RGB24
        )
        try:
            while not stop.is_set():
                try:
                    event = await asyncio.wait_for(anext(reader), 0.25)
                except TimeoutError:
                    continue
                except StopAsyncIteration:
                    break
                received = time.perf_counter()
                frame = event.frame
                pipeline.offer(
                    key,
                    generation,
                    Frame(
                        bytes(frame.data),
                        frame.width,
                        frame.height,
                        frame.width * 3,
                        PixelFormat.RGB24,
                    ),
                    received=received,
                )
        finally:
            await reader.aclose()

    try:
        while not stop.is_set():
            selected = {}
            for participant in room.remote_participants.values():
                if participant.identity != "bench-publisher":
                    continue
                for publication in participant.track_publications.values():
                    if publication.track and publication.kind == rtc.TrackKind.KIND_VIDEO:
                        key = room.name + ":" + participant.identity + ":" + publication.name
                        selected[key] = (publication.sid, publication.track)
            for key in list(readers):
                if key not in selected or readers[key][0] != selected[key][0]:
                    pipeline.retire(key)
                    readers[key][1].cancel()
                    await asyncio.gather(readers[key][1], return_exceptions=True)
                    del readers[key]
            for key, (sid, track) in selected.items():
                if key not in readers:
                    generations[key] = generations.get(key, 0) + 1
                    generation = generations[key]
                    pipeline.activate(key, generation)
                    readers[key] = (sid, asyncio.create_task(consume(key, track, generation)))
            await asyncio.sleep(0.05)
    finally:
        room.off("data_received", on_data)
        for key, (_, task) in readers.items():
            pipeline.retire(key)
            task.cancel()
        await asyncio.gather(*(t for _, t in readers.values()), return_exceptions=True)
        emit("receiver_closed", {})


async def run_video(config, data, pipeline, stop, emit, *, close_pipeline=True):
    connection = config["connection"]
    receiver, publisher = rtc.Room(), rtc.Room()
    sources, publications = [], []
    receive_task = None
    capture = None
    first_recording_frame = None
    try:
        await receiver.connect(connection["url"], connection["receiver_token"])
        receive_task = asyncio.create_task(receive(receiver, pipeline, stop, emit))
        emit("transport_ready", {"room": connection["room"], "source": config["source"]})
        if config["source"] == "camera":
            try:
                await asyncio.wait_for(stop.wait(), config["duration_s"])
            except TimeoutError:
                pass
            return
        await publisher.connect(connection["url"], connection["publisher_token"])
        if config["source"] == "recording":
            import cv2

            capture = cv2.VideoCapture(config["recording_path"])
            if not capture.isOpened():
                raise ValueError("Recording could not be opened")
            ok, pixels = capture.read()
            if not ok:
                raise ValueError("Recording contains no readable frames")
            image = Image.fromarray(cv2.cvtColor(pixels, cv2.COLOR_BGR2RGB))
            first_recording_frame = pixels
        else:
            image = Image.open(io.BytesIO(data)).convert("RGB")
        canvas = Image.new("RGB", (640, 480), "#c8d0da")
        image.thumbnail((600, 440), Image.Resampling.NEAREST)
        canvas.paste(image, ((640 - image.width) // 2, (480 - image.height) // 2))
        pixels = canvas.tobytes()

        async def publish(index):
            source = rtc.VideoSource(640, 480)
            sources.append(source)
            track = rtc.LocalVideoTrack.create_video_track(f"camera-{index}", source)
            publication = await publisher.local_participant.publish_track(
                track,
                rtc.TrackPublishOptions(
                    source=rtc.TrackSource.SOURCE_CAMERA,
                    simulcast=False,
                ),
            )
            return publication

        for index in range(config.get("streams", 1)):
            publications.append(await publish(index))
        started = time.perf_counter()
        index, replaced = 0, False
        emit(
            "publisher_started",
            {
                "width": 640,
                "height": 480,
                "requested_hz": config["input_hz"],
                "streams": len(sources),
            },
        )
        while not stop.is_set() and time.perf_counter() - started < config["duration_s"]:
            if capture is not None:
                if first_recording_frame is not None:
                    ok, raw = True, first_recording_frame
                    first_recording_frame = None
                else:
                    ok, raw = capture.read()
                if not ok:
                    emit("recording_eof", {})
                    break
                raw = cv2.resize(raw, (640, 480))
                pixels = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB).tobytes()
            if (
                config.get("replace_track")
                and not replaced
                and time.perf_counter() - started > config["duration_s"] / 2
            ):
                action = config.get("recovery_action", "replace_track")
                emit("recovery_started", {"action": action})
                if action == "pause":
                    await asyncio.sleep(0.7)
                else:
                    for publication in publications:
                        await publisher.local_participant.unpublish_track(publication.sid)
                    for source in sources:
                        await source.aclose()
                    sources.clear()
                    publications.clear()
                    if action == "reconnect":
                        await publisher.disconnect()
                        publisher = rtc.Room()
                        await asyncio.sleep(0.3)
                        await publisher.connect(connection["url"], connection["publisher_token"])
                    else:
                        await asyncio.sleep(0.3)
                    for n in range(config.get("streams", 1)):
                        publications.append(await publish(n))
                replaced = True
                emit("recovery_completed", {"action": action})
                if action == "replace_track":
                    emit("track_replaced", {})
            if index == 0:
                emit("first_frame_captured", {})
            for source in sources:
                source.capture_frame(rtc.VideoFrame(640, 480, rtc.VideoBufferType.RGB24, pixels))
                pipeline.meter.counts["published"] += 1
            index += 1
            await asyncio.sleep(max(0, started + index / config["input_hz"] - time.perf_counter()))
        # Drain transport while the publication still exists.
        await asyncio.sleep(0.3)
    finally:
        stop.set()
        if capture is not None:
            capture.release()
        if receive_task:
            await receive_task
        if close_pipeline:
            await pipeline.close()
        if publisher.isconnected():
            for publication in publications:
                with contextlib.suppress(Exception):
                    await publisher.local_participant.unpublish_track(publication.sid)
        for source in sources:
            await source.aclose()
        await publisher.disconnect()
        await receiver.disconnect()
        emit("transport_closed", {})
