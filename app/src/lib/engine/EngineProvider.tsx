import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import { useBrowserLive } from "./browserLive";
import { useScreenLive } from "./screenLive";
import { EngineClient } from "./client";
import { onEngineStatus, resolveEngine, type EngineBootInfo } from "./connection";
import { EventStream } from "./events";
import { notifyDesktop, watchShortcut } from "../desktop";
import { uiLog } from "../log";
import { setVoiceLevel, useVoiceStore } from "../voice";
import { useEngineStore } from "./store";
import type { EngineEvent, VoicePhase } from "./types";

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
  ["voice.status", "voice"],
  ["voice.turn", "conversations"],
  ["plan.", "plans"],
  ["plan.finished", "conversations"],
  ["audit.", "audit"],
  ["browser.", "browser"],
  ["screen.share", "screen-share"],
  ["automation.", "automations"],
  ["workflow.", "automations"],
  ["integration.", "integrations"],
  ["telegram.", "telegram"],
  ["briefing.", "conversations"],
  ["skill.", "skills"],
  ["skill.", "tools"],
  ["mcp.", "mcp"],
  ["agent.", "agents"],
  ["suggestion.", "suggestions"],
];

/** Une seule annonce de session par lancement de l'app (le briefing du jour en dépend). */
let sessionAnnounced = false;

/** Événements qui méritent une notification quand la fenêtre est en arrière-plan. */
function notifyFor(event: EngineEvent): void {
  const reason = typeof event.payload.reason === "string" ? event.payload.reason : "";
  if (event.type === "llm.provider_degraded") {
    const provider = typeof event.payload.provider === "string" ? event.payload.provider : "";
    void notifyDesktop("Fournisseur indisponible", `${provider} ne répond pas : Jarvis bascule.`);
  } else if (event.type === "voice.tts_fallback") {
    void notifyDesktop(
      "Voix locale",
      `Cartesia ne répond pas (${reason}) : Jarvis parle en local.`,
    );
  } else if (event.type === "voice.error") {
    void notifyDesktop(
      "Voix indisponible",
      "Le pipeline vocal s'est arrêté. Nouvel essai en cours.",
    );
  } else if (event.type === "suggestion.created") {
    const title = typeof event.payload.title === "string" ? event.payload.title : "";
    void notifyDesktop("Une idée de Jarvis", title);
  } else if (event.type === "plan.proposed") {
    const title = typeof event.payload.title === "string" ? event.payload.title : "";
    void notifyDesktop("Action à valider", title || "Jarvis attend ta décision.");
  } else if (event.type === "plan.finished") {
    const ok = event.payload.status === "done";
    void notifyDesktop(
      ok ? "Plan terminé" : "Plan interrompu",
      ok ? "Jarvis a fini ce que tu as validé." : "Une étape a échoué : rien de plus n'a été fait.",
    );
  } else if (event.type === "notification") {
    const title = typeof event.payload.title === "string" ? event.payload.title : "Jarvis";
    const body = typeof event.payload.body === "string" ? event.payload.body : "";
    void notifyDesktop(title, body);
  } else if (event.type === "audit.integrity_failed") {
    void notifyDesktop("Journal des actions altéré", "Une entrée a été modifiée hors de Jarvis.");
  }
}

function handleVoiceEvent(event: EngineEvent): void {
  const voice = useVoiceStore.getState();
  if (event.type === "voice.state") {
    voice.setPhase(event.payload.state as VoicePhase);
  } else if (event.type === "voice.status") {
    voice.setPhase(event.payload.state as VoicePhase);
  } else if (event.type === "voice.transcript") {
    const text = event.payload.text;
    voice.setTranscript(typeof text === "string" ? text : null);
  } else if (event.type === "voice.sentence" && typeof event.payload.text === "string") {
    voice.addSentence(event.payload.text);
  } else if (event.type === "voice.turn" && typeof event.payload.conversation_id === "string") {
    voice.setConversation(event.payload.conversation_id);
  }
}

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
        // Après une coupure, des événements ont pu être manqués : on relit tout.
        if (state === "open") void queryClient.invalidateQueries();
        // Première connexion de ce lancement : à la première session du jour, le briefing.
        if (state === "open" && !sessionAnnounced) {
          sessionAnnounced = true;
          void client.post("/v1/session", { force: false }).catch(() => {
            sessionAnnounced = false;
          });
        }
      });
      stream.onEvent((event: EngineEvent) => {
        // Le niveau sonore arrive une douzaine de fois par seconde : il ne passe
        // ni par le journal des événements ni par React.
        if (event.type === "voice.level") {
          setVoiceLevel(Number(event.payload.level) || 0);
          return;
        }
        // Une nouvelle image de l'écran partagé : l'aperçu la lira.
        if (event.type === "screen.frame") {
          useScreenLive.getState().setSeq(Number(event.payload.seq) || 0);
          return;
        }
        // Une nouvelle image de la page de Jarvis : la vue en direct la lira.
        if (event.type === "browser.frame") {
          const { seq, url } = event.payload;
          useBrowserLive.getState().setFrame(Number(seq) || 0, typeof url === "string" ? url : "");
          return;
        }
        handleVoiceEvent(event);
        notifyFor(event);
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
    // Raccourci global : comme « Hey Jarvis », sans le dire.
    const stopShortcut = watchShortcut(() => {
      const client = useEngineStore.getState().client;
      if (client) void client.post("/v1/voice/listen").catch(() => undefined);
    });
    const unlisten = onEngineStatus((info) => {
      if (!cancelled) connect(info);
    });
    return () => {
      cancelled = true;
      stream?.stop();
      void unlisten.then((stop) => {
        stop();
      });
      void stopShortcut.then((stop) => {
        stop();
      });
    };
  }, [queryClient, setBoot, setStream, pushEvent]);

  return children;
}
