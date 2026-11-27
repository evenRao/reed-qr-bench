import type { Config } from "./types";
export function NumberField({
  label,
  value,
  min,
  max,
  onChange,
  disabled = false,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (n: number) => void;
  disabled?: boolean;
}) {
  return (
    <label>
      {label}
      <input
        type="number"
        disabled={disabled}
        min={min}
        max={max}
        step={min < 1 ? "any" : 1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}
export function CloudControls({
  config,
  setConfig,
  providers,
  disabled = false,
}: {
  config: Config;
  setConfig: (c: Config) => void;
  providers: Record<string, boolean>;
  disabled?: boolean;
}) {
  return (
    <fieldset className="cloud-controls" disabled={disabled}>
      <div className="form-grid">
        {Array.from(
          new Set(
            config.implementations
              .filter((i) => i.includes(":"))
              .map((i) => i.split(":")[0]),
          ),
        )
          .filter((p) => config.implementations.some((i) => i.startsWith(p)))
          .map((p) => (
            <label key={p}>
              {p === "openai" ? "OpenAI" : p === "gemini" ? "Gemini" : p} model
              ID · {providers[p] ? "key ready" : "key required"}
              <input
                value={config.models[p] || ""}
                onChange={(e) =>
                  setConfig({
                    ...config,
                    models: { ...config.models, [p]: e.target.value },
                  })
                }
                placeholder="Exact supported model ID"
              />
            </label>
          ))}
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={config.allow_cloud}
          onChange={(e) =>
            setConfig({ ...config, allow_cloud: e.target.checked })
          }
        />
        Allow paid cloud requests with these inputs
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={config.forced_tool}
          onChange={(e) =>
            setConfig({ ...config, forced_tool: e.target.checked })
          }
        />
        Require the first REED QR tool call (separate protocol)
      </label>
      <p className="note">
        Image comparisons only. Provider-hosted tools may be unsupported for a
        model. First output, tool execution, complete answer, and token usage
        are recorded separately. Billed totals are unknown.
      </p>
    </fieldset>
  );
}
