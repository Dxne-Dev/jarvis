import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Automation } from "../../lib/engine/types";
import { fakeEngine, renderScreen } from "../../test/render";
import { AutomationsScreen } from "./AutomationsScreen";

const EVENTS = [
  { type: "plan.finished", label: "Quand un plan se termine" },
  { type: "telegram.message", label: "Quand un message Telegram arrive" },
];

function automation(over: Partial<Automation> = {}): Automation {
  return {
    id: "a1",
    name: "Eau",
    trigger: {
      type: "horaire",
      quand: { type: "chaque_jour", heure: "08:00", jours: [0, 1, 2, 3, 4, 5, 6] },
    },
    action: { type: "rappel", texte: "Boire un verre d'eau." },
    when: "Tous les jours à 8 h 00",
    what: "Rappel : « Boire un verre d'eau. »",
    enabled: true,
    one_shot: false,
    created_by: "jarvis",
    created_at: "2026-10-15T06:00:00Z",
    updated_at: "2026-10-15T06:00:00Z",
    next_run_at: "2026-10-16T06:00:00Z",
    last_run_at: null,
    last_status: null,
    run_count: 0,
    conversation_id: null,
    ...over,
  };
}

function engine(list: Automation[]) {
  return fakeEngine((method, path, body) => {
    if (path === "/v1/automations/events") return [200, EVENTS];
    if (path === "/v1/automations" && method === "GET") return [200, list];
    if (path === "/v1/automations" && method === "POST")
      return [201, automation({ ...(body as object), id: "new" })];
    if (method === "PATCH") return [200, { ...list[0], ...(body as object) }];
    if (method === "DELETE") return [204, null];
    if (path.endsWith("/runs")) return [200, []];
    if (path.endsWith("/run")) return [200, { id: "r1", status: "pending" }];
    return [200, []];
  });
}

describe("Automatisations", () => {
  it("invite à créer une première automatisation", async () => {
    const { client } = engine([]);
    renderScreen(<AutomationsScreen />, { client });
    expect(await screen.findByText("Aucune automatisation")).toBeInTheDocument();
    expect(screen.getByText(/rappelle-moi tous les matins à 8 h/)).toBeInTheDocument();
  });

  it("crée un rappel certains jours à une heure locale", async () => {
    const { client, calls } = engine([]);
    const user = userEvent.setup();
    renderScreen(<AutomationsScreen />, { client });
    await user.click(await screen.findByRole("button", { name: "Créer une automatisation" }));
    const form = screen.getByRole("form", { name: "Nouvelle automatisation" });
    await user.type(within(form).getByLabelText("Nom"), "Sport");
    await user.selectOptions(within(form).getByLabelText("Fréquence"), "certains_jours");
    const time = within(form).getByLabelText("Heure");
    await user.clear(time);
    await user.type(time, "18:30");
    // Lundi à vendredi cochés par défaut : on retire le vendredi, on ajoute le samedi.
    await user.click(within(form).getByRole("checkbox", { name: "vendredi" }));
    await user.click(within(form).getByRole("checkbox", { name: "samedi" }));
    await user.type(within(form).getByLabelText("Message du rappel"), "Séance de sport.");
    await user.click(within(form).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => {
      const call = calls.find((c) => c.method === "POST" && c.path === "/v1/automations");
      expect(call?.body).toEqual({
        name: "Sport",
        trigger: {
          type: "horaire",
          quand: { type: "chaque_jour", heure: "18:30", jours: [0, 1, 2, 3, 5] },
        },
        action: { type: "rappel", texte: "Séance de sport." },
      });
    });
  });

  it("crée une tâche sur un événement", async () => {
    const { client, calls } = engine([]);
    const user = userEvent.setup();
    renderScreen(<AutomationsScreen />, { client });
    await user.click(await screen.findByRole("button", { name: "Créer une automatisation" }));
    const form = screen.getByRole("form", { name: "Nouvelle automatisation" });
    await user.type(within(form).getByLabelText("Nom"), "Telegram");
    await user.click(within(form).getByRole("radio", { name: "Quand quelque chose arrive" }));
    await user.selectOptions(within(form).getByLabelText("Événement"), "telegram.message");
    await user.click(within(form).getByRole("radio", { name: "Une tâche pour Jarvis" }));
    await user.type(within(form).getByLabelText("Ce que Jarvis doit faire"), "Résume le message.");
    await user.click(within(form).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => {
      const call = calls.find((c) => c.method === "POST");
      expect(call?.body).toEqual({
        name: "Telegram",
        trigger: { type: "evenement", evenement: "telegram.message" },
        action: { type: "consigne", texte: "Résume le message." },
      });
    });
  });

  it("montre l'horaire, la prochaine fois, et se désactive, se lance ou se supprime", async () => {
    const { client, calls } = engine([automation()]);
    const user = userEvent.setup();
    renderScreen(<AutomationsScreen />, { client });
    const card = await screen.findByRole("article", { name: "Eau" });
    expect(within(card).getByText("Tous les jours à 8 h 00")).toBeInTheDocument();
    expect(within(card).getByText(/Prochaine fois : vendredi 16 octobre/)).toBeInTheDocument();
    expect(within(card).getByText(/Créée par Jarvis à ta demande/)).toBeInTheDocument();
    await user.click(within(card).getByRole("switch", { name: "Désactiver Eau" }));
    await waitFor(() => {
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: false });
    });
    await user.click(within(card).getByRole("button", { name: "Lancer maintenant" }));
    await waitFor(() => {
      expect(calls.some((c) => c.method === "POST" && c.path === "/v1/automations/a1/run")).toBe(
        true,
      );
    });
    await user.click(within(card).getByRole("button", { name: "Supprimer" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Garder" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(within(card).getByRole("button", { name: "Supprimer" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Supprimer" }),
    );
    await waitFor(() => {
      expect(calls.some((c) => c.method === "DELETE" && c.path === "/v1/automations/a1")).toBe(
        true,
      );
    });
  });
});
