// Automatisations, intégrations et Telegram.

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
