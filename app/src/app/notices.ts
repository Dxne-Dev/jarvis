import type { EngineEvent } from "../lib/engine/types";

const PROVIDER_LABEL: Record<string, string> = {
  deepseek: "DeepSeek",
  anthropic: "Anthropic",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  ollama: "Ollama",
};

/** Message court pour les événements qui méritent l'attention, sinon null. */
export function noticeFor(event: EngineEvent): string | null {
  const raw = event.payload.provider;
  const provider = typeof raw === "string" ? raw : "";
  const name = PROVIDER_LABEL[provider] ?? provider;
  if (event.type === "llm.provider_degraded") {
    return `${name} ne répond pas : Jarvis passe par un autre modèle.`;
  }
  if (event.type === "llm.provider_recovered") return `${name} répond de nouveau.`;
  return null;
}
