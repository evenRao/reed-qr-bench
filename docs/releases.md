# CI and releases

The delivery target is a Windows application ZIP and the provider-neutral tools
wheel/source distribution on GitHub Releases. The app serves its interface on
loopback. Python backend tests also run on Linux and macOS.

## Pipeline

`ci.yml` runs on pull requests, merge queues, updates to `main` and `release/**`,
manual dispatch, and tagged release verification. Its required `CI passed` job
checks all preceding results and fails when a prerequisite fails or is skipped.

| Gate | Coverage |
| --- | --- |
| Source quality | Version consistency, actionlint, Ruff, Python/browser formatting, TypeScript and production UI build |
| Backend matrix | Python 3.11–3.14 across Ubuntu 24.04/26.04, Windows 2025, macOS 15 Intel/Apple Silicon, and Xcode 27; 24 combinations |
| Integration | Windows 3.14 with the checksum-verified local LiveKit server, actual RTC workloads, Edge workflows, synthetic camera, and mobile layout |
| Dependency security | Locked runtime including voice, audited under every supported Python version; npm production/build dependency audit |
| Code security | CodeQL for Python, JavaScript/TypeScript, and Actions |
| Packaging | Built UI, tools wheel/sdist, license presence, checksummed ZIP, runtime requirements, two CycloneDX SBOMs, a clean wheel install, and a 12-attempt smoke run from the extracted application |

The SDK uses the pinned PyPI distribution; no sibling checkout or Rust compiler
is needed. Python 3.15 is excluded by the app's declared dependency range. The
local RTC launcher and application release remain Windows-specific. Passing
portable backend tests does not establish camera/RTC support on other platforms.

Actions use immutable commit pins. Jobs have read-only repository access except
CodeQL result uploads and the release publishing job. Pull requests receive no
provider or publication credentials. Cloud API/voice accuracy and pricing checks
require separate account validation; CI uses local workloads and controlled responses.

CodeQL results upload on branches and pull requests. Tag and merge-queue runs
analyze the source without uploading a second set of results.
CodeQL job success means analysis completed; enforce alert severity with the
repository's code-scanning protection rule as described below.

## Before the first production release

1. Upload the project, including `.github`, `VERSION`, both lockfiles, licenses,
   and `.env.example`. Keep `.env`, `.venv`, `.cache`, `node_modules`, `reports`, and
   local `dist` files out of the source upload.
2. Set the default branch to `main`, or update both branch filters in `ci.yml`.
   Allow the pinned GitHub/Astral actions. The workflows use GitHub-hosted runners;
   confirm the six selected images and available Actions minutes for the account.
3. Enable dependency graph, Dependabot alerts/security updates, secret scanning,
   and push protection where available. Enable CodeQL advanced setup for these
   workflows; do not enable a competing default CodeQL setup. Private repositories
   need a plan that permits CodeQL and artifact attestations for the chosen setup.
4. Run CI on the uploaded source. Protect `main` with required pull-request review,
   the `CI passed` status check, resolved conversations, and blocked force pushes.
   Configure a code-scanning rule requiring CodeQL results and blocking high/critical
   security alerts. Verify the exact status-check names after the first run.
5. Create the GitHub environment **`release` before pushing any release tag**.
   Require a reviewer, disable self-review where available, and restrict deployment
   to protected `v*` tags. Add a tag ruleset restricting tag creation/update/deletion
   to maintainers. The workflow references the environment; protection is configured
   in repository settings, not automatically by the YAML.
6. Review licenses/SBOMs, the completed CI reports, SDK compatibility, and the
   known measurement/RTC limits in [verification](verification.md). Run any required
   paid-provider, microphone, real-camera, or target-machine acceptance checks.
7. Create a matching version tag from the reviewed `main` revision using your
   normal release process. Let the release workflow create the GitHub Release.
   Inspect the uploaded checksums, attestations, installation smoke result, and
   generated notes before announcing it.

No long-lived publication secret is required: the publishing job uses its scoped
`GITHUB_TOKEN` and GitHub OIDC for provenance. Package registry publication or a
hosted deployment would require a separate destination and configuration.

## Version changes

`VERSION` is the authoritative stable semantic version. The app reads it for the
bootstrap API and benchmark environment evidence. The tools package shares the
same release number. Update all manifests and lockfile metadata together:

```powershell
python scripts/version.py --set 0.2.1
uv lock --check
python scripts/version.py --check
```

The helper updates the app/tools project metadata, tools runtime version, internal
tools dependency, npm manifests/lockfile, and uv package versions. CI rejects
drift. A release tag must be exactly `v` plus `VERSION`; mismatched tags fail
before the full release build.

Dependabot checks GitHub Actions, npm, and uv weekly. Patch/minor changes are
grouped; major upgrades remain separate. The internal tools package is versioned
by the version helper. Review every update through CI. uv, actionlint, and the
audit tool also have explicit version pins in workflow/scripts; maintain those
pins as part of tooling updates.

## Build and inspect locally

```powershell
uv sync --locked --extra voice
npm --prefix web ci
npm --prefix web run build
uv run --no-sync python scripts/version.py --check
uv run --no-sync python scripts/check-workflows.py
uv run --no-sync python scripts/build-release.py
uv run --no-sync python scripts/build-release.py --verify-directory dist
```

Use `--output .cache/release-check` for a separate empty build directory. The ZIP
contains the built UI and an allowlist of application inputs. Credentials,
development environments, caches, dependency directories, and repository metadata
are excluded. `release-manifest.json` records each bundled file's SHA-256.
`SHA256SUMS` covers every downloadable payload. GitHub provenance attestations
bind the released files to the workflow and source revision.

Consumers can extract the ZIP and run:

```powershell
.\scripts\start-benchmark.ps1 -UseBuiltUI -SetupLiveKit
```

This installs the locked runtime and local LiveKit server; the built UI needs no
Node.js installation. The first run requires network access. Keep a known-good
release ZIP and export important evidence before upgrades. To roll back, extract
that release into a separate directory and use its own environment; do not
overwrite evidence produced by a newer version.

References: [GitHub runner images](https://github.com/actions/runner-images),
[uv Dependabot support](https://docs.astral.sh/uv/guides/integration/dependabot/),
[secure Actions usage](https://docs.github.com/en/actions/reference/security/secure-use),
and [artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations).
