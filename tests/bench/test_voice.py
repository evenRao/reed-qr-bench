import asyncio
from types import SimpleNamespace as NS

from reed_bench import voice_agent
from reed_bench.voice import VoiceHost


def test_real_agent_tool_registration_and_audio_session_without_paid_requests(monkeypatch):
    captured = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured["model"] = kwargs

    class FakeSession:
        def __init__(self, **kwargs):
            pass

        def on(self, event):
            return lambda callback: callback

        async def start(self, **kwargs):
            captured["session"] = kwargs

        async def aclose(self):
            captured["closed"] = True

    class Room:
        local_participant = NS(publish_data=None)

        def on(self, event):
            return lambda callback: callback

    class Context:
        room = Room()

        async def connect(self, **kwargs):
            captured["connect"] = kwargs

        async def wait_for_participant(self, **kwargs):
            assert kwargs["identity"] == "bench-publisher"

        def add_shutdown_callback(self, callback):
            captured["cleanup"] = callback

    monkeypatch.setenv("LIVEKIT_API_KEY", "fixture-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "fixture-secret")
    monkeypatch.setattr(voice_agent.inference, "RealtimeModel", FakeModel)
    monkeypatch.setattr(voice_agent, "AgentSession", FakeSession)

    async def scenario():
        await voice_agent.session(Context())
        agent = captured["session"]["agent"]
        assert len(agent.tools) == 1
        assert agent.tools[0].info.name == "scan_qr"
        options = captured["session"]["room_options"]
        assert options.video_input is False
        assert options.audio_input is True
        assert options.audio_output is True
        await captured["cleanup"]()
        assert captured["closed"]

    asyncio.run(scenario())


def test_unconfigured_voice_has_no_automatic_side_effects(monkeypatch, tmp_path):
    for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(key, raising=False)
    host = VoiceHost(tmp_path, "http://127.0.0.1:8765", "test-token")
    assert not host.configured()
    assert host.process is None
