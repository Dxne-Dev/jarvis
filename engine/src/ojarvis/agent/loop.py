"""Ce que Jarvis fait d'un appel d'outil pendant une conversation.

- Outil de niveau 1 (lire) : exécuté tout de suite, par la porte des permissions ; son
  résultat revient au modèle encadré comme une donnée s'il vient de l'extérieur.
- `proposer_un_plan` : le plan est vérifié, enregistré, et attend ta décision.
- Appel direct d'une action (niveau 2 ou 3) : jamais exécuté ; il devient un plan
  d'une étape, à valider comme les autres.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

import anyio.to_thread
from pydantic import ValidationError

from ojarvis.agent.executor import PlanExecutor
from ojarvis.agent.measures import MEASURE_AFTER, MEASURE_BEFORE
from ojarvis.agent.plans import (
    FINISHED,
    MAX_STEPS,
    PLACEHOLDER,
    PLAN_TOOL,
    PlanIn,
    PlanRecord,
    PlanStore,
    StepIn,
    StepRecord,
    plan_tool_spec,
)
from ojarvis.agent.review import CodeReviewer, Review
from ojarvis.core.errors import ConflictError, EngineError, InvalidInputError, NotFoundError
from ojarvis.core.logs import get_logger
from ojarvis.events.bus import EventBus
from ojarvis.llm.types import ToolCall, ToolSpec
from ojarvis.permissions.gate import PermissionGate
from ojarvis.security.redaction import REDACTOR
from ojarvis.shell.commands import talks_to_network
from ojarvis.tools.base import LEVEL_LABELS, Level
from ojarvis.tools.guards import DATA_RULE, as_data

log = get_logger(__name__)

#: Fin de la sortie d'une commande montrée dans le terminal (le modèle lit tout).
OUTPUT_PREVIEW_CHARS = 2000
#: Tours d'outils au plus dans une réponse (ensuite, le modèle doit conclure). Une PR
#: GitHub en demande souvent 6 ou 7 : lister les outils, lire le dépôt, puis le plan.
MAX_TOOL_ROUNDS = 8

AGENT_RULES = (
    "Tu as des outils. Dans leurs descriptions, « ton dossier personnel », « tes fichiers "
    "» et « ~ » désignent ceux de l'utilisateur, sur cet ordinateur. Niveau 1 (lire : "
    "recherche web, pages, fichiers, navigateur, code "
    "isolé) : utilise-les directement quand ils aident, sans demander. Niveaux 2 et 3 "
    "(agir : cliquer, remplir, écrire un fichier, utiliser une session ; détruire) : ne "
    "les appelle jamais seuls ; propose un plan avec proposer_un_plan, que l'utilisateur "
    "validera. Le plan est ta demande de confirmation : ne demande pas « tu confirmes ? » "
    "avant de le proposer. S'il manque une information indispensable (quoi, où, quand), "
    "demande-la ; si tu peux la lire toi-même (identifiant, contenu d'un fichier), lis-la "
    "d'abord avec un outil de lecture. Sinon propose le plan tout de suite. Si une partie "
    "de la demande t'est impossible (lancer une commande dans un terminal, par exemple), "
    "propose quand même le plan pour le reste et dis clairement ce qu'il restera à faire. "
    "Ne dis jamais qu'un plan attend une validation si tu n'as pas appelé "
    "proposer_un_plan. Pour une tâche en plusieurs étapes, propose tout le plan d'un coup, "
    "avec des cibles précises (adresse, fichier, bouton). N'invente jamais le résultat "
    "d'un outil. Cite tes sources quand tu t'appuies sur le web. Pour GitHub, Notion ou "
    "l'agenda : regarde d'abord les outils avec integrations_outils, puis appelle-les avec "
    "integration_appeler. Si une capacité te manque et qu'elle se calcule (sans Internet "
    "ni fichiers), crée-la avec creer_skill (fonctions Python pures et leurs tests) : si "
    "ses tests réussissent, son activation est proposée à l'utilisateur ; une fois actif, "
    "utilise ses outils.\n\n" + DATA_RULE
)
NO_TERMINAL = (
    "Ici, tu ne lances pas de commande dans un terminal, même avec le contrôle du PC activé ; "
    "pour regarder un dossier ou un fichier, lister_dossier et lire_fichier suffisent. Ouvre le "
    "mode shell (ouvrir_mode_shell, dans le dossier demandé, sinon ~) seulement quand "
    "l'utilisateur le demande (« passe en mode shell », « ouvre un terminal ») ou qu'une tâche "
    "demande vraiment des commandes. Une fois ouvert, ne le rouvre pas : c'est dans ce terminal "
    "qu'il écrit ses demandes, en français, et que tu lances les commandes. S'il te demande "
    "quoi y faire, dis-le-lui simplement."
)
SHELL_RULES = (
    "Mode shell : l'utilisateur t'a ouvert un terminal, vous travaillez dans le dossier "
    "{folder}. Lance les commandes avec executer_commande, avec dossier=« {folder} » sauf "
    "s'il te demande un autre dossier. Les lectures (ls, cat, git status, df, du…) partent "
    "tout de suite ; une autre action devient un plan qu'il valide dans le terminal ; une "
    "suppression demande sa double confirmation. Avance par petites étapes : lance, lis la "
    "sortie, corrige, relance, jusqu'au résultat. Après une action, vérifie son effet par une "
    "lecture avant de dire que c'est fait : quand l'action doit changer un chiffre ou un "
    "état (place libérée, paquet installé, service démarré), ajoute au plan une mesure "
    "(mesure.commande, une lecture comme df -h /) ; elle est prise avant et après tes étapes. "
    "Compare-les : « vérifié » si l'après confirme, sinon « non vérifié ». Ne lance "
    "jamais sudo : propose la commande avec proposer_sudo ; il la lance lui-même en un appui "
    "(son mot de passe va directement à sudo), et sa sortie te revient. Une commande ne reçoit "
    "aucune "
    "entrée : utilise les options non interactives (-y, --yes). Pour lire un fichier, "
    "préfère cat, head, tail ou grep. Une mesure de place prend du temps (un dossier "
    "personnel : plusieurs minutes) : pour un disque plein, lance du -xh -d1 ~ 2>/dev/null | "
    "sort -h | tail -15 avec delai_s=300, puis descends dans les plus gros dossiers, sans "
    "rien supprimer. Une lecture coupée au délai se relance avec un delai_s plus grand "
    "(jusqu'à 900). Une commande qui ne se termine pas (serveur de "
    "développement, surveillance) : lance-la avec arriere_plan=true, puis vérifie qu'elle "
    "répond (ss -ltn, curl -I http://localhost:PORT). Si une vérification échoue (no-listen, "
    "erreur, code non nul), dis-le et corrige : n'annonce jamais un succès que la sortie "
    "contredit. Pour changer un fichier existant, lis-le, puis utilise modifier_fichier (un "
    "passage exact remplacé, dont le diff est montré) plutôt que de le réécrire. Après une "
    "modification de code, lance les tests du projet (pytest, npm test…) et corrige jusqu'à ce "
    "qu'ils passent. Un relecteur commente chaque modification proposée : s'il signale un "
    "problème, propose un plan corrigé. Quand un test échoue, avant de proposer un "
    "correctif, consulte les impasses du projet (consulter_impasses) ; si un correctif que tu "
    "as appliqué n'a pas réglé l'échec, note-le (noter_impasse). Pour une page web servie sur "
    "la machine (serveur de "
    "développement), regarde-la avec voir_page (une capture lue par la vision, avec les "
    "erreurs de la console) et corrige ce qui cloche à l'écran. Réponds court, en texte "
    "simple : c'est un terminal."
)
OS_CONTROL_ON = (
    "Contrôle du PC activé : tu peux ouvrir ou fermer une application, ouvrir une adresse "
    "dans son navigateur et ranger des fichiers (par un plan à valider), et regarder l'écran "
    "avec regarder_ecran quand on te le demande."
)
OS_CONTROL_OFF = (
    "Contrôle du PC désactivé : tu ne peux ni ouvrir ni fermer une application, ni ranger des "
    "fichiers, ni regarder l'écran. Si on te le demande, dis-le et indique qu'on l'active "
    "dans Réglages, section « Contrôle du PC »."
)
ROUNDS_EXHAUSTED = (
    "[Note du système] Tu as atteint le nombre d'étapes de cette réponse : n'appelle plus "
    "d'outil. Dis en deux ou trois phrases où tu en es et ce qu'il reste à faire ; "
    "l'utilisateur pourra te dire de continuer."
)
SHELL_ONLY = (
    "{tool} n'existe qu'en mode shell. Dis à l'utilisateur qu'il peut l'ouvrir (« passe en "
    "mode shell ») pour lancer des commandes."
)
PLAN_STARTED = (
    "Plan lancé : il ne fait que lire, il part donc sans attendre ; son résultat arrivera "
    "dans la conversation. N'appelle pas d'autre outil : dis en une phrase ce que tu fais."
)
PLAN_PENDING = (
    "Plan enregistré. L'utilisateur le voit à l'écran avec « Valider » et « Refuser » ; rien "
    "n'est exécuté avant sa décision. N'appelle pas d'autre outil. Dis-lui en une phrase "
    "qu'il attend sa validation, et ce que fera le plan seulement si tu ne l'as pas déjà "
    "dit : ne répète pas tes phrases d'avant, et ne pose pas de question (valider est sa "
    "réponse)."
)


#: L'état d'un plan, tel que Jarvis le lit à chaque tour (il ne le devine jamais).
PLAN_STATES = {
    "proposed": "attend la validation de l'utilisateur",
    "approved": "validé, en cours",
    "running": "en cours",
    "done": "exécuté",
    "failed": "échoué",
    "refused": "refusé",
    "stopped": "arrêté par l'utilisateur avant la fin",
}

#: Le modèle annonce un plan à valider (« le plan est prêt », « confirme à l'écran »…), ou
#: écrit l'appel de l'outil dans son texte au lieu de le faire.
PLAN_CLAIM = re.compile(
    r"(?:valid|confirm)\w*\s*(?:-le)?\s+(?:le\s+plan|à\s+l['’]écran)|plan\s+est\s+prêt"
    r"|attend\w*\s+ta\s+validation|passe\s+par\s+un\s+plan|voici\s+le\s+plan"
    r"|<\s*/?\s*proposer_un_plan",
    re.IGNORECASE,
)
#: « Je te prépare un plan » : une annonce, sauf posée en question (« je te prépare un plan
#: pour libérer ça ? »), qui attend ta réponse.
PLAN_PROMISE = re.compile(
    r"je\s+(?:te\s+)?(?:prépare|propose)\s+(?:le|ce|un)\s+plan", re.IGNORECASE
)
PLAN_MISSING = (
    "[Note du système] Tu viens d'annoncer un plan à valider, mais tu n'as pas appelé "
    "proposer_un_plan : aucun plan n'existe et l'utilisateur ne verra rien à valider. Propose-le "
    "maintenant (lis d'abord avec un outil de lecture ce qui te manque, un identifiant par "
    "exemple), ou dis en une phrase que tu ne peux pas."
)


#: Une offre (« tu veux que je te propose un plan ? ») n'annonce aucun plan : la relance
#: le faisait proposer sans attendre la réponse (essai du 28/10/2026).
PLAN_OFFER = re.compile(
    r"\b(?:tu\s+veux|veux-tu|voulez-vous|tu\s+souhaites|souhaites-tu|je\s+peux|dois-je)\b"
    r"[^?]*\?\s*$",
    re.IGNORECASE,
)


def claims_missing_plan(text: str, proposed: list[str]) -> bool:
    """Un plan annoncé dans la réponse alors qu'aucun n'a été proposé pendant le tour."""
    if proposed:
        return False
    for sentence in re.split(r"(?<=[.!?…])\s+|\n+", text):
        if PLAN_CLAIM.search(sentence) and not PLAN_OFFER.search(sentence):
            return True
        if PLAN_PROMISE.search(sentence) and not sentence.rstrip().endswith("?"):
            return True
    return False


_URL = re.compile(r"https?://[^\s<>\"'()\[\]{}«»]+")


def urls_in(value: Any) -> set[str]:
    """Adresses web citées dans un texte (ou dans les valeurs d'un résultat structuré)."""
    if isinstance(value, str):
        return {u.rstrip(".,;:!?").rstrip("/") for u in _URL.findall(value)}
    if isinstance(value, dict):
        return set().union(*(urls_in(v) for v in value.values())) if value else set()
    if isinstance(value, list | tuple):
        return set().union(*(urls_in(v) for v in value)) if value else set()
    return set()


@dataclass
class AgentTurn:
    """Ce qui s'est passé pendant un tour : outils utilisés, plans proposés."""

    #: Un contenu externe a été lu : un plan proposé ensuite est signalé à la validation.
    tainted: bool = False
    #: Tour du mode shell : seul à pouvoir lancer une commande (`executer_commande`).
    shell: bool = False
    #: Un contenu venu d'ailleurs a été lu (page, recherche, intégration, curl…) : « toujours »
    #: ne s'applique pas.
    web: bool = False
    tools: list[dict[str, Any]] = field(default_factory=list)
    plans: list[str] = field(default_factory=list)
    #: Adresses connues pendant ce tour : celles de ta demande et celles lues (liens, résultats).
    known_urls: set[str] = field(default_factory=set)

    def knows(self, url: str) -> bool:
        return url.strip().rstrip("/") in self.known_urls


class ShellOnlyError(EngineError):
    status_code = 403
    code = "shell_only"


@dataclass(frozen=True)
class CallOutcome:
    content: str
    event: dict[str, Any]
    is_error: bool = False
    plan: PlanRecord | None = None


#: L'outil des commandes du mode shell (`ojarvis.tools.shell.RunCommand`).
SHELL_TOOL = "executer_commande"


@dataclass(frozen=True, slots=True)
class RanCommand:
    """Une commande que l'utilisateur a lancée lui-même (sudo, proposée par Jarvis)."""

    command: str
    code: int
    output: str


@dataclass(frozen=True)
class PlanReport:
    """Les résultats d'un plan fini, rendus au modèle pour la suite du mode shell."""

    text: str
    #: La demande d'origine : la suite d'un plan n'a pour texte que « Continue. ».
    request: str
    #: Des sorties de commandes sont revenues : des données, jamais des consignes.
    tainted: bool = False
    #: L'une d'elles a parlé au réseau (curl, git clone…) : pas de « toujours » ensuite.
    web: bool = False
    urls: frozenset[str] = frozenset()
    #: Chaque commande lancée, et si elle a échoué : de quoi voir un test toujours rouge.
    commands: tuple[tuple[str, bool], ...] = ()


#: « code de sortie 1 (0,4 s) » dans la sortie d'une commande.
EXIT_CODE = re.compile(r"code de sortie (-?\d+)")


def command_failed(step: StepRecord) -> bool:
    """Une commande en échec : l'étape a échoué, ou la commande a rendu un code non nul."""
    if step.status == "failed":
        return True
    found = EXIT_CODE.search(step.result or "")
    return found is not None and found.group(1) != "0"


#: Sources de ta machine : un fichier, le bac à sable, les tests d'un skill.
LOCAL_SOURCES = frozenset({"bac à sable", "tests du skill", "carte de la machine"})


def from_web(source: str | None, command: str | None = None) -> bool:
    """Une donnée venue d'ailleurs que ta machine : une page, une recherche, une intégration
    (GitHub, Notion…), un serveur MCP, un agent, ton écran, ou une commande qui parle au
    réseau (curl, git clone…). Un contenu piégé peut s'y cacher."""
    if not source:
        return False
    if "://" in source:
        host = urlsplit(source).hostname or ""
        return host not in ("localhost", "127.0.0.1", "::1")
    if source.startswith(("/", "~")):
        return False  # un fichier de ta machine
    if source == "commande":
        return command is not None and talks_to_network(command)
    return source not in LOCAL_SOURCES


def plan_summary(
    plan: PlanRecord,
    previews: dict[int, str] | None = None,
    review: Review | None = None,
    *,
    web: bool = False,
) -> dict[str, Any]:
    """Le plan tel qu'il s'affiche : ses étapes (outil, commande, aperçu en diff), l'avis du
    relecteur, et s'il suit une lecture venue du web."""
    previews = previews or {}
    summary: dict[str, Any] = {
        "id": plan.id,
        "title": plan.title,
        "status": plan.status,
        "max_level": plan.max_level,
        "tainted": plan.tainted,
        "web": web,
        "steps": [
            {
                "position": s.position,
                "description": s.description,
                "level": s.level,
                "tool": s.tool,
                **(
                    {"command": str(s.arguments["commande"])}
                    if s.tool == "executer_commande" and "commande" in s.arguments
                    else {}
                ),
                **({"preview": previews[s.position]} if s.position in previews else {}),
                **(
                    {"measure": "avant" if s.why == MEASURE_BEFORE else "après"}
                    if s.why in (MEASURE_BEFORE, MEASURE_AFTER)
                    else {}
                ),
            }
            for s in plan.steps
        ],
    }
    if review is not None:
        summary["review"] = review.as_dict()
    return summary


class Agent:
    def __init__(
        self,
        *,
        gate: PermissionGate,
        plans: PlanStore,
        bus: EventBus,
        executor: PlanExecutor | None = None,
        reviewer: CodeReviewer | None = None,
    ) -> None:
        self._gate = gate
        self._plans = plans
        self._bus = bus
        self._executor = executor
        #: Mode shell : relit chaque modification de code avant ta validation.
        self._reviewer = reviewer

    async def plan_states(self, conversation_id: str) -> str:
        """L'état réel des plans de la conversation, du plus ancien au plus récent."""
        plans = await self._plans.list(limit=8, conversation_id=conversation_id)
        if not plans:
            return ""
        lines = [
            f"- « {' '.join(p.title.split())[:80]} » : {PLAN_STATES.get(p.status, p.status)}"
            for p in reversed(plans)
        ]
        return "État réel des plans de cette conversation (du plus ancien au plus récent) :\n" + (
            "\n".join(lines)
        )

    async def plan_report(self, plan_id: str, conversation_id: str) -> PlanReport:
        """Les résultats d'un plan fini de cette conversation, marqués comme données : en mode
        shell, Jarvis les lit pour continuer (corriger, relancer, vérifier)."""
        plan = await self._plans.get(plan_id)
        if plan.conversation_id != conversation_id:
            raise NotFoundError("Ce plan n'appartient pas à cette conversation.")
        if plan.status not in FINISHED:
            raise ConflictError("Ce plan n'est pas encore terminé.")
        if plan.status == "refused":
            refused = f"L'utilisateur a refusé le plan « {plan.title} » : rien n'a été lancé."
            return PlanReport(refused, plan.request, tainted=plan.tainted)
        ran = [step for step in plan.steps if step.status == "done"]
        commands = [str(s.arguments.get("commande", "")) for s in ran if s.tool == SHELL_TOOL]
        report = PlanReport(
            "",
            plan.request,
            # Des sorties de commandes ou de fichiers : des données, jamais des consignes.
            tainted=plan.tainted or bool(ran),
            web=any(talks_to_network(command) for command in commands if command),
            urls=frozenset(urls_in([step.result or "" for step in ran])),
            commands=tuple(
                (" ".join(str(step.arguments.get("commande", "")).split()), command_failed(step))
                for step in plan.steps
                if step.tool == SHELL_TOOL and step.status in ("done", "failed")
            ),
        )
        sections = []
        measured = any(step.why == MEASURE_BEFORE for step in plan.steps)
        for step in plan.steps:
            if step.why in (MEASURE_BEFORE, MEASURE_AFTER) and step.status == "done":
                label = "Mesure avant" if step.why == MEASURE_BEFORE else "Mesure après"
                body = as_data(step.result or "", origin="commande")
                sections.append(f"{label} ({step.description}) :\n{body}")
            elif step.status == "done":
                body = as_data(step.result or "", origin="commande")
                sections.append(f"Étape {step.position}, faite ({step.description}) :\n{body}")
            elif step.status == "failed":
                sections.append(f"Étape {step.position}, échec ({step.description}) : {step.error}")
            else:
                sections.append(f"Étape {step.position}, non lancée ({step.description}).")
        state = PLAN_STATES.get(plan.status, plan.status)
        text = (
            f"Le plan validé « {plan.title} » est {state}. Résultats :\n\n"
            + "\n\n".join(sections)
            + "\n\nContinue la tâche à partir de ces résultats, ou conclus si elle est finie."
        )
        if measured:
            text += (
                " Compare la mesure d'avant et celle d'après : si l'après confirme le résultat, "
                "dis « vérifié » avec les deux chiffres ; sinon dis « non vérifié » et ce qui "
                "manque, jamais « fait »."
            )
        elif any(step.level >= Level.AGIR and step.tool == SHELL_TOOL for step in ran):
            text += (
                " Ce plan n'avait pas de mesure : ne dis pas « fait ». Vérifie par une lecture, "
                "ou dis « non vérifié »."
            )
        return replace(report, text=text)

    async def user_ran(self, ran: RanCommand) -> PlanReport:
        """Une commande lancée par l'utilisateur lui-même : au journal, puis rendue au modèle
        comme une donnée, masquée, pour qu'il continue."""
        await self._gate.note_user_command(ran.command, ran.code)
        output = REDACTOR.redact(ran.output)
        body = as_data(
            f"$ {ran.command}\ncode de sortie {ran.code}\n--- sortie ---\n{output}",
            origin="commande lancée par l’utilisateur",
        )
        text = (
            f"L'utilisateur a lancé lui-même la commande proposée (code de sortie {ran.code}). "
            f"Résultat :\n\n{body}\n\nContinue la tâche à partir de ce résultat, ou conclus si "
            "elle est finie."
        )
        return PlanReport(
            text,
            "",
            tainted=True,
            web=talks_to_network(ran.command),
            urls=frozenset(urls_in(output)),
            commands=((" ".join(ran.command.split()), ran.code != 0),),
        )

    def rules(self, *, shell_folder: str | None = None) -> str:
        """Consignes du tour, selon ce que Jarvis a le droit de faire en ce moment."""
        os_control = OS_CONTROL_ON if self._gate.os_control() else OS_CONTROL_OFF
        terminal = NO_TERMINAL if shell_folder is None else SHELL_RULES.format(folder=shell_folder)
        return f"{AGENT_RULES}\n\n{terminal}\n\n{os_control}"

    def specs(self, *, shell_mode: bool = False) -> list[ToolSpec]:
        specs = self._gate.registry.specs(
            max_level=Level.DETRUIRE, os_control=self._gate.os_control(), shell_mode=shell_mode
        )
        return [*specs, plan_tool_spec()]

    async def _previews(self, plan_in: PlanIn) -> dict[int, str]:
        previews: dict[int, str] = {}
        touched: set[str] = set()
        after_command = False
        for position, step in enumerate(plan_in.etapes, 1):
            target = str(step.arguments.get("chemin", ""))
            if step.outil == SHELL_TOOL:
                # Une mesure ne change rien : les retouches qui la suivent gardent leur diff.
                after_command = after_command or step.pourquoi != MEASURE_BEFORE
                continue
            if (
                PLACEHOLDER.search(str(step.arguments))
                or (target and target in touched)
                or after_command
            ):
                # Cible connue seulement à l'exécution, ou fichier qu'une étape précédente a
                # pu changer ou créer : son aperçu ne serait pas juste, le résultat le montrera.
                continue
            preview = await anyio.to_thread.run_sync(self._gate.preview, step.outil, step.arguments)
            if preview is not None:
                previews[position] = preview
                touched.add(target)
        return previews

    def _measured(self, plan_in: PlanIn, turn: AgentTurn) -> PlanIn:
        """La mesure d'un plan (#15) : une lecture prise avant les étapes, puis après. Sans
        elle, Jarvis ne peut pas montrer la preuve de l'effet."""
        measure = plan_in.mesure
        if measure is None:
            return self._final_read_as_measure(plan_in, turn)
        self._require_shell(SHELL_TOOL, turn)
        folders = [
            str(s.arguments["dossier"]) for s in plan_in.etapes if s.arguments.get("dossier")
        ]
        folder = measure.dossier or (folders[0] if folders else "~")
        arguments = {"commande": measure.commande, "dossier": folder}
        _tool, _args, level = self._gate.check(SHELL_TOOL, arguments)
        if level != Level.LIRE:
            raise InvalidInputError(
                "La mesure d'un plan est une simple lecture (df, ls, systemctl status…)."
            )
        if len(plan_in.etapes) + 2 > MAX_STEPS:
            raise InvalidInputError(
                f"Avec la mesure avant et après, le plan dépasserait {MAX_STEPS} étapes."
            )
        before = StepIn(outil=SHELL_TOOL, arguments=arguments, pourquoi=MEASURE_BEFORE)
        after = StepIn(outil=SHELL_TOOL, arguments=arguments, pourquoi=MEASURE_AFTER)
        return PlanIn(titre=plan_in.titre, etapes=[before, *plan_in.etapes, after])

    def _final_read_as_measure(self, plan_in: PlanIn, turn: AgentTurn) -> PlanIn:
        """Un plan d'actions qui finit par une lecture (« touch a.txt » puis « ls -l a.txt ») :
        cette vérification devient sa mesure, prise aussi avant les actions (#15). Muse Spark
        écrit ainsi sa preuve plus souvent qu'il ne remplit la mesure (essai du 28/10/2026)."""
        last = plan_in.etapes[-1]
        if (
            not turn.shell
            or len(plan_in.etapes) < 2
            or len(plan_in.etapes) + 1 > MAX_STEPS
            or last.outil != SHELL_TOOL
            or PLACEHOLDER.search(str(last.arguments))
        ):
            return plan_in
        try:
            levels = [self._gate.check(s.outil, s.arguments)[2] for s in plan_in.etapes]
        except EngineError:
            return plan_in  # la proposition dira l'erreur
        if levels[-1] != Level.LIRE or max(levels[:-1]) < Level.AGIR:
            return plan_in
        before = StepIn(outil=SHELL_TOOL, arguments=last.arguments, pourquoi=MEASURE_BEFORE)
        after = StepIn(outil=SHELL_TOOL, arguments=last.arguments, pourquoi=MEASURE_AFTER)
        return PlanIn(titre=plan_in.titre, etapes=[before, *plan_in.etapes[:-1], after])

    def _require_shell(self, name: str, turn: AgentTurn) -> None:
        """Hors du mode shell, une commande n'est ni lancée ni proposée, même si le modèle
        appelle l'outil sans l'avoir vu, ou le glisse dans un plan."""
        registry = self._gate.registry
        if not turn.shell and name in registry and registry.get(name).shell_only:
            raise ShellOnlyError(SHELL_ONLY.format(tool=name))

    def describe(self, call: ToolCall) -> str:
        """Ce que fait l'appel, en clair (pour l'interface), sans rien exécuter."""
        if call.name == PLAN_TOOL:
            return "Préparer un plan"
        try:
            tool, args, _ = self._gate.check(call.name, call.arguments)
        except EngineError:
            return call.name
        return tool.describe(args)

    async def handle(
        self,
        call: ToolCall,
        turn: AgentTurn,
        *,
        conversation_id: str | None,
        request: str,
    ) -> CallOutcome:
        if call.name == PLAN_TOOL:
            try:
                plan_in = PlanIn.model_validate(call.arguments)
            except ValidationError as exc:
                first = exc.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                return self._failed(call, f"Plan invalide ({where} : {first.get('msg')}).")
            return await self._propose(call, plan_in, turn, conversation_id, request)
        try:
            self._require_shell(call.name, turn)
            tool, args, level = self._gate.check(call.name, call.arguments)
        except EngineError as exc:
            return self._failed(call, exc.message)
        if level >= Level.AGIR:
            # Une action n'est jamais exécutée sur un simple appel : elle devient un plan.
            plan_in = PlanIn(
                titre=tool.describe(args)[:120],
                etapes=[
                    StepIn(
                        outil=call.name,
                        arguments=call.arguments,
                        pourquoi="Action demandée pendant la conversation.",
                    )
                ],
            )
            return await self._propose(call, plan_in, turn, conversation_id, request)
        url = call.arguments.get("url")
        if turn.tainted and isinstance(url, str) and not turn.knows(url):
            # Après une lecture externe, une adresse fabriquée (absente de ta demande et de ce
            # qui a été lu) pourrait servir à faire fuir des données : tu valides d'abord.
            plan_in = PlanIn(
                titre=f"Ouvrir {url}"[:120],
                etapes=[
                    StepIn(
                        outil=call.name,
                        arguments=call.arguments,
                        pourquoi=(
                            "Adresse absente de ta demande et des pages lues : elle peut "
                            "venir d'un contenu piégé."
                        ),
                    )
                ],
            )
            return await self._propose(call, plan_in, turn, conversation_id, request)
        return await self._read(
            call,
            tool.describe(args),
            int(level),
            turn,
            conversation_id=conversation_id,
            request=request,
        )

    async def _read(
        self,
        call: ToolCall,
        description: str,
        level: int,
        turn: AgentTurn,
        *,
        conversation_id: str | None,
        request: str,
    ) -> CallOutcome:
        """Outil de niveau 1 : exécuté tout de suite, par la porte des permissions."""
        try:
            output = await self._gate.execute(call.name, call.arguments)
        except EngineError as exc:
            return self._failed(call, exc.message, description)
        except Exception as exc:
            log.exception("tool_failed", tool=call.name)
            return self._failed(call, f"Erreur inattendue ({type(exc).__name__}).", description)
        event = {
            "id": call.id,
            "name": call.name,
            "description": description,
            "level": level,
            "status": "done",
            "source": output.source,
        }
        if self._gate.registry.get(call.name).shell_only:
            # Le terminal montre la fin de la sortie ; le modèle, lui, la lit en entier.
            event["output"] = REDACTOR.redact(output.text[-OUTPUT_PREVIEW_CHARS:])
        if isinstance(output.data, dict) and output.data.get("sudo"):
            event["sudo"] = output.data["sudo"]  # le terminal la propose : tu la lances
        turn.tools.append(event)
        turn.known_urls |= urls_in(output.text) | urls_in(output.data)
        if output.external:
            turn.tainted = True
            command = call.arguments.get("commande")
            turn.web = turn.web or from_web(
                output.source, command if isinstance(command, str) else None
            )
        content = as_data(output.text, origin=output.source) if output.external else output.text
        if output.follow_up is None:
            return CallOutcome(content, event)
        # L'outil propose sa suite (ex. activer un skill dont les tests ont réussi) : un plan,
        # au niveau de cette suite, qui attend ta décision.
        follow = output.follow_up
        plan_in = PlanIn(
            titre=follow.why[:120],
            etapes=[StepIn(outil=follow.tool, arguments=follow.arguments, pourquoi=follow.why)],
        )
        proposed = await self._propose(call, plan_in, turn, conversation_id, request)
        return CallOutcome(f"{content}\n\n{proposed.content}", event, plan=proposed.plan)

    async def _propose(
        self,
        call: ToolCall,
        plan_in: PlanIn,
        turn: AgentTurn,
        conversation_id: str | None,
        request: str,
    ) -> CallOutcome:
        try:
            plan_in = self._measured(plan_in, turn)
            for step in plan_in.etapes:
                self._require_shell(step.outil, turn)
            # Le diff de chaque modification, montré avant ta validation. Une retouche qui ne
            # s'appliquerait pas (passage introuvable) revient au modèle, pas à toi.
            previews = await self._previews(plan_in)
            plan = await self._plans.create(
                plan_in, conversation_id=conversation_id, request=request, tainted=turn.tainted
            )
        except EngineError as exc:
            return self._failed(call, f"Plan refusé : {exc.message} Corrige-le.")
        turn.plans.append(plan.id)
        if self._executor is not None and plan.max_level == 1 and not plan.tainted:
            plan = await self._executor.start(plan.id)
            event = {
                "id": call.id,
                "name": PLAN_TOOL,
                "description": f"Plan lancé : {plan.title}",
                "level": plan.max_level,
                "status": "proposed",
                "plan": plan_summary(plan),
            }
            turn.tools.append({k: v for k, v in event.items() if k != "plan"})
            return CallOutcome(PLAN_STARTED, event, plan=plan)
        review = None
        if previews and turn.shell and self._reviewer is not None:
            review = await self._reviewer.review(request, list(previews.values()))
        summary = plan_summary(plan, previews, review, web=turn.web)
        await self._bus.publish(
            "plan.proposed",
            {"id": plan.id, "title": plan.title, "max_level": plan.max_level},
        )
        steps = "\n".join(
            f"{s.position}. {s.description} (niveau {s.level} : {LEVEL_LABELS[Level(s.level)]})"
            for s in plan.steps
        )
        if review is not None:
            # L'auteur lit l'avis : s'il signale un problème, il peut proposer un plan corrigé.
            steps += f"\n\n{review.for_author()}"
        event = {
            "id": call.id,
            "name": PLAN_TOOL,
            "description": f"Plan proposé : {plan.title}",
            "level": plan.max_level,
            "status": "proposed",
            "plan": summary,
        }
        turn.tools.append({k: v for k, v in event.items() if k != "plan"})
        return CallOutcome(f"{PLAN_PENDING}\n\nÉtapes :\n{steps}", event, plan=plan)

    @staticmethod
    def _failed(call: ToolCall, message: str, description: str | None = None) -> CallOutcome:
        event = {
            "id": call.id,
            "name": call.name,
            "description": description or call.name,
            "status": "failed",
            "error": message,
        }
        return CallOutcome(f"Échec : {message}", event, is_error=True)
