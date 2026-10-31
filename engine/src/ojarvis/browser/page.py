"""Lire une page du navigateur de Jarvis : le texte affiché, les éléments à cliquer ou à
remplir (scripts exécutés dans la page), et l'attente qu'une app web ait fini de dessiner.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

MAX_TEXT = 12_000

MAX_ELEMENTS = 60

MAX_LINKS = 80

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
