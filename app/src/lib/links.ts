import { openUrl } from "@tauri-apps/plugin-opener";

import { runtime } from "./engine/connection";

/** Ouvre un lien web dans le navigateur de l'utilisateur, jamais dans la fenêtre de l'app. */
export async function openExternal(href: string): Promise<void> {
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return;
  if (runtime === "tauri") await openUrl(url.href);
  else window.open(url.href, "_blank", "noopener,noreferrer");
}
