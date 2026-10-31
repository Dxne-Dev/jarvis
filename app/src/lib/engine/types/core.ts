// État du moteur, clés, préférences, voix, modèles locaux, événements et journal technique.

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
  routing: Record<string, string>;
  model_profile: "auto" | "meta";
  /** Profil « Tout Meta » : échecs de la même commande avant le relais (0 : coupé). */
  relay_after: number;
  /** Le modèle de relais, « fournisseur/modèle ». */
  relay_model: string;
  learn_from_conversations: boolean;
  voice_enabled: boolean;
  voice_input_device: string | null;
  voice_output_device: string | null;
  voice_name: string;
  voice_engine: "auto" | "piper";
  voice_stt: "groq" | "cartesia" | "local";
  wake_sensitivity: "basse" | "normale" | "haute";
  voice_follow_up: boolean;
  voice_barge_in: boolean;
  voice_headset: boolean;
  briefing_enabled: boolean;
  os_control_enabled: boolean;
  screen_vision: "local" | "en_ligne";
  /** Montrer le navigateur de Jarvis : Chromium s'ouvre en fenêtre. */
  browser_visible: boolean;
}

export type VoicePhase =
  "off" | "starting" | "idle" | "listening" | "thinking" | "speaking" | "error";

export interface VoiceStatus {
  state: VoicePhase;
  enabled: boolean;
  error: string | null;
  models: Record<string, string>;
  echo_cancel: boolean;
  tts_engine: string | null;
  tts_fallback: string | null;
  stt_engine: string | null;
  stt_fallback: boolean;
  last_latency_ms: number | null;
  last_turn_at: number | null;
}

export interface LocalModelFile {
  name: string;
  url: string;
  sha256: string;
  size: number | null;
  present: boolean;
  /** Octets déjà reçus d'un téléchargement interrompu. */
  partial: number;
}

export interface LocalModel {
  key: string;
  label: string;
  folder: string;
  ready: boolean;
  /** « prêt », « absent », « téléchargement 42 % », « erreur »… */
  state: string;
  files: LocalModelFile[];
}

export interface ImportedModelFile {
  key: string;
  label: string;
  file: string;
  ready: boolean;
}

export interface VoiceDevices {
  inputs: { name: string; label: string }[];
  outputs: { name: string; label: string }[];
}

export interface CartesiaVoice {
  id: string;
  name: string;
  gender: string | null;
  description: string;
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
