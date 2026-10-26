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
  if (event.type === "notification") {
    const title = typeof event.payload.title === "string" ? event.payload.title : "Jarvis";
    const body = typeof event.payload.body === "string" ? event.payload.body : "";
    const short = body.length > 160 ? `${body.slice(0, 157)}…` : body;
    return short ? `${title} — ${short}` : title;
  }
  return null;
}

export { Notices } from "./Notices.tsx";
