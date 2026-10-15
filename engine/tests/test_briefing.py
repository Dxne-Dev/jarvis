"""Briefing du matin : à la première session du jour, une seule fois, avec la journée."""

from __future__ import annotations

import time
from typing import Any

from anyio.from_thread import BlockingPortal
from fastapi.testclient import TestClient

from ojarvis.briefing.service import STATE_KEY
from ojarvis.llm.providers.fake import FakeProvider, FakeReply
from ojarvis.llm.structured import TOOL_NAME
from ojarvis.llm.types import LLMRequest, ToolCall
from ojarvis.services import Services

SPOKEN = "Bonjour Octave. Aujourd'hui, ton rappel « Eau » est à dix heures trente."


def portal(client: TestClient) -> BlockingPortal:
    assert client.portal is not None
    return client.portal


def briefing_script(request: LLMRequest) -> FakeReply:
    if request.tools and request.tools[0].name == TOOL_NAME:
        return FakeReply(tool_calls=[ToolCall("m", TOOL_NAME, {"faits": []})])
    if "briefing du matin" in request.messages[0].content:
        return FakeReply(text=SPOKEN)
    return FakeReply(text="ok")


class FakeVoice:
    def __init__(self) -> None:
        self.said: list[str] = []

    def say(self, text: str) -> bool:
        self.said.append(text)
        return True


def wait_delivered(client: TestClient, count: int = 1) -> list[dict[str, Any]]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        events = client.get("/v1/events", params={"type_prefix": "briefing."}).json()
        if len(events) >= count:
            return list(events)
        time.sleep(0.05)
    raise AssertionError("pas de briefing")


def test_the_first_session_of_the_day_plays_the_briefing_once(
    client: TestClient, services: Services, llm: dict[str, FakeProvider]
) -> None:
    llm["deepseek"]._script = briefing_script
    voice = FakeVoice()
    services.briefing._voice = voice  # type: ignore[assignment]
    reminder = {"type": "rappel", "texte": "Boire un verre d'eau."}
    soon = {"type": "horaire", "quand": {"type": "intervalle", "minutes": 5}}
    client.post("/v1/automations", json={"name": "Eau", "trigger": soon, "action": reminder})

    first = client.post("/v1/session", json={}).json()
    assert first["briefing"] is not None
    delivered = wait_delivered(client)[0]
    assert delivered["payload"]["spoken"] is True
    assert voice.said == [SPOKEN]
    conversation = client.get(f"/v1/conversations/{delivered['payload']['conversation_id']}").json()
    assert conversation["title"].startswith("Briefing du ")
    assert conversation["messages"][0]["content"] == SPOKEN
    notice = client.get("/v1/events", params={"type_prefix": "notification"}).json()[0]
    assert notice["payload"]["kind"] == "briefing"

    # La journée est passée au modèle comme des données : rappels du jour, nuit.
    request = next(
        r for r, _ in llm["deepseek"].requests if "briefing du matin" in r.messages[0].content
    )
    user = request.messages[1].content
    assert '<donnees origine="rappels">' in user
    assert "Eau (Rappel : « Boire un verre d'eau. »)" in user
    assert '<donnees origine="nuit">' in user

    # Deuxième ouverture le même jour : pas de second briefing.
    assert client.post("/v1/session", json={}).json() == {"briefing": None}


def test_a_new_day_brings_a_new_briefing_and_it_can_be_turned_off(
    client: TestClient, services: Services, llm: dict[str, FakeProvider]
) -> None:
    llm["deepseek"]._script = briefing_script
    portal(client).call(services.settings.set_state, STATE_KEY, "2026-01-01")
    assert client.post("/v1/session", json={}).json()["briefing"] is not None
    wait_delivered(client)

    portal(client).call(services.settings.set_state, STATE_KEY, "2026-01-01")
    assert client.patch("/v1/settings", json={"briefing_enabled": False}).status_code == 200
    assert client.post("/v1/session", json={}).json() == {"briefing": None}
    # « Écouter le briefing » le joue quand même, à la demande.
    assert client.post("/v1/session", json={"force": True}).json()["briefing"] is not None
    wait_delivered(client, count=2)


def test_without_a_model_the_briefing_still_says_something(
    client: TestClient, services: Services, llm: dict[str, FakeProvider]
) -> None:
    from ojarvis.llm.errors import ProviderUnavailableError  # noqa: PLC0415

    llm["deepseek"]._script = lambda r: FakeReply(error=ProviderUnavailableError("panne"))
    client.post("/v1/session", json={})
    delivered = wait_delivered(client)[0]
    conversation = client.get(f"/v1/conversations/{delivered['payload']['conversation_id']}").json()
    assert conversation["messages"][0]["content"].startswith("Bonjour. Voici ta journée.")
