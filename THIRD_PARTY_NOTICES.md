# Third-party dependency notices

REED QR Bench and its SDK dependency use third-party libraries under their
respective licenses. The locked manifests record dependency versions. This
inventory does not replace the required license texts or a transitive license audit.

The SDK's October 26, 2026 inventory and its known gaps are documented in
[LICENSE_AUDIT.md](https://github.com/evenRao/reed-qr/blob/main/LICENSE_AUDIT.md), with per-package/per-file tables under
the plugin's `docs/licenses/`. That diagnostic inventory does not itself complete the release
license/attribution bundle or resolve every native-binary licensing question.

- rxing 0.9.3: Apache-2.0; a Rust port of ZXing with upstream ZXing notices.
- REED QR SDK 0.1.0: MIT; native dependency notices are included in the SDK distribution.
- image 0.25.8: MIT OR Apache-2.0.
- PyO3 0.30.1: MIT OR Apache-2.0.
- thiserror: MIT OR Apache-2.0.
- qrcode 0.14.1: MIT OR Apache-2.0; development/test encoder only.
- segno 1.6.6: BSD-3-Clause; independent benchmark fixture encoder.
- LiveKit RTC 1.1.21: Apache-2.0; optional Python integration.
- LiveKit server 1.13.10 and browser client: Apache-2.0; the server is
  downloaded separately and the browser client is included in the web build.

Before publication, generate and review the complete transitive inventory and
include all required license texts and notices in release artifacts. This list
does not imply that the transitive review has already been completed.

## Benchmark application

- The public QR black-box subset is copied from ZXing `zxing-3.5.3`,
  `core/src/test/resources/blackbox/qrcode-1`, with unmodified image/label bytes.
  `assets/corpora/zxing-subset.zip` contains its manifest, upstream Apache-2.0
  LICENSE, and NOTICE. Source:
  https://github.com/zxing/zxing/tree/zxing-3.5.3/core/src/test/resources/blackbox/qrcode-1
- The browser application uses React/React DOM, LiveKit client, and
  the Vite/TypeScript toolchain. Exact application versions are locked in
  `web/package-lock.json`; installed license texts remain in their package metadata.
- Playwright Core is used for browser testing under Apache-2.0.
