"""Clés des fournisseurs : écriture seule. Une valeur enregistrée n'est jamais renvoyée."""

from __future__ import annotations

import anyio.to_thread
from fastapi import APIRouter, Response

from ojarvis.api.deps import ServicesDep
from ojarvis.api.schemas import CheckOut, SecretIn, SecretStatusOut
from ojarvis.providers.checks import run_check
from ojarvis.security.secrets import SecretStore

router = APIRouter(prefix="/v1/secrets")


@router.get("")
async def list_secrets(services: ServicesDep) -> list[SecretStatusOut]:
    rows = await anyio.to_thread.run_sync(services.secrets.status)
    return [SecretStatusOut.model_validate(r) for r in rows]


@router.put("/{name}", status_code=204)
async def set_secret(name: str, body: SecretIn, services: ServicesDep) -> Response:
    SecretStore.spec(name)
    await anyio.to_thread.run_sync(lambda: services.secrets.set(name, body.value, source="ui"))
    await services.bus.publish("secret.updated", {"name": name, "configured": True})
    return Response(status_code=204)


@router.delete("/{name}", status_code=204)
async def delete_secret(name: str, services: ServicesDep) -> Response:
    SecretStore.spec(name)
    await anyio.to_thread.run_sync(services.secrets.delete, name)
    await services.bus.publish("secret.updated", {"name": name, "configured": False})
    return Response(status_code=204)


@router.post("/{name}/check")
async def check_secret(name: str, services: ServicesDep) -> CheckOut:
    spec = SecretStore.spec(name)
    async with (
        services.tracer.trace(
            f"Vérification {spec.label}", kind="check", meta={"secret": name}
        ) as trace,
        services.tracer.span("appel fournisseur", kind="http", secret=name) as span,
    ):
        result = await run_check(name, services.secrets, services.http)
        span.set(ok=result.ok, latency_ms=result.latency_ms)
        if not result.ok:
            span.fail(result.detail)
            trace.fail(result.detail)
    await anyio.to_thread.run_sync(
        lambda: services.secrets.record_check(
            name, ok=result.ok, detail=result.detail, latency_ms=result.latency_ms
        )
    )
    await services.bus.publish("secret.checked", {"name": name, "ok": result.ok})
    return CheckOut(
        name=name,
        ok=result.ok,
        detail=result.detail,
        latency_ms=result.latency_ms,
        trace_id=trace.id,
    )
