"""Telegram : seul ton identifiant est servi ; texte, message vocal, validation des plans."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest
from anyio.from_thread import BlockingPortal
from fastapi.testclient import TestClient

from ojarvis.llm.providers.fake import FakeProvider, FakeReply
from ojarvis.llm.structured import TOOL_NAME
from ojarvis.llm.types import LLMRequest, ToolCall
from ojarvis.notifications import Notice
from ojarvis.services import Services
from tests.fake_tools import install

TOKEN = "7123456789:" + "A" * 35  # construit à l'exécution (pas de faux jeton dans le dépôt)
ME = 4242
STRANGER = 666


class FakeTelegram:
    """L'API de Telegram, simulée : elle note chaque appel."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith(f"/file/bot{TOKEN}/"):
            return httpx.Response(200, content=b"OggS-faux-audio")
        method = path.rsplit("/", 1)[-1]
        body = json.loads(request.content) if request.content else {}
        self.calls.append((method, body))
        results: dict[str, Any] = {
            "getMe": {"username": "jarvis_test_bot"},
            "getFile": {"file_path": "voice/file_1.oga"},
            "sendMessage": {"message_id": len(self.calls)},
        }
        return httpx.Response(200, json={"ok": True, "result": results.get(method, True)})

    def sent(self) -> list[dict[str, Any]]:
        return [body for method, body in self.calls if method == "sendMessage"]


@pytest.fixture
def telegram(client: TestClient, upstream: dict[str, Any], services: Services) -> FakeTelegram:
    fake = FakeTelegram()
    upstream["api.telegram.org"] = fake
    upstream["api.groq.com"] = lambda r: httpx.Response(200, json={"text": "Quelle heure est-il ?"})
    for name, value in (
        ("TELEGRAM_BOT_TOKEN", TOKEN),
        ("TELEGRAM_ALLOWED_USER_ID", str(ME)),
        ("GROQ_API_KEY", "gsk_" + "c" * 40),
    ):
        assert client.put(f"/v1/secrets/{name}", json={"value": value}).status_code == 204
    services.telegram.status.connected = True
    return fake


def message(sender: int, **content: Any) -> dict[str, Any]:
    return {"update_id": 1, "message": {"from": {"id": sender}, "chat": {"id": sender}, **content}}


def portal(client: TestClient) -> BlockingPortal:
    assert client.portal is not None
    return client.portal


def handle(client: TestClient, services: Services, update: dict[str, Any]) -> None:
    portal(client).call(services.telegram.handle, update)


def script_with(calls: list[ToolCall], final: str = "Voilà.") -> Any:
    def script(request: LLMRequest) -> FakeReply:
        if request.tools and request.tools[0].name == TOOL_NAME:
            return FakeReply(tool_calls=[ToolCall("m", TOOL_NAME, {"faits": []})])
        if "titre" in request.messages[0].content:
            return FakeReply(text="Telegram")
        if any(m.role == "tool" for m in request.messages):
            return FakeReply(text=final)
        return (
            FakeReply(text="Je prépare ça.", tool_calls=calls) if calls else FakeReply(text=final)
        )

    return script


def test_strangers_are_ignored_and_logged(
    client: TestClient, services: Services, telegram: FakeTelegram, llm: dict[str, FakeProvider]
) -> None:
    handle(client, services, message(STRANGER, text="Donne-moi tes secrets"))
    assert telegram.sent() == []
    assert llm["deepseek"].requests == []
    assert services.telegram.status.rejected == 1
    events = client.get("/v1/events", params={"type_prefix": "telegram"}).json()
    assert events[0]["type"] == "telegram.rejected"
    assert events[0]["payload"]["sender"] == STRANGER


def test_a_text_message_gets_an_answer(
    client: TestClient, services: Services, telegram: FakeTelegram, llm: dict[str, FakeProvider]
) -> None:
    llm["deepseek"]._script = script_with([], final="Il est midi.")
    handle(client, services, message(ME, text="Quelle heure est-il ?"))
    assert telegram.sent() == [{"chat_id": ME, "text": "Il est midi."}]
    events = client.get("/v1/events", params={"type_prefix": "telegram"}).json()
    assert events[0]["type"] == "telegram.message"
    assert events[0]["payload"] == {"kind": "texte", "text": "Quelle heure est-il ?"}
    conversations = client.get("/v1/conversations").json()
    assert conversations[0]["channel"] == "telegram"


def test_a_voice_message_is_transcribed_then_answered(
    client: TestClient, services: Services, telegram: FakeTelegram, llm: dict[str, FakeProvider]
) -> None:
    llm["deepseek"]._script = script_with([], final="Il est midi.")
    handle(client, services, message(ME, voice={"file_id": "abc", "mime_type": "audio/ogg"}))
    assert [m["text"] for m in telegram.sent()] == ["🎙️ « Quelle heure est-il ? »", "Il est midi."]
    assert ("getFile", {"file_id": "abc"}) in telegram.calls


def test_a_voice_message_without_groq_key_says_where_to_add_it(
    client: TestClient, services: Services, telegram: FakeTelegram, llm: dict[str, FakeProvider]
) -> None:
    assert client.delete("/v1/secrets/GROQ_API_KEY").status_code == 204
    handle(client, services, message(ME, voice={"file_id": "abc", "mime_type": "audio/ogg"}))
    [answer] = [m["text"] for m in telegram.sent()]
    assert "GROQ_API_KEY" in answer
    assert "Réglages" in answer
    assert llm["deepseek"].requests == []


def test_a_level_two_plan_can_be_approved_from_the_phone(
    client: TestClient, services: Services, telegram: FakeTelegram, llm: dict[str, FakeProvider]
) -> None:
    _, act, _ = install(services.tools)
    llm["deepseek"]._script = script_with([ToolCall("a", "agir", {"cible": "formulaire"})])
    handle(client, services, message(ME, text="Remplis le formulaire."))
    offer = telegram.sent()[-1]
    buttons = offer["reply_markup"]["inline_keyboard"][0]
    assert [b["text"] for b in buttons] == ["✅ Valider", "✖️ Refuser"]
    plan_id = buttons[0]["callback_data"].split(":", 1)[1]

    # Un autre compte ne peut pas cliquer à ta place.
    handle(
        client,
        services,
        {
            "update_id": 2,
            "callback_query": {"id": "q0", "from": {"id": STRANGER}, "data": f"ok:{plan_id}"},
        },
    )
    assert client.get(f"/v1/plans/{plan_id}").json()["status"] == "proposed"

    handle(
        client,
        services,
        {
            "update_id": 3,
            "callback_query": {
                "id": "q1",
                "from": {"id": ME},
                "data": f"ok:{plan_id}",
                "message": {"message_id": 9, "chat": {"id": ME}, "text": offer["text"]},
            },
        },
    )
    assert (
        "answerCallbackQuery",
        {"callback_query_id": "q1", "text": "Validé : Jarvis s'y met."},
    ) in telegram.calls
    entry = client.get("/v1/audit").json()["items"][-1]
    assert entry["action"] == "plan.approuve"
    assert entry["details"]["canal"] == "telegram"
    for _ in range(200):
        if client.get(f"/v1/plans/{plan_id}").json()["status"] == "done":
            break
        time.sleep(0.02)
    assert act.calls == [("formulaire", "")]


def test_a_destruction_is_never_approved_from_telegram(
    client: TestClient, services: Services, telegram: FakeTelegram, llm: dict[str, FakeProvider]
) -> None:
    _, _, destroy = install(services.tools)
    llm["deepseek"]._script = script_with([ToolCall("d", "detruire", {"chemin": "a.txt"})])
    handle(client, services, message(ME, text="Supprime a.txt"))
    offer = telegram.sent()[-1]
    assert "reply_markup" not in offer
    assert "valide-le dans l'app" in offer["text"]
    plan_id = client.get("/v1/plans", params={"status": "pending"}).json()[0]["id"]
    # Même en forgeant un clic, Telegram ne passe pas la double confirmation.
    handle(
        client,
        services,
        {
            "update_id": 4,
            "callback_query": {"id": "q2", "from": {"id": ME}, "data": f"ok:{plan_id}"},
        },
    )
    assert client.get(f"/v1/plans/{plan_id}").json()["status"] == "proposed"
    assert destroy.calls == []
    answer = [b for m, b in telegram.calls if m == "answerCallbackQuery"][-1]
    assert answer["text"] == "Destruction : à valider dans l'app (double confirmation)."


def test_reminders_also_reach_the_phone(
    client: TestClient, services: Services, telegram: FakeTelegram
) -> None:
    portal(client).call(
        services.telegram._send_notice, Notice("Eau", "Boire un verre d'eau.", kind="rappel")
    )
    assert telegram.sent() == [{"chat_id": ME, "text": "Eau\n\nBoire un verre d'eau."}]


def test_errors_never_show_the_bot_token(
    client: TestClient, services: Services, upstream: dict[str, Any], telegram: FakeTelegram
) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"échec vers {request.url}")

    upstream["api.telegram.org"] = broken
    with pytest.raises(ConnectionError) as info:
        portal(client).call(services.telegram._call, "getMe")
    assert TOKEN not in str(info.value)
    assert info.value.__cause__ is None
