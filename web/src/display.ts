export const names: Record<string, string> = {
  plugin: "REED QR plugin",
  sdk: "Direct REED SDK",
  opencv: "OpenCV",
  off: "Scanning disabled",
  "openai:vision": "OpenAI · vision",
  "openai:code": "OpenAI · code tools",
  "openai:reed": "OpenAI + REED QR",
  "gemini:vision": "Gemini · vision",
  "gemini:code": "Gemini · code tools",
  "gemini:reed": "Gemini + REED QR",
};
export const number = (value: number | null | undefined, digits = 1) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString(undefined, {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
