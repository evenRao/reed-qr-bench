"""Build a portable application ZIP, tools distributions, SBOMs, and checksums."""

import argparse
import email.parser
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

from version import check, validate_version

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "VERSION",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    "web/package.json",
    "web/package-lock.json",
    "web/tsconfig.json",
    "web/index.html",
)
SOURCE_DIRS = (
    ".github",
    "reed_bench",
    "packages/reed-qr-tools",
    "protocols",
    "assets",
    "docs",
    "scripts",
    "tests",
    "web/src",
    "web/dist",
)
EXCLUDED_PARTS = {"__pycache__", "node_modules", ".venv", ".cache", ".git"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def application_files(root):
    if not (root / "web/dist/index.html").is_file():
        raise ValueError("Build the browser UI before assembling a release")
    paths = {root / name for name in ROOT_FILES}
    for directory in SOURCE_DIRS:
        paths.update(path for path in (root / directory).rglob("*") if path.is_file())
    for path in sorted(paths):
        relative = path.relative_to(root)
        if EXCLUDED_PARTS.intersection(relative.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.name.startswith(".env") and relative.as_posix() != ".env.example":
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Release inputs must be regular project files: {relative}")
        yield relative.as_posix(), path.read_bytes()


def bundle(root, output, version, artifacts, commit=None):
    inputs = dict(application_files(root))
    for path in artifacts:
        inputs["release/" + path.name] = path.read_bytes()
    manifest = {
        "version": version,
        "commit": commit,
        "files": {name: digest(data) for name, data in sorted(inputs.items())},
    }
    inputs["release-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    target = output / f"reed-qr-bench-{version}-windows.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(inputs.items()):
            entry = zipfile.ZipInfo(f"reed-qr-bench-{version}/{name}", (1980, 1, 1, 0, 0, 0))
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    verify(target)
    return target


def verify(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or not names:
            raise ValueError("Release ZIP has duplicate entries or is empty")
        prefix = names[0].split("/", 1)[0] + "/"
        manifest = json.loads(archive.read(prefix + "release-manifest.json"))
        version = validate_version(manifest["version"])
        if prefix != f"reed-qr-bench-{version}/":
            raise ValueError("Release ZIP directory differs from its version")
        expected = {prefix + name for name in manifest["files"]}
        if set(names) != expected | {prefix + "release-manifest.json"}:
            raise ValueError("Release ZIP contents differ from its manifest")
        for name, checksum in manifest["files"].items():
            parts = Path(name).parts
            if Path(name).is_absolute() or ".." in parts or "\\" in name:
                raise ValueError("Release ZIP contains an unsafe path")
            if digest(archive.read(prefix + name)) != checksum:
                raise ValueError(f"Release checksum mismatch: {name}")
        if archive.read(prefix + "VERSION").decode().strip() != manifest["version"]:
            raise ValueError("Release VERSION differs from its manifest")
    return manifest


def verify_directory(output, version):
    expected = {
        f"reed_qr_tools-{version}-py3-none-any.whl",
        f"reed_qr_tools-{version}.tar.gz",
        f"reed-qr-bench-{version}-windows.zip",
        "requirements-runtime.txt",
        "python-sbom.cdx.json",
        "web-sbom.cdx.json",
    }
    # uv build can add a .gitignore marker alongside its output artifacts.
    entries = {p.name: p for p in output.iterdir()}
    marker = entries.pop(".gitignore", None)
    if marker and (not marker.is_file() or marker.read_text("utf-8").strip() != "*"):
        raise ValueError("Unexpected build-output marker")
    if entries.keys() != expected | {"SHA256SUMS"}:
        raise ValueError("Release directory contains missing or unexpected files")
    checksums = {}
    for line in (output / "SHA256SUMS").read_text("utf-8").splitlines():
        checksum, name = line.split("  ", 1)
        if name not in expected or name in checksums:
            raise ValueError("Unexpected or duplicate checksum entry")
        checksums[name] = checksum
    if checksums.keys() != expected:
        raise ValueError("Every release file must have a checksum")
    for name, checksum in checksums.items():
        path = output / name
        if path.is_symlink() or digest(path.read_bytes()) != checksum:
            raise ValueError(f"Release checksum mismatch: {name}")
    manifest = verify(output / f"reed-qr-bench-{version}-windows.zip")
    if manifest["version"] != version:
        raise ValueError("Release artifacts differ from VERSION")
    for name in expected - {f"reed-qr-bench-{version}-windows.zip"}:
        if manifest["files"].get("release/" + name) != checksums[name]:
            raise ValueError(f"Bundled and downloadable artifacts differ: {name}")
    with zipfile.ZipFile(output / f"reed_qr_tools-{version}-py3-none-any.whl") as wheel:
        metadata_path = f"reed_qr_tools-{version}.dist-info/METADATA"
        metadata = email.parser.Parser().parsestr(wheel.read(metadata_path).decode())
        if metadata["Name"] != "reed-qr-tools" or metadata["Version"] != version:
            raise ValueError("Tools wheel metadata differs from VERSION")
        if not any(name.endswith("/licenses/LICENSE") for name in wheel.namelist()):
            raise ValueError("Tools wheel is missing its license")
    with tarfile.open(output / f"reed_qr_tools-{version}.tar.gz") as archive:
        names = set(archive.getnames())
        prefix = f"reed_qr_tools-{version}/"
        if not {prefix + "LICENSE", prefix + "README.md", prefix + "pyproject.toml"} <= names:
            raise ValueError("Tools source distribution is missing release metadata or licenses")
    for name in ("python-sbom.cdx.json", "web-sbom.cdx.json"):
        if json.loads((output / name).read_text("utf-8"))["bomFormat"] != "CycloneDX":
            raise ValueError(f"Invalid SBOM: {name}")


def run(program, *args, stdout=None):
    executable = shutil.which(program + ".cmd" if os.name == "nt" and program == "npm" else program)
    if not executable:
        raise ValueError(f"Required build tool is missing: {program}")
    subprocess.run([executable, *map(str, args)], cwd=ROOT, stdout=stdout, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--verify", type=Path, help="Verify an existing ZIP without building")
    parser.add_argument("--verify-directory", type=Path, help="Verify a complete release directory")
    args = parser.parse_args()
    if args.verify:
        manifest = verify(args.verify)
        print(f"Verified release {manifest['version']}: {len(manifest['files'])} files")
        return
    version = check(ROOT)
    if args.verify_directory:
        verify_directory(args.verify_directory, version)
        print(f"Verified release files and licenses: {version}")
        return
    output = args.output.resolve()
    if not output.is_relative_to(ROOT) or output == ROOT:
        parser.error("Build output must be a directory inside this project")
    if output.exists() and any(output.iterdir()):
        parser.error("Choose an empty output directory to avoid mixing release versions")
    output.mkdir(parents=True, exist_ok=True)
    # Validate the application inputs before downloading or building dependencies.
    list(application_files(ROOT))
    run("uv", "build", "--wheel", "--sdist", "--out-dir", output, "packages/reed-qr-tools")
    requirements = output / "requirements-runtime.txt"
    run(
        "uv",
        "export",
        "--locked",
        "--no-dev",
        "--extra",
        "voice",
        "--no-header",
        "--no-emit-project",
        "--no-emit-package",
        "reed-qr-tools",
        "--output-file",
        requirements,
        stdout=subprocess.DEVNULL,
    )
    python_sbom = output / "python-sbom.cdx.json"
    run(
        "uv",
        "export",
        "--locked",
        "--no-dev",
        "--extra",
        "voice",
        "--no-emit-project",
        "--format",
        "cyclonedx1.5",
        "--output-file",
        python_sbom,
        stdout=subprocess.DEVNULL,
    )
    web_sbom = output / "web-sbom.cdx.json"
    with web_sbom.open("w", encoding="utf-8") as stream:
        run(
            "npm", "--prefix", "web", "sbom", "--omit=dev", "--sbom-format=cyclonedx", stdout=stream
        )
    artifacts = [
        output / f"reed_qr_tools-{version}-py3-none-any.whl",
        output / f"reed_qr_tools-{version}.tar.gz",
        requirements,
        python_sbom,
        web_sbom,
    ]
    archive = bundle(ROOT, output, version, artifacts, os.getenv("GITHUB_SHA"))
    artifacts.append(archive)
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest(path.read_bytes())}  {path.name}\n" for path in sorted(artifacts)),
        "utf-8",
        newline="\n",
    )
    verify_directory(output, version)
    print(f"Built and verified release {version}: {output}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
