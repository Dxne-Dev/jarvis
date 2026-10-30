"""Autorisations du navigateur de Jarvis : domaines où il utilise tes sessions.

Deux façons d'en ajouter, toutes deux à ton initiative (Réglages > Navigateur) :
- te connecter toi-même dans sa fenêtre ;
- importer les cookies d'un domaine depuis Chrome, Chromium ou Brave.
Chaque ajout et chaque révocation est écrit au journal immuable (niveau 2).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import anyio.to_thread
from sqlalchemy import select
from sqlalchemy.orm import Session

from ojarvis.audit.journal import AuditJournal
from ojarvis.browser.cookies import (
    BROWSERS,
    BrowserSource,
    find_source,
    find_sources,
    read_cookies,
    safe_storage_password,
)
from ojarvis.browser.live import LiveView
from ojarvis.browser.proxy import GuardProxy
from ojarvis.browser.session import BrowserSession
from ojarvis.browser.vault import CookieVault, normalize_domain
from ojarvis.core.clock import utc_now
from ojarvis.core.errors import NotFoundError
from ojarvis.core.logs import get_logger
from ojarvis.db.engine import Database
from ojarvis.db.models import CookieGrant
from ojarvis.events.bus import EventBus

log = get_logger(__name__)


@dataclass(frozen=True)
class GrantRecord:
    domain: str
    source: str
    imported_at: datetime
    count: int


class BrowserAccess:
    def __init__(
        self,
        *,
        db: Database,
        vault: CookieVault,
        journal: AuditJournal,
        bus: EventBus,
        home: Path,
        allowed_hosts: tuple[str, ...] = (),
        proxy: GuardProxy | None = None,
        visible: Callable[[], bool] = lambda: False,
    ) -> None:
        self._db = db
        self._vault = vault
        self._journal = journal
        self._bus = bus
        self._home = home
        self._granted: set[str] = set()
        self._login_domain: str | None = None
        self._finish_lock = asyncio.Lock()
        self.session = BrowserSession(
            vault,
            allowed_hosts=allowed_hosts,
            granted=lambda: set(self._granted),
            proxy=proxy,
            visible=visible,
            live=LiveView(self._frame_ready),
        )

    async def _frame_ready(self, seq: int, url: str) -> None:
        """Une nouvelle image de la page de Jarvis attend l'app (GET /v1/browser/live)."""
        await self._bus.publish("browser.frame", {"seq": seq, "url": url}, persist=False)

    async def start(self) -> None:
        self._granted = {g.domain for g in await self.grants()}

    def granted(self) -> set[str]:
        return set(self._granted)

    @property
    def login_domain(self) -> str | None:
        return self._login_domain if self.session.login_active else None

    async def grants(self) -> list[GrantRecord]:
        def read(session: Session) -> list[GrantRecord]:
            rows = session.scalars(
                select(CookieGrant)
                .where(CookieGrant.revoked_at.is_(None))
                .order_by(CookieGrant.domain)
            )
            return [GrantRecord(r.domain, r.source, r.imported_at, r.count) for r in rows]

        return await self._db.run(read)

    async def sources(self) -> list[BrowserSource]:
        return await anyio.to_thread.run_sync(find_sources, self._home)

    async def _record(self, domain: str, source: str, count: int) -> GrantRecord:
        now = utc_now()

        def write(session: Session) -> GrantRecord:
            row = session.get(CookieGrant, domain)
            if row is None:
                row = CookieGrant(domain=domain, source=source, imported_at=now, count=count)
                session.add(row)
            row.source = source
            row.imported_at = now
            row.count = count
            row.revoked_at = None
            return GrantRecord(domain, source, now, count)

        record = await self._db.run(write)
        self._granted.add(domain)
        await self._bus.publish("browser.grants_changed", {"domain": domain, "granted": True})
        return record

    async def import_cookies(self, source_id: str, raw_domain: str) -> GrantRecord:
        domain = normalize_domain(raw_domain)
        source = await anyio.to_thread.run_sync(find_source, self._home, source_id)
        application = BROWSERS[source.browser][2]
        password = await anyio.to_thread.run_sync(safe_storage_password, application)
        cookies = await anyio.to_thread.run_sync(
            lambda: read_cookies(source, domain, password=password)
        )
        if not cookies:
            raise NotFoundError(f"Aucun cookie pour {domain} dans {source.label}.")
        await self.session.change_vault(lambda: self._vault.merge(cookies))
        await self._journal.append(
            actor="utilisateur",
            action="navigateur.cookies_importes",
            level=2,
            summary=f"Cookies de {domain} importés depuis {source.label}",
            details={"domaine": domain, "source": source.id, "nombre": len(cookies)},
        )
        log.info("browser_cookies_imported", domain=domain, count=len(cookies))
        return await self._record(domain, source.browser, len(cookies))

    async def revoke(self, raw_domain: str) -> int:
        domain = normalize_domain(raw_domain)
        if domain not in self._granted:
            raise NotFoundError("Aucune autorisation pour ce domaine.")
        removed = await self.session.change_vault(lambda: self._vault.remove_domain(domain))
        now = utc_now()

        def write(session: Session) -> None:
            row = session.get(CookieGrant, domain)
            if row is not None:
                row.revoked_at = now

        await self._db.run(write)
        self._granted.discard(domain)
        await self._journal.append(
            actor="utilisateur",
            action="navigateur.cookies_revoques",
            level=2,
            summary=f"Accès à ta session sur {domain} révoqué",
            details={"domaine": domain, "cookies_effaces": removed},
        )
        await self._bus.publish("browser.grants_changed", {"domain": domain, "granted": False})
        return removed

    async def login_start(self, url: str) -> str:
        domain = normalize_domain(url)
        target = url if "://" in url else f"https://{url}"
        await self.session.login_start(target, on_closed=self._closed_by_user)
        self._login_domain = domain
        await self._bus.publish("browser.login_started", {"domain": domain}, persist=False)
        return domain

    async def _closed_by_user(self) -> None:
        # NotFoundError : déjà terminée par le bouton « Terminer ».
        with contextlib.suppress(NotFoundError):
            await self.login_finish()

    async def login_finish(self) -> GrantRecord | None:
        async with self._finish_lock:
            domain = self._login_domain
            state = await self.session.login_finish()
            self._login_domain = None
            if domain is None:
                return None
            count = await self.session.change_vault(lambda: self._vault.absorb(state, domain))
            if count == 0:
                await self._bus.publish(
                    "browser.login_finished", {"domain": domain, "ok": False}, persist=False
                )
                return None
            await self._journal.append(
                actor="utilisateur",
                action="navigateur.connexion",
                level=2,
                summary=f"Connexion à {domain} gardée par le navigateur de Jarvis",
                details={"domaine": domain, "nombre": count},
            )
            record = await self._record(domain, "connexion", count)
            await self._bus.publish(
                "browser.login_finished", {"domain": domain, "ok": True, "count": count}
            )
            return record

    async def close(self) -> None:
        await self.session.close()
