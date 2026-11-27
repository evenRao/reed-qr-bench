import json
import os
import threading

import pytest

from reed_bench.store import Store


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
def test_report_update_survives_a_temporary_reader(tmp_path):
    store = Store(tmp_path)
    run = {"id": "a" * 24, "created": "2026-11-25", "status": "running"}
    try:
        store.save(run)
        report = store.directory(run["id"]) / "report.json"
        reader = report.open("rb")
        release = threading.Timer(0.05, reader.close)
        release.start()
        try:
            store.save({**run, "status": "completed"})
        finally:
            release.join()
            reader.close()
        assert json.loads(report.read_text("utf-8"))["status"] == "completed"
        assert store.get(run["id"])["status"] == "completed"
        assert not report.with_suffix(".pending").exists()
    finally:
        store.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows file sharing semantics")
def test_report_update_preserves_committed_data_when_a_reader_stays_open(tmp_path):
    store = Store(tmp_path)
    run = {"id": "b" * 24, "created": "2026-11-25", "status": "running"}
    try:
        store.save(run)
        report = store.directory(run["id"]) / "report.json"
        with report.open("rb"):
            with pytest.raises(PermissionError):
                store.save({**run, "status": "completed"})
        assert json.loads(report.read_text("utf-8"))["status"] == "running"
        assert store.get(run["id"])["status"] == "running"
        store.save({**run, "status": "completed"})
        assert store.get(run["id"])["status"] == "completed"
    finally:
        store.close()
