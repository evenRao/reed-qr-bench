"""Loopback control plane serving one instrumented React application."""

import hashlib
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web
from dotenv import load_dotenv

from . import __version__
from .adapters import provider_metadata, providers
from .config import AI_MODES, MODES, SUITES
from .corpus import read_corpus
from .fixtures import SCENARIOS
from .resources import Resources
from .store import Store, csv_report, html_report
from .supervisor import Supervisor
from .transport import LiveKitService
from .voice import VoiceHost

ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = web.AppKey("supervisor", Supervisor)


def create_app(root=ROOT, data_dir=None):
    root = Path(root)
    load_dotenv(root / ".env", override=False)
    store = Store(data_dir or root / ".cache/bench-v2/runs")
    store.recover()
    resources = Resources()
    service = LiveKitService(root)
    supervisor = Supervisor(root, store, resources, service)
    bundled = root / "assets/corpora/zxing-subset.zip"
    if bundled.exists():
        _, parsed = read_corpus(bundled.read_bytes(), resources)
        supervisor.corpora["zxing-subset"] = parsed
    token = secrets.token_urlsafe(32)
    supervisor.voice = VoiceHost(root, "", token)

    @web.middleware
    async def guard(request, handler):
        hostname = urlsplit("http://" + request.host).hostname
        if hostname not in ("localhost", "127.0.0.1"):
            raise web.HTTPForbidden(text="Open this tool on localhost")
        origin = request.headers.get("Origin")
        if origin and origin != f"{request.scheme}://{request.host}":
            raise web.HTTPForbidden(text="Use the local Bench interface")
        if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(
            request.headers.get("X-REED-Bench", ""), token
        ):
            raise web.HTTPForbidden(text="Refresh the local Bench page")
        try:
            response = await handler(request)
        except ValueError as error:
            response = web.json_response({"error": str(error)}, status=400)
        except web.HTTPException:
            raise
        except Exception as error:
            response = web.json_response(
                {"error": f"Request failed ({type(error).__name__})"}, status=500
            )
        cloud = urlsplit(os.getenv("LIVEKIT_URL", ""))
        cloud_origin = (
            f"wss://{cloud.netloc} https://{cloud.netloc}"
            if cloud.scheme == "wss"
            and cloud.hostname
            and not cloud.username
            and not cloud.password
            else ""
        )
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data: blob:; media-src 'self' blob:; "
                    f"connect-src 'self' ws://127.0.0.1:7880 {cloud_origin} "
                    "wss://*.livekit.cloud https://*.livekit.cloud; worker-src 'self' blob:; "
                    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                ),
            }
        )
        return response

    app = web.Application(client_max_size=70 * 1024 * 1024, middlewares=[guard])
    app[SUPERVISOR] = supervisor

    async def lifecycle(app):
        yield
        await supervisor.close()
        store.close()

    app.cleanup_ctx.append(lifecycle)

    async def bootstrap(request):
        return web.json_response(
            {
                "token": token,
                "version": __version__,
                "suites": SUITES,
                "scenarios": SCENARIOS,
                "implementations": MODES + AI_MODES,
                "voice_configured": supervisor.voice.configured(),
                "providers": {
                    p: v["configured"] for p, v in provider_metadata(supervisor.keys).items()
                },
                "provider_specs": provider_metadata(supervisor.keys),
                "corpora": [
                    {"id": k, "name": v["metadata"]["name"], "cases": len(v["items"])}
                    for k, v in supervisor.corpora.items()
                ],
                "livekit_installed": (root / ".cache/livekit/1.13.10/livekit-server.exe").exists(),
            }
        )

    async def status(request):
        run = supervisor.active
        return web.json_response(
            {
                "run": {
                    "id": run["id"],
                    "status": run["status"],
                    "progress": run["progress"],
                    "summary": run["summary"],
                    "config": run["config"],
                    "error": run.get("error"),
                }
                if run
                else None,
                "live": supervisor.live,
                "series": supervisor.series,
                "components": supervisor.components,
            }
        )

    async def start(request):
        supervisor.voice.host_url = f"{request.scheme}://{request.host}"
        run = await supervisor.start(await request.json())
        return web.json_response({"id": run["id"], "status": run["status"]}, status=202)

    async def stop(request):
        async with supervisor.admission:
            await supervisor.stop()
            await service.close()
        return web.json_response({"status": "stopped"})

    async def images(request):
        data = await request.read()
        resource = resources.add(data)
        return web.json_response(
            {
                "id": resource.id,
                "width": resource.width,
                "height": resource.height,
                "bytes": len(data),
            }
        )

    async def image(request):
        resource = resources.get(request.match_info["id"])
        return web.Response(body=resource.data, content_type=resource.mime)

    async def recording(request):
        data = await request.read()
        if not data or len(data) > 64 * 1024 * 1024:
            raise ValueError("Upload a recording no larger than 64 MiB")
        folder = root / ".cache/bench-v2/uploads"
        folder.mkdir(parents=True, exist_ok=True)
        identifier = secrets.token_hex(16)
        path = folder / (identifier + ".video")
        path.write_bytes(data)
        import cv2

        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise ValueError("This recording is not supported by the installed video reader")
            width, height = (
                capture.get(cv2.CAP_PROP_FRAME_WIDTH),
                capture.get(cv2.CAP_PROP_FRAME_HEIGHT),
            )
            if width * height > 16_000_000:
                raise ValueError("Recording frames exceed 16 megapixels")
            supervisor.recordings[identifier] = path
            return web.json_response(
                {
                    "id": identifier,
                    "width": width,
                    "height": height,
                    "frames": capture.get(cv2.CAP_PROP_FRAME_COUNT),
                    "original_fps": capture.get(cv2.CAP_PROP_FPS),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            capture.release()

    async def corpus(request):
        identifier, parsed = read_corpus(await request.read(), resources)
        supervisor.corpora[identifier] = parsed
        return web.json_response(
            {"id": identifier, "cases": len(parsed["items"]), "metadata": parsed["metadata"]}
        )

    async def settings(request):
        data = await request.json()
        for p in providers():
            if p in data:
                if not isinstance(data[p], str) or len(data[p]) > 512:
                    raise ValueError("Invalid API key")
                if data[p].strip():
                    supervisor.keys[p] = data[p].strip()
                else:
                    supervisor.keys.pop(p, None)
        return web.json_response({"status": "Keys held in host memory until shutdown"})

    async def history(request):
        return web.json_response(store.list())

    async def scan(request):
        return web.json_response(await supervisor.scan())

    async def corpus_example(request):
        return web.json_response(
            {
                "name": "My independently labelled QR corpus",
                "version": "1.0",
                "source": "Describe collection and labelling",
                "license": "Your distribution license",
                "real_world": True,
                "items": [
                    {
                        "file": "images/photo.png",
                        "split": "held_out",
                        "scenario": "camera_photo",
                        "expected": ["exact QR content"],
                        "sha256": "optional: SHA-256 of the image bytes",
                    },
                    {
                        "file": "images/negative.png",
                        "split": "development",
                        "scenario": "no_code",
                        "expected": [],
                    },
                ],
            },
            headers={"Content-Disposition": 'attachment; filename="manifest.json"'},
        )

    async def report(request):
        identifier = request.match_info["id"]
        run = store.get(identifier)
        format = request.query.get("format", "json")
        if format == "csv":
            return web.Response(
                text=csv_report(run),
                content_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{identifier}.csv"'},
            )
        if format == "html":
            return web.Response(
                text=html_report(run),
                content_type="text/html",
                headers={"Content-Disposition": f'attachment; filename="{identifier}.html"'},
            )
        if format == "zip":
            if run["status"] in ("queued", "running", "cancelling", "finalizing"):
                raise ValueError("Stop or finish the run before exporting a stable evidence ZIP")
            return web.FileResponse(
                path=store.evidence_path(identifier),
                headers={
                    "Content-Disposition": f'attachment; filename="{identifier}-evidence.zip"'
                },
            )
        return web.json_response(run)

    async def artifact(request):
        try:
            path = store.artifact_path(request.match_info["id"], request.match_info["path"])
        except ValueError as error:
            raise web.HTTPNotFound() from error
        return web.FileResponse(path)

    async def index(request):
        path = root / "web/dist/index.html"
        if not path.exists():
            return web.Response(text="Build the UI first: npm --prefix web run build", status=503)
        return web.FileResponse(path)

    app.add_routes(
        [
            web.get("/api/bootstrap", bootstrap),
            web.get("/api/status", status),
            web.post("/api/runs", start),
            web.post("/api/stop", stop),
            web.post("/api/images", images),
            web.get("/api/images/{id}", image),
            web.post("/api/recordings", recording),
            web.post("/api/corpora", corpus),
            web.post("/api/settings", settings),
            web.get("/api/runs", history),
            web.get("/api/corpus-example", corpus_example),
            web.post("/api/voice/scan", scan),
            web.get("/api/runs/{id}", report),
            web.get("/api/runs/{id}/artifact/{path:.*}", artifact),
            web.get("/", index),
        ]
    )
    if (root / "web/dist/assets").exists():
        app.router.add_static("/assets/", root / "web/dist/assets")
    return app
