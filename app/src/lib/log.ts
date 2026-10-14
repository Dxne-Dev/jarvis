import { invoke } from "@tauri-apps/api/core";

import { runtime } from "./engine/connection";

type Level = "info" | "warn" | "error";

const WINDOW_MS = 60_000;
const MAX_PER_WINDOW = 30;
let windowStart = 0;
let sent = 0;

/**
 * Journal de l'interface : dans l'app, les messages rejoignent les logs du shell
 * (même sans moteur) ; dans un navigateur, la console seule.
 */
export function uiLog(level: Level, message: string): void {
  const text = message.slice(0, 2000);
  if (level === "error") console.error(text);
  else if (level === "warn") console.warn(text);
  else console.info(text);
  if (runtime !== "tauri") return;
  const now = Date.now();
  if (now - windowStart > WINDOW_MS) {
    windowStart = now;
    sent = 0;
  }
  sent += 1;
  if (sent > MAX_PER_WINDOW) return;
  invoke("ui_log", { level, message: text }).catch(() => undefined);
}

export function installGlobalErrorLogging(): void {
  window.addEventListener("error", (event) => {
    uiLog("error", `erreur : ${event.message} (${event.filename}:${event.lineno})`);
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason: unknown = event.reason;
    uiLog(
      "error",
      `promesse rejetée : ${reason instanceof Error ? reason.message : String(reason)}`,
    );
  });
}
