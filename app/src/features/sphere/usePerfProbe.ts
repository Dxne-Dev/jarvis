import { useCallback, useEffect, useRef, useState } from "react";

import { sendPerfReport } from "../../lib/engine/queries";
import { useEngineStore } from "../../lib/engine/store";
import type { PerfSample } from "../../lib/engine/types";
import { runtime } from "../../lib/engine/connection";
import { uiLog } from "../../lib/log";
import { FrameRecorder } from "./perf";
import { SPHERE_STATES, type SphereState } from "./states";

const WARMUP_MS = 1200;
const MEASURE_MS = 6000;

export interface ProbeStatus {
  running: boolean;
  current: SphereState | null;
  samples: PerfSample[];
  savedAs: string | null;
  error: string | null;
}

/**
 * Mesure de fluidité de la sphère : chaque état est affiché, chauffé, puis mesuré.
 * Le rapport est envoyé au moteur, qui le garde comme preuve.
 */
export function usePerfProbe(enabled: boolean) {
  const client = useEngineStore((s) => s.client);
  const recorder = useRef(new FrameRecorder());
  const [status, setStatus] = useState<ProbeStatus>({
    running: false,
    current: null,
    samples: [],
    savedAs: null,
    error: null,
  });
  // Vrai une fois le rapport envoyé : la mesure ne se relance pas à chaque rendu.
  const done = useRef(false);

  const onFrame = useCallback((intervalMs: number) => {
    recorder.current.record(intervalMs);
  }, []);

  useEffect(() => {
    // En développement, React monte deux fois chaque effet : le premier passage est annulé
    // par son nettoyage, le second fait la mesure.
    if (!enabled || !client || done.current) return;
    let cancelled = false;
    // Lu à travers une fonction : la valeur change pendant les attentes.
    const isCancelled = () => cancelled;
    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        setTimeout(resolve, ms);
      });

    const run = async () => {
      const samples: PerfSample[] = [];
      uiLog("info", "mesure de fluidité : début");
      setStatus((s) => ({ ...s, running: true }));
      for (const state of SPHERE_STATES) {
        if (isCancelled()) return;
        uiLog("info", `mesure de fluidité : état ${state}`);
        setStatus((s) => ({ ...s, current: state }));
        await wait(WARMUP_MS);
        recorder.current.start(performance.now());
        await wait(MEASURE_MS);
        if (isCancelled()) return;
        samples.push(recorder.current.stop(state, performance.now()));
        setStatus((s) => ({ ...s, samples: [...samples] }));
      }
      const canvas = document.querySelector("canvas");
      try {
        const result = await sendPerfReport(client, {
          runtime: runtime === "tauri" ? "tauri-webkitgtk" : "navigateur",
          user_agent: navigator.userAgent.slice(0, 400),
          device_pixel_ratio: window.devicePixelRatio || 1,
          canvas_px: canvas?.width ?? 0,
          refresh_hint_hz: null,
          samples,
          notes: "mesure automatique : 1,2 s de chauffe puis 6 s par état",
        });
        uiLog("info", `mesure de fluidité : rapport ${result.saved_as}`);
        done.current = true;
        if (!cancelled) {
          setStatus((s) => ({ ...s, running: false, current: null, savedAs: result.saved_as }));
        }
      } catch (error) {
        uiLog("error", `mesure de fluidité : envoi impossible (${String(error)})`);
        if (!cancelled) {
          setStatus((s) => ({
            ...s,
            running: false,
            current: null,
            error: error instanceof Error ? error.message : String(error),
          }));
        }
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [enabled, client]);

  return { status, onFrame };
}
