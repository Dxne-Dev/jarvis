// Ce que Jarvis fait : outils, plans, journal des actions, navigateur, écran partagé.

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

/** L'écran partagé en direct avec Jarvis (portail ScreenCast de GNOME). */
export interface ScreenShareState {
  active: boolean;
  frames: number;
  since: number | null;
}

export type PlanStatus =
  "proposed" | "approved" | "running" | "done" | "failed" | "refused" | "stopped";
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
