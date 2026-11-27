import importlib.util
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.version import check, set_version

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def release_module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "build_release", ROOT / "scripts/build-release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def metadata_copy(tmp_path):
    for name in (
        "VERSION",
        "pyproject.toml",
        "uv.lock",
        "web/package.json",
        "web/package-lock.json",
        "packages/reed-qr-tools/pyproject.toml",
        "packages/reed-qr-tools/src/reed_qr_tools/__init__.py",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    return tmp_path


def test_version_update_keeps_internal_dependency_and_both_lockfiles_consistent(metadata_copy):
    current = check(ROOT)
    major, minor, patch = map(int, current.split("."))
    updated = f"{major}.{minor}.{patch + 1}"
    assert check(metadata_copy) == current
    assert set_version(updated, metadata_copy) == updated
    assert check(metadata_copy, tag=f"v{updated}") == updated
    with pytest.raises(ValueError, match="Release tag"):
        check(metadata_copy, tag=f"v{current}")
    before = (metadata_copy / "VERSION").read_bytes()
    with pytest.raises(ValueError, match="stable semantic version"):
        set_version("0.2.1; unsafe", metadata_copy)
    assert (metadata_copy / "VERSION").read_bytes() == before


def test_version_check_rejects_metadata_drift(metadata_copy):
    current = check(ROOT)
    major, minor, patch = map(int, current.split("."))
    (metadata_copy / "VERSION").write_text(f"{major}.{minor}.{patch + 1}\n", "utf-8")
    with pytest.raises(ValueError, match="Version checks failed"):
        check(metadata_copy)


def test_release_bundle_excludes_credentials_and_detects_tampering(tmp_path, release_module):
    root = tmp_path / "source"
    root.mkdir()
    for name in release_module.ROOT_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("0.2.0\n" if name == "VERSION" else "fixture\n", "utf-8")
    for name in (
        "web/dist/index.html",
        "reed_bench/example.py",
        "reed_bench/.env",
        "reed_bench/__pycache__/example.pyc",
        ".env",
        ".cache/private.txt",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", "utf-8")
    output = tmp_path / "output"
    output.mkdir()
    archive = release_module.bundle(root, output, "0.2.0", [])
    manifest = release_module.verify(archive)
    assert ".env.example" in manifest["files"]
    assert "web/dist/index.html" in manifest["files"]
    assert "reed_bench/.env" not in manifest["files"]
    assert not any("__pycache__" in name or ".cache" in name for name in manifest["files"])
    changed = output / "changed.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(changed, "w") as target:
        for name in source.namelist():
            data = b"changed" if name.endswith("example.py") else source.read(name)
            target.writestr(name, data)
    with pytest.raises(ValueError, match="checksum mismatch"):
        release_module.verify(changed)


def test_release_requires_a_built_browser(tmp_path, release_module):
    with pytest.raises(ValueError, match="Build the browser UI"):
        list(release_module.application_files(tmp_path))
