import type { ApiErrorBody } from "./types";

/** Le moteur a répondu, mais par une erreur (forme normalisée). */
export class EngineApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string | null;

  constructor(status: number, code: string, message: string, correlationId: string | null) {
    super(message);
    this.name = "EngineApiError";
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }
}

/** Le moteur n'a pas répondu du tout (arrêté, en redémarrage). */
export class EngineUnreachableError extends Error {
  constructor() {
    super("Le moteur ne répond pas.");
    this.name = "EngineUnreachableError";
  }
}

export interface EngineEndpoint {
  baseUrl: string;
  token: string;
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof value.error === "object"
  );
}

export class EngineClient {
  readonly endpoint: EngineEndpoint;
  private readonly fetchImpl: typeof fetch;

  constructor(endpoint: EngineEndpoint, fetchImpl: typeof fetch = fetch.bind(globalThis)) {
    this.endpoint = endpoint;
    this.fetchImpl = fetchImpl;
  }

  get wsUrl(): string {
    return this.endpoint.baseUrl.replace(/^http/, "ws") + "/v1/events/ws";
  }

  async request<T>(method: Method, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.endpoint.token}`,
      "X-Correlation-ID": crypto.randomUUID().replaceAll("-", "").slice(0, 16),
    };
    const raw = body instanceof Blob;
    if (body !== undefined)
      headers["Content-Type"] = raw ? "application/octet-stream" : "application/json";
    let response: Response;
    try {
      response = await this.fetchImpl(this.endpoint.baseUrl + path, {
        method,
        headers,
        body: body === undefined ? null : raw ? body : JSON.stringify(body),
      });
    } catch {
      throw new EngineUnreachableError();
    }
    if (response.status === 204) return undefined as T;
    const data: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      if (isErrorBody(data)) {
        throw new EngineApiError(
          response.status,
          data.error.code,
          data.error.message,
          data.error.correlation_id,
        );
      }
      throw new EngineApiError(
        response.status,
        "http_error",
        `Erreur HTTP ${response.status}.`,
        null,
      );
    }
    return data as T;
  }

  /** Un fichier (une image) : `null` s'il n'existe pas encore (404). */
  async blob(path: string): Promise<Blob | null> {
    let response: Response;
    try {
      response = await this.fetchImpl(this.endpoint.baseUrl + path, {
        headers: { Authorization: `Bearer ${this.endpoint.token}` },
      });
    } catch {
      throw new EngineUnreachableError();
    }
    if (response.status === 404) return null;
    if (!response.ok)
      throw new EngineApiError(
        response.status,
        "http_error",
        `Erreur HTTP ${response.status}.`,
        null,
      );
    return response.blob();
  }

  /** Requête POST dont la réponse est lue au fil de l'eau (flux SSE). */
  async stream(path: string, body: unknown, signal?: AbortSignal): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchImpl(this.endpoint.baseUrl + path, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${this.endpoint.token}`,
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(body),
        signal: signal ?? null,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new EngineUnreachableError();
    }
    if (!response.ok) {
      const data: unknown = await response.json().catch(() => null);
      if (isErrorBody(data)) {
        throw new EngineApiError(
          response.status,
          data.error.code,
          data.error.message,
          data.error.correlation_id,
        );
      }
      throw new EngineApiError(
        response.status,
        "http_error",
        `Erreur HTTP ${response.status}.`,
        null,
      );
    }
    return response;
  }

  get<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }

  post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("PUT", path, body);
  }

  patch<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("PATCH", path, body);
  }

  delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", path);
  }

  /** Envoie un fichier tel quel (corps brut), sans le lire en mémoire côté interface. */
  upload<T>(path: string, file: Blob): Promise<T> {
    return this.request<T>("POST", path, file);
  }
}

/** Message lisible pour l'interface, quel que soit le type d'erreur. */
export function describeError(error: unknown): string {
  if (error instanceof EngineUnreachableError)
    return "Le moteur ne répond pas. Nouvel essai en cours…";
  if (error instanceof EngineApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Erreur inattendue.";
}
