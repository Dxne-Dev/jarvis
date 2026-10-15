"""Un skill : un module versionné (description, mode d'emploi, outils, code, tests).

Jarvis peut s'en construire un. Son code est du Python pur qui tourne toujours dans le bac
à sable : ni Internet, ni tes fichiers, ni tes clés ; temps et mémoire bornés. Chaque outil
est une fonction du code, avec le schéma JSON de ses arguments.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import jsonschema
from pydantic import Field, field_validator, model_validator

from ojarvis.tools.base import ToolArgs

SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"
TOOL_NAME = r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$"
SEMVER = r"^\d{1,4}\.\d{1,4}\.\d{1,4}$"


class SkillTool(ToolArgs):
    nom: str = Field(
        min_length=2, max_length=30, pattern=TOOL_NAME, description="Nom de la fonction Python."
    )
    description: str = Field(min_length=5, max_length=300, description="Ce que fait l'outil.")
    parametres: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="Schéma JSON (objet) des arguments de la fonction.",
    )

    @field_validator("parametres")
    @classmethod
    def _schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("type") != "object":
            raise ValueError("le schéma des arguments doit décrire un objet")
        if len(json.dumps(value)) > 5_000:
            raise ValueError("schéma des arguments trop long (5 000 caractères au plus)")
        try:
            jsonschema.Draft202012Validator.check_schema(value)
        except jsonschema.SchemaError as exc:
            raise ValueError(f"schéma JSON invalide : {exc.message}") from exc
        return value


class SkillDefinition(ToolArgs):
    nom: str = Field(
        min_length=3,
        max_length=30,
        pattern=SLUG,
        description="Identifiant : minuscules, chiffres et tirets (ex. jours-entre-dates).",
    )
    version: str = Field(default="1.0.0", pattern=SEMVER, description="Version (ex. 1.0.0).")
    description: str = Field(min_length=5, max_length=300, description="À quoi sert le skill.")
    instructions: str = Field(
        default="", max_length=1000, description="Mode d'emploi : quand et comment l'utiliser."
    )
    outils: list[SkillTool] = Field(
        min_length=1, max_length=8, description="Les fonctions exposées, chacune décrite."
    )
    code: str = Field(
        min_length=10,
        max_length=20_000,
        description="Module Python pur (bibliothèque standard seulement) qui définit chaque outil.",
    )
    tests: str = Field(
        min_length=10,
        max_length=20_000,
        description="Fonctions test_… avec des assert ; elles voient les fonctions du code.",
    )

    @model_validator(mode="after")
    def _coherent(self) -> SkillDefinition:
        names = [t.nom for t in self.outils]
        if len(set(names)) != len(names):
            raise ValueError("deux outils portent le même nom")
        if "def test_" not in self.tests:
            raise ValueError("il faut au moins une fonction test_… dans les tests")
        return self

    def manifest(self) -> dict[str, Any]:
        """Ce qui décrit le skill, sans son code ni ses tests (gardés à part)."""
        return {
            "instructions": self.instructions,
            "outils": [t.model_dump() for t in self.outils],
        }

    def digest(self) -> str:
        """Empreinte de tout le skill : la version testée est celle qui sera activée."""
        canonical = json.dumps(self.model_dump(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def tool_name(skill: str, tool: str) -> str:
    """Nom de l'outil vu par le modèle : `jours_entre_dates__compter` (≤ 64 caractères)."""
    return f"{skill.replace('-', '_')}__{tool}"
