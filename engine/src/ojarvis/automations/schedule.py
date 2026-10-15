"""Quand une automatisation tourne : calcul en heure locale, rangement en UTC.

« Tous les matins à 8 h » doit rester 8 h après chaque changement d'heure. On calcule donc
la prochaine date dans le fuseau du système (zoneinfo connaît ses règles), puis on la
convertit en UTC pour la ranger. Les deux nuits délicates :
- au printemps, 2 h 30 n'existe pas : l'automatisation tourne à 3 h 30 ;
- à l'automne, 2 h 30 existe deux fois : elle tourne une seule fois, à la première.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _parse_hhmm(value: str) -> time:
    match = _HHMM.match(value.strip())
    if not match:
        raise ValueError("heure attendue au format HH:MM (ex. 08:00)")
    return time(int(match.group(1)), int(match.group(2)))


def say_time(moment: time) -> str:
    return f"{moment.hour} h {moment.minute:02d}"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Daily(_Base):
    """Chaque jour (ou certains jours de la semaine) à une heure locale."""

    type: Literal["chaque_jour"] = "chaque_jour"
    heure: str = Field(description="Heure locale, HH:MM (ex. 08:00).")
    jours: list[int] = Field(
        default_factory=lambda: list(range(7)),
        description="Jours de la semaine : 0 = lundi … 6 = dimanche (tous par défaut).",
    )

    @field_validator("heure")
    @classmethod
    def _check_time(cls, value: str) -> str:
        parsed = _parse_hhmm(value)
        return f"{parsed.hour:02d}:{parsed.minute:02d}"

    @field_validator("jours")
    @classmethod
    def _check_days(cls, value: list[int]) -> list[int]:
        days = sorted(set(value))
        if not days or any(d < 0 or d > 6 for d in days):
            raise ValueError("jours entre 0 (lundi) et 6 (dimanche)")
        return days


class Once(_Base):
    """Une seule fois, à une date et une heure locales."""

    type: Literal["une_fois"] = "une_fois"
    le: str = Field(description="Date et heure locales, AAAA-MM-JJTHH:MM (ex. 2026-10-16T09:00).")

    @field_validator("le")
    @classmethod
    def _check_moment(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError("date attendue au format AAAA-MM-JJTHH:MM") from exc
        if parsed.tzinfo is not None:
            raise ValueError("donne l'heure locale, sans fuseau")
        return parsed.strftime("%Y-%m-%dT%H:%M")


class Every(_Base):
    """À intervalle régulier."""

    type: Literal["intervalle"] = "intervalle"
    minutes: int = Field(ge=5, le=7 * 24 * 60, description="Toutes les N minutes (5 au moins).")


class Monthly(_Base):
    """Chaque mois, un jour donné (le dernier jour si le mois est plus court)."""

    type: Literal["chaque_mois"] = "chaque_mois"
    jour: int = Field(ge=1, le=31, description="Jour du mois, 1 à 31.")
    heure: str = Field(description="Heure locale, HH:MM.")

    @field_validator("heure")
    @classmethod
    def _check_time(cls, value: str) -> str:
        parsed = _parse_hhmm(value)
        return f"{parsed.hour:02d}:{parsed.minute:02d}"


AnySchedule = Daily | Once | Every | Monthly
Schedule = Annotated[AnySchedule, Field(discriminator="type")]


def _wall(day: date, moment: time, tz: tzinfo) -> datetime:
    """Heure locale d'un jour donné, ramenée à un instant réel (changements d'heure gérés)."""
    local = datetime.combine(day, moment, tzinfo=tz)
    # Aller-retour par UTC : une heure qui n'existe pas (printemps) glisse d'une heure.
    return local.astimezone(UTC).astimezone(tz)


def next_run(schedule: AnySchedule, after: datetime, tz: tzinfo) -> datetime | None:
    """Prochain passage strictement après `after` (UTC), ou None s'il n'y en a plus."""
    after = after.astimezone(UTC)
    local = after.astimezone(tz)
    if isinstance(schedule, Every):
        return after + timedelta(minutes=schedule.minutes)
    if isinstance(schedule, Once):
        moment = _wall_from_iso(schedule.le, tz)
        return moment.astimezone(UTC) if moment > after else None
    if isinstance(schedule, Daily):
        at = _parse_hhmm(schedule.heure)
        for offset in range(8):
            day = local.date() + timedelta(days=offset)
            if day.weekday() not in schedule.jours:
                continue
            candidate = _wall(day, at, tz)
            if candidate > after:
                return candidate.astimezone(UTC)
        return None  # pragma: no cover - au moins un jour par semaine
    at = _parse_hhmm(schedule.heure)
    year, month = local.year, local.month
    for _ in range(13):
        last = calendar.monthrange(year, month)[1]
        candidate = _wall(date(year, month, min(schedule.jour, last)), at, tz)
        if candidate > after:
            return candidate.astimezone(UTC)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None  # pragma: no cover


def _wall_from_iso(value: str, tz: tzinfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _wall(parsed.date(), parsed.time(), tz)


def describe(schedule: AnySchedule) -> str:
    """En français, comme on le dirait."""
    if isinstance(schedule, Every):
        if schedule.minutes % 60 == 0:
            hours = schedule.minutes // 60
            return "Toutes les heures" if hours == 1 else f"Toutes les {hours} heures"
        return f"Toutes les {schedule.minutes} minutes"
    if isinstance(schedule, Once):
        moment = datetime.fromisoformat(schedule.le)
        return (
            f"Le {moment.day} {_MONTHS[moment.month - 1]} {moment.year} à {say_time(moment.time())}"
        )
    at = say_time(_parse_hhmm(schedule.heure))
    if isinstance(schedule, Monthly):
        day = "1er" if schedule.jour == 1 else str(schedule.jour)
        return f"Le {day} de chaque mois à {at}"
    return f"{_describe_days(schedule.jours)} à {at}"


def _describe_days(days: list[int]) -> str:
    if days == list(range(7)):
        return "Tous les jours"
    if days == list(range(5)):
        return "Du lundi au vendredi"
    if days == [5, 6]:
        return "Le week-end"
    names = [DAYS[d] for d in days]
    if len(names) == 1:
        return f"Le {names[0]}"
    return "Les " + ", ".join(names[:-1]) + " et " + names[-1]
