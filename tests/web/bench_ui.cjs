const assert = require("node:assert/strict");
const { mkdirSync } = require("node:fs");
const { createRequire } = require("node:module");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const root = path.resolve(__dirname, "../..");
const webRequire = createRequire(path.join(root, "web/package.json"));
const { chromium } = webRequire("playwright-core");
const outputDir = path.join(root, ".cache/browser-qa");
const fixturePath = path.join(outputDir, "public-corpus-example.png");
const runRtc = process.env.REED_BENCH_SKIP_RTC !== "1";
mkdirSync(outputDir, { recursive: true });
execFileSync(path.join(root, ".venv/Scripts/python.exe"), [
  "-c",
  "import pathlib,sys,zipfile;pathlib.Path(sys.argv[2]).write_bytes(zipfile.ZipFile(sys.argv[1]).read('images/10.png'))",
  path.join(root, "assets/corpora/zxing-subset.zip"),
  fixturePath,
]);
(async () => {
  const browser = await chromium.launch({
    executablePath:
      process.env.REED_QR_BROWSER ||
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    headless: true,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1100 },
  });
  async function launch(name = "Start test") {
    const pending = page.waitForResponse(
      (r) => r.url().endsWith("/api/runs") && r.request().method() === "POST",
    );
    await page.getByRole("button", { name, exact: true }).click();
    const response = await pending;
    const value = await response.json();
    assert.equal(response.status(), 202, JSON.stringify(value));
    return value.id;
  }
  async function waitStatus(id, predicate, timeout = 60000) {
    const deadline = Date.now() + timeout;
    let state;
    while (Date.now() < deadline) {
      const response = await page.request.get(origin + "/api/status");
      state = await response.json();
      if (state.run?.id === id && predicate(state)) return state;
      if (
        state.run?.id === id &&
        ["error", "cancelled", "interrupted"].includes(state.run.status)
      ) {
        throw new Error("Run failed: " + JSON.stringify(state.run));
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(
      "Run did not reach expected state: " + JSON.stringify(state),
    );
  }
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const origin = process.env.REED_BENCH_URL || "http://127.0.0.1:8765";
  try {
    await page.goto(origin);
    await page
      .getByRole("button", { name: "Start test", exact: true })
      .waitFor();
    await page.screenshot({
      path: path.join(outputDir, "bench-v2-desktop.png"),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "Image / chat", exact: true })
      .click();
    const started1 = await launch();
    await waitStatus(started1, (s) => s.run?.status === "completed");
    await page.getByText("rq-", { exact: false }).first().waitFor();
    await page
      .getByRole("button", { name: "Encode text", exact: true })
      .click();
    await page
      .getByLabel("Exact payload")
      .fill("Browser verified REED QR round trip");
    const started2 = await launch();
    await waitStatus(
      started2,
      (s) => s.run?.status === "completed" && s.live?.source === "encode",
    );
    await page
      .getByAltText("Generated QR code, independently verified")
      .waitFor();
    await page.getByRole("link", { name: "Experiments", exact: true }).click();
    const experimentRun = await launch("Run experiment");
    await waitStatus(
      experimentRun,
      (s) => s.run?.status === "completed" && s.run.progress.completed === 12,
    );
    await page
      .getByRole("button", { name: "Open results", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Comparison by condition" })
      .waitFor();
    await page
      .getByRole("link", { name: "Evidence ZIP", exact: true })
      .waitFor();
    assert.equal(
      await page
        .getByRole("link", { name: "Evidence ZIP", exact: true })
        .count(),
      1,
    );
    await page
      .getByRole("button", { name: "Inspect", exact: true })
      .first()
      .click();
    await page.getByRole("dialog").waitFor();
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await page.screenshot({
      path: path.join(outputDir, "bench-v2-reports.png"),
      fullPage: true,
    });
    await page.getByRole("link", { name: "Test bench", exact: true }).click();
    if (runRtc) {
      await page
        .getByRole("button", { name: "LiveKit fixture", exact: true })
        .click();
      await page.getByLabel("Duration (seconds)", { exact: true }).fill("4");
      const started3 = await launch();
      await waitStatus(
        started3,
        (s) =>
          s.live?.source === "video" &&
          (s.live.metrics?.counts?.processed || 0) > 5,
      );
      await page.waitForFunction(
        () =>
          document.querySelector(".metrics-grid .eyebrow")?.textContent ===
            "Received video" &&
          Number(
            document
              .querySelectorAll(".metric-value")[1]
              ?.textContent.replace(/[^\d.]/g, ""),
          ) > 0,
      );
      await page.waitForFunction(() => {
        const dt = Array.from(document.querySelectorAll("dt")).find(
          (n) => n.textContent === "Received / processed",
        );
        return Number(dt?.nextElementSibling?.textContent?.split("/")[1]) > 5;
      });
      await page.screenshot({
        path: path.join(outputDir, "bench-v2-live-metrics.png"),
        fullPage: true,
      });
      await waitStatus(started3, (s) => s.run?.status === "completed");
      await page
        .getByRole("button", { name: "Start test", exact: true })
        .waitFor();
      await page
        .getByRole("button", { name: "LiveKit camera", exact: true })
        .click();
      await page.getByLabel("Duration (seconds)", { exact: true }).fill("4");
      const started4 = await launch();
      await waitStatus(
        started4,
        (s) =>
          s.live?.source === "camera" &&
          (s.live.metrics?.counts?.processed || 0) > 4,
      );
      await page
        .getByText("Publishing through LiveKit", { exact: true })
        .waitFor();
      await page.waitForFunction(() => {
        const dt = Array.from(document.querySelectorAll("dt")).find(
          (n) => n.textContent === "Received / processed",
        );
        return Number(dt?.nextElementSibling?.textContent?.split("/")[1]) > 5;
      });
      await page.screenshot({
        path: path.join(outputDir, "bench-v2-camera.png"),
        fullPage: true,
      });
      const stopping = page.waitForResponse((r) =>
        r.url().endsWith("/api/stop"),
      );
      await page
        .getByRole("button", { name: "Stop test", exact: true })
        .click();
      await (await stopping).finished();
      await page
        .getByRole("button", { name: "Start test", exact: true })
        .waitFor();
    }
    await page
      .getByRole("button", { name: "Image / chat", exact: true })
      .click();
    await page
      .getByLabel("Implementation", { exact: true })
      .selectOption("plugin");
    await page
      .getByLabel("Upload image or batch", { exact: true })
      .setInputFiles(fixturePath);
    await page.getByText(/public-corpus-example.png/).waitFor();
    const started5 = await launch();
    const completedImage = await waitStatus(
      started5,
      (s) =>
        s.live?.source === "image" &&
        s.run?.status === "completed" &&
        Boolean(s.live?.result),
    );
    const actual = completedImage.live.result;
    assert.ok(actual.detections.length > 0);
    if (actual.detections[0].payload_status === "unsupported")
      await page
        .getByText("QR found · unsupported payload", { exact: true })
        .waitFor();
    else assert.ok(actual.payloads.length > 0);
    await page.screenshot({
      path: path.join(outputDir, "bench-v2-fidelity.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: path.join(outputDir, "bench-v2-mobile.png"),
      fullPage: true,
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    await page
      .getByRole("button", { name: "Integrations", exact: true })
      .click();
    await page.getByRole("dialog").waitFor();
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("dialog").count(), 0);
    console.log(
      "Verified image decode, encoding, controlled experiment, report details/export, modal keyboard handling, and mobile layout.",
    );
    console.log(
      runRtc
        ? "Verified live RTC metrics and synthetic-device camera publishing."
        : "Skipped local RTC and camera checks (REED_BENCH_SKIP_RTC=1).",
    );
  } catch (e) {
    await page.screenshot({
      path: path.join(outputDir, "bench-v2-failure.png"),
      fullPage: true,
    });
    if (await page.locator("main").count())
      console.error((await page.locator("main").innerText()).slice(-8000));
    throw e;
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
