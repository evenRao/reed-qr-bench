import asyncio
import io
import zipfile

import pytest
from aiohttp.test_utils import TestClient, TestServer

from reed_bench.corpus import read_corpus
from reed_bench.evidence import score
from reed_bench.fixtures import build_fixture
from reed_bench.metrics import bootstrap_median, summarize
from reed_bench.replay import read_evidence
from reed_bench.resources import Resources
from reed_bench.scoring import evaluate
from reed_bench.server import ROOT, SUPERVISOR, create_app
from reed_bench.store import Store


def test_exactness_preserves_case_whitespace_duplicates_and_empty_negatives():
    assert score(["Hello\n"], ["Hello"]) == "incorrect"
    assert score(["a"], ["a", "a"]) == "incorrect"
    assert score([], []) == "correct"
    assert score(["wrong"], []) == "false_detection"
    assert score([], None) == "unscored"


def test_unsupported_payload_is_not_a_miss_or_a_true_negative():
    result = {
        "payloads": [],
        "detections": [
            {"text": None, "payload_status": "unsupported", "byte_segments_hex": ["7061727469616c"]}
        ],
    }
    assert evaluate(result, ["complete expected payload"]) == "unsupported_payload"
    assert evaluate(result, []) == "false_detection"
    assert evaluate(result, None) == "unscored"
    assert evaluate({"payloads": [], "detections": []}, ["expected"]) == "missed"


def test_independent_attempt_statistics_do_not_pool_conditions():
    base = {
        "implementation": "plugin",
        "source": "video",
        "temperature": "warm",
        "streams": 1,
        "status": "completed",
        "score": "correct",
        "expected": ["a"],
        "expected_positive": True,
        "elapsed_ms": 100,
        "first_correct_ms": 12,
        "metrics": {"first_result_ms": 2, "p95_ms": 10, "processed_rate": 5},
    }
    rows = summarize(
        [
            {**base, "scenario": "clean"},
            {**base, "scenario": "no_code", "expected": [], "expected_positive": False},
            {**base, "scenario": "clean", "temperature": "cold"},
        ],
        {},
    )
    assert len(rows) == 3
    assert all(r["verdict"] == "unrated" for r in rows)
    assert rows[0]["first_result_p50_ms"] == 12
    assert rows[1]["first_result_p50_ms"] is None
    assert bootstrap_median([1, 2]) is None
    assert bootstrap_median([1, 1, 1]) == [1, 1]
    repeated = [{**base, "scenario": "clean", "input_sha256": "same-input"} for _ in range(20)]
    row = summarize(repeated, {})[0]
    assert row["unique_inputs"] == 1
    assert row["consistent_inputs"] == 1
    assert row["accuracy_ci95"][0] < 0.3


def test_public_corpus_uses_independent_labels_and_preserves_splits():
    _, corpus = read_corpus((ROOT / "assets/corpora/zxing-subset.zip").read_bytes(), Resources())
    assert len(corpus["items"]) == 12
    assert {i["split"] for i in corpus["items"]} == {"development", "held_out"}
    assert all(i["expected"] for i in corpus["items"])
    assert "Apache" in corpus["metadata"]["license"]


def test_http_origin_guard_exports_and_verified_replay(tmp_path):
    async def scenario():
        app = create_app(data_dir=tmp_path)
        async with TestClient(TestServer(app)) as client:
            boot = await (await client.get("/api/bootstrap")).json()
            assert "token" in boot
            assert (await client.post("/api/runs", json={})).status == 403
            headers = {"X-REED-Bench": boot["token"]}
            assert (
                await client.post(
                    "/api/runs", json={}, headers={**headers, "Origin": "https://elsewhere.test"}
                )
            ).status == 403
            response = await client.post(
                "/api/runs", json={"implementations": ["plugin"], "repetitions": 1}, headers=headers
            )
            assert response.status == 202
            identifier = (await response.json())["id"]
            await app[SUPERVISOR].task
            response = await client.get(f"/api/runs/{identifier}?format=zip")
            exported = await response.read()
            previous, cases, recording = read_evidence(exported)
            assert previous["attempts"][0]["score"] == "correct"
            assert cases[0]["data"] == build_fixture("clean", 42, 0).data
            assert recording is None
            html = await (await client.get(f"/api/runs/{identifier}?format=html")).text()
            assert "REED QR Bench" in html
            assert (await client.get(f"/api/runs/{identifier}/artifact/../../.env")).status != 200
            assert (
                await client.get(
                    f"/api/runs/{identifier}/artifact/{previous['attempts'][0]['id']}.stderr.log"
                )
            ).status == 404
            # A modified image cannot be replayed under an unchanged evidence manifest.
            changed = io.BytesIO()
            with (
                zipfile.ZipFile(io.BytesIO(exported)) as source,
                zipfile.ZipFile(changed, "w") as destination,
            ):
                for name in source.namelist():
                    destination.writestr(
                        name, b"modified" if name == cases[0]["input_file"] else source.read(name)
                    )
            with pytest.raises(ValueError, match="checksum"):
                read_evidence(changed.getvalue())

    asyncio.run(scenario())


def test_cancellation_preserves_attempt_and_cleans_owned_worker(tmp_path):
    async def scenario():
        app = create_app(data_dir=tmp_path)
        supervisor = app[SUPERVISOR]
        try:
            run = await supervisor.start(
                {"implementations": ["plugin"], "operations": 10000, "repetitions": 1}
            )
            while supervisor.process is None:
                await asyncio.sleep(0.01)
            with pytest.raises(ValueError, match="active run"):
                await supervisor.start({})
            await supervisor.stop()
            assert run["status"] == "cancelled"
            assert len(run["attempts"]) == 1
            assert run["attempts"][0]["status"] == "cancelled"
            assert supervisor.process is None
        finally:
            await supervisor.close()
            supervisor.store.close()

    asyncio.run(scenario())


def test_evidence_directory_has_one_owner(tmp_path):
    first = Store(tmp_path)
    try:
        with pytest.raises(ValueError, match="already in use"):
            Store(tmp_path)
    finally:
        first.close()
    second = Store(tmp_path)
    second.close()


def test_deadline_keeps_partial_metrics_and_reclaims_process(tmp_path):
    async def scenario():
        app = create_app(data_dir=tmp_path)
        supervisor = app[SUPERVISOR]
        try:
            run = await supervisor.start(
                {
                    "implementations": ["plugin"],
                    "repetitions": 1,
                    "operations": 10000,
                    "deadline_s": 2,
                }
            )
            await supervisor.task
            result = run["attempts"][0]
            assert result["status"] == "timeout"
            assert result["metrics"]["counts"]["processed"] > 0
            assert result["worker_exit_code"] != 0
            assert supervisor.process is None
        finally:
            await supervisor.close()
            supervisor.store.close()

    asyncio.run(scenario())
