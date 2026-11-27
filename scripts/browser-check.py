"""Run browser checks against an owned host and reclaim all owned processes."""

import argparse
import http.client
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-rtc", action="store_true", help="Explicitly skip RTC/camera checks")
    args = parser.parse_args()
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    data = ROOT / ".cache" / f"browser-tests-{port}"
    env = os.environ.copy()
    env["REED_BENCH_URL"] = f"http://127.0.0.1:{port}"
    env["REED_BENCH_SKIP_RTC"] = "1" if args.skip_rtc else "0"
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        parser.error("npm is required for browser verification")
    with (reports / "browser-host.log").open("w", encoding="utf-8") as log:
        host = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "reed_bench",
                "--port",
                str(port),
                "--data-dir",
                str(data),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if host.poll() is not None:
                    raise RuntimeError("Browser host exited; inspect reports/browser-host.log")
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                try:
                    connection.request("GET", "/api/bootstrap")
                    response = connection.getresponse()
                    response.read()
                    if response.status == 200:
                        break
                except OSError:
                    pass
                finally:
                    connection.close()
                time.sleep(0.1)
            else:
                raise RuntimeError("Browser host did not start within 30 seconds")
            subprocess.run(
                [npm, "--prefix", "web", "run", "test:browser"],
                cwd=ROOT,
                env=env,
                check=True,
                timeout=300,
            )
        finally:
            if host.poll() is None:
                owned = psutil.Process(host.pid)
                processes = owned.children(recursive=True) + [owned]
                for process in reversed(processes):
                    try:
                        process.terminate()
                    except psutil.NoSuchProcess:
                        pass
                _, remaining = psutil.wait_procs(processes, timeout=10)
                for process in remaining:
                    try:
                        process.kill()
                    except psutil.NoSuchProcess:
                        pass
            host.wait(timeout=10)


if __name__ == "__main__":
    main()
