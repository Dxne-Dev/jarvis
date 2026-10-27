import { useId } from "react";

import { ErrorState, LoadingState } from "../../components/States";
import { describeError } from "../../lib/engine/client";
import {
  useLlmModels,
  useLlmStatus,
  usePreferences,
  useUpdatePreferences,
} from "../../lib/engine/queries";
import type { ModelInfo, ProviderStatus } from "../../lib/engine/types";
import { Choice, PreferenceSwitch } from "./PreferenceControls";
import styles from "./SettingsScreen.module.css";

const PROVIDER_LABEL: Record<string, string> = {
  deepseek: "DeepSeek",
  anthropic: "Anthropic",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  meta: "Meta",
  ollama: "Ollama (local)",
};

const TASKS: { id: string; label: string; hint: string }[] = [
  { id: "chat", label: "Conversation", hint: "Réponses écrites." },
  { id: "voice", label: "Voix", hint: "Rapide avant tout." },
  { id: "reasoning", label: "Réflexion", hint: "Plans et problèmes difficiles." },
  { id: "extract", label: "Souvenirs", hint: "Extraction des faits." },
  { id: "title", label: "Titres", hint: "Titres des conversations." },
  { id: "vision", label: "Vision", hint: "Images et écran." },
  { id: "review", label: "Relecture du code", hint: "Un autre regard sur chaque modification." },
];

function providerState(status: ProviderStatus): { tone: string; label: string } {
  if (!status.configured) {
    return status.local
      ? { tone: "off", label: "Service local absent" }
      : { tone: "off", label: "Pas de clé" };
  }
  if (status.degraded || !status.available) return { tone: "down", label: "En panne, contourné" };
  return { tone: "ok", label: status.local ? "Prêt, sur la machine" : "Prêt" };
}

function TaskRouting({ models }: { models: ModelInfo[] }) {
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const routing = preferences.data?.routing ?? {};
  const baseId = useId();

  const choose = (task: string, value: string) => {
    const others = Object.fromEntries(Object.entries(routing).filter(([key]) => key !== task));
    update.mutate({ routing: value === "auto" ? others : { ...others, [task]: value } });
  };

  return (
    <div className={styles.routing}>
      {TASKS.map((task) => {
        const fieldId = `${baseId}-${task.id}`;
        const eligible = models.filter((m) => task.id !== "vision" || m.vision);
        return (
          <div key={task.id} className={styles.routingRow}>
            <label htmlFor={fieldId} className={styles.routingLabel}>
              <span>{task.label}</span>
              <span className={styles.radioHint}>{task.hint}</span>
            </label>
            <select
              id={fieldId}
              className={`${styles.input} ${styles.select}`}
              value={routing[task.id] ?? "auto"}
              disabled={!preferences.data || update.isPending}
              onChange={(e) => {
                choose(task.id, e.target.value);
              }}
            >
              <option value="auto">Automatique (recommandé)</option>
              {eligible.map((m) => (
                <option key={`${m.provider}/${m.model}`} value={`${m.provider}/${m.model}`}>
                  {m.label} — {PROVIDER_LABEL[m.provider] ?? m.provider}
                </option>
              ))}
            </select>
          </div>
        );
      })}
      {update.isError && (
        <p className={styles.ko} role="alert">
          {describeError(update.error)}
        </p>
      )}
    </div>
  );
}

export function ModelsSection() {
  const status = useLlmStatus();
  const models = useLlmModels();
  if (status.isPending || models.isPending) return <LoadingState label="État des modèles…" />;
  if (status.isError) return <ErrorState message={describeError(status.error)} />;
  if (models.isError) return <ErrorState message={describeError(models.error)} />;
  const configured = new Set(status.data.filter((s) => s.configured).map((s) => s.provider));
  return (
    <>
      <ul className={styles.providers} aria-label="Fournisseurs de modèles">
        {status.data.map((s) => {
          const state = providerState(s);
          return (
            <li key={s.provider} className={styles.provider} data-tone={state.tone}>
              <span className={styles.providerDot} aria-hidden="true" />
              <span className={styles.providerName}>
                {PROVIDER_LABEL[s.provider] ?? s.provider}
              </span>
              <span className={styles.providerState}>{state.label}</span>
            </li>
          );
        })}
      </ul>
      <Choice
        name="model_profile"
        label="Profil de modèles"
        options={[
          {
            value: "auto",
            label: "Automatique",
            hint: "Le meilleur modèle disponible pour chaque tâche.",
          },
          {
            value: "meta",
            label: "Tout Meta",
            hint: "Muse Spark pour chaque tâche, vision comprise ; les autres en secours. Clé Meta requise.",
            // Seul ce choix demande la clé : sans elle, on peut toujours revenir en arrière.
            disabled: !configured.has("meta"),
          },
        ]}
      />
      <TaskRouting models={models.data.filter((m) => configured.has(m.provider))} />
      <PreferenceSwitch
        name="learn_from_conversations"
        label="Apprendre de mes conversations"
        hint="Jarvis retient faits et préférences (visibles et modifiables dans Mémoire)."
      />
    </>
  );
}
