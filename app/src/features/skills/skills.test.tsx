import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Skill } from "../../lib/engine/types";
import { fakeEngine, renderScreen } from "../../test/render";
import { SkillsScreen } from "./SkillsScreen";

function skill(over: Partial<Skill> = {}): Skill {
  return {
    id: "s1",
    name: "jours-entre-dates",
    version: "1.0.0",
    description: "Compte les jours entre deux dates.",
    instructions: "Pour toute question de durée entre deux dates.",
    status: "pret",
    tools: [
      {
        name: "jours_entre_dates__jours_entre",
        tool: "jours_entre",
        description: "Jours entre deux dates AAAA-MM-JJ.",
        parameters: { type: "object" },
      },
    ],
    permissions: "calcul en bac à sable : ni Internet, ni tes fichiers, ni tes clés",
    report: {
      ok: true,
      cases: [
        { name: "test_un_jour", ok: true, detail: "" },
        { name: "test_une_annee", ok: true, detail: "" },
      ],
      error: null,
      backend: "docker",
      duration_ms: 1400,
      summary: "2/2 tests réussis",
    },
    created_by: "jarvis",
    conversation_id: null,
    created_at: "2026-10-15T20:00:00Z",
    tested_at: "2026-10-15T20:00:02Z",
    activated_at: null,
    digest: "a".repeat(64),
    ...over,
  };
}

function engine(list: Skill[]) {
  return fakeEngine((method, path) => {
    if (path === "/v1/skills" && method === "GET") return [200, list];
    if (path === "/v1/skills/s1" && method === "GET")
      return [
        200,
        { ...list[0], code: "def jours_entre(debut, fin): ...", tests: "def test_x(): ..." },
      ];
    if (path === "/v1/skills/s1/activate") return [200, { ...list[0], status: "actif" }];
    return [200, list[0]];
  });
}

describe("Skills et plugins", () => {
  it("explique comment obtenir un premier skill", async () => {
    const { client } = engine([]);
    renderScreen(<SkillsScreen />, { client });
    expect(await screen.findByText("Aucun skill pour l'instant")).toBeInTheDocument();
    expect(screen.getByText(/compte les jours entre deux dates/)).toBeInTheDocument();
  });

  it("montre outils, permissions et tests, puis n'active qu'après confirmation", async () => {
    const user = userEvent.setup();
    const { client, calls } = engine([skill()]);
    renderScreen(<SkillsScreen />, { client });
    const card = await screen.findByRole("article", { name: /jours-entre-dates/ });
    expect(within(card).getByText("Prêt à activer")).toBeInTheDocument();
    expect(within(card).getByText("jours_entre")).toBeInTheDocument();
    expect(within(card).getByText(/ni Internet, ni tes fichiers/)).toBeInTheDocument();
    expect(within(card).getByText(/2\/2 tests réussis/)).toBeInTheDocument();
    expect(within(card).getAllByLabelText("réussi")).toHaveLength(2);

    await user.click(within(card).getByRole("button", { name: /Voir le code/ }));
    expect(await within(card).findByText(/def jours_entre/)).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Activer…" }));
    const dialog = await screen.findByRole("alertdialog", {
      name: /Activer « jours-entre-dates »/,
    });
    expect(dialog).toHaveTextContent("sans te demander");
    await user.click(within(dialog).getByRole("button", { name: "Annuler" }));
    expect(calls.some((c) => c.path.endsWith("/activate"))).toBe(false);

    await user.click(within(card).getByRole("button", { name: "Activer…" }));
    await user.click(await screen.findByRole("button", { name: "Activer" }));
    await waitFor(() => {
      expect(calls.find((c) => c.path.endsWith("/activate"))?.body).toEqual({
        double_confirm: true,
      });
    });
  });

  it("n'offre pas d'activer un skill dont les tests échouent", async () => {
    const failing = skill({
      status: "echec",
      report: {
        ok: false,
        cases: [{ name: "test_une_annee", ok: false, detail: "== 366" }],
        error: null,
        backend: "docker",
        duration_ms: 900,
        summary: "0/1 tests réussis",
      },
    });
    const { client } = engine([failing]);
    renderScreen(<SkillsScreen />, { client });
    const card = await screen.findByRole("article", { name: /jours-entre-dates/ });
    expect(within(card).getByText("Tests en échec")).toBeInTheDocument();
    expect(within(card).getByText("== 366")).toBeInTheDocument();
    expect(within(card).getByLabelText("échoué")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Activer…" })).not.toBeInTheDocument();
  });
});
