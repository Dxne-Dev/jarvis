import { useEffect, useSyncExternalStore } from "react";

import { usePreferences } from "./engine/queries";

const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(callback: () => void): () => void {
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", callback);
  return () => {
    media.removeEventListener("change", callback);
  };
}

function systemPrefersReduced(): boolean {
  return window.matchMedia(QUERY).matches;
}

/**
 * Animations réduites si le système le demande, ou si l'utilisateur l'impose
 * dans Réglages. « full » garde toutes les animations même si le système dit non.
 */
export function useReducedMotion(): boolean {
  const system = useSyncExternalStore(subscribe, systemPrefersReduced, () => false);
  const { data } = usePreferences();
  const choice = data?.reduced_motion ?? "system";
  const reduced = choice === "reduce" || (choice === "system" && system);

  useEffect(() => {
    const root = document.documentElement;
    if (choice === "reduce") root.dataset.motion = "reduce";
    else delete root.dataset.motion;
  }, [choice]);

  return reduced;
}
