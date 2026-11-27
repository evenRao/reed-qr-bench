import hashlib
import json
import os
import threading
import zipfile

import pytest

from reed_bench.store import Store


@pytest.mark.parametrize(
    "identifier",
    [
        None,
        123,
        "",
        "a" * 23,
        "a" * 25,
        "A" * 24,
        "g" * 24,
        "../" + "a" * 21,
        "..\\" + "a" * 21,
        "a" * 22 + ":x",
        "a" * 24 + "\n",
    ],
)
def test_run_directory_rejects_untrusted_path_components(tmp_path, identifier):
    store = Store(tmp_path / "runs")
    try:
        with pytest.raises(ValueError, match="Unknown run"):
            store.directory(identifier)
    finally:
        store.close()


def test_evidence_export_keeps_nested_files_and_exact_checksums(tmp_path):
    store = Store(tmp_path / "runs")
    run = {"id": "a" * 24, "created": "2026-11-27", "status": "completed"}
    try:
        store.save(run)
        directory = store.directory(run["id"])
        (directory / "inputs").mkdir()
        (directory / "inputs/fixture.png").write_bytes(b"fixture bytes")
        (directory / "measure.events.ndjson").write_text("{}\n", "utf-8")
        (directory / "report.pending").write_text("unfinished", "utf-8")
        (directory / "worker.stderr.log").write_text("private diagnostics", "utf-8")
        target = store.evidence_path(run["id"])
        with zipfile.ZipFile(target) as archive:
            assert set(archive.namelist()) == {
                "report.json",
                "inputs/fixture.png",
                "measure.events.ndjson",
                "SHA256.json",
            }
            manifest = json.loads(archive.read("SHA256.json"))
            assert set(manifest) == set(archive.namelist()) - {"SHA256.json"}
            for name, checksum in manifest.items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == checksum
    finally:
        store.close()


def test_artifact_lookup_stays_within_the_requested_run(tmp_path):
    store = Store(tmp_path / "runs")
    run = {"id": "a" * 24, "created": "2026-11-27", "status": "completed"}
    other = {**run, "id": "b" * 24}
    try:
        store.save(run)
        store.save(other)
        directory = store.directory(run["id"])
        (directory / "inputs").mkdir()
        image = directory / "inputs/fixture.png"
        image.write_bytes(b"authorized image")
        (directory / "worker.stderr.log").write_text("private diagnostics", "utf-8")
        private_image = store.directory(other["id"]) / "private.png"
        private_image.write_bytes(b"another run")
        assert store.artifact_path(run["id"], "inputs/fixture.png") == image
        for relative in (f"../{other['id']}/private.png", str(private_image), "worker.stderr.log"):
            with pytest.raises(ValueError):
                store.artifact_path(run["id"], relative)
    finally:
        store.close()


def make_link(target, link):
    if os.name == "nt" and target.is_dir():
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                pytest.skip("Creating file symlinks requires Windows symlink privileges")
            raise


@pytest.mark.parametrize("linked_directory", ["run", "exports"])
def test_evidence_export_rejects_linked_run_and_export_directories(tmp_path, linked_directory):
    store = Store(tmp_path / "runs")
    run = {"id": "a" * 24, "created": "2026-11-27", "status": "completed"}
    # This sibling shares the runs prefix but is outside its directory boundary.
    outside = tmp_path / "runs-private"
    outside.mkdir()
    (outside / "secret.txt").write_text("must remain private", "utf-8")
    try:
        if linked_directory == "run":
            make_link(outside, store.root / run["id"])
            with pytest.raises(ValueError, match="escapes"):
                store.save(run)
        else:
            store.save(run)
            make_link(outside, store.root / "exports")
            with pytest.raises(ValueError, match="escapes"):
                store.evidence_path(run["id"])
        assert sorted(path.name for path in outside.iterdir()) == ["secret.txt"]
        assert not store.exports
    finally:
        store.close()


@pytest.mark.parametrize("directory_link", [False, True])
@pytest.mark.parametrize("outside_run", [False, True])
def test_evidence_export_rejects_links_before_archiving(tmp_path, directory_link, outside_run):
    store = Store(tmp_path / "runs")
    run = {"id": "a" * 24, "created": "2026-11-27", "status": "completed"}
    try:
        store.save(run)
        directory = store.directory(run["id"])
        contents = tmp_path / "private" if outside_run else directory / "inputs"
        contents.mkdir()
        secret = contents / "secret.txt"
        secret.write_text("must not be followed through a link", "utf-8")
        make_link(contents if directory_link else secret, directory / "linked")
        with pytest.raises(ValueError, match="linked"):
            store.evidence_path(run["id"])
        assert not list((store.root / "exports").glob("*.zip"))
        assert not store.exports
        assert secret.read_text("utf-8") == "must not be followed through a link"
    finally:
        store.close()


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
