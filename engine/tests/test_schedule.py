"""Horaires des automatisations : heure locale, changements d'heure, jours, mois."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from ojarvis.automations.schedule import Daily, Every, Monthly, Once, describe, next_run

PARIS = ZoneInfo("Europe/Paris")


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def local(moment: datetime | None) -> str:
    assert moment is not None
    return moment.astimezone(PARIS).strftime("%Y-%m-%d %H:%M %z")


def test_eight_oclock_stays_eight_oclock_across_the_spring_change() -> None:
    # Le 29 mars 2026, Paris passe de UTC+1 à UTC+2.
    morning = Daily(heure="08:00")
    before = next_run(morning, utc("2026-03-28T05:00"), PARIS)
    after = next_run(morning, utc("2026-03-28T07:30"), PARIS)
    assert local(before) == "2026-03-28 08:00 +0100"
    assert before == utc("2026-03-28T07:00")
    assert local(after) == "2026-03-29 08:00 +0200"
    assert after == utc("2026-03-29T06:00")  # même heure locale, une heure UTC plus tôt


def test_eight_oclock_stays_eight_oclock_across_the_autumn_change() -> None:
    # Le 25 octobre 2026, Paris repasse de UTC+2 à UTC+1.
    morning = Daily(heure="08:00")
    assert local(next_run(morning, utc("2026-10-24T05:00"), PARIS)) == "2026-10-24 08:00 +0200"
    sunday = next_run(morning, utc("2026-10-24T07:00"), PARIS)
    assert local(sunday) == "2026-10-25 08:00 +0100"
    assert sunday == utc("2026-10-25T07:00")


def test_a_time_that_does_not_exist_runs_one_hour_later() -> None:
    # 2 h 30 n'existe pas le 29 mars 2026 : on passe de 2 h à 3 h.
    night = Daily(heure="02:30")
    moment = next_run(night, utc("2026-03-28T23:00"), PARIS)
    assert local(moment) == "2026-03-29 03:30 +0200"


def test_a_time_that_exists_twice_runs_only_once() -> None:
    # 2 h 30 existe deux fois le 25 octobre 2026 : une seule exécution, à la première.
    night = Daily(heure="02:30")
    first = next_run(night, utc("2026-10-24T22:00"), PARIS)
    assert first == utc("2026-10-25T00:30")
    following = next_run(night, first, PARIS)
    assert local(following) == "2026-10-26 02:30 +0100"


def test_weekdays_only() -> None:
    weekdays = Daily(heure="07:30", jours=[0, 1, 2, 3, 4])
    friday_evening = utc("2026-10-16T18:00")
    assert local(next_run(weekdays, friday_evening, PARIS)) == "2026-10-19 07:30 +0200"


def test_once_then_never_again() -> None:
    once = Once(le="2026-10-16T09:00")
    assert next_run(once, utc("2026-10-15T12:00"), PARIS) == utc("2026-10-16T07:00")
    assert next_run(once, utc("2026-10-16T07:00"), PARIS) is None


def test_interval_and_month_end() -> None:
    assert next_run(Every(minutes=30), utc("2026-10-15T12:00"), PARIS) == utc("2026-10-15T12:30")
    end = Monthly(jour=31, heure="09:00")
    assert local(next_run(end, utc("2026-02-01T00:00"), PARIS)) == "2026-02-28 09:00 +0100"
    assert local(next_run(end, utc("2026-03-01T00:00"), PARIS)) == "2026-03-31 09:00 +0200"


def test_descriptions_are_plain_french() -> None:
    assert describe(Daily(heure="8:00")) == "Tous les jours à 8 h 00"
    assert describe(Daily(heure="07:30", jours=[0, 1, 2, 3, 4])) == "Du lundi au vendredi à 7 h 30"
    assert describe(Daily(heure="10:00", jours=[5, 6])) == "Le week-end à 10 h 00"
    assert describe(Daily(heure="18:15", jours=[2])) == "Le mercredi à 18 h 15"
    assert describe(Daily(heure="18:15", jours=[0, 3])) == "Les lundi et jeudi à 18 h 15"
    assert describe(Once(le="2026-10-16T09:05")) == "Le 16 octobre 2026 à 9 h 05"
    assert describe(Every(minutes=90)) == "Toutes les 90 minutes"
    assert describe(Every(minutes=120)) == "Toutes les 2 heures"
    assert describe(Monthly(jour=1, heure="09:00")) == "Le 1er de chaque mois à 9 h 00"


@pytest.mark.parametrize(
    "build",
    [
        lambda: Daily(heure="25:00"),
        lambda: Daily(heure="08:00", jours=[7]),
        lambda: Daily(heure="08:00", jours=[]),
        lambda: Once(le="demain"),
        lambda: Once(le="2026-10-16T09:00+02:00"),
        lambda: Every(minutes=1),
        lambda: Monthly(jour=32, heure="09:00"),
    ],
)
def test_bad_schedules_are_refused(build: object) -> None:
    with pytest.raises(ValidationError):
        build()  # type: ignore[operator]
