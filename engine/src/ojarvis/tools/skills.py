"""Outils des skills : en créer un (brouillon testé), l'activer, et ceux qu'il apporte.

- `creer_skill` (niveau 1) : enregistre un brouillon et lance ses tests dans le bac à sable ;
  rien ne change pour Jarvis tant que tu ne l'as pas activé.
- `activer_skill` (niveau 3, « s'étendre ») : double confirmation, après avoir vu son code,
  ses outils et le résultat de ses tests.
- Les outils d'un skill actif (niveau 1) : leur code tourne dans le bac à sable, sans Internet
  ni tes fichiers ; leur résultat est une donnée.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, cast

import jsonschema
from pydantic import ConfigDict, Field

from ojarvis.core.errors import UpstreamError
from ojarvis.llm.types import ToolSpec
from ojarvis.skills.models import SEMVER, SLUG, SkillDefinition, SkillTool, tool_name
from ojarvis.skills.runner import SkillCallError
from ojarvis.skills.service import SANDBOX_RULES
from ojarvis.tools.base import (
    LEVEL_LABELS,
    InvalidToolArgumentsError,
    Level,
    Tool,
    ToolArgs,
    ToolContext,
    ToolOutput,
)

if TYPE_CHECKING:
    from ojarvis.skills.service import SkillService
    from ojarvis.skills.store import SkillRecord

MAX_TEXT = 8_000


class CreateSkill(Tool[SkillDefinition]):
    name: ClassVar[str] = "creer_skill"
    description: ClassVar[str] = (
        "Crée un skill : une capacité durable faite de fonctions Python pures (bibliothèque "
        "standard, sans Internet ni fichiers) avec leurs tests, lancés dans le bac à sable. "
        "Il reste en brouillon : propose ensuite activer_skill, que l'utilisateur confirme "
        "deux fois."
    )
    Args: ClassVar[type[ToolArgs]] = SkillDefinition
    level: ClassVar[Level] = Level.LIRE

    def __init__(self, skills: SkillService) -> None:
        self._skills = skills

    def describe(self, args: SkillDefinition) -> str:
        return (
            f"Créer le skill « {args.nom} » v{args.version} ({len(args.outils)} outil(s)) "
            "et lancer ses tests dans le bac à sable"
        )

    async def run(self, args: SkillDefinition, ctx: ToolContext) -> ToolOutput:
        del ctx
        record = await self._skills.propose(args, created_by="jarvis")
        report = record.report
        summary = report.summary() if report else "pas testé"
        lines = [f"Skill {record.label} enregistré en brouillon. Tests : {summary}."]
        failures = [c for c in report.cases if not c.ok] if report else []
        lines += [f"- {c.name} : {c.detail}" for c in failures]
        if record.tested_ok:
            lines.append(
                "Pour qu'il serve, propose activer_skill : l'utilisateur verra son code, ses "
                "outils et ses tests, et confirmera deux fois."
            )
        else:
            lines.append(
                "Corrige le code ou les tests, puis recrée-le (même version tant qu'il n'a "
                "jamais été activé)."
            )
        return ToolOutput(
            "\n".join(lines),
            {"skill": record.id, "statut": record.status},
            # Les messages d'échec viennent du code testé : une donnée, pas une consigne.
            external=bool(failures or (report and report.error)),
            source="tests du skill",
        )


class ActivateArgs(ToolArgs):
    nom: str = Field(min_length=3, max_length=30, pattern=SLUG, description="Nom du skill.")
    version: str = Field(pattern=SEMVER, description="Version à activer.")


class ActivateSkill(Tool[ActivateArgs]):
    name: ClassVar[str] = "activer_skill"
    description: ClassVar[str] = (
        "Active un skill dont les tests ont réussi : ses outils deviennent utilisables. "
        "L'utilisateur confirme deux fois."
    )
    Args: ClassVar[type[ToolArgs]] = ActivateArgs
    level: ClassVar[Level] = Level.DETRUIRE

    def __init__(self, skills: SkillService) -> None:
        self._skills = skills

    def describe(self, args: ActivateArgs) -> str:
        record = self._skills.known(args.nom, args.version)
        if record is None:
            return f"Activer le skill « {args.nom} » v{args.version} (inconnu pour l'instant)"
        tools = ", ".join(t.nom for t in record.definition.outils)
        tests = record.report.summary() if record.report else "pas encore testé"
        return (
            f"Activer le skill {record.label} — outils : {tools} ; {SANDBOX_RULES} ; "
            f"tests : {tests}"
        )

    async def run(self, args: ActivateArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        record = await self._skills.find(args.nom, args.version)
        record = await self._skills.activate(record.id)
        tools = ", ".join(tool_name(record.name, t.nom) for t in record.definition.outils)
        return ToolOutput(
            f"Skill {record.label} actif. Ses outils : {tools}.", {"skill": record.id}
        )


class SkillToolArgs(ToolArgs):
    """Arguments libres, vérifiés par le schéma JSON de l'outil du skill."""

    model_config = ConfigDict(extra="allow")


class SkillToolBase(Tool[SkillToolArgs]):
    Args: ClassVar[type[ToolArgs]] = SkillToolArgs
    level: ClassVar[Level] = Level.LIRE

    def __init__(self, skills: SkillService, record: SkillRecord, spec: SkillTool) -> None:
        self._skills = skills
        self._record = record
        self._spec = spec

    def parse(self, raw: dict[str, Any]) -> SkillToolArgs:
        try:
            jsonschema.validate(raw, self._spec.parametres)
        except jsonschema.ValidationError as exc:
            where = ".".join(str(p) for p in exc.absolute_path) or "arguments"
            raise InvalidToolArgumentsError(
                f"Arguments invalides pour {self.name} ({where} : {exc.message})."
            ) from exc
        return SkillToolArgs.model_validate(raw)

    def spec(self) -> ToolSpec:
        label = LEVEL_LABELS[self.level]
        return ToolSpec(
            self.name,
            f"{self.description} (niveau {int(self.level)} : {label})",
            self._spec.parametres,
        )

    def describe(self, args: SkillToolArgs) -> str:
        shown = json.dumps(args.model_dump(), ensure_ascii=False)
        shown = shown if len(shown) <= 160 else shown[:157] + "…"
        return f"Skill « {self._record.name} » : {self._spec.nom} {shown}"

    async def run(self, args: SkillToolArgs, ctx: ToolContext) -> ToolOutput:
        del ctx
        try:
            result = await self._skills.call(self._record, self._spec.nom, args.model_dump())
        except SkillCallError as exc:
            raise UpstreamError(f"Le skill « {self._record.name} » a échoué : {exc}") from exc
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return ToolOutput(
            text[:MAX_TEXT],
            {"resultat": result},
            external=True,
            source=f"skill {self._record.name}",
        )


def make_skill_tool(skills: SkillService, record: SkillRecord, spec: SkillTool) -> Tool[Any]:
    """Un outil par fonction du skill, avec son propre nom et sa description."""
    about = f"[skill {record.name} v{record.version}] {spec.description}"
    if record.definition.instructions:
        about += f" Mode d'emploi : {record.definition.instructions[:300]}"
    tool_class = type(
        "SkillTool",
        (SkillToolBase,),
        {"name": tool_name(record.name, spec.nom), "description": about},
    )
    return cast("Tool[Any]", tool_class(skills, record, spec))


def skill_tools(skills: SkillService) -> list[Tool[Any]]:
    return [CreateSkill(skills), ActivateSkill(skills)]
