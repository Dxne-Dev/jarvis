import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import { EngineClient } from "./client";
import { onEngineStatus, resolveEngine, type EngineBootInfo } from "./connection";
import { EventStream } from "./events";
import { uiLog } from "../log";
import { useEngineStore } from "./store";
import type { EngineEvent } from "./types";

/** Requêtes à rafraîchir quand un événement du moteur arrive. */
const INVALIDATIONS: [prefix: string, key: string][] = [
  ["secret.", "secrets"],
  ["settings.", "settings"],
  ["trace.finished", "traces"],
  ["engine.", "status"],
  ["memory.", "memory"],
  ["conversation.", "conversations"],
  ["chat.completed", "conversations"],
  ["llm.", "llm"],
];

export function EngineProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const setBoot = useEngineStore((s) => s.setBoot);
  const setStream = useEngineStore((s) => s.setStream);
  const pushEvent = useEngineStore((s) => s.pushEvent);

  useEffect(() => {
    let stream: EventStream | null = null;
    let cancelled = false;
    let current = "";

    const connect = (info: EngineBootInfo) => {
      // L'adresse arrive deux fois au démarrage (réponse directe et événement du shell) :
      // on ne recrée la connexion que si quelque chose a changé.
      const key = `${info.status}|${info.base_url ?? ""}|${info.token ?? ""}`;
      if (key === current) return;
      current = key;
      stream?.stop();
      stream = null;
      uiLog(
        info.status === "failed" ? "error" : "info",
        `moteur : ${info.status}${info.error ? ` (${info.error})` : ""}${info.perf_probe ? ", mesure de fluidité demandée" : ""}`,
      );
      if (info.status !== "ready" || !info.base_url || !info.token) {
        setBoot(info, null);
        setStream("closed");
        return;
      }
      const client = new EngineClient({ baseUrl: info.base_url, token: info.token });
      setBoot(info, client);
      stream = new EventStream(client.wsUrl, info.token);
      stream.onState((state) => {
        uiLog("info", `flux d'événements : ${state}`);
        setStream(state);
      });
      stream.onEvent((event: EngineEvent) => {
        pushEvent(event);
        for (const [prefix, key] of INVALIDATIONS) {
          if (event.type.startsWith(prefix))
            void queryClient.invalidateQueries({ queryKey: [key] });
        }
      });
      stream.start();
      void queryClient.invalidateQueries();
    };

    const boot = async () => {
      try {
        const info = await resolveEngine();
        if (!cancelled) connect(info);
      } catch (error) {
        if (!cancelled) {
          connect({
            status: "failed",
            base_url: null,
            token: null,
            error: error instanceof Error ? error.message : String(error),
            perf_probe: false,
          });
        }
      }
    };

    void boot();
    const unlisten = onEngineStatus((info) => {
      if (!cancelled) connect(info);
    });
    return () => {
      cancelled = true;
      stream?.stop();
      void unlisten.then((stop) => {
        stop();
      });
    };
  }, [queryClient, setBoot, setStream, pushEvent]);

  return children;
}
