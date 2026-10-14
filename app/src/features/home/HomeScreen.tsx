import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";

import { usePreferences, useStatus } from "../../lib/engine/queries";
import { useEngineStore } from "../../lib/engine/store";
import { useReducedMotion } from "../../lib/motion";
import { createDemoLevel } from "../sphere/demoLevel";
import { Sphere } from "../sphere/Sphere";
import { SPHERE_STATES, STATE_LABELS, type SphereState } from "../sphere/states";
import { usePerfProbe } from "../sphere/usePerfProbe";
import styles from "./HomeScreen.module.css";

function greeting(date: Date): string {
  const hour = date.getHours();
  if (hour < 5 || hour >= 18) return "Bonsoir";
  if (hour < 12) return "Bonjour";
  return "Bon après-midi";
}

/** État réel de la sphère tant que la conversation (phase 2) n'existe pas. */
function useLiveSphereState(): SphereState {
  const phase = useEngineStore((s) => s.phase);
  const stream = useEngineStore((s) => s.stream);
  if (phase === "failed") return "error";
  if (phase === "booting") return "thinking";
  return stream === "closed" ? "error" : "idle";
}

const SUBTITLES: Record<SphereState, string> = {
  idle: "Jarvis est prêt.",
  listening: "Jarvis t'écoute.",
  thinking: "Démarrage de Jarvis…",
  speaking: "Jarvis parle.",
  awaiting: "Une action attend ta validation.",
  error: "Le moteur ne répond pas. Nouvel essai en cours…",
};

export function HomeScreen() {
  const [params] = useSearchParams();
  const perfProbe = useEngineStore((s) => s.perfProbe) || params.has("perf");
  const status = useStatus();
  const preferences = usePreferences();
  const reducedMotion = useReducedMotion();
  const live = useLiveSphereState();
  const [preview, setPreview] = useState<SphereState | null>(null);
  const { status: probe, onFrame } = usePerfProbe(perfProbe);
  const demoLevel = useMemo(() => createDemoLevel(), []);

  const showPreview = params.has("demo") || status.data?.dev_mode === true;
  const state: SphereState = probe.current ?? preview ?? live;
  const usesAudio = state === "listening" || state === "speaking";

  return (
    <div className={styles.home}>
      <header className={styles.header}>
        <h1 className={styles.title}>{greeting(new Date())}.</h1>
        <p className={styles.subtitle}>{SUBTITLES[live]}</p>
      </header>

      <section className={styles.stage} aria-label="Jarvis">
        <Sphere
          state={state}
          {...(usesAudio ? { level: demoLevel } : {})}
          quality={preferences.data?.sphere_quality ?? "auto"}
          reducedMotion={reducedMotion}
          onFrame={onFrame}
        />
        <p className={styles.stateLabel} aria-live="polite" data-state={state}>
          {STATE_LABELS[state]}
        </p>
      </section>

      {probe.running && (
        <p className={styles.probe} role="status">
          Mesure de fluidité en cours : {probe.current ? STATE_LABELS[probe.current] : "…"} (
          {probe.samples.length + 1}/{SPHERE_STATES.length})
        </p>
      )}
      {!probe.running && probe.samples.length > 0 && (
        <section className={styles.results} aria-label="Résultats de la mesure de fluidité">
          <h2 className={styles.resultsTitle}>Fluidité mesurée</h2>
          <ul className={styles.resultsList}>
            {probe.samples.map((s) => (
              <li key={s.state}>
                <span>{STATE_LABELS[s.state as SphereState]}</span>
                <span className={styles.mono}>
                  {s.fps_mean.toFixed(1)} i/s · p95 {s.frame_ms_p95.toFixed(1)} ms
                </span>
              </li>
            ))}
          </ul>
          {probe.savedAs && <p className={styles.mono}>Rapport : {probe.savedAs}</p>}
          {probe.error && <p role="alert">Envoi du rapport impossible : {probe.error}</p>}
        </section>
      )}

      {showPreview && !probe.running && (
        <section className={styles.preview} aria-label="Aperçu des états de la sphère">
          <h2 className={styles.previewTitle}>Aperçu des états</h2>
          <div className={styles.previewButtons} role="group" aria-label="États de la sphère">
            <button
              type="button"
              className={styles.chip}
              aria-pressed={preview === null}
              onClick={() => {
                setPreview(null);
              }}
            >
              Réel
            </button>
            {SPHERE_STATES.map((s) => (
              <button
                key={s}
                type="button"
                className={styles.chip}
                aria-pressed={preview === s}
                onClick={() => {
                  setPreview(s);
                }}
              >
                {STATE_LABELS[s]}
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
