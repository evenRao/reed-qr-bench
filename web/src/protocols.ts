import type { Config } from "./types";
export const initial: Config = {
  suite: "smoke",
  source: "image",
  implementations: ["plugin", "sdk", "opencv"],
  scenarios: ["clean", "no_code"],
  repetitions: 2,
  seed: 42,
  warmups: 1,
  operations: 1,
  duration_s: 5,
  input_hz: 15,
  scan_hz: 10,
  deadline_s: 90,
  max_queue_age_ms: 1000,
  loads: [1],
  replace_track: false,
  split: "development",
  allow_cloud: false,
  models: { openai: "", gemini: "" },
  forced_tool: false,
  targets: {},
  image_ids: [],
  expected: null,
  text: "REED QR / exact round trip",
  correction: "M",
  scale: 8,
};
export const sources = [
  { id: "video", label: "LiveKit fixture" },
  { id: "camera", label: "LiveKit camera" },
  { id: "image", label: "Image / chat" },
  { id: "recording", label: "Video recording" },
  { id: "encode", label: "Encode text" },
];
export function suiteDescription(suite: string) {
  return (
    (
      {
        smoke:
          "A quick correctness and instrumentation check. Useful for setup; insufficient for performance claims.",
        calibration:
          "Matched minimal/full tracing on the same images. Both profiles retain resource sampling. Review measured overhead and its uncertainty before making performance claims.",
        performance:
          "Independent image attempts with warmup separated from measurement. Direct SDK and plugin share the same decoder.",
        robustness:
          "Seeded blur, perspective, glare, compression, multiple codes, small codes, and no-code controls.",
        video:
          "Actual publisher → LiveKit server → RTC receiver → QR operation. Includes a scanning-disabled transport control.",
        recovery:
          "Replaces a published track halfway through the observation. Late results are rejected and generation two must decode.",
        load: "Runs 1, 2, 4, and 8 concurrent video streams in one room. Every attempt records actual received and processed rates.",
        endurance:
          "Sustained decoding with sampled memory and raw per-frame events. Increase duration and repetitions for soak evidence.",
        ai: "Same images and model IDs: vision alone, hosted code tools, and the registered REED QR capability. Fresh contexts; no oracle leakage.",
        encoding:
          "Public SDK encoding with exact-payload round trips verified by OpenCV. Verification time is excluded from encoding latency.",
      } as Record<string, string>
    )[suite] || ""
  );
}
