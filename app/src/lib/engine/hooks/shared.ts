import type { EngineClient } from "../client";

/** Le client du moteur, ou une erreur claire tant qu'il ne répond pas. */
export function requireClient(client: EngineClient | null): EngineClient {
  if (!client) throw new Error("Moteur indisponible.");
  return client;
}
