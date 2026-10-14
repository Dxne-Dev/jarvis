"""Vérification réelle d'une clé : un appel léger, sans effet de bord, chez le fournisseur.

Aucune URL ni réponse brute n'est journalisée (le jeton Telegram fait partie de l'URL).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ojarvis.security.secrets import SecretStore

CARTESIA_VERSION = "2026-08-14"
NOTION_VERSION = "2022-06-28"


@dataclass(frozen=True, slots=True)
class CheckResult:
    ok: bool
    detail: str
    latency_ms: int | None = None


Getter = Callable[[str], str | None]
Check = Callable[[httpx.AsyncClient, Getter], Awaitable[CheckResult]]


def _status_detail(response: httpx.Response) -> str:
    if response.status_code in (401, 403):
        return "Clé refusée par le service."
    if response.status_code == 429:
        return "Service saturé (limite de débit), réessaie plus tard."
    return f"Réponse inattendue (HTTP {response.status_code})."


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {"_list": data}


async def _bearer_get(
    client: httpx.AsyncClient, url: str, key: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await client.get(url, headers={"Authorization": f"Bearer {key}", **(headers or {})})


async def check_deepseek(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("DEEPSEEK_API_KEY") or ""
    response = await _bearer_get(client, "https://api.deepseek.com/models", key)
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    models = [m.get("id") for m in _json(response).get("data", []) if isinstance(m, dict)]
    return CheckResult(True, f"Modèles : {', '.join(str(m) for m in models) or 'aucun'}.")


async def check_openrouter(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("OPENROUTER_API_KEY") or ""
    response = await _bearer_get(client, "https://openrouter.ai/api/v1/key", key)
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    data = _json(response).get("data", {})
    free = isinstance(data, dict) and data.get("is_free_tier")
    return CheckResult(True, "Offre gratuite (modèles :free)." if free else "Clé avec crédit.")


async def check_openai(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("OPENAI_API_KEY") or ""
    response = await _bearer_get(client, "https://api.openai.com/v1/models", key)
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    return CheckResult(True, "Clé acceptée.")


async def check_anthropic(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("ANTHROPIC_API_KEY") or ""
    response = await client.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    return CheckResult(True, "Clé acceptée.")


async def check_cartesia(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("CARTESIA_API_KEY") or ""
    response = await _bearer_get(
        client,
        "https://api.cartesia.ai/voices?language=fr&limit=20",
        key,
        {"Cartesia-Version": CARTESIA_VERSION},
    )
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    body = _json(response)
    voices = body.get("data", body.get("_list", []))
    count = len(voices) if isinstance(voices, list) else 0
    return CheckResult(True, f"{count} voix françaises disponibles.")


async def check_tavily(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("TAVILY_API_KEY") or ""
    response = await _bearer_get(client, "https://api.tavily.com/usage", key)
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    account = _json(response).get("account", {})
    if isinstance(account, dict) and account.get("plan_limit"):
        return CheckResult(
            True, f"Recherches ce mois : {account.get('plan_usage', 0)} / {account['plan_limit']}."
        )
    return CheckResult(True, "Clé acceptée.")


async def check_github(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("GITHUB_TOKEN") or ""
    response = await _bearer_get(
        client,
        "https://api.github.com/user",
        key,
        {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
    )
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    return CheckResult(True, f"Compte {_json(response).get('login', '?')}.")


async def check_notion(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    key = get("NOTION_TOKEN") or ""
    response = await _bearer_get(
        client, "https://api.notion.com/v1/users/me", key, {"Notion-Version": NOTION_VERSION}
    )
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    bot = _json(response).get("bot", {})
    workspace = bot.get("workspace_name") if isinstance(bot, dict) else None
    return CheckResult(True, f"Espace : {workspace or 'inconnu'}.")


async def check_google(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    """Échange d'un faux code : `invalid_grant` prouve que le client OAuth est reconnu."""
    client_id, secret = get("GOOGLE_CLIENT_ID"), get("GOOGLE_CLIENT_SECRET")
    if not client_id or not secret:
        return CheckResult(False, "Il faut l'identifiant et le secret du client.")
    response = await client.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "authorization_code",
            "code": "4/ojarvis-verification",
            "client_id": client_id,
            "client_secret": secret,
            "redirect_uri": "http://127.0.0.1:53682",
        },
    )
    error = _json(response).get("error")
    if error == "invalid_grant":
        return CheckResult(True, "Client OAuth reconnu.")
    if error in ("invalid_client", "unauthorized_client"):
        return CheckResult(False, "Identifiant ou secret du client refusé.")
    return CheckResult(False, f"Réponse inattendue ({error or response.status_code}).")


async def check_telegram(client: httpx.AsyncClient, get: Getter) -> CheckResult:
    token = get("TELEGRAM_BOT_TOKEN") or ""
    try:
        response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
    except httpx.HTTPError:
        return CheckResult(False, "Telegram injoignable.")
    if response.status_code != 200:
        return CheckResult(False, _status_detail(response))
    result = _json(response).get("result", {})
    username = result.get("username") if isinstance(result, dict) else None
    return CheckResult(True, f"Bot @{username}.")


async def check_telegram_user(_: httpx.AsyncClient, get: Getter) -> CheckResult:
    value = get("TELEGRAM_ALLOWED_USER_ID") or ""
    if value.isdigit():
        return CheckResult(True, "Identifiant numérique valide.")
    return CheckResult(False, "L'identifiant doit être un nombre.")


CHECKS: dict[str, Check] = {
    "DEEPSEEK_API_KEY": check_deepseek,
    "OPENROUTER_API_KEY": check_openrouter,
    "OPENAI_API_KEY": check_openai,
    "ANTHROPIC_API_KEY": check_anthropic,
    "CARTESIA_API_KEY": check_cartesia,
    "TAVILY_API_KEY": check_tavily,
    "GITHUB_TOKEN": check_github,
    "NOTION_TOKEN": check_notion,
    "GOOGLE_CLIENT_ID": check_google,
    "GOOGLE_CLIENT_SECRET": check_google,
    "TELEGRAM_BOT_TOKEN": check_telegram,
    "TELEGRAM_ALLOWED_USER_ID": check_telegram_user,
}


async def run_check(name: str, store: SecretStore, client: httpx.AsyncClient) -> CheckResult:
    if store.get(name) is None:
        return CheckResult(False, "Aucune valeur enregistrée.")
    check = CHECKS[name]
    start = time.perf_counter()
    try:
        result = await check(client, store.get)
    except httpx.TimeoutException:
        result = CheckResult(False, "Le service n'a pas répondu à temps.")
    except httpx.HTTPError:
        result = CheckResult(False, "Service injoignable (réseau).")
    latency = int((time.perf_counter() - start) * 1000)
    return CheckResult(result.ok, result.detail, latency)
