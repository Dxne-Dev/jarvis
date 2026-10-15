import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { MemoryGraph } from "../../lib/engine/types";
import { fakeEngine, renderScreen } from "../../test/render";
import { layoutGraph } from "./graphLayout";
import { MemoryScreen } from "./MemoryScreen";

const NOW = "2026-10-15T21:00:00Z";

const GRAPH: MemoryGraph = {
  entities: [
    {
      id: 1,
      kind: "moi",
      name: "Moi",
      description: null,
      source: "conversation",
      mentions: 3,
      created_at: NOW,
      last_seen_at: NOW,
    },
    {
      id: 2,
      kind: "projet",
      name: "O-jarvis",
      description: "Assistant personnel.",
      source: "conversation",
      mentions: 3,
      created_at: NOW,
      last_seen_at: NOW,
    },
    {
      id: 3,
      kind: "personne",
      name: "Aïcha",
      description: "Sa sœur.",
      source: "conversation",
      mentions: 2,
      created_at: NOW,
      last_seen_at: NOW,
    },
  ],
  relations: [
    { id: 10, source_id: 1, target_id: 2, label: "travaille sur", mentions: 2, last_seen_at: NOW },
    { id: 11, source_id: 3, target_id: 2, label: "teste", mentions: 1, last_seen_at: NOW },
  ],
};

describe("Placement du graphe", () => {
  it("donne toujours le même dessin, toi au centre, tout dans le cadre", () => {
    const nodes = GRAPH.entities.map((e) => ({ id: e.id, fixed: e.kind === "moi" }));
    const first = layoutGraph(nodes, GRAPH.relations, 760, 480);
    const second = layoutGraph(nodes, GRAPH.relations, 760, 480);
    expect([...first]).toEqual([...second]);
    expect(first.get(1)).toEqual({ x: 380, y: 240 });
    for (const point of first.values()) {
      expect(point.x).toBeGreaterThanOrEqual(48);
      expect(point.x).toBeLessThanOrEqual(760 - 48);
      expect(point.y).toBeGreaterThanOrEqual(48);
      expect(point.y).toBeLessThanOrEqual(480 - 48);
    }
  });
});

describe("Mémoire — graphe", () => {
  it("montre les entités, leurs liens, et permet de corriger", async () => {
    const user = userEvent.setup();
    const { client, calls } = fakeEngine((method, path) => {
      if (path === "/v1/memory/graph") return [200, GRAPH];
      if (path.startsWith("/v1/memory")) return [200, []];
      if (method === "DELETE") return [204, null];
      return [201, {}];
    });
    renderScreen(<MemoryScreen />, { client, path: "/memoire" });
    await user.click(await screen.findByRole("tab", { name: "Graphe" }));
    const list = await screen.findByRole("list", { name: "Entités" });
    expect(within(list).getAllByRole("button")).toHaveLength(3);
    await user.click(within(list).getByRole("button", { name: /Aïcha/ }));
    const details = screen.getByRole("region", { name: "Aïcha" });
    expect(within(details).getByText(/Personne · cité 2 fois/)).toBeInTheDocument();
    const links = within(details).getByRole("list", { name: "Liens de Aïcha" });
    expect(links).toHaveTextContent("Aïcha teste O-jarvis");
    await user.click(within(details).getByRole("button", { name: /Retirer le lien/ }));
    await waitFor(() => {
      expect(
        calls.some((c) => c.method === "DELETE" && c.path === "/v1/memory/graph/relations/11"),
      ).toBe(true);
    });
    await user.type(within(details).getByLabelText("Nouveau lien"), "connaît");
    await user.selectOptions(within(details).getByLabelText("Relier à"), "Moi");
    await user.click(within(details).getByRole("button", { name: "Relier" }));
    await waitFor(() => {
      expect(
        calls.find((c) => c.path === "/v1/memory/graph/relations" && c.method === "POST")?.body,
      ).toEqual({
        source_id: 3,
        label: "connaît",
        target_id: 1,
      });
    });
    const add = screen.getByRole("form", { name: "Ajouter une entité" });
    await user.type(within(add).getByPlaceholderText("Nom"), "Thèse");
    await user.selectOptions(within(add).getByLabelText("Type"), "Projet");
    await user.click(within(add).getByRole("button", { name: "Ajouter" }));
    await waitFor(() => {
      expect(calls.find((c) => c.path === "/v1/memory/graph/entities")?.body).toEqual({
        name: "Thèse",
        kind: "projet",
        description: "",
      });
    });
  });

  it("explique comment remplir un graphe vide", async () => {
    const user = userEvent.setup();
    const { client } = fakeEngine((_method, path) => {
      if (path === "/v1/memory/graph") return [200, { entities: [], relations: [] }];
      return [200, []];
    });
    renderScreen(<MemoryScreen />, { client, path: "/memoire" });
    await user.click(await screen.findByRole("tab", { name: "Graphe" }));
    expect(await screen.findByText("Le graphe est vide")).toBeInTheDocument();
  });
});
