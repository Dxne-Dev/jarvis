import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type Runtime = "tauri" | "browser";

/** Ce que l'app sait du moteur qu'elle a lancé. */
export interface EngineBootInfo {
  status: "starting" | "ready" | "failed";
  base_url: string | null;
  token: string | null;
  error: string | null;
  perf_probe: boolean;
}

export const runtime: Runtime = isTauri() ? "tauri" : "browser";

/**
 * Dans l'app : demande au shell Tauri l'adresse et le jeton du moteur.
 * Dans un navigateur (développement et tests de bout en bout uniquement) :
 * lit l'adresse et le jeton fournis au serveur Vite.
 */
export async function resolveEngine(): Promise<EngineBootInfo> {
  if (runtime === "tauri") return invoke<EngineBootInfo>("engine_info");
  const url = import.meta.env.VITE_OJARVIS_ENGINE_URL;
  const token = import.meta.env.VITE_OJARVIS_TOKEN;
  const perfProbe = new URLSearchParams(window.location.search).has("perf");
  if (import.meta.env.DEV && url && token) {
    return { status: "ready", base_url: url, token, error: null, perf_probe: perfProbe };
  }
  return {
    status: "failed",
    base_url: null,
    token: null,
    error: "Moteur introuvable : lance l'app avec « pnpm tauri dev ».",
    perf_probe: false,
  };
}

/** Changements d'état du moteur annoncés par le shell (redémarrage, arrêt). */
export async function onEngineStatus(handler: (info: EngineBootInfo) => void): Promise<UnlistenFn> {
  if (runtime !== "tauri") return () => undefined;
  return listen<EngineBootInfo>("engine://status", (event) => {
    handler(event.payload);
  });
}

export async function restartEngine(): Promise<void> {
  if (runtime === "tauri") await invoke("engine_restart");
}

export async function quitApp(): Promise<void> {
  if (runtime === "tauri") await invoke("app_quit");
}
