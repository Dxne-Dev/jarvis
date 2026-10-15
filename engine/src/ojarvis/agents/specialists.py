"""Les trois agents de départ : développement, recherche, coach d'apprentissage."""

from __future__ import annotations

from typing import ClassVar

from ojarvis.agents.base import BaseAgent


class DevAgent(BaseAgent):
    name: ClassVar[str] = "dev"
    label: ClassVar[str] = "Développement"
    goal: ClassVar[str] = (
        "comprendre et écrire du code : lire les fichiers du projet, essayer du Python dans le "
        "bac à sable, regarder les dépôts et issues GitHub, proposer des modifications précises "
        "(fichier, contenu) que l'utilisateur validera."
    )
    tools: ClassVar[tuple[str, ...]] = (
        "lire_fichier",
        "lister_dossier",
        "executer_code",
        "ecrire_fichier",
        "recherche_web",
        "lire_page",
        "integrations_outils",
        "integration_appeler",
    )


class ResearchAgent(BaseAgent):
    name: ClassVar[str] = "recherche"
    label: ClassVar[str] = "Recherche"
    goal: ClassVar[str] = (
        "trouver et recouper l'information : chercher sur le web, lire les pages, comparer les "
        "sources et rendre une synthèse sourcée (adresses citées), en signalant ce qui est "
        "incertain."
    )
    tools: ClassVar[tuple[str, ...]] = (
        "recherche_web",
        "lire_page",
        "navigateur_ouvrir",
        "navigateur_lire",
        "integrations_outils",
        "integration_appeler",
    )
    max_steps: ClassVar[int] = 8


class CoachAgent(BaseAgent):
    name: ClassVar[str] = "coach"
    label: ClassVar[str] = "Coach d'apprentissage"
    goal: ClassVar[str] = (
        "aider l'utilisateur à apprendre : une notion à la fois, expliquée simplement avec un "
        "exemple, puis une seule question pour vérifier ; un exercice si utile (vérifié dans le "
        "bac à sable) ; des rappels espacés (automatisations, qu'il validera) pour réviser."
    )
    tools: ClassVar[tuple[str, ...]] = (
        "recherche_web",
        "lire_page",
        "executer_code",
        "lister_automatisations",
        "creer_automatisation",
    )


STARTERS: tuple[type[BaseAgent], ...] = (DevAgent, ResearchAgent, CoachAgent)
