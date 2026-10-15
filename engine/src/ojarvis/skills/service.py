"""Le registre des skills : proposer (brouillon testé), activer, désactiver, appeler.

Activer un skill, c'est donner un nouvel outil à Jarvis : niveau 3, après ta double
confirmation. Ses outils entrent alors dans le registre et passent par la porte comme les
autres ; leur code ne tourne que dans le bac à sable.
"""

from __future__ import annotations

from typing import Any

from ojarvis.core.errors import NotFoundError
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.skills.models import SkillDefinition, tool_name
from ojarvis.skills.runner import SkillRunner
from ojarvis.skills.store import SkillRecord, SkillStore
from ojarvis.tools.base import ToolRegistry

log = get_logger(__name__)

#: Ce que peut faire le code d'un skill (montré avant l'activation).
SANDBOX_RULES = "calcul en bac à sable : ni Internet, ni tes fichiers, ni tes clés"


class SkillService:
    def __init__(
        self, store: SkillStore, runner: SkillRunner, registry: ToolRegistry, bus: EventBus
    ) -> None:
        self._store = store
        self._runner = runner
        self._registry = registry
        self._bus = bus
        #: Versions connues, lues sans attendre la base (écran de validation).
        self._known: dict[tuple[str, str], SkillRecord] = {}

    async def start(self) -> None:
        """Au démarrage : les skills actifs retrouvent leurs outils."""
        for record in await self._store.all():
            self._known[(record.name, record.version)] = record
            if record.status == "actif":
                self._register(record)

    def known(self, name: str, version: str) -> SkillRecord | None:
        return self._known.get((name, version))

    def records(self) -> list[SkillRecord]:
        return sorted(self._known.values(), key=lambda r: (r.name, r.version))

    async def get(self, skill_id: str) -> SkillRecord:
        return await self._store.get(skill_id)

    async def find(self, name: str, version: str) -> SkillRecord:
        record = self.known(name, version) or await self._store.find(name, version)
        if record is None:
            raise NotFoundError(f"Aucun skill « {name} » en version {version}.")
        return record

    async def propose(
        self,
        definition: SkillDefinition,
        *,
        created_by: str,
        conversation_id: str | None = None,
    ) -> SkillRecord:
        """Enregistre un brouillon, puis lance ses tests dans le bac à sable."""
        draft = await self._store.save_draft(
            definition, created_by=created_by, conversation_id=conversation_id
        )
        self._known[(draft.name, draft.version)] = draft
        await self._publish("skill.created", draft)
        return await self.retest(draft.id)

    async def retest(self, skill_id: str) -> SkillRecord:
        record = await self._store.get(skill_id)
        report = await self._runner.test(record.definition)
        record = await self._store.set_report(skill_id, report)
        self._known[(record.name, record.version)] = record
        log.info("skill_tested", skill=record.name, version=record.version, ok=report.ok)
        await self._publish("skill.tested", record)
        return record

    async def activate(self, skill_id: str) -> SkillRecord:
        record, replaced = await self._store.activate(skill_id)
        if replaced is not None:
            self._unregister(replaced)
            self._known[(replaced.name, replaced.version)] = replaced
        if not all(
            tool_name(record.name, t.nom) in self._registry for t in record.definition.outils
        ):
            self._register(record)
        self._known[(record.name, record.version)] = record
        await self._publish("skill.activated", record)
        return record

    async def disable(self, skill_id: str) -> SkillRecord:
        record = await self._store.disable(skill_id)
        self._unregister(record)
        self._known[(record.name, record.version)] = record
        await self._publish("skill.disabled", record)
        return record

    async def delete(self, skill_id: str) -> SkillRecord:
        record = await self._store.delete(skill_id)
        self._known.pop((record.name, record.version), None)
        await self._publish("skill.deleted", record)
        return record

    async def call(self, record: SkillRecord, tool: str, args: dict[str, Any]) -> Any:
        return await self._runner.call(record.definition, tool, args)

    def capabilities(self) -> list[str]:
        """Pour « lister_capacites » : les skills actifs et ceux qui attendent."""
        lines = []
        for record in self.records():
            if record.status in ("actif", "pret", "echec"):
                tools = ", ".join(t.nom for t in record.definition.outils)
                lines.append(
                    f"- {record.name} v{record.version} [{record.status}] : "
                    f"{record.definition.description} (outils : {tools})"
                )
        return lines

    def _register(self, record: SkillRecord) -> None:
        from ojarvis.tools.skills import make_skill_tool  # noqa: PLC0415 - outil ↔ service

        for spec in record.definition.outils:
            name = tool_name(record.name, spec.nom)
            if name in self._registry:
                self._registry.unregister(name)
            self._registry.register(make_skill_tool(self, record, spec))

    def _unregister(self, record: SkillRecord) -> None:
        for spec in record.definition.outils:
            name = tool_name(record.name, spec.nom)
            if name in self._registry:
                self._registry.unregister(name)

    async def _publish(self, event: str, record: SkillRecord) -> None:
        await self._bus.publish(
            event,
            {
                "id": record.id,
                "name": record.name,
                "version": record.version,
                "status": record.status,
                "summary": record.report.summary() if record.report else None,
            },
            source="skills",
        )
