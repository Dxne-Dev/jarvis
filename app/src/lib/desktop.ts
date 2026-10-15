import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import {
  isPermissionGranted,
  requestPermission,
  sendNotification,
} from "@tauri-apps/plugin-notification";
import { create } from "zustand";

import { runtime } from "./engine/connection";
import { uiLog } from "./log";

export interface ShortcutStatus {
  state: "inconnu" | "demande" | "pret" | "indisponible";
  trigger: string | null;
  error: string | null;
}

/** État du raccourci global, tenu par la coque (portail GlobalShortcuts). */
export const useShortcutStore = create<{ status: ShortcutStatus }>(() => ({
  status: { state: "inconnu", trigger: null, error: null },
}));

/**
 * Écoute le raccourci global de la coque. `onTalk` est appelé à chaque appui.
 * Hors de l'app de bureau (navigateur, tests), rien n'est branché.
 */
export async function watchShortcut(onTalk: () => void): Promise<UnlistenFn> {
  if (runtime !== "tauri") return () => undefined;
  const stops = await Promise.all([
    listen("shortcut://parler", () => {
      onTalk();
    }),
    listen<ShortcutStatus>("shortcut://etat", (event) => {
      useShortcutStore.setState({ status: event.payload });
    }),
  ]);
  try {
    const status = await invoke<ShortcutStatus>("shortcut_status");
    useShortcutStore.setState({ status });
  } catch (error) {
    uiLog("warn", `état du raccourci illisible : ${String(error)}`);
  }
  return () => {
    for (const stop of stops) stop();
  };
}

let permission: boolean | null = null;

/** Notification du bureau, seulement si la fenêtre n'est pas déjà sous les yeux. */
export async function notifyDesktop(title: string, body: string): Promise<void> {
  if (runtime !== "tauri" || (document.hasFocus() && !document.hidden)) return;
  try {
    permission ??= (await isPermissionGranted()) || (await requestPermission()) === "granted";
    if (permission) sendNotification({ title, body });
  } catch (error) {
    uiLog("warn", `notification impossible : ${String(error)}`);
  }
}
