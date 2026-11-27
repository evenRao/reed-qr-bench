"""SQLite run index plus immutable input, trace, and report artifacts."""

import csv
import hashlib
import html
import io
import json
import os
import secrets
import sqlite3
import time
import zipfile
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.owner = (self.root / ".owner.lock").open("a+b")
        if self.owner.seek(0, 2) == 0:
            self.owner.write(b"0")
            self.owner.flush()
        self.owner.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.owner.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.owner.close()
            raise ValueError(
                "Evidence directory is already in use by another Bench host; "
                "choose a different --data-dir"
            ) from error
        self.db = sqlite3.connect(self.root / "index.sqlite3")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS runs "
            "(id TEXT PRIMARY KEY, created TEXT, status TEXT, report TEXT)"
        )
        self.db.commit()
        self.exports = []

    def directory(self, identifier):
        if (
            not isinstance(identifier, str)
            or len(identifier) != 24
            or any(c not in "0123456789abcdef" for c in identifier)
        ):
            raise ValueError("Unknown run")
        directory = self.root / identifier
        directory.mkdir(exist_ok=True)
        return directory

    def save(self, run):
        text = json.dumps(run, ensure_ascii=True, indent=2)
        directory = self.directory(run["id"])
        pending = directory / "report.pending"
        pending.write_text(text, encoding="utf-8")
        # Windows readers can briefly deny replacement of an otherwise writable report.
        for attempt in range(6):
            try:
                pending.replace(directory / "report.json")
                break
            except PermissionError:
                if os.name != "nt" or attempt == 5:
                    raise
                time.sleep(0.01 * 2**attempt)
        self.db.execute(
            "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?)",
            (run["id"], run["created"], run["status"], text),
        )
        self.db.commit()

    def get(self, identifier):
        row = self.db.execute("SELECT report FROM runs WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise ValueError("Unknown run")
        return json.loads(row[0])

    def list(self):
        return [
            {
                "id": r[0],
                "created": r[1],
                "status": r[2],
                "source": json.loads(r[3])["config"]["source"],
                "suite": json.loads(r[3])["config"]["suite"],
            }
            for r in self.db.execute(
                "SELECT id,created,status,report FROM runs ORDER BY created DESC LIMIT 100"
            )
        ]

    def recover(self):
        for row in self.db.execute(
            "SELECT report FROM runs WHERE status IN ('running','queued','cancelling','finalizing')"
        ).fetchall():
            run = json.loads(row[0])
            run["status"] = "interrupted"
            run["error"] = "The host ended before this run reached a terminal state"
            self.save(run)

    def evidence_zip(self, identifier):
        return self.evidence_path(identifier).read_bytes()

    def evidence_path(self, identifier):
        self.get(identifier)
        directory = self.directory(identifier)
        export_root = self.root / "exports"
        export_root.mkdir(exist_ok=True)
        target = export_root / (secrets.token_hex(16) + ".zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            manifest = {}
            for path in directory.rglob("*"):
                if (
                    not path.is_file()
                    or path.suffix == ".pending"
                    or path.name.endswith(".stderr.log")
                ):
                    continue
                relative = path.relative_to(directory).as_posix()
                bundle.write(path, relative)
                with path.open("rb") as source:
                    manifest[relative] = hashlib.file_digest(source, "sha256").hexdigest()
            bundle.writestr("SHA256.json", json.dumps(manifest, indent=2))
        self.exports.append(target)
        while len(self.exports) > 10:
            previous = self.exports.pop(0)
            try:
                previous.unlink(missing_ok=True)
            except PermissionError:
                self.exports.append(previous)
                break
        return target

    def close(self):
        self.db.close()
        self.owner.close()
        for path in self.exports:
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass


def csv_report(run):
    output = io.StringIO(newline="")
    fields = [
        "id",
        "implementation",
        "model",
        "scenario",
        "source",
        "streams",
        "temperature",
        "status",
        "score",
        "elapsed_ms",
        "first_correct_ms",
        "startup_ms",
        "cpu_peak",
        "rss_peak_mb",
        "error",
        "resolved_model",
        "telemetry_profile",
        "load_kind",
        "workers",
        "first_capture_to_correct_ms",
        "recovery_first_correct_ms",
        "first_token_ms",
        "tool_requested_ms",
        "tool_result_ms",
        "complete_answer_ms",
        "provider_cleanup_ms",
    ]
    metric_fields = [
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "received_rate",
        "processed_rate",
        "queue_p95_ms",
        "latency_samples",
        "p95_drift_ms",
    ]
    counter_fields = [
        "received",
        "processed",
        "sampled_out",
        "replaced",
        "stale",
        "late_rejected",
        "expired_results",
        "errors",
    ]
    fields += metric_fields + ["count_" + k for k in counter_fields]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for item in run["attempts"]:
        row = {**item}
        row.update({k: item.get("metrics", {}).get(k) for k in metric_fields})
        row.update(
            {
                "count_" + k: item.get("metrics", {}).get("counts", {}).get(k, 0)
                for k in counter_fields
            }
        )
        # Spreadsheet formula injection must not execute when a CSV is opened.
        for k, v in row.items():
            if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")):
                row[k] = "'" + v
        writer.writerow(row)
    return output.getvalue()


def html_report(run):
    escaped = html.escape(json.dumps(run, ensure_ascii=True, indent=2))

    def cell(value):
        return html.escape("—" if value is None else str(value))

    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{cell(r.get(k))}</td>"
            for k in (
                "implementation",
                "scenario",
                "temperature",
                "correct",
                "attempts",
                "frame_p95_ms",
                "processed_rate",
                "verdict",
                "first_result_p50_ms",
                "outcomes",
                "consistent_inputs",
                "unique_inputs",
            )
        )
        + "</tr>"
        for r in run.get("summary", [])
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>REED QR Bench report</title><style>
body{{background:#0f172a;color:#f1f5f9;font:16px/1.6 system-ui;margin:40px;max-width:1400px}}
table{{border-collapse:collapse;width:100%}}
td,th{{padding:12px;text-align:left;border-bottom:1px solid #475569}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.table{{overflow:auto}}</style>
<h1>REED QR Bench</h1><p>Run {run["id"]} · {run["status"]} · {run["created"]}</p>
<p>QR latency excludes worker startup and warmup. CPU and memory refer to the isolated worker.
Cloud timings are client-observed; provider internals and invoice totals are unknown.
Small samples are exploratory. No preset targets means unrated.</p>
<div class="table"><table><thead><tr><th>Implementation</th><th>Scenario</th>
<th>Temperature</th><th>Correct</th><th>Attempts</th><th>Median attempt p95 (ms)</th>
<th>Median rate (/s)</th><th>Verdict</th><th>First correct payload p50 (ms)</th>
<th>Outcomes</th><th>Inputs passing every repeat</th><th>Unique inputs</th>
</tr></thead><tbody>{rows}</tbody></table></div>
<details><summary>Full configuration and evidence</summary><pre>{escaped}</pre></details></html>"""
