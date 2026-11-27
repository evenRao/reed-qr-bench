"""Owned optional LiveKit Cloud agent. Starting it requires an explicit voice-enabled test."""

import asyncio
import contextlib
import os
import secrets
import sys
from datetime import timedelta
from urllib.parse import urlsplit

from livekit import api


class VoiceHost:
    def __init__(self, root, host_url, host_token):
        self.root, self.host_url, self.host_token = root, host_url, host_token
        self.process = None
        self.client = None
        self.room = None
        self.log = None
        self.drain = None

    def configured(self):
        return all(os.getenv(k) for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))

    async def start(self, room):
        if not self.configured():
            raise ValueError(
                "Voice needs LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET in .env"
            )
        url = os.environ["LIVEKIT_URL"].strip()
        parsed = urlsplit(url)
        if parsed.scheme != "wss" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Voice requires a valid wss:// LiveKit Cloud URL")
        name = "reed-bench-" + secrets.token_hex(6)
        self.client = api.LiveKitAPI(
            url, os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]
        )
        self.room = room
        logs = self.root / ".cache/bench-v2"
        logs.mkdir(parents=True, exist_ok=True)
        self.log = (logs / "voice.stderr.log").open("wb")
        env = os.environ.copy()
        env.update(
            REED_BENCH_HOST=self.host_url, REED_BENCH_TOKEN=self.host_token, REED_BENCH_AGENT=name
        )
        try:
            await self.client.room.create_room(
                api.CreateRoomRequest(name=room, empty_timeout=30, max_participants=4)
            )
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-u",
                "-m",
                "reed_bench.voice_agent",
                "start",
                cwd=self.root,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=self.log,
            )
            async with asyncio.timeout(45):
                while line := await self.process.stdout.readline():
                    if line.strip() == b"REED_BENCH_VOICE_READY":
                        break
                else:
                    raise ValueError(
                        "Voice worker exited before registering; "
                        "inspect .cache/bench-v2/voice.stderr.log"
                    )

            async def drain():
                while await self.process.stdout.readline():
                    pass

            self.drain = asyncio.create_task(drain())
            await self.client.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=name, room=room)
            )
        except BaseException:
            await self.close()
            raise

        def token(identity, publish):
            return (
                api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
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

        return {
            "url": url,
            "room": room,
            "receiver_token": token("bench-receiver", False),
            "publisher_token": token("bench-publisher", True),
        }

    async def close(self):
        if self.client and self.room:
            with contextlib.suppress(Exception):
                async with asyncio.timeout(5):
                    await self.client.room.delete_room(api.DeleteRoomRequest(room=self.room))
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.drain:
            self.drain.cancel()
            await asyncio.gather(self.drain, return_exceptions=True)
        if self.client:
            await self.client.aclose()
        if self.log:
            self.log.close()
        self.process = self.client = self.room = self.log = self.drain = None
