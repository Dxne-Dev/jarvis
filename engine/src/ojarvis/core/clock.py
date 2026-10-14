"""Heures : tout est stocké en UTC ; le fuseau local est celui du système, jamais codé en dur."""

from __future__ import annotations

import os
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_iso(moment: datetime) -> str:
    """Format ISO 8601 en UTC avec le suffixe Z."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def system_timezone_name() -> str | None:
    """Nom IANA du fuseau du système (`TZ`, puis `/etc/localtime`, puis `/etc/timezone`)."""
    tz_env = os.environ.get("TZ", "").lstrip(":")
    if tz_env and "/" in tz_env:
        return tz_env
    localtime = Path("/etc/localtime")
    if localtime.is_symlink():
        target = str(localtime.resolve())
        marker = "zoneinfo/"
        if marker in target:
            return target.split(marker, 1)[1]
    timezone_file = Path("/etc/timezone")
    if timezone_file.is_file():
        name = timezone_file.read_text(encoding="utf-8").strip()
        return name or None
    return None


def local_timezone() -> tzinfo:
    """Fuseau du système, avec ses règles de changement d'heure ; UTC en dernier recours."""
    name = system_timezone_name()
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return UTC
