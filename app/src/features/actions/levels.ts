import type { PermissionLevel, PlanStatus, StepStatus } from "../../lib/engine/types";

/** Les trois niveaux de permission, dits simplement. */
export const LEVEL_NAME: Record<PermissionLevel, string> = {
  1: "Lecture",
  2: "Action",
  3: "Destruction",
};

export const LEVEL_HINT: Record<PermissionLevel, string> = {
  1: "Jarvis lit, sans rien changer : il le fait seul.",
  2: "Jarvis agit pour toi : rien ne part sans ta validation.",
  3: "Jarvis supprime ou change une permission : double confirmation.",
};

export const PLAN_STATUS: Record<PlanStatus, string> = {
  proposed: "En attente de ta décision",
  approved: "Validé",
  running: "En cours",
  done: "Terminé",
  failed: "Interrompu",
  refused: "Refusé",
  stopped: "Arrêté par toi",
};

export const STEP_STATUS: Record<StepStatus, string> = {
  pending: "à faire",
  running: "en cours",
  done: "faite",
  failed: "en échec",
  skipped: "non faite",
};

export function asLevel(value: number | undefined): PermissionLevel {
  return value === 3 ? 3 : value === 2 ? 2 : 1;
}
