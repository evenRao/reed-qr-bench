"""Independent labels, verified image bytes, explicit provenance and frozen splits."""

import hashlib
import io
import json
import zipfile


def read_corpus(data, resources):
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("Corpus archive exceeds 64 MiB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ValueError("Upload a ZIP corpus with manifest.json") from error
    with archive:
        if sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
            raise ValueError("Expanded corpus exceeds 64 MiB")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, ValueError) as error:
            raise ValueError("Corpus requires manifest.json") from error
        items = manifest.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 200:
            raise ValueError("Corpus requires 1–200 labelled items")
        if not all(
            isinstance(manifest.get(k), str) and manifest[k].strip()
            for k in ("name", "version", "source", "license")
        ):
            raise ValueError("Corpus requires name, version, source, and license")
        prepared = []
        for item in items:
            if (
                not isinstance(item, dict)
                or item.get("split") not in ("development", "held_out")
                or not isinstance(item.get("expected"), list)
                or any(not isinstance(v, str) for v in item["expected"])
            ):
                raise ValueError("Each case needs a split and exact expected payloads")
            name = item.get("file", "")
            if (
                not isinstance(name, str)
                or name.startswith(("/", "\\"))
                or ".." in name.replace("\\", "/").split("/")
            ):
                raise ValueError("Invalid corpus filename")
            try:
                resource = resources.add(archive.read(name))
            except KeyError as error:
                raise ValueError("Corpus references a missing image") from error
            digest = hashlib.sha256(resource.data).hexdigest()
            if item.get("sha256") and item["sha256"] != digest:
                raise ValueError("Corpus checksum mismatch")
            prepared.append(
                {
                    "id": digest,
                    "scenario": str(item.get("scenario", "real_world"))[:80],
                    "split": item["split"],
                    "expected": item["expected"],
                    "data": resource.data,
                    "mime": resource.mime,
                }
            )
    identifier = hashlib.sha256(data).hexdigest()
    metadata = {k: manifest[k] for k in ("name", "version", "source", "license")}
    metadata.update(
        sha256=identifier, real_world=manifest.get("real_world") is True, split="manifest-assigned"
    )
    return identifier, {"metadata": metadata, "items": prepared, "archive": data}
