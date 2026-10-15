"""Outils web : recherche (Tavily) et lecture d'une page.

Sans tes cookies, et seulement vers des adresses publiques.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from pydantic import Field

from ojarvis.core.errors import UpstreamError
from ojarvis.tools.base import Level, Tool, ToolArgs, ToolContext, ToolOutput
from ojarvis.tools.guards import BlockedTargetError, check_public_url

MAX_PAGE_BYTES = 2_000_000
MAX_PAGE_CHARS = 12_000
MAX_REDIRECTS = 5
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) O-jarvis/0.1 (+assistant personnel)"
_SPACES = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def page_text(html: str) -> tuple[str, str]:
    """Titre et texte lisible d'une page (sans scripts, styles ni menus)."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "template", "svg", "nav", "footer", "iframe"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = root.get_text("\n", strip=True)
    text = _BLANK_LINES.sub("\n\n", _SPACES.sub(" ", text))
    return title, text


class SearchArgs(ToolArgs):
    requete: str = Field(min_length=2, max_length=300, description="Ce qu'il faut chercher.")
    resultats: int = Field(default=5, ge=1, le=8, description="Nombre de résultats.")


class WebSearch(Tool[SearchArgs]):
    name: ClassVar[str] = "recherche_web"
    description: ClassVar[str] = "Cherche sur le web (titres, adresses et extraits)."
    Args: ClassVar[type[ToolArgs]] = SearchArgs
    level: ClassVar[Level] = Level.LIRE

    def describe(self, args: SearchArgs) -> str:
        return f"Chercher sur le web : « {args.requete} »"

    async def run(self, args: SearchArgs, ctx: ToolContext) -> ToolOutput:
        key = ctx.secret("TAVILY_API_KEY")
        if not key:
            raise UpstreamError("Recherche web indisponible : clé Tavily absente.")
        response = await ctx.http.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {key}"},
            json={"query": args.requete, "max_results": args.resultats, "search_depth": "basic"},
            timeout=15.0,
        )
        if response.status_code != 200:
            raise UpstreamError(f"Recherche web refusée (HTTP {response.status_code}).")
        results: list[dict[str, Any]] = [
            r for r in response.json().get("results", []) if isinstance(r, dict)
        ]
        lines = []
        for i, item in enumerate(results, 1):
            snippet = str(item.get("content", ""))[:500]
            lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}\n   {snippet}")
        text = "\n".join(lines) or "Aucun résultat."
        urls = [str(r.get("url", "")) for r in results]
        return ToolOutput(text, {"urls": urls}, external=True, source="recherche web")


class ReadPageArgs(ToolArgs):
    url: str = Field(min_length=8, max_length=2000, description="Adresse http(s) de la page.")


async def _follow(
    http: httpx.AsyncClient, url: str, ctx: ToolContext
) -> tuple[httpx.Response, str]:
    """Redirections suivies à la main : chaque étape repasse par la garde réseau."""
    for _ in range(MAX_REDIRECTS + 1):
        response = await http.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr,en;q=0.8"},
            follow_redirects=False,
            timeout=15.0,
        )
        if response.is_redirect and "location" in response.headers:
            target = urljoin(url, response.headers["location"])
            url = await check_public_url(target, allowed_hosts=ctx.allowed_private_hosts)
            continue
        return response, url
    raise UpstreamError("Trop de redirections.")


class ReadPage(Tool[ReadPageArgs]):
    name: ClassVar[str] = "lire_page"
    description: ClassVar[str] = "Lit le texte d'une page web publique (sans tes cookies)."
    Args: ClassVar[type[ToolArgs]] = ReadPageArgs
    level: ClassVar[Level] = Level.LIRE

    def describe(self, args: ReadPageArgs) -> str:
        return f"Lire la page {args.url}"

    async def run(self, args: ReadPageArgs, ctx: ToolContext) -> ToolOutput:
        url = await check_public_url(args.url, allowed_hosts=ctx.allowed_private_hosts)
        # Par le proxy de garde : il résout le nom et se connecte lui-même à l'adresse
        # vérifiée (une réponse DNS qui changerait entre-temps ne mène nulle part).
        own = httpx.AsyncClient(proxy=ctx.fetch_proxy) if ctx.fetch_proxy else None
        try:
            response, url = await _follow(own or ctx.http, url, ctx)
        except httpx.ProxyError as exc:
            raise BlockedTargetError("Adresse privée ou locale refusée.") from exc
        finally:
            if own is not None:
                await own.aclose()
        if response.status_code != 200:
            raise UpstreamError(f"La page répond HTTP {response.status_code}.")
        kind = response.headers.get("content-type", "")
        if "html" not in kind and "text/plain" not in kind:
            raise UpstreamError(f"Ce n'est pas une page lisible ({kind or 'type inconnu'}).")
        body = response.content[:MAX_PAGE_BYTES].decode(response.encoding or "utf-8", "replace")
        title, text = page_text(body) if "html" in kind else ("", body)
        truncated = len(text) > MAX_PAGE_CHARS
        text = text[:MAX_PAGE_CHARS] + ("\n[…page tronquée]" if truncated else "")
        content = f"# {title}\n\n{text}" if title else text
        return ToolOutput(content, {"titre": title, "url": url}, external=True, source=url)
