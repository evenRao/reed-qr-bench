"""Verify and replay recorded inputs without trusting archive paths or regenerating QR codes."""

import hashlib
import io
import json
import zipfile


def read_evidence(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(i.file_size for i in archive.infolist()) > 256 * 1024 * 1024:
            raise ValueError("Expanded evidence exceeds 256 MiB")
        manifest = json.loads(archive.read("SHA256.json"))
        for name, digest in manifest.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Evidence checksum mismatch")
        run = json.loads(archive.read("report.json"))
        cases = []
        for attempt in run["attempts"]:
            if attempt["input_file"] not in manifest:
                raise ValueError("Input is missing from the evidence checksum manifest")
            image = archive.read(attempt["input_file"])
            if hashlib.sha256(image).hexdigest() != attempt["input_sha256"]:
                raise ValueError("Attempt input checksum mismatch")
            cases.append(
                {
                    k: attempt[k]
                    for k in (
                        "implementation",
                        "model",
                        "scenario",
                        "source",
                        "streams",
                        "repetition",
                        "fixture_id",
                        "input_sha256",
                        "input_file",
                        "mime",
                        "expected",
                        "expected_positive",
                        "temperature",
                    )
                }
            )
            cases[-1]["data"] = image
            cases[-1]["telemetry_profile"] = attempt.get("telemetry_profile", "full")
            cases[-1]["load_kind"] = attempt.get("load_kind", "streams")
            cases[-1]["workers"] = attempt.get("workers", 1)
        recording = archive.read("recording.video") if "recording.video" in manifest else None
        return run, cases, recording
