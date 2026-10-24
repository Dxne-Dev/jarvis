"""Modèles locaux : état, nouvel essai, import de fichiers téléchargés à la main, dossier."""

from __future__ import annotations

from typing import Any

import anyio
from fastapi import APIRouter, Request, Response

from ojarvis.api.deps import ServicesDep
from ojarvis.core.downloads import ChecksumError, files_present
from ojarvis.core.errors import InvalidInputError
from ojarvis.desktop.apps import open_folder
from ojarvis.local_models import describe, import_file, model_set

router = APIRouter(prefix="/v1/local-models")


def _listing(services: ServicesDep) -> list[dict[str, Any]]:
    states = services.model_states()
    models = describe(services.models_dir)
    for model in models:
        model["state"] = "prêt" if model["ready"] else states.get(model["key"], "absent")
    return models


@router.get("")
async def local_models(services: ServicesDep) -> list[dict[str, Any]]:
    return _listing(services)


@router.post("/retry", status_code=202)
async def retry(services: ServicesDep) -> Response:
    """Reprend les téléchargements là où ils se sont arrêtés."""
    services.retry_local_models()
    return Response(status_code=202)


@router.post("/import")
async def import_model_file(request: Request, services: ServicesDep) -> dict[str, Any]:
    """Corps brut : le fichier. Reconnu par son empreinte, quel que soit son nom."""
    try:
        imported = await import_file(services.models_dir, request.stream())
    except ChecksumError as exc:
        raise InvalidInputError(f"Fichier refusé : {exc}.", code="model_rejected") from exc
    model = model_set(imported.key)
    ready = model is not None and files_present(services.models_dir / model.folder, model.files)
    if ready:
        services.retry_local_models()
    return {"key": imported.key, "label": imported.label, "file": imported.file, "ready": ready}


@router.post("/open-folder", status_code=204)
async def open_models_folder(services: ServicesDep) -> Response:
    await anyio.Path(services.models_dir).mkdir(parents=True, exist_ok=True)
    await open_folder(services.models_dir)
    return Response(status_code=204)
