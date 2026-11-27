import argparse
import asyncio
import json
from pathlib import Path

from aiohttp import web

from .replay import read_evidence
from .server import ROOT, SUPERVISOR, create_app


def main():
    parser = argparse.ArgumentParser(description="REED QR Bench")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Separate evidence directory for another host or headless verification",
    )
    parser.add_argument("--run", type=Path, help="Execute a JSON protocol without opening the UI")
    parser.add_argument(
        "--replay", type=Path, help="Verify and replay a previously exported evidence ZIP"
    )
    parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="Explicitly allow paid requests when replaying cloud evidence",
    )
    args = parser.parse_args()
    if args.run or args.replay:

        async def headless():
            app = create_app(data_dir=args.data_dir)
            supervisor = app[SUPERVISOR]
            try:
                if args.replay:
                    previous, cases, recording = read_evidence(args.replay.read_bytes())
                    config = previous["config"]
                    if any(":" in m for m in config["implementations"]) and not args.allow_cloud:
                        raise ValueError("Replaying cloud evidence requires --allow-cloud")
                    config.update(corpus_id=None, image_ids=[])
                    supervisor.replay_cases = cases
                    if recording:
                        path = ROOT / ".cache/bench-v2/replay.video"
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(recording)
                        supervisor.recordings["replay"] = path
                        config["recording_id"] = "replay"
                    run = await supervisor.start(config)
                    run["replayed_from"] = previous["id"]
                else:
                    run = await supervisor.start(json.loads(args.run.read_text("utf-8")))
                await supervisor.task
                print(
                    json.dumps(
                        {"id": run["id"], "status": run["status"], "summary": run["summary"]},
                        indent=2,
                    )
                )
            finally:
                await supervisor.close()
                supervisor.store.close()

        asyncio.run(headless())
    else:
        web.run_app(
            create_app(ROOT, data_dir=args.data_dir),
            host="127.0.0.1",
            port=args.port,
            print=lambda message: print(message, flush=True),
        )


if __name__ == "__main__":
    main()
