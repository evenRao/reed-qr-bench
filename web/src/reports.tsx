import type { Run, Summary, Config } from "./types";
import { names, number } from "./display";
export function SummaryTable({ rows }: { rows: Summary[] }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Comparison by condition</h2>
        <span className="muted">Independent attempts · 95% intervals</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Implementation</th>
              <th>Condition</th>
              <th>Exact correctness</th>
              <th>Processing rate</th>
              <th>Frame / operation p95</th>
              <th>First correct payload p50</th>
              <th>Acceptance</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>
                  {names[r.implementation]}
                  <small>{r.model || r.temperature}</small>
                  {r.implementation.endsWith(":reed") && (
                    <small>
                      QR tool used {r.qr_tool_invocations || 0}/{r.attempts}
                    </small>
                  )}
                  {r.implementation.endsWith(":code") && (
                    <small>
                      Code tool observed {r.code_tools_observed || 0}/
                      {r.attempts}
                    </small>
                  )}
                </td>
                <td>
                  {r.scenario}
                  <small>
                    {r.source} · {r.streams}{" "}
                    {r.load_kind === "rooms" ? "room(s)" : "stream(s)"} ·{" "}
                    {r.workers || 1} worker(s)
                    <br />
                    {r.telemetry_profile || "full"} telemetry
                  </small>
                </td>
                <td>
                  {r.scored ? `${r.correct} / ${r.scored}` : "Unscored"}
                  <small>
                    {r.accuracy_ci95
                      ? r.unique_inputs != null
                        ? `${r.consistent_inputs}/${r.unique_inputs} inputs passed every repeat · ${number(r.accuracy_ci95[0] * 100)}–${number(r.accuracy_ci95[1] * 100)}% CI`
                        : `Earlier execution CI: ${number(r.accuracy_ci95[0] * 100)}–${number(r.accuracy_ci95[1] * 100)}%`
                      : "No oracle"}
                  </small>
                  <small>
                    {Object.entries(r.outcomes)
                      .map(
                        ([name, count]) =>
                          `${name.replaceAll("_", " ")} ${count}`,
                      )
                      .join(" / ")}
                  </small>
                </td>
                <td>
                  {number(r.processed_rate)}{" "}
                  {["video", "recording", "camera"].includes(r.source)
                    ? "fps"
                    : r.source === "encode"
                      ? "codes/s"
                      : "images/s"}
                </td>
                <td>
                  {number(r.frame_p95_ms)} ms
                  <small>Median across attempts</small>
                </td>
                <td>
                  {number(r.first_result_p50_ms)} ms
                  <small>
                    {r.first_result_median_ci95
                      ? `${number(r.first_result_median_ci95[0])}–${number(r.first_result_median_ci95[1])} ms CI`
                      : r.first_result_p50_ms == null
                        ? "No scored positive payload timing"
                        : "Too few attempts for CI"}
                  </small>
                </td>
                <td>
                  <span
                    className={`badge ${r.verdict === "pass" ? "good" : ""}`}
                  >
                    {r.verdict}
                  </span>
                  <small>
                    {r.sample_warning || `${r.attempts} independent attempts`}
                  </small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
export function Comparison({
  current,
  baseline,
}: {
  current: Run;
  baseline: Run;
}) {
  const fields = Array.from(
    new Set([
      ...Object.keys(current.config || {}),
      ...Object.keys(baseline.config || {}),
    ]),
  ).filter(
    (k) => !["targets", "suite", "schema_version", "attempt_limit"].includes(k),
  );
  const mismatches = fields.filter(
    (k) =>
      JSON.stringify(current.config?.[k as keyof Config]) !==
      JSON.stringify(baseline.config?.[k as keyof Config]),
  );
  const signature = (run: Run) =>
    JSON.stringify(
      (run.attempts || [])
        .map((a) =>
          JSON.stringify([
            a.implementation,
            a.model,
            a.resolved_model,
            a.scenario,
            a.source,
            a.streams,
            a.temperature,
            a.input_sha256,
            a.recording_sha256,
            a.repetition,
            a.telemetry_profile,
          ]),
        )
        .sort(),
    );
  if (signature(current) !== signature(baseline))
    mismatches.push("actual inputs / reported models");
  return (
    <section className="panel">
      <h2>Run-to-run comparison</h2>
      {mismatches.length ? (
        <p className="error">
          Not comparable: protocol differs in {mismatches.join(", ")}. No
          regression verdict is assigned.
        </p>
      ) : (
        <>
          <p className="note">
            Matched workload and input signatures. These are point estimates,
            not a statistical regression verdict. Review environment
            fingerprints before attributing changes to the SDK. Positive deltas
            mean slower latency; negative deltas mean faster latency.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Condition</th>
                  <th>Previous p95</th>
                  <th>Current p95</th>
                  <th>Change</th>
                </tr>
              </thead>
              <tbody>
                {current.summary.map((r, i) => {
                  const old = baseline.summary.find((b) =>
                    [
                      "implementation",
                      "model",
                      "scenario",
                      "source",
                      "temperature",
                      "streams",
                      "workers",
                      "load_kind",
                      "telemetry_profile",
                    ].every(
                      (k) => r[k as keyof Summary] === b[k as keyof Summary],
                    ),
                  );
                  return (
                    <tr key={i}>
                      <td>
                        {names[r.implementation]} · {r.scenario} · {r.streams}{" "}
                        stream(s)
                      </td>
                      <td>{number(old?.frame_p95_ms)} ms</td>
                      <td>{number(r.frame_p95_ms)} ms</td>
                      <td>
                        {old?.frame_p95_ms && r.frame_p95_ms != null
                          ? `${number((r.frame_p95_ms / old.frame_p95_ms - 1) * 100)}%`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
