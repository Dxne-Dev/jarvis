import { create } from "zustand";

import type { EngineClient } from "./client";
import type { EngineBootInfo } from "./connection";
import type { StreamState } from "./events";
import type { EngineEvent } from "./types";

export type EnginePhase = "booting" | "ready" | "failed";

const MAX_EVENTS = 200;

interface EngineState {
  phase: EnginePhase;
  error: string | null;
  client: EngineClient | null;
  perfProbe: boolean;
  stream: StreamState;
  events: EngineEvent[];
  setBoot: (info: EngineBootInfo, client: EngineClient | null) => void;
  setStream: (state: StreamState) => void;
  pushEvent: (event: EngineEvent) => void;
}

export const useEngineStore = create<EngineState>((set) => ({
  phase: "booting",
  error: null,
  client: null,
  perfProbe: false,
  stream: "connecting",
  events: [],
  setBoot: (info, client) => {
    set({
      phase: info.status === "ready" ? "ready" : info.status === "failed" ? "failed" : "booting",
      error: info.error,
      client,
      perfProbe: info.perf_probe,
    });
  },
  setStream: (stream) => {
    set({ stream });
  },
  pushEvent: (event) => {
    set((state) => ({ events: [event, ...state.events].slice(0, MAX_EVENTS) }));
  },
}));

/** Vrai quand le moteur est démarré et que le flux d'événements est ouvert. */
export function useEngineOnline(): boolean {
  return useEngineStore((s) => s.phase === "ready" && s.stream === "open");
}

export function useEngineClient(): EngineClient | null {
  return useEngineStore((s) => s.client);
}
