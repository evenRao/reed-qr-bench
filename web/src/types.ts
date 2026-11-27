export type Metrics = {
  elapsed_s?: number;
  received_rate?: number | null;
  processed_rate?: number | null;
  p50_ms?: number | null;
  p95_ms?: number | null;
  p99_ms?: number | null;
  first_result_ms?: number | null;
  queue_p95_ms?: number | null;
  latency_samples?: number;
  cpu_percent?: number;
  rss_mb?: number;
  counts?: Record<string, number>;
  scope?: string;
  latest?: { detections?: Detection[] };
};
export type Detection = {
  text?: string | null;
  bytes_hex?: string | null;
  payload_status?: string;
  byte_segments_hex?: string[];
};
export type Series = {
  t: number;
  received: number | null;
  processed: number | null;
  p95: number | null;
  rss_mb: number;
};
export type Summary = {
  implementation: string;
  model?: string;
  scenario: string;
  source: string;
  temperature: string;
  streams: number;
  load_kind?: string;
  workers?: number;
  telemetry_profile?: string;
  correct: number;
  scored: number;
  attempts: number;
  completed: number;
  verdict: string;
  processed_rate: number | null;
  frame_p95_ms: number | null;
  first_result_p50_ms: number | null;
  first_result_median_ci95?: number[] | null;
  attempt_duration_p50_ms: number | null;
  rss_peak_mb: number;
  sample_warning?: string;
  accuracy_ci95?: number[];
  unique_inputs?: number;
  consistent_inputs?: number;
  duration_median_ci95?: number[];
  checks: Record<string, boolean>;
  statuses: Record<string, number>;
  outcomes: Record<string, number>;
  qr_tool_invocations?: number;
  code_tools_observed?: number;
};
export type Attempt = {
  input_sha256?: string;
  recording_sha256?: string;
  resolved_model?: string;
  repetition?: number;
  telemetry_profile?: string;
  id: string;
  implementation: string;
  scenario: string;
  status: string;
  score: string;
  source: string;
  streams: number;
  model?: string;
  temperature: string;
  elapsed_ms: number;
  startup_ms: number;
  first_correct_ms?: number | null;
  metrics: Metrics;
  payloads?: string[];
  expected?: string[] | null;
  error?: string;
  events_file: string;
  artifact?: string;
  input_file: string;
  cpu_peak?: number;
  rss_peak_mb?: number;
  qr_tool_used?: boolean;
  first_token_ms?: number;
  tool_requested_ms?: number;
  tool_result_ms?: number;
  usage?: Record<string, number>;
  trace?: unknown;
  cleanup?: string;
  worker_exit_code?: number;
};
export type Run = {
  id: string;
  status: string;
  created?: string;
  suite?: string;
  progress: { completed: number; total: number };
  summary: Summary[];
  config?: Config;
  attempts?: Attempt[];
  error?: string;
  limitations?: string[];
  environment?: unknown;
  corpus?: unknown;
  observer_overhead?: {
    implementation: string;
    pairs: number;
    median_overhead_percent: number;
    median_ci95?: number[];
    scope: string;
  }[];
  component_resource_peaks?: Record<
    string,
    { cpu_percent: number; rss_mb: number }
  >;
};
export type Live = {
  host_to_first_payload_ms?: number;
  streams?: number;
  workers?: number;
  load_kind?: string;
  model_stages?: Record<string, number>;
  first_correct_ms?: number;
  attempt_id: string;
  implementation: string;
  scenario: string;
  source: string;
  state: string;
  voice?: {
    type: string;
    value:
      | string
      | {
          role?: string;
          text?: string;
          transcript_to_tool_ms?: number;
          agent_tool_roundtrip_ms?: number;
          worker_scan_ms?: number;
          status?: string;
        };
  }[];
  metrics?: Metrics;
  preview?: string;
  events: { event: string; ms: number }[];
  camera?: { url: string; token: string };
  result?: {
    detections?: Detection[];
    payloads?: string[];
    score?: string;
    status?: string;
    error?: string;
    artifact?: string;
    first_correct_ms?: number;
    first_token_ms?: number;
    tool_requested_ms?: number;
    tool_result_ms?: number;
    usage?: Record<string, number>;
    complete_answer_ms?: number;
    generation_after_first_output_ms?: number;
    provider_cleanup_ms?: number;
  };
};
export type Status = {
  run: Run | null;
  live: Live | null;
  series: Series[];
  components?: Record<string, { cpu_percent: number; rss_mb: number }>;
};
export type Config = {
  suite: string;
  source: string;
  implementations: string[];
  scenarios: string[];
  repetitions: number;
  seed: number;
  warmups: number;
  operations: number;
  duration_s: number;
  input_hz: number;
  scan_hz: number;
  deadline_s: number;
  max_queue_age_ms: number;
  loads: number[];
  replace_track: boolean;
  split: string;
  allow_cloud: boolean;
  models: Record<string, string>;
  forced_tool: boolean;
  targets: Record<string, number>;
  image_ids: string[];
  expected: string[] | null;
  text: string;
  correction: string;
  scale: number;
  corpus_id?: string;
  recording_id?: string;
  voice?: boolean;
  workers?: number;
  load_kind?: string;
  recovery_action?: string;
  telemetry_profiles?: string[];
};
export type Bootstrap = {
  token: string;
  version: string;
  providers: Record<string, boolean>;
  provider_specs: Record<
    string,
    { label: string; configured: boolean; model: string; modes: string[] }
  >;
  scenarios: Record<string, string>;
  suites: Record<string, Partial<Config> & { title: string }>;
  livekit_installed: boolean;
  voice_configured: boolean;
  corpora: { id: string; name: string; cases: number }[];
};
