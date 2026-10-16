import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Plan } from "../../lib/engine/types";
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
