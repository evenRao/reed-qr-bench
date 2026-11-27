import type React from "react";
import type { Series, Detection } from "./types";
import { number } from "./display";
export function Icon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    bench: (
      <>
        <path d="M3 17h18M5 17V9m7 8V4m7 13v-6" />
      </>
    ),
    experiments: (
      <>
        <path d="M9 3h6m-5 0v7L4 20h16l-6-10V3M7 15h10" />
      </>
    ),
    reports: (
      <>
        <path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7m-7 4h7" />
      </>
    ),
    settings: (
      <>
        <path d="M4 7h16M4 17h16" />
        <circle cx="9" cy="7" r="3" />
        <circle cx="15" cy="17" r="3" />
      </>
    ),
    play: <path d="m8 5 11 7-11 7z" />,
    stop: <rect x="6" y="6" width="12" height="12" />,
    qr: (
      <>
        <path d="M3 3h6v6H3zM15 3h6v6h-6zM3 15h6v6H3zM15 15h3v3h3v3h-6z" />
      </>
    ),
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name] || paths.bench}
    </svg>
  );
}

export function Payloads({
  payloads,
  detections,
  processed,
}: {
  payloads?: string[];
  detections?: Detection[];
  processed: boolean;
}) {
  if (payloads?.length)
    return (
      <>
        {payloads.map((text, i) => (
          <code key={i}>{text || "(empty text payload)"}</code>
        ))}
      </>
    );
  if (detections?.length)
    return (
      <>
        {detections.map((d, i) => (
          <div key={i}>
            {d.text != null ? (
              <code>{d.text || "(empty text payload)"}</code>
            ) : d.bytes_hex ? (
              <>
                <strong>Binary payload · exact bytes</strong>
                <code>{d.bytes_hex}</code>
              </>
            ) : (
              <>
                <strong>QR found · unsupported payload</strong>
                <p className="note">
                  The SDK did not return complete text or complete bytes.
                  Partial byte segments are retained in the evidence and are not
                  a complete payload.
                </p>
              </>
            )}
          </div>
        ))}
      </>
    );
  return (
    <span className="muted">
      {processed
        ? "No QR payload returned. Processing measurements are still recorded."
        : "Waiting for a measured operation."}
    </span>
  );
}

export function Metric({
  label,
  value,
  unit,
  note,
  accent,
}: {
  label: string;
  value: number | null | undefined;
  unit?: string;
  note: string;
  accent?: string;
}) {
  return (
    <article className={`metric ${accent || ""}`}>
      <div className="eyebrow">{label}</div>
      <div className="metric-value">
        {number(value)}
        <span>{unit}</span>
      </div>
      <p>{note}</p>
    </article>
  );
}
export function Chart({
  title,
  unit,
  series,
  lines,
}: {
  title: string;
  unit: string;
  series: Series[];
  lines: {
    key: "received" | "processed" | "p95" | "rss_mb";
    label: string;
    color: string;
  }[];
}) {
  const values = series.flatMap((s) =>
    lines.map((l) => s[l.key]).filter((n): n is number => n != null),
  );
  const max = Math.max(...values, 1) * 1.1,
    begin = series[0]?.t || 0,
    end = Math.max(series.at(-1)?.t || 0, begin + 1);
  return (
    <section className="panel chart">
      <div className="panel-heading">
        <h2>{title}</h2>
        <span className="muted">{unit}</span>
      </div>
      <div className="legend">
        {lines.map((l) => (
          <span key={l.key}>
            <i style={{ background: l.color }} />
            {l.label}
          </span>
        ))}
      </div>
      {values.length ? (
        <svg
          viewBox="0 0 620 180"
          role="img"
          aria-label={`${title}, ${series.length} measured samples, latest ${lines.map((l) => `${l.label} ${number(series.at(-1)?.[l.key])} ${unit}`).join(", ")}`}
        >
          {[0, 0.5, 1].map((p) => (
            <g key={p}>
              <line
                x1="48"
                y1={150 - p * 130}
                x2="606"
                y2={150 - p * 130}
                className="gridline"
              />
              <text x="2" y={155 - p * 130}>
                {number(max * p, 0)}
              </text>
            </g>
          ))}
          {lines.map((l) => (
            <polyline
              key={l.key}
              fill="none"
              stroke={l.color}
              strokeWidth="2"
              points={series
                .filter((s) => s[l.key] != null)
                .map(
                  (s) =>
                    `${48 + ((s.t - begin) / (end - begin)) * 558},${150 - ((s[l.key] || 0) / max) * 130}`,
                )
                .join(" ")}
            />
          ))}
          <text x="48" y="177">
            {number(begin, 0)} s
          </text>
          <text x="562" y="177">
            {number(end, 0)} s
          </text>
        </svg>
      ) : (
        <div className="empty-chart">
          Start a test to see measured samples.
          <small>Refreshes every 250 ms, including frames without a QR.</small>
        </div>
      )}
    </section>
  );
}
