import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { AgentInfo, AgentRun } from "../../lib/engine/types";
import { fakeEngine, renderScreen } from "../../test/render";
import { AgentsScreen } from "./AgentsScreen";

const AGENTS: AgentInfo[] = [
  {
    name: "dev",
    label: "Développement",
    goal: "comprendre et écrire du code.",
    tools: ["lire_fichier", "executer_code"],
    busy: false,
    run: null,
  },
  {
    name: "recherche",
    label: "Recherche",
    goal: "trouver et recouper l'information.",
    tools: ["recherche_web", "lire_page"],
    busy: true,
    run: "r1",
  },
  {
    name: "coach",
    label: "Coach d'apprentissage",
    goal: "aider à apprendre, une notion à la fois.",
    tools: ["recherche_web"],
    busy: false,
    run: null,
  },
];

function run(over: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "r1",
    agent: "recherche",
    task: "Origine du thé vert",
    status: "en_cours",
    origin: "chat",
    result: null,
    error: null,
    steps: [
      { tool: "recherche_web", description: "Chercher « thé vert origine »", status: "done" },
      { tool: "lire_page", description: "Lire https://exemple.org", status: "running" },
    ],
    plans: [],
    trace_id: null,
    started_at: "2026-10-15T21:00:00Z",
    ended_at: null,
    ...over,
  };
}

function engine(runs: AgentRun[]) {
  return fakeEngine((method, path, body) => {
    if (path === "/v1/agents") return [200, AGENTS];
    if (path.startsWith("/v1/agents/runs")) return [200, runs];
    if (method === "POST") return [202, run({ id: "r2", agent: "dev", ...(body as object) })];
    return [200, []];
  });
}

describe("Agents", () => {
  it("montre chaque agent, ses outils, et la mission en cours en direct", async () => {
    const { client } = engine([run()]);
    renderScreen(<AgentsScreen />, { client });
    const research = await screen.findByRole("article", { name: "Recherche" });
    expect(within(research).getByText("En mission")).toBeInTheDocument();
    expect(within(research).getByText("« Origine du thé vert »")).toBeInTheDocument();
    expect(within(research).getByLabelText("en cours")).toBeInTheDocument();
    expect(within(research).getByText("recherche_web")).toBeInTheDocument();
    const dev = screen.getByRole("article", { name: "Développement" });
    expect(within(dev).getByText("Disponible")).toBeInTheDocument();
    // Un agent occupé ne prend pas d'autre mission.
    expect(within(research).getByRole("button", { name: "Confier" })).toBeDisabled();
  });

  it("confie une tâche à un agent", async () => {
    const user = userEvent.setup();
    const { client, calls } = engine([]);
    renderScreen(<AgentsScreen />, { client });
    const dev = await screen.findByRole("article", { name: "Développement" });
    await user.type(within(dev).getByLabelText("Lui confier une tâche"), "Relis main.py");
    await user.click(within(dev).getByRole("button", { name: "Confier" }));
    await waitFor(() => {
      expect(calls.find((c) => c.method === "POST")).toMatchObject({
        path: "/v1/agents/dev/runs",
        body: { task: "Relis main.py" },
      });
    });
    expect(await screen.findByText("Aucune mission pour l'instant")).toBeInTheDocument();
  });

  it("garde l'historique des missions, avec plans et trace", async () => {
    const done = run({
      status: "fini",
      result: "Le thé vert vient de Chine.",
      plans: ["p1"],
      trace_id: "t1",
      ended_at: "2026-10-15T21:01:00Z",
      steps: [{ tool: "recherche_web", description: "Chercher", status: "done" }],
    });
    const { client } = engine([done]);
    renderScreen(<AgentsScreen />, { client });
    const history = await screen.findByRole("list", { name: "Missions récentes" });
    expect(within(history).getByText("Terminée")).toBeInTheDocument();
    expect(within(history).getByText("Le thé vert vient de Chine.")).toBeInTheDocument();
    expect(
      within(history).getByRole("link", { name: "Un plan attend ta validation" }),
    ).toHaveAttribute("href", "/actions");
    expect(within(history).getByText(/confiée par Jarvis/)).toBeInTheDocument();
  });
});
