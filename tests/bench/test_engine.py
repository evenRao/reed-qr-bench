import asyncio

from reed_bench.resources import Resources
from reed_bench.server import ROOT
from reed_bench.store import Store
from reed_bench.supervisor import Supervisor
from reed_bench.transport import LiveKitService


def test_isolated_smoke_and_export(tmp_path):
    async def scenario():
        store = Store(tmp_path)
        supervisor = Supervisor(ROOT, store, Resources(), LiveKitService(ROOT))
        try:
            run = await supervisor.start(
                {
                    "scenarios": ["clean", "no_code"],
                    "implementations": ["plugin", "sdk", "opencv"],
                    "repetitions": 1,
                }
            )
            await supervisor.task
            assert run["status"] == "completed", run.get("error")
            assert len(run["attempts"]) == 6
            for item in run["attempts"]:
                assert item["status"] == "completed", item
                assert item["score"] == "correct", item
                assert item["metrics"]["counts"]["processed"] == 1
                assert item["startup_ms"] > 0
                assert item["rss_peak_mb"] > 0
            assert len(store.evidence_zip(run["id"])) > 100
        finally:
            await supervisor.close()
            store.close()

    asyncio.run(scenario())
