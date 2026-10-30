import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { useBrowserLive } from "../../lib/engine/browserLive";
import type { Plan, PlanStep } from "../../lib/engine/types";
import { fakeEngine, renderScreen } from "../../test/render";
import { PlanView } from "./PlanCard";

const plan: Plan = {
  id: "p1",
  conversation_id: "c1",
  title: "Rapport d'incident",
  request: "Écris le rapport.",
  status: "done",
  max_level: 2,
  tainted: false,
  created_at: "2026-10-16T08:00:00Z",
  updated_at: "2026-10-16T08:00:05Z",
  decided_at: "2026-10-16T08:00:02Z",
  result: "Rapport écrit dans ~/Téléchargements/rapport.txt.",
  steps: [],
};

function show(showSynthesis?: boolean) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PlanView plan={plan} compact showSynthesis={showSynthesis} />
    </QueryClientProvider>,
  );
}

describe("Carte d'un plan", () => {
  it("montre le compte rendu dans l'écran des actions", () => {
    show();
    expect(screen.getByText(plan.result ?? "")).toBeInTheDocument();
  });

  it("ne le répète pas dans une conversation, où il suit en message", () => {
    show(false);
    expect(screen.queryByText(plan.result ?? "")).not.toBeInTheDocument();
  });
});

describe("Voir Jarvis agir (#34)", () => {
  const step = (position: number, status: PlanStep["status"]): PlanStep => ({
    position,
    tool: "navigateur_cliquer",
    arguments: { cible: position === 1 ? "Ajouter au panier" : "Commander" },
    why: "",
    level: 2,
    description: position === 1 ? "Cliquer sur Ajouter au panier" : "Cliquer sur Commander",
    status,
    result: null,
    error: null,
  });
  const running: Plan = {
    ...plan,
    status: "running",
    result: null,
    steps: [step(1, "running"), step(2, "pending")],
  };

  it("montre la page pendant le plan, et « Arrêter » ne lance pas l'étape suivante", async () => {
    const user = userEvent.setup();
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => "blob:page"),
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    const { client, calls } = fakeEngine((_method, path) => {
      if (path === "/v1/plans/p1/stop") return [200, running];
      return [200, {}];
    });
    renderScreen(<PlanView plan={running} compact />, { client });
    expect(await screen.findByText(/La page s'affichera/)).toBeInTheDocument();
    act(() => {
      useBrowserLive.getState().setFrame(1, "https://boutique.example/");
    });
    const page = await screen.findByRole("img", { name: "La page que Jarvis manipule" });
    expect(page).toHaveAttribute("src", "blob:page");
    expect(calls.some((c) => c.path === "/v1/browser/live")).toBe(true);
    expect(screen.getByText("https://boutique.example/")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Arrêter" }));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/plans/p1/stop")).toBe(true);
    });
    expect(await screen.findByRole("button", { name: "Arrêt après cette étape" })).toBeDisabled();
  });

  it("une fois arrêté, ni page ni bouton : le compte rendu", () => {
    const stopped: Plan = {
      ...running,
      status: "stopped",
      result: "Panier rempli ; arrêté avant de commander.",
      steps: [step(1, "done"), step(2, "skipped")],
    };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PlanView plan={stopped} compact />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Arrêté par toi")).toBeInTheDocument();
    expect(screen.getByText(stopped.result ?? "")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Arrêter" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Le navigateur de Jarvis, en direct")).not.toBeInTheDocument();
  });
});

describe("Cliquer dans une application (#48)", () => {
  it("montre où Jarvis va cliquer avant la validation", async () => {
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => "blob:capture"),
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    const click: Plan = {
      ...plan,
      status: "proposed",
      result: null,
      steps: [
        {
          position: 1,
          tool: "cliquer_ecran",
          arguments: { repere: "rab12cd" },
          why: "Exporter le rapport.",
          level: 2,
          description: "Cliquer sur le bouton Exporter en PDF (repère rab12cd)",
          status: "pending",
          result: null,
          error: null,
        },
      ],
    };
    const { client, calls } = fakeEngine(() => [200, {}]);
    renderScreen(<PlanView plan={click} compact />, { client });
    const capture = await screen.findByRole("img", { name: /Où Jarvis va cliquer : Cliquer sur/ });
    expect(capture).toHaveAttribute("src", "blob:capture");
    expect(calls.some((c) => c.path === "/v1/desktop/marks/rab12cd")).toBe(true);
    expect(screen.getByRole("button", { name: "Valider" })).toBeInTheDocument();
  });
});
