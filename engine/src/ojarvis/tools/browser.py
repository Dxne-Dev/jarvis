"""Outils du navigateur de Jarvis : ouvrir et lire (niveau 1), cliquer et remplir (niveau 2).

Ouvrir une page d'un domaine où tu es connecté utilise tes cookies : niveau 2 aussi.
"""

from __future__ import annotations

from typing import ClassVar, Literal
from urllib.parse import urlsplit

from pydantic import Field

from ojarvis.browser.page import PageView
from ojarvis.browser.session import BrowserSession
from ojarvis.tools.base import Level, Tool, ToolArgs, ToolContext, ToolOutput


def _output(view: PageView, extra: str = "") -> ToolOutput:
    text = view.render() + (f"\n\n{extra}" if extra else "")
    return ToolOutput(
        text,
        {"url": view.url, "titre": view.title, "session": view.identity},
        external=True,
        source=view.url,
    )


class OpenArgs(ToolArgs):
    url: str = Field(min_length=8, max_length=2000, description="Adresse http(s) à ouvrir.")


class BrowserOpen(Tool[OpenArgs]):
    name: ClassVar[str] = "navigateur_ouvrir"
    description: ClassVar[str] = (
        "Ouvre une page dans le navigateur de Jarvis et rend son texte et ses éléments "
        "(boutons, liens, champs). Sur un domaine autorisé dans les réglages, la session "
        "enregistrée est utilisée : niveau 2."
    )
    Args: ClassVar[type[ToolArgs]] = OpenArgs
    level: ClassVar[Level] = Level.LIRE

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    def level_for(self, args: OpenArgs) -> Level:
        return Level.AGIR if self._session.uses_identity(args.url) else Level.LIRE

    def describe(self, args: OpenArgs) -> str:
        if self._session.uses_identity(args.url):
            host = urlsplit(args.url).hostname or args.url
            return f"Ouvrir {args.url} avec ta session (cookies de {host})"
        return f"Ouvrir {args.url} dans le navigateur de Jarvis"

    async def run(self, args: OpenArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        return _output(await self._session.goto(args.url))


class ReadArgs(ToolArgs):
    quoi: Literal["texte", "liens", "tableaux"] = Field(
        default="texte", description="texte de la page, liste des liens, ou tableaux."
    )


class BrowserRead(Tool[ReadArgs]):
    name: ClassVar[str] = "navigateur_lire"
    description: ClassVar[str] = (
        "Relit la page ouverte dans le navigateur de Jarvis : son texte, ses liens (avec "
        "leurs adresses) ou ses tableaux."
    )
    Args: ClassVar[type[ToolArgs]] = ReadArgs
    level: ClassVar[Level] = Level.LIRE

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    def describe(self, args: ReadArgs) -> str:
        what = {"texte": "le texte", "liens": "les liens", "tableaux": "les tableaux"}[args.quoi]
        return f"Lire {what} de la page ouverte"

    async def run(self, args: ReadArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        if args.quoi == "liens":
            view, links = await self._session.links()
            lines = [f"- {link['text']} → {link['href']}" for link in links]
            return _output(view, "Liens :\n" + ("\n".join(lines) or "(aucun)"))
        if args.quoi == "tableaux":
            view, tables = await self._session.tables()
            blocks = ["\n".join(" | ".join(row) for row in table) for table in tables if table]
            return _output(view, "Tableaux :\n" + ("\n\n".join(blocks) or "(aucun)"))
        return _output(await self._session.current())


class ClickArgs(ToolArgs):
    element: str = Field(
        min_length=1,
        max_length=200,
        description="Nom visible du bouton ou du lien, tel qu'il apparaît dans la page.",
    )


class BrowserClick(Tool[ClickArgs]):
    name: ClassVar[str] = "navigateur_cliquer"
    description: ClassVar[str] = "Clique sur un bouton ou un lien de la page ouverte."
    Args: ClassVar[type[ToolArgs]] = ClickArgs
    level: ClassVar[Level] = Level.AGIR

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    def describe(self, args: ClickArgs) -> str:
        return f"Cliquer sur « {args.element} » dans la page ouverte"

    async def run(self, args: ClickArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        return _output(await self._session.click(args.element))


class FillArgs(ToolArgs):
    champ: str = Field(
        min_length=1, max_length=200, description="Nom visible du champ (libellé ou indication)."
    )
    valeur: str = Field(max_length=5000, description="Texte à écrire dans le champ.")


class BrowserFill(Tool[FillArgs]):
    name: ClassVar[str] = "navigateur_remplir"
    description: ClassVar[str] = (
        "Écrit un texte dans un champ de la page ouverte (jamais un mot de passe ni une carte)."
    )
    Args: ClassVar[type[ToolArgs]] = FillArgs
    level: ClassVar[Level] = Level.AGIR
    dynamic_fields: ClassVar[tuple[str, ...]] = ("valeur",)

    def __init__(self, session: BrowserSession) -> None:
        self._session = session

    def describe(self, args: FillArgs) -> str:
        value = args.valeur if len(args.valeur) <= 80 else args.valeur[:77] + "…"
        return f"Écrire « {value} » dans le champ « {args.champ} »"

    async def run(self, args: FillArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        view = await self._session.fill(args.champ, args.valeur)
        return _output(view, f"Champ « {args.champ} » rempli.")
