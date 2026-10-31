"""Agents : isolés (objectif, outils, contexte), délégués par un orchestrateur sans logique
métier, soumis à la même porte que Jarvis, visibles en direct."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ojarvis.agents.base import BaseAgent
from ojarvis.agents.orchestrator import Orchestrator
from ojarvis.agents.specialists import STARTERS, CoachAgent, DevAgent, ResearchAgent
from ojarvis.llm.providers.fake import FakeProvider, FakeReply
from ojarvis.llm.structured import TOOL_NAME
from ojarvis.llm.types import LLMRequest, ToolCall
from ojarvis.services import Services
from tests.fake_tools import Act, Destroy, Echo, install
from tests.test_agent_chat import chat


@pytest.fixture
def tools(services: Services, monkeypatch: pytest.MonkeyPatch) -> tuple[Echo, Act, Destroy]:
    echo, act, destroy = install(services.tools)
    # L'agent de recherche reçoit, pour ce test, un outil de lecture et un outil d'action.
    research = services.orchestrator.agents["recherche"]
    monkeypatch.setattr(research, "tools", ("echo", "agir"))
    return echo, act, destroy


def is_agent(request: LLMRequest, label: str) -> bool:
    return bool(request.messages) and f"Tu es l'agent « {label} »" in request.messages[0].content


def test_every_starter_agent_inherits_base_agent() -> None:
    assert {a.name for a in STARTERS} == {"dev", "recherche", "coach"}
    for agent in (DevAgent, ResearchAgent, CoachAgent):
        assert issubclass(agent, BaseAgent)
        assert agent.tools  # des outils propres
        assert "deleguer" not in agent.tools  # un agent ne délègue pas à son tour


def test_the_orchestrator_has_no_business_logic() -> None:
    """Il lance, suit et rapporte : il ne choisit pas l'agent ni ne lit la tâche."""
    import inspect  # noqa: PLC0415

    source = inspect.getsource(Orchestrator)
    for word in ("recherche", "coach", "dev", "complete(", "router"):
        assert word not in source


def test_jarvis_delegates_and_the_agent_works_alone(
    client: TestClient,
    services: Services,
    llm: dict[str, FakeProvider],
    tools: tuple[Echo, Act, Destroy],
) -> None:
    echo, act, _ = tools
    seen: dict[str, list[LLMRequest]] = {"agent": [], "jarvis": []}

    def script(request: LLMRequest) -> FakeReply:  # noqa: PLR0911 - un modèle simulé, deux rôles
        system = request.messages[0].content if request.messages else ""
        if request.tools and request.tools[0].name == TOOL_NAME:
            return FakeReply(tool_calls=[ToolCall("m", TOOL_NAME, {"faits": []})])
        if "titre" in system:
            return FakeReply(text="Agents")
        done = sum(1 for m in request.messages if m.role == "assistant" and m.tool_calls)
        if is_agent(request, "Recherche"):
            seen["agent"].append(request)
            if done == 0:
                return FakeReply(tool_calls=[ToolCall("e", "echo", {"texte": "sources"})])
            if done == 1:
                # Un outil hors de ses attributions est refusé, même s'il existe.
                return FakeReply(tool_calls=[ToolCall("d", "detruire", {"chemin": "x"})])
            if done == 2:
                step = {"outil": "agir", "arguments": {"cible": "notes"}, "pourquoi": "Garder."}
                return FakeReply(
                    tool_calls=[
                        ToolCall("p", "proposer_un_plan", {"titre": "Noter", "etapes": [step]})
                    ]
                )
            return FakeReply(text="Trois sources concordent : le thé vert vient de Chine.")
        seen["jarvis"].append(request)
        if done == 0:
            task = {
                "agent": "recherche",
                "tache": "Trouve l'origine du thé vert, sources à l'appui.",
            }
            return FakeReply(tool_calls=[ToolCall("g", "deleguer", task)])
        return FakeReply(text="Selon l'agent de recherche, le thé vert vient de Chine.")

    llm["deepseek"]._script = script
    events = chat(client, "D'où vient le thé vert ?")
    said = "".join(d["text"] for e, d in events if e == "delta")
    assert "Chine" in said
    # Isolé : l'agent ne voit que sa tâche, avec ses seuls outils.
    first = seen["agent"][0]
    assert [m.content for m in first.messages if m.role == "user"] == [
        "Trouve l'origine du thé vert, sources à l'appui."
    ]
    assert {t.name for t in first.tools} == {"echo", "agir", "proposer_un_plan"}
    assert "D'où vient le thé vert ?" not in str(first.messages)
    assert echo.calls == ["sources"]
    assert act.calls == []  # l'action attend ta validation
    runs = client.get("/v1/agents/runs").json()
    assert len(runs) == 1
    run = runs[0]
    assert (run["agent"], run["status"], run["origin"]) == ("recherche", "fini", "chat")
    assert [(s["tool"], s["status"]) for s in run["steps"]] == [
        ("echo", "done"),
        ("detruire", "failed"),
        ("proposer_un_plan", "proposed"),
    ]
    assert len(run["plans"]) == 1
    plan = client.get(f"/v1/plans/{run['plans'][0]}").json()
    assert plan["status"] == "proposed"
    # Ses appels au modèle sont rangés dans une trace à son nom.
    traces = client.get("/v1/traces").json()
    assert any(t["kind"] == "agent" and t["name"].startswith("Agent Recherche") for t in traces)


def test_a_mission_from_the_screen_runs_in_the_background_with_live_state(
    client: TestClient,
    services: Services,
    llm: dict[str, FakeProvider],
    tools: tuple[Echo, Act, Destroy],
) -> None:
    def script(request: LLMRequest) -> FakeReply:
        done = sum(1 for m in request.messages if m.role == "assistant" and m.tool_calls)
        if is_agent(request, "Recherche") and done == 0:
            return FakeReply(tool_calls=[ToolCall("e", "echo", {"texte": "a"})])
        return FakeReply(text="Fini.")

    llm["deepseek"]._script = script
    started = client.post("/v1/agents/recherche/runs", json={"task": "Cherche quelque chose."})
    assert started.status_code == 202
    run_id = started.json()["id"]
    run: dict[str, Any] = {}
    for _ in range(100):
        run = client.get(f"/v1/agents/runs/{run_id}").json()
        if run["status"] != "en_cours":
            break
        time.sleep(0.05)
    assert run["status"] == "fini"
    assert run["result"] == "Fini."
    assert run["origin"] == "interface"
    kinds = [e["type"] for e in client.get("/v1/events", params={"limit": 50}).json()]
    assert {"agent.started", "agent.step", "agent.finished"} <= set(kinds)
    agents = {a["name"]: a for a in client.get("/v1/agents").json()}
    assert agents["recherche"]["busy"] is False
    assert agents["coach"]["label"] == "Coach d'apprentissage"
    missing = client.post("/v1/agents/inconnu/runs", json={"task": "Rien du tout."})
    assert missing.status_code == 404


def test_an_interrupted_mission_is_never_replayed(client: TestClient, services: Services) -> None:
    async def scenario() -> str:
        run = await services.orchestrator._open("coach", "Révise les verbes.", "interface")
        services.orchestrator._busy.clear()
        await services.orchestrator.recover()
        return (await services.orchestrator.get(run.id)).status

    assert client.portal is not None
    assert client.portal.call(scenario) == "interrompu"


# --------------------------------------------------------------------------- garde-fous (#15)


def wait_run(client: TestClient, run_id: str) -> dict[str, Any]:
    run: dict[str, Any] = {}
    for _ in range(200):
        run = client.get(f"/v1/agents/runs/{run_id}").json()
        if run["status"] != "en_cours":
            break
        time.sleep(0.05)
    return run


def endless(request: LLMRequest) -> FakeReply:
    """L'agent lit sans fin : seul un garde-fou l'arrête."""
    if is_agent(request, "Recherche"):
        call = ToolCall(f"e{len(request.messages)}", "echo", {"texte": "encore"})
        return FakeReply(text="Je lis encore.", tool_calls=[call])
    return FakeReply(text="Fini.")


def test_a_mission_over_budget_is_suspended_and_you_are_told(
    client: TestClient, llm: dict[str, FakeProvider], tools: tuple[Echo, Act, Destroy]
) -> None:
    echo, _act, _destroy = tools
    llm["deepseek"]._script = endless
    body = {"task": "Cherche sans t'arrêter.", "budget_dollars": 0.000001}
    run = wait_run(client, client.post("/v1/agents/recherche/runs", json=body).json()["id"])
    assert run["status"] == "suspendue"
    assert run["result"].startswith("Mission suspendue : budget de ")
    assert len(echo.calls) == 1  # arrêtée dès le premier tour, sans nouvel appel au modèle
    notices = [
        e["payload"]
        for e in client.get("/v1/events", params={"limit": 50}).json()
        if e["type"] == "notification"
    ]
    assert [n["title"] for n in notices] == ["Mission suspendue : Recherche"]
    assert notices[0]["body"].startswith("budget de ")


def test_repeated_failures_suspend_a_mission(
    client: TestClient, llm: dict[str, FakeProvider], tools: tuple[Echo, Act, Destroy]
) -> None:
    del tools

    def stuck(request: LLMRequest) -> FakeReply:
        if is_agent(request, "Recherche"):
            calls = [ToolCall(f"x{i}", "inconnu", {}) for i in range(3)]  # hors de ses outils
            return FakeReply(text="J'essaie.", tool_calls=calls)
        return FakeReply(text="Fini.")

    llm["deepseek"]._script = stuck
    started = client.post("/v1/agents/recherche/runs", json={"task": "Fais l'impossible."})
    run = wait_run(client, started.json()["id"])
    assert run["status"] == "suspendue"
    assert run["result"].startswith("Mission suspendue : 3 échecs d'affilée.")


def test_a_mission_never_runs_an_action_or_a_destruction_on_its_own(
    client: TestClient,
    services: Services,
    llm: dict[str, FakeProvider],
    tools: tuple[Echo, Act, Destroy],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _echo, act, destroy = tools
    monkeypatch.setattr(services.orchestrator.agents["recherche"], "tools", ("agir", "detruire"))

    def bold(request: LLMRequest) -> FakeReply:
        done = sum(1 for m in request.messages if m.role == "assistant" and m.tool_calls)
        if is_agent(request, "Recherche") and done == 0:
            calls = [
                ToolCall("a", "agir", {"cible": "fiche", "contenu": "modifiée"}),
                ToolCall("d", "detruire", {"chemin": "~/projet/a.txt"}),
            ]
            return FakeReply(text="J'agis.", tool_calls=calls)
        return FakeReply(text="J'ai proposé deux plans.")

    llm["deepseek"]._script = bold
    started = client.post("/v1/agents/recherche/runs", json={"task": "Range et supprime."})
    run = wait_run(client, started.json()["id"])
    # Rien n'est lancé : chaque action devient un plan qui attend ta validation.
    assert act.calls == []
    assert destroy.calls == []
    assert [s["status"] for s in run["steps"]] == ["proposed", "proposed"]
    plans = [client.get(f"/v1/plans/{p}").json() for p in run["plans"]]
    assert sorted((p["max_level"], p["status"]) for p in plans) == [
        (2, "proposed"),
        (3, "proposed"),
    ]
