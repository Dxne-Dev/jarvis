// Skills, serveurs MCP, agents, mémoire graphe et suggestions.

import type { PermissionLevel } from "./actions";

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
  status: "en_cours" | "fini" | "echec" | "interrompu" | "suspendue";
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

export interface SuggestionInfo {
  id: string;
  kind: "repetition" | "inactivite";
  title: string;
  detail: string | null;
  options: { id: string; label: string }[];
  confidence: number;
  status: "nouvelle" | "acceptee" | "ecartee";
  conversation_id: string | null;
  created_at: string;
}
