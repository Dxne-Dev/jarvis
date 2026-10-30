"""Le navigateur de Jarvis : Chromium piloté par Playwright, jamais ton propre navigateur.

- Deux contextes isolés : un anonyme (aucun cookie, lecture libre) et un « identité »,
  chargé depuis le coffre avec les seuls domaines que tu as autorisés. Y naviguer, c'est
  utiliser un cookie : niveau 2. Une page anonyme piégée n'a donc jamais tes sessions.
- Tout le trafic passe par un proxy de garde (`proxy.py`) : seules les adresses publiques
  sont joignables, redirections comprises (pas le moteur, la box ni le réseau local).
- On lit le texte visible et la liste des boutons, liens et champs ; on agit en les
  désignant par leur nom, comme on le dirait à quelqu'un.
- Connexion : une fenêtre visible où tu te connectes toi-même ; Jarvis ne tape jamais
  un mot de passe ni un numéro de carte.
- Voir Jarvis agir (#34) : la page est filmée pour l'app (`live.py`), et l'option
  « Montrer le navigateur » ouvre Chromium en fenêtre plutôt qu'en arrière-plan.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import anyio.to_thread

from ojarvis.browser.live import LiveView
from ojarvis.browser.proxy import GuardProxy
from ojarvis.browser.vault import CookieVault, State, in_domain
from ojarvis.core.errors import ConflictError, InvalidInputError, NotFoundError, UnavailableError
from ojarvis.core.logs import get_logger
from ojarvis.tools.guards import check_public_url

log = get_logger(__name__)

MAX_TEXT = 12_000
MAX_ELEMENTS = 60
MAX_LINKS = 80
NAVIGATION_TIMEOUT_MS = 20_000
ACTION_TIMEOUT_MS = 6_000
#: Une app web (React…) dessine sa page après le chargement, ou après un clic sans
#: rechargement : on attend que le texte affiché ne bouge plus (le 30/10, un clic sur
#: « Projets » relisait encore l'accueil). Les durées sont en secondes.
SETTLE_MAX_S = 5.0
SETTLE_STABLE_S = 0.5
#: Après un clic, le temps laissé à la page pour commencer à changer.
SETTLE_CHANGE_S = 1.5
SETTLE_POLL_S = 0.15
#: Au-delà, des éléments du même nom restent ambigus, même visibles.
MAX_TWINS = 10
LOGIN_SNAPSHOT_S = 2.0

_ELEMENTS_SCRIPT = """
(limit) => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
  const name = (el) => clean(
    el.getAttribute('aria-label')
    || (el.labels && el.labels[0] && el.labels[0].innerText)
    || el.getAttribute('placeholder') || el.innerText || el.value || el.name || ''
  );
  const out = [];
  const query = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button]';
  for (const el of document.querySelectorAll(query)) {
    const box = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    if ((box.width === 0 && box.height === 0) || style.visibility === 'hidden') continue;
    const button = el.tagName === 'BUTTON' || el.getAttribute('role') === 'button'
      || ['submit', 'button'].includes(el.type);
    const kind = el.tagName === 'A' ? 'lien' : button ? 'bouton' : 'champ';
    const label = name(el);
    if (label) out.push({kind, label});
    if (out.length >= limit) break;
  }
  return out;
}
"""

_LINKS_SCRIPT = """
(limit) => {
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const text = (a.innerText || a.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim();
    if (!text || !/^https?:/.test(a.href)) continue;
    out.push({text: text.slice(0, 100), href: a.href.slice(0, 300)});
    if (out.length >= limit) break;
  }
  return out;
}
"""

_TABLES_SCRIPT = """
() => Array.from(document.querySelectorAll('table')).slice(0, 5).map((table) =>
  Array.from(table.querySelectorAll('tr')).slice(0, 60).map((tr) =>
    Array.from(tr.querySelectorAll('th, td')).map((c) => c.innerText.replace(/\\s+/g, ' ').trim())
  )
)
"""

#: Champs que Jarvis ne remplit jamais : c'est toi qui les saisis.
_PROTECTED_FIELD_JS = """
(el) => {
  const type = (el.getAttribute('type') || '').toLowerCase();
  const auto = (el.getAttribute('autocomplete') || '').toLowerCase();
  return type === 'password' || /password|cc-|one-time-code/.test(auto);
}
"""


@dataclass(frozen=True)
class PageView:
    title: str
    url: str
    text: str
    elements: list[dict[str, str]] = field(default_factory=list)
    identity: bool = False

    def render(self) -> str:
        lines = [f"Titre : {self.title}", f"Adresse : {self.url}", "", self.text]
        if self.elements:
            lines += ["", "Éléments de la page :"]
            lines += [f"- {e['kind']} « {e['label']} »" for e in self.elements]
        return "\n".join(lines)


_install_lock = asyncio.Lock()


async def install_chromium(timeout_s: float = 900.0) -> bool:
    """Télécharge le Chromium de Playwright (dans ~/.cache/ms-playwright) avec son pilote."""
    from playwright._impl._driver import (  # noqa: PLC0415
        compute_driver_executable,
        get_driver_env,
    )

    async with _install_lock:
        node, cli = compute_driver_executable()
        log.info("chromium_installing")
        try:
            process = await asyncio.create_subprocess_exec(
                node,
                cli,
                "install",
                "chromium",
                env=get_driver_env(),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            ok = await asyncio.wait_for(process.wait(), timeout_s) == 0
        except (OSError, TimeoutError):
            ok = False
        log.info("chromium_installed" if ok else "chromium_install_failed")
        return ok


class BrowserSession:
    def __init__(
        self,
        vault: CookieVault,
        *,
        allowed_hosts: tuple[str, ...] = (),
        granted: Callable[[], set[str]] = set,
        proxy: GuardProxy | None = None,
        visible: Callable[[], bool] = lambda: False,
        live: LiveView | None = None,
    ) -> None:
        self._vault = vault
        #: Chromium en fenêtre (option « Montrer le navigateur »), relu à chaque lancement.
        self._visible = visible
        self._headless: bool | None = None
        self.live = live
        self._allowed_hosts = allowed_hosts
        #: Domaines autorisés (non révoqués), relus à chaque décision.
        self._granted = granted
        self._playwright: Any = None
        self._browser: Any = None
        self._contexts: dict[bool, Any] = {}
        self._page: Any = None
        self._page_identity = False
        self._lock = asyncio.Lock()
        # Proxy de garde partagé avec les autres outils web (sinon, le sien).
        self._proxy = proxy or GuardProxy(allowed_hosts=allowed_hosts)
        self._owns_proxy = proxy is None
        self._login: _LoginWindow | None = None

    # ------------------------------------------------------------------ décisions

    def uses_identity(self, url: str) -> bool:
        """L'adresse appartient à un domaine autorisé : y aller utilise tes cookies."""
        host = (urlsplit(url.strip()).hostname or "").lower()
        return bool(host) and any(in_domain(host, d) for d in self._granted())

    @property
    def on_identity_page(self) -> bool:
        return self._page is not None and self._page_identity

    # ------------------------------------------------------------------ cycle de vie

    async def _start(self) -> Any:
        if self._playwright is None:
            try:
                from playwright.async_api import async_playwright  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover - dépendance du moteur
                raise UnavailableError("Navigateur indisponible (Playwright absent).") from exc
            self._playwright = await async_playwright().start()
        return self._playwright

    async def _launch(self, *, headless: bool) -> Any:
        """Chromium dont tout le trafic passe par le proxy de garde (adresses publiques)."""
        playwright = await self._start()
        port = await self._proxy.start()
        return await playwright.chromium.launch(
            headless=headless,
            # Playwright fait aussi passer les adresses locales par le proxy (« <-loopback> »).
            proxy={"server": f"http://127.0.0.1:{port}"},
            args=["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
        )

    async def _context(self, identity: bool) -> Any:
        headless = not self._visible()
        browser = self._browser
        if browser is not None and (not browser.is_connected() or self._headless != headless):
            # Fenêtre fermée à la main, ou l'option « Montrer le navigateur » a changé.
            await self._drop_browser()
        context = self._contexts.get(identity)
        if context is not None:
            return context
        if self._browser is None:
            try:
                self._browser = await self._launch(headless=headless)
            except Exception as exc:
                # App installée : Chromium se télécharge au premier usage (~170 Mo), une fois.
                if "Executable doesn't exist" not in str(exc) or not await install_chromium():
                    raise UnavailableError(
                        "Navigateur indisponible (Chromium de Playwright absent ou "
                        "impossible à télécharger)."
                    ) from exc
                self._browser = await self._launch(headless=headless)
            self._headless = headless
        state: State | None = None
        if identity:
            state = await anyio.to_thread.run_sync(self._vault.load)
        context = await self._new_context(self._browser, state)
        self._contexts[identity] = context
        return context

    async def _new_context(self, browser: Any, state: State | None) -> Any:
        context = await browser.new_context(
            storage_state=state,
            locale="fr-FR",
            timezone_id="Europe/Paris",
            viewport={"width": 1280, "height": 900},
            accept_downloads=False,
            service_workers="block",
        )
        context.set_default_timeout(ACTION_TIMEOUT_MS)
        context.on("page", self._adopt)
        return context

    def _adopt(self, page: Any) -> None:
        """Une page ouverte par un clic (nouvel onglet) devient la page courante."""
        if self._page is not None and page.context == self._page.context:
            self._page = page

    async def change_vault[T](self, change: Callable[[], T]) -> T:
        """Modifie le coffre (import, révocation, connexion) sans course avec une page en
        cours ; le contexte « identité » sera rechargé avec les nouvelles autorisations."""
        async with self._lock:
            result = await anyio.to_thread.run_sync(change)
            context = self._contexts.pop(True, None)
            if self._page_identity:
                self._page = None
                self._page_identity = False
            if context is not None:
                with contextlib.suppress(Exception):
                    await context.close()
            return result

    async def _drop_browser(self) -> None:
        if self.live is not None:
            await self.live.stop()
        for context in list(self._contexts.values()):
            with contextlib.suppress(Exception):
                await context.close()
        self._contexts.clear()
        self._page = None
        self._page_identity = False
        browser, self._browser = self._browser, None
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()

    async def _watch(self) -> None:
        """La page courante est filmée pour l'app (et le reste un moment après l'action)."""
        if self.live is not None and self._page is not None and not self._page.is_closed():
            await self.live.follow(self._page)

    async def close(self) -> None:
        async with self._lock:
            await self._close_login()
            if self.live is not None:
                await self.live.close()
            await self._drop_browser()
            playwright, self._playwright = self._playwright, None
            if playwright is not None:
                with contextlib.suppress(Exception):
                    await playwright.stop()
            if self._owns_proxy:
                await self._proxy.close()

    async def _persist(self) -> None:
        """Après un passage sur un domaine autorisé : sessions remises au coffre (filtrées)."""
        if not self._page_identity:
            return
        context = self._contexts.get(True)
        if context is None:
            return
        state = await context.storage_state()
        domains = self._granted()
        await anyio.to_thread.run_sync(self._vault.replace_domains, state, domains)

    # ------------------------------------------------------------------ lecture

    async def _view(self, page: Any) -> PageView:
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=ACTION_TIMEOUT_MS)
        title = await page.title()
        # innerText : le texte affiché seulement (un texte masqué en CSS n'y entre pas).
        text = await page.locator("body").inner_text(timeout=ACTION_TIMEOUT_MS)
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "\n[…page tronquée]"
        elements = await page.evaluate(_ELEMENTS_SCRIPT, MAX_ELEMENTS)
        return PageView(title, page.url, text, list(elements), self._page_identity)

    async def goto(self, url: str) -> PageView:
        target = await check_public_url(url, allowed_hosts=self._allowed_hosts)
        identity = self.uses_identity(target)
        async with self._lock:
            context = await self._context(identity)
            if self._page is None or self._page.is_closed() or self._page_identity != identity:
                if self._page is not None and not self._page.is_closed():
                    with contextlib.suppress(Exception):
                        await self._page.close()
                self._page = await context.new_page()
                self._page_identity = identity
            await self._watch()  # on voit la page se charger
            await self._page.goto(
                target, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
            )
            await _settle(self._page)
            view = await self._view(self._page)
            await self._persist()
            await self._watch()
            return view

    def _require_page(self) -> Any:
        if self._page is None or self._page.is_closed():
            raise NotFoundError("Aucune page ouverte dans le navigateur de Jarvis.")
        return self._page

    async def current(self) -> PageView:
        async with self._lock:
            return await self._view(self._require_page())

    async def links(self) -> tuple[PageView, list[dict[str, str]]]:
        async with self._lock:
            page = self._require_page()
            return await self._view(page), list(await page.evaluate(_LINKS_SCRIPT, MAX_LINKS))

    async def tables(self) -> tuple[PageView, list[list[list[str]]]]:
        async with self._lock:
            page = self._require_page()
            return await self._view(page), list(await page.evaluate(_TABLES_SCRIPT))

    # ------------------------------------------------------------------ actions

    async def click(self, target: str) -> PageView:
        async with self._lock:
            page = self._require_page()
            candidates = (
                page.get_by_role("button", name=target, exact=True),
                page.get_by_role("link", name=target, exact=True),
                page.get_by_role("button", name=target),
                page.get_by_role("link", name=target),
                page.get_by_text(target, exact=True),
            )
            await self._watch()
            for locator in candidates:
                element = await _single(locator, same_link=True)
                if element is not None:
                    before = await _signature(page)
                    await element.click()
                    with contextlib.suppress(Exception):
                        await self._page.wait_for_load_state(
                            "domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS
                        )
                    await _settle(self._page, before=before)
                    view = await self._view(self._page)
                    await self._persist()
                    await self._watch()  # un clic a pu ouvrir un nouvel onglet
                    return view
            raise NotFoundError(f"Élément « {target} » introuvable (ou ambigu) sur la page.")

    async def fill(self, field_name: str, value: str) -> PageView:
        async with self._lock:
            page = self._require_page()
            candidates = (
                page.get_by_label(field_name, exact=True),
                page.get_by_label(field_name),
                page.get_by_placeholder(field_name),
                page.get_by_role("textbox", name=field_name),
            )
            for locator in candidates:
                field = await _single(locator)
                if field is not None:
                    if await field.evaluate(_PROTECTED_FIELD_JS):
                        raise InvalidInputError(
                            "Jarvis ne saisit ni mot de passe ni carte bancaire : connecte-toi "
                            "toi-même (Réglages > Navigateur).",
                            code="secret_field",
                        )
                    await self._watch()
                    await field.fill(value)
                    return await self._view(page)
            raise NotFoundError(f"Champ « {field_name} » introuvable (ou ambigu) sur la page.")

    # ------------------------------------------------------------------ connexion

    @property
    def login_active(self) -> bool:
        return self._login is not None and not self._login.done.is_set()

    async def login_start(
        self, url: str, on_closed: Callable[[], Awaitable[Any]] | None = None
    ) -> None:
        """Fenêtre visible : tu te connectes toi-même. Ferme-la (ou « Terminer ») à la fin."""
        target = await check_public_url(url, allowed_hosts=self._allowed_hosts)
        if self.login_active:
            raise ConflictError("Une fenêtre de connexion est déjà ouverte.", code="login_active")
        await self._close_login()
        try:
            browser = await self._launch(headless=False)
        except Exception as exc:
            raise UnavailableError("Impossible d'ouvrir la fenêtre du navigateur.") from exc
        state = await anyio.to_thread.run_sync(self._vault.load)
        context = await self._new_context(browser, state)
        page = await context.new_page()
        window = _LoginWindow(browser, context, on_closed)
        self._login = window
        page.on("close", lambda *_: window.closed())
        browser.on("disconnected", lambda *_: window.closed())
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        except Exception as exc:
            await self._close_login()
            raise UnavailableError("La page de connexion ne s'ouvre pas.") from exc
        window.start()

    async def login_finish(self) -> State:
        """Dernier état de la fenêtre de connexion (cookies compris), puis fermeture."""
        window = self._login
        if window is None:
            raise NotFoundError("Aucune fenêtre de connexion ouverte.")
        await window.snapshot()
        await self._close_login()
        return window.state

    async def _close_login(self) -> None:
        window, self._login = self._login, None
        if window is not None:
            await window.close()


#: Le titre et une empreinte du texte affiché : de quoi voir que la page a changé.
_SIGNATURE_JS = """() => {
  const text = document.body ? document.body.innerText : "";
  let hash = 0;
  for (let i = 0; i < text.length; i += 7) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  return `${document.title}|${text.length}|${hash}`;
}"""


async def _signature(page: Any) -> str | None:
    try:
        return str(await page.evaluate(_SIGNATURE_JS))
    except Exception:  # page en cours de remplacement
        return None


async def _settle(page: Any, *, before: str | None = None) -> None:
    """Laisse une app web dessiner sa page : son texte ne bouge plus depuis
    `SETTLE_STABLE_S`. Après un clic (`before`), on lui laisse d'abord le temps de changer.
    `SETTLE_MAX_S` au plus : une page qui s'anime sans fin est lue telle quelle."""
    loop = asyncio.get_running_loop()
    start = loop.time()
    last = await _signature(page)
    stable_since = start
    while (now := loop.time()) - start < SETTLE_MAX_S:
        changed = before is None or last != before
        if now - stable_since >= SETTLE_STABLE_S and (changed or now - start >= SETTLE_CHANGE_S):
            return
        await asyncio.sleep(SETTLE_POLL_S)
        current = await _signature(page)
        if current != last:
            last, stable_since = current, loop.time()


async def _single(locator: Any, *, same_link: bool = False) -> Any | None:
    """L'élément désigné, s'il n'y en a qu'un. Plusieurs du même nom : le seul visible, ou,
    pour des liens, le premier quand tous mènent au même endroit (« Blog » dans le menu et
    en bas de page). Sinon, c'est ambigu : rien."""
    count = await locator.count()
    if count == 1:
        return locator
    if count == 0 or count > MAX_TWINS:
        return None
    visible = [locator.nth(i) for i in range(count) if await locator.nth(i).is_visible()]
    if len(visible) == 1:
        return visible[0]
    if not same_link or not visible:
        return None
    targets = {await element.get_attribute("href") for element in visible}
    return visible[0] if len(targets) == 1 and None not in targets else None


class _LoginWindow:
    """Fenêtre de connexion : son état est relevé toutes les 2 s, et une dernière fois
    quand tu la fermes."""

    def __init__(
        self, browser: Any, context: Any, on_closed: Callable[[], Awaitable[Any]] | None
    ) -> None:
        self.browser = browser
        self.context = context
        self.state: State = {"cookies": [], "origins": []}
        self.done = asyncio.Event()
        self._on_closed = on_closed
        self._closing = False
        self._watch_task: asyncio.Task[None] | None = None
        self._final_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._watch_task = asyncio.create_task(self._watch())

    def closed(self) -> None:
        """Page ou navigateur fermé par toi : dernier relevé, puis fin de la connexion."""
        if self._closing:
            return
        self._closing = True
        self._final_task = asyncio.create_task(self._finalize())

    async def _finalize(self) -> None:
        with contextlib.suppress(Exception):
            self.state = await self.context.storage_state()
        self.done.set()
        if self._on_closed is not None:
            await self._on_closed()

    async def snapshot(self) -> None:
        if self._closing:
            return
        with contextlib.suppress(Exception):
            self.state = await self.context.storage_state()

    async def _watch(self) -> None:
        while not self.done.is_set():
            await self.snapshot()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.done.wait(), LOGIN_SNAPSHOT_S)

    async def close(self) -> None:
        self._closing = True
        self.done.set()
        if self._watch_task is not None:
            self._watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._watch_task
        with contextlib.suppress(Exception):
            await self.context.close()
        with contextlib.suppress(Exception):
            await self.browser.close()
