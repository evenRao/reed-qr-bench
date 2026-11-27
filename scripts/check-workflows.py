"""Validate workflows with a pinned, checksum-verified actionlint binary."""

import hashlib
import io
import os
import platform
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.7.12"
CHECKSUMS = {
    ("Windows", "amd64"): "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9",
    ("Windows", "arm64"): "cadcf7ea4efe3a68728893813643cebe1185e5b1d4be5b96245f65c9a4d5ea41",
    ("Linux", "amd64"): "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
    ("Linux", "arm64"): "325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6",
    ("Darwin", "amd64"): "5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644",
    ("Darwin", "arm64"): "aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f",
}


def main():
    system = platform.system()
    machine = platform.machine().lower()
    architecture = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(
        machine
    )
    checksum = CHECKSUMS.get((system, architecture))
    if checksum is None:
        raise ValueError(f"No verified actionlint build for {system}/{machine}")
    suffix = "zip" if system == "Windows" else "tar.gz"
    name = f"actionlint_{VERSION}_{system.lower()}_{architecture}.{suffix}"
    cache = ROOT / ".cache/actionlint" / VERSION
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.exists():
        url = f"https://github.com/rhysd/actionlint/releases/download/v{VERSION}/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != checksum:
            raise ValueError("Downloaded actionlint checksum differs from the pinned value")
        archive.write_bytes(data)
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != checksum:
        raise ValueError("Cached actionlint archive failed verification")
    executable_name = "actionlint.exe" if system == "Windows" else "actionlint"
    if suffix == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            binary = bundle.read(executable_name)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as bundle:
            member = bundle.extractfile(executable_name)
            if member is None:
                raise ValueError("actionlint release is missing the executable")
            binary = member.read()
    executable = cache / executable_name
    executable.write_bytes(binary)
    executable.chmod(0o755)
    subprocess.run(
        [
            str(executable),
            "-config-file",
            ".github/actionlint.yaml",
            "-pyflakes=",
            *map(str, sorted((ROOT / ".github/workflows").glob("*.yml"))),
        ],
        cwd=ROOT,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


if __name__ == "__main__":
    main()
