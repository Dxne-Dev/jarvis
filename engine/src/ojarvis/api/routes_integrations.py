"""Intégrations (GitHub, Notion, Google Agenda) et Telegram : leur état, leur reconnexion."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from ojarvis.api.deps import ServicesDep
from ojarvis.core.errors import NotFoundError
from ojarvis.integrations.manager import SERVERS
from ojarvis.services import Services

router = APIRouter(prefix="/v1")


def _status(services: Services) -> list[dict[str, Any]]:
    rows = services.integrations.status()
    for row in rows:
        if row["name"] == "agenda":
            # Google : des clés (identifiant d'app) puis ta connexion à ton compte.
            row["account_configured"] = services.google.configured()
            row["account_connected"] = services.google.connected
    return rows


@router.get("/integrations")
async def integrations(services: ServicesDep) -> list[dict[str, Any]]:
    return _status(services)


@router.post("/integrations/google/connect")
async def google_connect(services: ServicesDep) -> dict[str, str]:
    """Adresse de la page de consentement de Google, à ouvrir dans le navigateur."""
    return {"url": await services.google.start_login()}


@router.post("/integrations/google/disconnect")
async def google_disconnect(services: ServicesDep) -> list[dict[str, Any]]:
    await services.google.disconnect()
    await services.integrations.reset("agenda")
    services.integrations.set_target("agenda", None)
    return _status(services)


@router.post("/integrations/{name}/reconnect")
async def reconnect(name: str, services: ServicesDep) -> list[dict[str, Any]]:
    if name not in SERVERS:
        raise NotFoundError("Intégration inconnue.")
    await services.integrations.reset(name)
    if name == "agenda":
        services.spawn(services._attach_agenda())
    elif services.integrations.configured(name):
        connection = await services.integrations.connection(name)
        await connection.start(wait=False)
    return _status(services)


@router.get("/telegram")
async def telegram(services: ServicesDep) -> dict[str, Any]:
    """État du bot : jamais son jeton."""
    return asdict(services.telegram.status)
