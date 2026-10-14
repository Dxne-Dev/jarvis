/** Formes JSON du moteur (voir engine/src/ojarvis/api/schemas.py). */

export interface EngineStatus {
  version: string;
  dev_mode: boolean;
  started_at: string;
  uptime_s: number;
  keyring: string;
  keyring_error: string | null;
  secrets_configured: number;
  secrets_total: number;
  events_published: number;
  events_dropped: number;
  stream_clients: number;
  timezone: string | null;
}

export type SecretGroup = "llm" | "voice" | "search" | "integrations" | "phone";

export interface SecretStatus {
  name: string;
  label: string;
  group: SecretGroup;
  help: string;
  configured: boolean;
  source: "env" | "ui" | "generated" | null;
  updated_at: string | null;
  last_check_ok: boolean | null;
  last_check_at: string | null;
  last_check_detail: string | null;
  last_check_latency_ms: number | null;
}

export interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
  latency_ms: number | null;
  trace_id: string;
}

export interface Preferences {
  reduced_motion: "system" | "reduce" | "full";
  sphere_quality: "auto" | "high" | "low";
}

export interface EngineEvent {
  id: number | null;
  type: string;
  ts: string;
  source: string;
  correlation_id: string | null;
  payload: Record<string, unknown>;
}

export interface TraceSummary {
  id: string;
  name: string;
  kind: string;
  status: "running" | "ok" | "error";
  started_at: string;
  duration_ms: number | null;
  correlation_id: string | null;
  error: string | null;
  span_count: number;
  meta: Record<string, unknown>;
}

export interface Span {
  id: string;
  parent_id: string | null;
  name: string;
  kind: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  attributes: Record<string, unknown>;
  error: string | null;
}

export interface TraceDetail extends Omit<TraceSummary, "span_count"> {
  ended_at: string | null;
  spans: Span[];
}

export interface PerfSample {
  state: string;
  duration_s: number;
  frames: number;
  fps_mean: number;
  frame_ms_p50: number;
  frame_ms_p95: number;
  frame_ms_p99: number;
  long_frames: number;
}

export interface PerfReport {
  runtime: string;
  user_agent: string;
  device_pixel_ratio: number;
  canvas_px: number;
  refresh_hint_hz: number | null;
  samples: PerfSample[];
  notes: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    correlation_id: string | null;
  };
}
