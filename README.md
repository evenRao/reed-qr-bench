# REED QR Bench

A local application for evaluating QR decoding in application and AI workflows.
The interface contains **Test bench**, **Experiments**, and **Reports**.
The decoder is the public REED QR SDK. This repository supplies
the host, installable tool interface, instrumentation, and independent evaluator.

## Start

Requires Windows, Node.js 22.12 or later, and uv. The SDK is installed from PyPI
at the version pinned in `uv.lock`; a separate SDK checkout is unnecessary.
The Python version is pinned in `.python-version`; uv prepares the environment.

```powershell
.\scripts\start-benchmark.ps1
```

Open **http://127.0.0.1:8765**. If that port is occupied, add `-Port 8766`.
On a new machine, add `-SetupLiveKit` to install the pinned local LiveKit service.
No camera, microphone, API request, or cloud voice session starts automatically.
Stop the host with Ctrl+C.

Published application ZIPs include the built UI. From an extracted release, run
`.\scripts\start-benchmark.ps1 -UseBuiltUI -SetupLiveKit`; Node.js is only needed
when building the browser source.

## Use the tool

- **Test bench:** choose a LiveKit fixture, camera, image/batch, recording, or
  encoding. See input/processing rates, p50/p95 latency, CPU, memory, queue counters,
  result, and charts during a test. No-code frames still produce measurements.
  Unlabelled uploads and arbitrary camera scenes are unscored.
- **Experiments:** run smoke, SDK performance, robustness, LiveKit pipeline,
  recovery, stream/room load, endurance, AI image, encoding, or observer-overhead
  protocols. Set targets first. Use the pinned public ZXing subset or import a
  labelled corpus with provenance and development/held-out assignments.
- **Reports:** inspect attempts and raw events, compare matching protocols, review
  confidence intervals and failures, and export JSON, CSV, standalone HTML, or a
  checksum-verified evidence ZIP with the actual inputs.

**Scanning disabled** is a transport/frame-handling control. Direct SDK and plugin
share the same decoder, so that comparison measures wrapper overhead. OpenCV is an
independent decoder baseline. LiveKit is transport infrastructure, not a competing
QR decoder.

## AI and voice

Configure OpenAI/Gemini keys in **Integrations** for this host session, or in `.env`.
Choose exact model IDs available to your account. Uploaded-image experiments
compare vision, hosted code tools where supported, and the registered REED QR
function. Each attempt starts a fresh conversation. Enable paid cloud requests
explicitly to send the selected inputs to those APIs. Unsupported tools, quota
failures, timeouts, invalid answers, and unused QR tools stay visible.

For camera tests, optional **LiveKit voice control** requires LiveKit Cloud
credentials in `.env`, the voice extra, and microphone permission. The agent asks
the same instrumented worker for a result from an eligible frame received after
the request. QR latency, transcript-to-tool time, and agent tool round-trip time are
separate measurements. Stopping the test closes the owned agent and room.

API experiments do not measure consumer chat applications or their live-video features.

## Reproduce without the browser

```powershell
.\.venv\Scripts\python.exe -m reed_bench --data-dir .cache/headless-runs --run protocols/smoke.json
.\.venv\Scripts\python.exe -m reed_bench --data-dir .cache/replayed-runs --replay downloaded-evidence.zip
```

Cloud replay also requires `--allow-cloud`. Replay verifies checksums and reuses
stored inputs and evaluator labels. It repeats software configuration, not hardware
state or provider availability. Camera sessions need a live publisher and cannot
be reproduced from an image-only artifact.
Each data directory has one owning host or CLI process. Use a separate directory
for headless runs while the browser host is open.

## Embed the same capability

`packages/reed-qr-tools` is the installable, provider-neutral capability. Supply an
authorized image resolver, register `QRTools.declaration()`, route model calls to
`QRTools.invoke()`, and close the toolset. Video hosts can call `decode_frame()`
with source/generation metadata. The model and resolver never receive evaluator
answers. The benchmark imports this package instead of copying a QR engine.

See [architecture](docs/architecture.md), [methodology](docs/methodology.md),
[testing and known limits](docs/verification.md), and
[provider extensions](docs/provider-extensions.md).

## Interpret the evidence

This is an evaluation instrument, not a certification or a promise that REED QR
wins. Small samples are exploratory. CPU/RSS have explicit process scopes; short
operations and sampled peaks have measurement limits. Native payload bytes and
fidelity remain in raw evidence, while the supplied accuracy suites score text.
Earlier held-out public-corpus checks exposed SDK payload-support gaps. Reports
retain unsupported-payload failures; partial byte segments never become full text.
Repeat the corpus protocol for the installed SDK before drawing current conclusions.
See the verification record before making adoption or speed claims.
Observed native LiveKit shutdown warnings are recorded per attempt. Paid AI and
voice behavior needs validation with your account; mock tests do not establish
model performance. See methodology for exact boundaries.

## Development and local data

Run `uv sync --locked --extra voice` and `npm --prefix web ci` to install the
locked dependencies. Run `npm --prefix web run build` after browser changes.
See [testing](docs/verification.md) for backend, RTC, browser, and artifact checks.
See [releases and repository setup](docs/releases.md) for CI, dependency updates,
version changes, and the first production release.

Store credentials in the ignored `.env` file, using `.env.example` as a template.
Runs and uploads live under `.cache/bench-v2`; older data stays in its original
directory. Local data, environments, dependencies, and browser build output are
excluded by `.gitignore`. Export reports before deleting any saved run data.
