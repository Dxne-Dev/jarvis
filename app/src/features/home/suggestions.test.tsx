import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { SuggestionInfo } from "../../lib/engine/types";
import { fakeEngine, renderScreen } from "../../test/render";
import { Suggestions } from "./Suggestions";

const IDEA: SuggestionInfo = {
  id: "s1",
  kind: "repetition",
  title: "Tu m'as demandé « Résume les issues de O-jarvis » 3 jours différents ce mois-ci.",
  detail: "Souvent vers 8 h 10.",
  options: [
    { id: "automatisation", label: "En faire une automatisation" },
    { id: "skill", label: "En faire un skill" },
  ],
  confidence: 0.85,
  status: "nouvelle",
  conversation_id: null,
  created_at: "2026-10-15T06:10:00Z",
};

describe("Suggestions de l'accueil", () => {
  it("montre l'idée et sa confiance, puis ouvre la conversation choisie", async () => {
    const user = userEvent.setup();
    const opened: string[] = [];
    const { client, calls } = fakeEngine((method, path) => {
      if (path === "/v1/suggestions") return [200, [IDEA]];
      if (path.endsWith("/accept"))
        return [200, { ...IDEA, status: "acceptee", conversation_id: "c9" }];
      return [200, { ...IDEA, status: "ecartee" }];
    });
    renderScreen(
      <Suggestions
        onOpen={(id) => {
          opened.push(id);
        }}
      />,
      { client },
    );
    const panel = await screen.findByRole("region", { name: "Jarvis te suggère" });
    expect(within(panel).getByText(/3 jours différents/)).toBeInTheDocument();
    expect(within(panel).getByText("Souvent vers 8 h 10. · Confiance : 85 %")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "En faire une automatisation" }));
    await waitFor(() => {
      expect(opened).toEqual(["c9"]);
    });
    expect(calls.find((c) => c.path.endsWith("/accept"))?.body).toEqual({
      option: "automatisation",
    });
    await user.click(within(panel).getByRole("button", { name: "Écarter" }));
    await waitFor(() => {
      expect(calls.some((c) => c.path === "/v1/suggestions/s1/dismiss")).toBe(true);
    });
  });

  it("ne montre rien quand il n'y a pas d'idée", async () => {
    const { client } = fakeEngine(() => [200, []]);
    const { container } = renderScreen(<Suggestions onOpen={() => undefined} />, { client });
    await waitFor(() => {
      expect(container.querySelector("section")).toBeNull();
    });
  });
});
