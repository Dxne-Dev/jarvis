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

export interface Conversation {
  id: string;
  title: string;
  channel: "app" | "voice" | "telegram";
  created_at: string;
  updated_at: string;
  message_count: number;
  preview: string;
}

export interface StoredMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  status: "ok" | "error" | "interrupted" | "streaming";
  created_at: string;
  provider: string | null;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  latency_ms: number | null;
  trace_id: string | null;
  /** Outils utilisés et plans proposés pendant ce tour. */
  meta?: { tools?: ToolActivity[]; plans?: string[] };
}

export interface ConversationDetail extends Conversation {
  messages: StoredMessage[];
}

export type MemoryKind = "fait" | "preference" | "profil";

export interface MemoryItem {
  id: number;
  kind: MemoryKind;
  content: string;
  source: "conversation" | "manuel";
  confidence: number;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  use_count: number;
}

export interface ProviderStatus {
  provider: string;
  configured: boolean;
  local: boolean;
  available: boolean;
  degraded: boolean;
  last_error: string | null;
}

export interface ModelInfo {
  provider: string;
  model: string;
  label: string;
  tools: boolean;
  vision: boolean;
  local: boolean;
  price_in: number | null;
  price_out: number | null;
}

export interface ContextItemSummary {
  kind: string;
  preview: string;
  kept: boolean;
}

export type ChatStreamEvent =
  | {
      type: "start";
      conversation_id: string;
      user_message_id: number;
      assistant_message_id: number;
    }
  | { type: "context"; budget: number; used: number; items: ContextItemSummary[] }
  | { type: "route"; provider: string; model: string; fallback_from: string | null }
  | { type: "delta"; text: string }
  | ({ type: "tool" } & ToolActivity)
  | ({ type: "plan" } & PlanSummary)
  | {
      type: "done";
      conversation_id: string;
      message_id: number;
      provider: string | null;
      model: string | null;
      tokens_in: number;
      tokens_out: number;
      cost_usd: number | null;
      latency_ms: number | null;
      first_token_ms: number | null;
      trace_id: string;
      plans?: string[];
    }
  | { type: "error"; message: string; partial?: boolean };

// ---------------------------------------------------------------- Jarvis agit

/** 1 : lire (autonome) ; 2 : agir (ta validation) ; 3 : détruire (double confirmation). */
export type PermissionLevel = 1 | 2 | 3;

export interface ToolActivity {
  id: string;
  name: string;
  description: string;
  status: "running" | "done" | "failed" | "proposed";
  level?: PermissionLevel;
  source?: string | null;
  error?: string;
}

export interface PlanSummary {
  id: string;
  title: string;
  status: PlanStatus;
  max_level: PermissionLevel;
  tainted: boolean;
  steps: { position: number; description: string; level: PermissionLevel }[];
}

export type PlanStatus = "proposed" | "approved" | "running" | "done" | "failed" | "refused";
export type StepStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface PlanStep {
  position: number;
  tool: string;
  arguments: Record<string, unknown>;
  why: string;
  level: PermissionLevel;
  description: string;
  status: StepStatus;
  result: string | null;
  error: string | null;
}

export interface Plan {
  id: string;
  conversation_id: string | null;
  title: string;
  request: string;
  status: PlanStatus;
  max_level: PermissionLevel;
  /** Proposé après lecture d'un contenu externe (page, fichier). */
  tainted: boolean;
  created_at: string;
  updated_at: string;
  decided_at: string | null;
  result: string | null;
  steps: PlanStep[];
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: "utilisateur" | "jarvis" | "automatisation";
  action: string;
  level: PermissionLevel;
  summary: string;
  details: Record<string, unknown>;
  hash: string;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
  integrity_ok: boolean | null;
  broken_at: number | null;
}

export interface ToolInfo {
  name: string;
  description: string;
  level: PermissionLevel;
  level_label: string;
  os_control: boolean;
}

export interface BrowserGrant {
  domain: string;
  source: string;
  imported_at: string;
  count: number;
}

export interface BrowserState {
  sources: { id: string; label: string }[];
  grants: BrowserGrant[];
  login_domain: string | null;
}

// ---------------------------------------------------------------- automatisations

export type Schedule =
  | { type: "chaque_jour"; heure: string; jours: number[] }
  | { type: "une_fois"; le: string }
  | { type: "intervalle"; minutes: number }
  | { type: "chaque_mois"; jour: number; heure: string };

export type AutomationTrigger =
  | { type: "horaire"; quand: Schedule }
  | { type: "evenement"; evenement: string; filtre?: Record<string, string | number | boolean> };

export type AutomationAction =
  { type: "rappel"; texte: string } | { type: "consigne"; texte: string };

export interface Automation {
  id: string;
  name: string;
  trigger: AutomationTrigger;
  action: AutomationAction;
  when: string;
  what: string;
  enabled: boolean;
  one_shot: boolean;
  created_by: "utilisateur" | "jarvis";
  created_at: string;
  updated_at: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: "ok" | "failed" | "missed" | "running" | null;
  run_count: number;
  conversation_id: string | null;
}

export interface AutomationRun {
  id: string;
  title: string;
  status: "pending" | "running" | "done" | "failed";
  position: number;
  steps: number;
  attempts: number;
  error: string | null;
  reason: "horaire" | "evenement" | "manuel" | null;
  summary: string | null;
  plans: string[];
  conversation_id: string | null;
  created_at: string;
  ended_at: string | null;
}

export interface AutomationDraft {
  name: string;
  trigger: AutomationTrigger;
  action: AutomationAction;
}

// ---------------------------------------------------------------- intégrations

export interface Integration {
  name: "github" | "notion" | "agenda";
  label: string;
  about: string;
  configured: boolean;
  status: "arrêté" | "connexion" | "prêt" | "erreur";
  error: string | null;
  tools: number;
  detail: string | null;
  account_configured?: boolean;
  account_connected?: boolean;
}

export interface TelegramStatus {
  configured: boolean;
  connected: boolean;
  bot: string | null;
  last_error: string | null;
  handled: number;
  rejected: number;
}

export type SkillStatus = "brouillon" | "pret" | "echec" | "actif" | "desactive" | "remplace";

export interface SkillReport {
  ok: boolean;
  cases: { name: string; ok: boolean; detail: string }[];
  error: string | null;
  backend: string | null;
  duration_ms: number;
  summary: string;
}

export interface SkillToolInfo {
  name: string;
  tool: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface Skill {
  id: string;
  name: string;
  version: string;
  description: string;
  instructions: string;
  status: SkillStatus;
  tools: SkillToolInfo[];
  permissions: string;
  report: SkillReport | null;
  created_by: string;
  conversation_id: string | null;
  created_at: string;
  tested_at: string | null;
  activated_at: string | null;
  digest: string;
}

export interface SkillDetail extends Skill {
  code: string;
  tests: string;
}

export interface McpSetting {
  name: string;
  description: string;
  required: boolean;
  secret: boolean;
  default: string | null;
}

export interface McpRegistryEntry {
  name: string;
  title: string;
  description: string;
  version: string;
  repository: string | null;
  website: string | null;
  option: {
    kind: "npm" | "pypi" | "oci" | "remote";
    label: string;
    where: string;
    settings: McpSetting[];
  } | null;
  why_not: string | null;
  installed_id: string | null;
}

export interface McpTool {
  name: string;
  level: PermissionLevel;
  description?: string;
}

export interface McpProbe {
  ok: boolean;
  tools: McpTool[];
  error: string | null;
  runner: string;
  seconds: number;
}

export interface McpServerInfo {
  id: string;
  registry_name: string;
  title: string;
  description: string;
  version: string;
  kind: string;
  label: string;
  where: string;
  enabled: boolean;
  status: string;
  error: string | null;
  tools: McpTool[];
  variables: Record<string, string>;
  secret_names: string[];
  installed_at: string;
}

export interface McpInstallRequest {
  name: string;
  version: string;
  variables: Record<string, string>;
  secrets: Record<string, string>;
}

export interface AgentInfo {
  name: string;
  label: string;
  goal: string;
  tools: string[];
  busy: boolean;
  run: string | null;
}

export interface AgentStep {
  tool: string;
  description: string;
  status: "done" | "failed" | "proposed" | "running";
  error?: string;
}

export interface AgentRun {
  id: string;
  agent: string;
  task: string;
  status: "en_cours" | "fini" | "echec" | "interrompu";
  origin: "chat" | "interface";
  result: string | null;
  error: string | null;
  steps: AgentStep[];
  plans: string[];
  trace_id: string | null;
  started_at: string;
  ended_at: string | null;
}

export type GraphKind =
  "moi" | "personne" | "projet" | "evenement" | "lieu" | "organisation" | "sujet";

export interface GraphEntity {
  id: number;
  kind: GraphKind;
  name: string;
  description: string | null;
  source: string;
  mentions: number;
  created_at: string;
  last_seen_at: string;
}

export interface GraphRelation {
  id: number;
  source_id: number;
  target_id: number;
  label: string;
  mentions: number;
  last_seen_at: string;
}

export interface MemoryGraph {
  entities: GraphEntity[];
  relations: GraphRelation[];
}
