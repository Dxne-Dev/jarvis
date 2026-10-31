"""Voix : état du pipeline, parler sans mot de réveil, couper Jarvis, périphériques, voix."""

from __future__ import annotations

from typing import Any

import anyio.to_thread
import httpx
from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from ojarvis.api.deps import ServicesDep
from ojarvis.core.errors import ConflictError, UnavailableError, UpstreamError
from ojarvis.voice.devices import list_devices

router = APIRouter(prefix="/v1/voice")


@router.get("/status")
async def voice_status(services: ServicesDep) -> dict[str, Any]:
    return services.voice.snapshot()


@router.post("/listen", status_code=204)
async def listen(services: ServicesDep) -> Response:
    """Comme « Hey Jarvis » : bouton micro de l'interface, raccourci clavier global."""
    if not services.voice.listen_now():
        raise ConflictError("La voix n'est pas active.", code="voice_off")
    return Response(status_code=204)


@router.post("/stop", status_code=204)
async def stop(services: ServicesDep) -> Response:
    await services.voice.interrupt()
    return Response(status_code=204)


@router.get("/devices")
async def devices() -> dict[str, list[dict[str, str]]]:
    try:
        return await anyio.to_thread.run_sync(list_devices)
    except Exception as exc:
        raise UnavailableError(
            "Périphériques audio inaccessibles.", code="audio_unavailable"
        ) from exc


@router.get("/voices")
async def voices(services: ServicesDep) -> list[dict[str, Any]]:
    try:
        return await services.voice.voices()
    except httpx.HTTPError as exc:
        raise UpstreamError("Liste des voix Cartesia indisponible.", code="cartesia_error") from exc


class DictateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_s: int = Field(default=30, ge=5, le=120)


@router.post("/dictate")
async def dictate(body: DictateIn, services: ServicesDep) -> dict[str, str]:
    """Le terminal écoute une phrase (#10) : elle lui revient, au lieu d'une réponse parlée."""
    text = await services.voice.dictate(body.timeout_s)
    if text is None:
        raise ConflictError(
            "La voix est éteinte : allume-la dans Réglages (Voix), avec l'app ouverte."
        )
    return {"text": text}


class SayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)


@router.post("/say")
async def say(body: SayIn, services: ServicesDep) -> dict[str, bool]:
    """Dire à voix haute une réponse du terminal, si la voix est en veille."""
    return {"spoken": services.voice.say(body.text)}
