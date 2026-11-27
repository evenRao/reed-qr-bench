# Testing and known limits

Application/plugin 0.2.0, measurement revision 4. Checks validate the benchmark
and its integration contracts; they do not establish provider performance.

## Run the checks

Install dependencies with `uv sync --locked --extra voice` and
`npm --prefix web ci`, then run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check reed_bench packages/reed-qr-tools tests scripts
.\.venv\Scripts\ruff.exe format --check reed_bench packages/reed-qr-tools tests scripts
npm --prefix web run build
npm --prefix web run format:check
```

For local RTC integration, install the pinned service with
`.\scripts\setup-livekit-demo.ps1`, then run:

```powershell
$env:REED_BENCH_RTC_TEST = '1'
try {
    .\.venv\Scripts\python.exe -m pytest tests/bench/test_livekit.py -q
} finally {
    Remove-Item Env:REED_BENCH_RTC_TEST
}
```

For browser coverage, build the UI and run a host with a separate evidence
directory in one terminal:

```powershell
.\.venv\Scripts\python.exe -m reed_bench --port 8766 --data-dir .cache/browser-test-runs
```

In another terminal, run:

```powershell
$env:REED_BENCH_URL = 'http://127.0.0.1:8766'
npm --prefix web run test:browser
```

The browser check uses installed Microsoft Edge with synthetic camera input.
Set `REED_QR_BROWSER` to override its executable path. Screenshots are written to
`.cache/browser-qa`. Test reports stay in the separate host's evidence directory.
If another LiveKit service owns port 7880, set `REED_BENCH_SKIP_RTC=1` to run the
other browser checks. This explicitly skips RTC metrics and camera publishing;
the default browser check includes both.

For release verification, run `python scripts/version.py --check`, build the UI,
then run `python scripts/build-release.py`. It creates `dist/` with the application
ZIP, tools wheel/source distribution, locked runtime requirements, Python/browser
SBOMs, and checksums. It checks bundle contents, versions, licenses, and hashes.
The output directory must be empty to prevent mixing release versions.

CI installs the hash-locked runtime requirements and tools wheel in a clean
environment, then runs `scripts/verify-installed-sdk.py` with that environment's
Python. The SDK must come from an installed distribution rather than editable source.
See [release instructions](releases.md) for the full process.

## Verification results

Verified November 25, 2026:

| Check | Observed result |
| --- | --- |
| Backend suite | 35 passed, 1 opt-in RTC test skipped |
| Windows report persistence | Temporary reader lock recovers; persistent lock preserves committed data and raises an error |
| Ruff and Python formatting | Passed |
| TypeScript and production Vite build | Passed; lazy LiveKit browser chunk has a size advisory |
| Browser formatting | Passed |
| Python lockfile consistency | Passed |
| Version update helper | Passed, including an isolated version bump checked by uv |
| Workflow validation | Passed with pinned actionlint |
| Dependency audits | No known npm vulnerabilities or Python 3.14 runtime vulnerabilities after dependency updates |
| Release artifacts | ZIP, wheel/sdist, licenses, SBOMs, and checksums verified; clean hash-locked install passed; extracted application completed 12 correct smoke attempts |
| Browser workflow | Passed: image decode, independent encoding check, 12-attempt experiment, report inspection/export links, keyboard modal handling, unsupported-payload display, and mobile overflow check |

Local RTC integration could not run because an existing LiveKit service occupied
port 7880. Browser RTC metrics and synthetic-camera checks were explicitly skipped.
The existing service was left running. The last full RTC check passed on
November 23; that result does not constitute a fresh RTC verification. The current
clean installation uses the published REED QR 0.1.0 SDK and reed-qr-tools 0.2.0 wheel.
GitHub-hosted matrix jobs, CodeQL uploads, attestations, and release publication
still need their first run after repository upload.

The RTC test executes 13 real attempts: plugin/direct SDK/OpenCV/scanning-disabled
over positive and no-code video with track replacement, four streams with two
workers, two independent rooms, publisher reconnect, pause/resume, and recording
playback. Supported positive fixtures decode exactly; negative cases, processing
counts, source coverage, recovery, and owned process shutdown are asserted.

Other tests cover exact case/whitespace/multiplicity, corpus integrity and splits,
evaluator isolation, native cancellation ownership, late/retired-frame rejection,
deadlines and partial evidence, exclusive data-directory ownership, origin/CSRF
checks, export and replay checksums, provider wire/tool rounds, and voice-tool
registration with a mocked inference session. Repeated inputs do not inflate the
number of distinct inputs in the consistency confidence interval.

## Independent corpus finding

The November 23 verification used six distinct held-out images from the pinned
public ZXing subset, three repeats each, with independently preserved exact labels.

| Implementation | Complete exact text / 18 attempts | Unsupported complete payload | Missed |
| --- | ---: | ---: | ---: |
| Installed REED QR plugin | 0 | 12 | 6 |
| Direct REED QR SDK | 0 | 12 | 6 |
| OpenCV | 12 | 0 | 6 |

This is a small exploratory corpus, not a population estimate. Four of the six
distinct inputs were consistently decoded by OpenCV; none were completely decoded
by the current REED SDK. Repeats remain attempts, not additional independent images.

The SDK returns detections with `payload_status=unsupported`, no complete text or
bytes, and explicitly partial byte segments on four of these images. Read-only
inspection of the SDK codec confirms that its current fidelity gate rejects full
payload reconstruction for certain mixed-mode/non-byte segment combinations.
Regenerating supported byte-mode fixtures with the same intended text succeeds;
that does not repair or replace the original corpus result.

The benchmark preserves these detections and partial segments, scores them as
`unsupported_payload`, and leaves first-correct latency unavailable. It does not
concatenate fragments, change labels, or count fast failures as speed wins. The
sibling SDK was not modified. This finding needs SDK investigation before an
adoption pitch can promise broad real-world text decoding.

Reproduce the comparison without occupying the browser host's data directory:

```powershell
.\.venv\Scripts\python.exe -m reed_bench --data-dir .cache/corpus-verification --run protocols/public-corpus.json
```

## Operational limits and untested integrations

- Actual local RTC runs still emit native LiveKit `unknown FFI handle` shutdown
  warnings despite public cleanup calls. The harness counts these warnings,
  records cleanup status, and reclaims the worker process. This is a known
  limitation, not a demonstrated warning-free native lifecycle.
- Paid OpenAI/Gemini calls and LiveKit Cloud voice were not executed. Provider
  protocol and tool tests use controlled responses; they cannot establish model
  accuracy, latency, pricing, or account compatibility.
- Browser camera verification uses a synthetic device. No personal camera,
  microphone, or consumer chat application was used for automated checks.
- Short operation CPU samples can read zero; 250 ms resource sampling can miss
  peaks. Five-second video rates and per-attempt image rates have different scopes.
- Field data collection, larger held-out corpora, long endurance runs, and target
  hardware measurements remain necessary before external performance claims.

