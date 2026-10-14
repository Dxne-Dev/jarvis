import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { describeError, EngineApiError, EngineClient, EngineUnreachableError } from "./client";
import { EventStream } from "./events";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("EngineClient", () => {
  it("envoie le jeton, un ID de corrélation et le corps JSON", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    const client = new EngineClient({ baseUrl: "http://127.0.0.1:9", token: "abc" }, fetchMock);
    await expect(client.post("/v1/x", { a: 1 })).resolves.toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(url).toBe("http://127.0.0.1:9/v1/x");
    expect(headers.Authorization).toBe("Bearer abc");
    expect(headers["X-Correlation-ID"]).toMatch(/^[0-9a-f]{16}$/);
    expect(init.body).toBe('{"a":1}');
  });

  it("renvoie undefined sur 204", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    const client = new EngineClient({ baseUrl: "http://h", token: "t" }, fetchMock);
    await expect(client.put("/v1/secrets/X", { value: "v" })).resolves.toBeUndefined();
  });

  it("transforme l'erreur normalisée du moteur", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(404, {
        error: { code: "not_found", message: "Secret inconnu.", details: {}, correlation_id: "c1" },
      }),
    );
    const client = new EngineClient({ baseUrl: "http://h", token: "t" }, fetchMock);
    const error = await client.get("/v1/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(EngineApiError);
    expect(error).toMatchObject({ status: 404, code: "not_found", correlationId: "c1" });
    expect(describeError(error)).toBe("Secret inconnu.");
  });

  it("gère une erreur sans corps lisible", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("<html>", { status: 502 }));
    const client = new EngineClient({ baseUrl: "http://h", token: "t" }, fetchMock);
    await expect(client.get("/v1/x")).rejects.toMatchObject({ status: 502, code: "http_error" });
  });

  it("signale un moteur injoignable", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const client = new EngineClient({ baseUrl: "http://h", token: "t" }, fetchMock);
    const error = await client.delete("/v1/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(EngineUnreachableError);
    expect(describeError(error)).toContain("ne répond pas");
    expect(describeError("bizarre")).toBe("Erreur inattendue.");
  });

  it("construit l'URL WebSocket", () => {
    const client = new EngineClient({ baseUrl: "http://127.0.0.1:4242", token: "t" });
    expect(client.wsUrl).toBe("ws://127.0.0.1:4242/v1/events/ws");
  });
});

class FakeSocket {
  static instances: FakeSocket[] = [];
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: MessageEvent<string>) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.onclose?.();
  }
  receive(data: unknown) {
    this.onmessage?.({
      data: typeof data === "string" ? data : JSON.stringify(data),
    } as MessageEvent<string>);
  }
}

describe("EventStream", () => {
  beforeEach(() => {
    FakeSocket.instances = [];
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const create = () =>
    new EventStream(
      "ws://h/v1/events/ws",
      "jeton",
      (u) => new FakeSocket(u) as unknown as WebSocket,
    );

  it("s'authentifie, s'ouvre au hello et distribue les événements", () => {
    const stream = create();
    const states: string[] = [];
    const events: string[] = [];
    stream.onState((s) => states.push(s));
    stream.onEvent((e) => events.push(e.type));
    stream.start();
    const socket = FakeSocket.instances[0];
    expect(socket).toBeDefined();
    socket?.onopen?.();
    expect(JSON.parse(socket?.sent[0] ?? "{}")).toEqual({ type: "auth", token: "jeton" });
    socket?.receive({ type: "hello" });
    socket?.receive("pas du json");
    socket?.receive({ type: "event", event: { type: "secret.updated", payload: {} } });
    expect(states).toEqual(["open"]);
    expect(events).toEqual(["secret.updated"]);
  });

  it("se reconnecte avec un délai croissant puis s'arrête sur demande", () => {
    const stream = create();
    stream.start();
    FakeSocket.instances[0]?.close();
    expect(stream.state).toBe("closed");
    vi.advanceTimersByTime(499);
    expect(FakeSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1]?.close();
    vi.advanceTimersByTime(999);
    expect(FakeSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeSocket.instances).toHaveLength(3);
    stream.stop();
    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(3);
  });
});
