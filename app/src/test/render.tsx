import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";

import { EngineClient } from "../lib/engine/client";
import { useEngineStore } from "../lib/engine/store";
import type { StreamState } from "../lib/engine/events";

export type Handler = (method: string, path: string, body: unknown) => [number, unknown];

/** Moteur simulé : chaque appel passe par `handler`, les appels sont gardés. */
export function fakeEngine(handler: Handler) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const path = url.replace("http://moteur", "");
    const body: unknown = init?.body ? JSON.parse(init.body as string) : undefined;
    const method = init?.method ?? "GET";
    calls.push({ method, path, body });
    const [status, payload] = handler(method, path, body);
    return Promise.resolve(
      new Response(status === 204 ? null : JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  const client = new EngineClient({ baseUrl: "http://moteur", token: "jeton" }, fetchMock);
  return { client, calls };
}

export function renderScreen(
  element: ReactElement,
  {
    client,
    stream = "open",
    phase = "ready",
    path = "/",
  }: {
    client: EngineClient | null;
    stream?: StreamState;
    phase?: "booting" | "ready" | "failed";
    path?: string;
  },
) {
  useEngineStore.setState({ phase, client, stream, error: null, perfProbe: false, events: [] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "*", element }], { initialEntries: [path] });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
