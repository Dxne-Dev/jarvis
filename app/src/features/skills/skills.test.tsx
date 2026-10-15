import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { McpRegistryEntry, McpServerInfo, Skill } from "../../lib/engine/types";
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
    if (path.startsWith("/v1/mcp")) return [200, []];
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

const WIKI: McpRegistryEntry = {
  name: "io.github.cyanheads/wikipedia-mcp-server",
  title: "wikipedia-mcp-server",
  description: "Search Wikipedia.",
  version: "0.2.6",
  repository: null,
  website: null,
  option: {
    kind: "npm",
    label: "paquet npm @cyanheads/wikipedia-mcp-server@0.2.6",
    where: "sur ce PC, isolé (sans tes fichiers, avec accès à Internet)",
    settings: [
      { name: "WIKI_KEY", description: "Clé.", required: true, secret: true, default: null },
    ],
  },
  why_not: null,
  installed_id: null,
};

function mcpEngine(installed: McpServerInfo[], found: McpRegistryEntry[]) {
  return fakeEngine((method, path, body) => {
    if (path === "/v1/skills") return [200, []];
    if (path === "/v1/mcp/servers" && method === "GET") return [200, installed];
    if (path.startsWith("/v1/mcp/registry")) return [200, found];
    if (path === "/v1/mcp/probe")
      return [
        200,
        {
          ok: true,
          tools: [
            { name: "wikipedia_get_summary", level: 1 },
            { name: "wikipedia_edit", level: 2 },
          ],
          error: null,
          runner: "bubblewrap",
          seconds: 9.8,
        },
      ];
    if (path === "/v1/mcp/servers" && method === "POST") return [201, { ...(body as object) }];
    if (method === "PATCH") return [200, { ...installed[0], ...(body as object) }];
    return [200, []];
  });
}

describe("Serveurs MCP", () => {
  it("cherche, essaie, puis n'installe qu'après confirmation, clé comprise", async () => {
    const user = userEvent.setup();
    const { client, calls } = mcpEngine([], [WIKI]);
    renderScreen(<SkillsScreen />, { client });
    expect(await screen.findByText("Aucun serveur installé")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Chercher dans le registre MCP officiel"), "wiki");
    await user.click(screen.getByRole("button", { name: "Chercher" }));
    const card = await screen.findByRole("article", { name: /wikipedia-mcp-server/ });
    expect(within(card).getByText(/isolé \(sans tes fichiers/)).toBeInTheDocument();
    const key = within(card).getByLabelText(/WIKI_KEY/);
    expect(key).toHaveAttribute("type", "password");
    // Clé obligatoire : pas d'essai sans elle.
    expect(within(card).getByRole("button", { name: "Essayer" })).toBeDisabled();
    await user.type(key, "cle-secrete");
    await user.click(within(card).getByRole("button", { name: "Essayer" }));
    expect(await within(card).findByText(/Essai réussi/)).toHaveTextContent(
      "2 outils : 1 en lecture, 1 en action",
    );
    expect(calls.find((c) => c.path === "/v1/mcp/probe")?.body).toEqual({
      name: WIKI.name,
      version: "0.2.6",
      variables: {},
      secrets: { WIKI_KEY: "cle-secrete" },
    });
    await user.click(within(card).getByRole("button", { name: "Installer…" }));
    const dialog = await screen.findByRole("alertdialog", { name: /Installer « wikipedia/ });
    expect(dialog).toHaveTextContent("Chaque action attendra ta validation");
    await user.click(within(dialog).getByRole("button", { name: "Installer" }));
    await waitFor(() => {
      expect(
        calls.find((c) => c.path === "/v1/mcp/servers" && c.method === "POST")?.body,
      ).toMatchObject({ double_confirm: true, secrets: { WIKI_KEY: "cle-secrete" } });
    });
  });

  it("dit pourquoi un serveur ne peut pas tourner ici", async () => {
    const user = userEvent.setup();
    const blocked = { ...WIKI, option: null, why_not: "Docker est nécessaire pour ce serveur" };
    const { client } = mcpEngine([], [blocked]);
    renderScreen(<SkillsScreen />, { client });
    await user.type(await screen.findByLabelText("Chercher dans le registre MCP officiel"), "wiki");
    await user.click(screen.getByRole("button", { name: "Chercher" }));
    expect(await screen.findByText(/Impossible ici : Docker est nécessaire/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Essayer" })).not.toBeInTheDocument();
  });

  it("montre un serveur installé et le désactive", async () => {
    const user = userEvent.setup();
    const server: McpServerInfo = {
      id: "wikipedia-mcp-server",
      registry_name: WIKI.name,
      title: "wikipedia-mcp-server",
      description: "Search Wikipedia.",
      version: "0.2.6",
      kind: "npm",
      label: "paquet npm @cyanheads/wikipedia-mcp-server@0.2.6",
      where: "sur ce PC, isolé (sans tes fichiers, avec accès à Internet)",
      enabled: true,
      status: "prêt",
      error: null,
      tools: [{ name: "wikipedia_get_summary", level: 1 }],
      variables: {},
      secret_names: ["WIKI_KEY"],
      installed_at: "2026-10-15T21:00:00Z",
    };
    const { client, calls } = mcpEngine([server], []);
    renderScreen(<SkillsScreen />, { client });
    const card = await screen.findByRole("article", { name: /wikipedia-mcp-server/ });
    expect(within(card).getByText(/1 outil : 1 en lecture/)).toBeInTheDocument();
    expect(within(card).getByText(/clé au trousseau : WIKI_KEY/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Désactiver" }));
    await waitFor(() => {
      expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: false });
    });
  });
});
