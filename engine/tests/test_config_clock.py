from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ojarvis.config import DEV_ORIGINS, load_config, repo_root, resolve_dotenv, resolve_paths
from ojarvis.core import clock


def test_ojarvis_home_groups_all_dirs(tmp_path: Path) -> None:
    paths = resolve_paths({"OJARVIS_HOME": str(tmp_path)})
    assert paths.data_dir == tmp_path / "data"
    assert paths.db_path == tmp_path / "data" / "ojarvis.db"
    assert paths.logs_dir == tmp_path / "state" / "logs"
    paths.ensure()
    assert paths.logs_dir.is_dir()
    assert (paths.data_dir.stat().st_mode & 0o777) == 0o700


def test_xdg_dirs_are_used(tmp_path: Path) -> None:
    env = {
        "XDG_DATA_HOME": str(tmp_path / "d"),
        "XDG_CONFIG_HOME": str(tmp_path / "c"),
        "XDG_CACHE_HOME": str(tmp_path / "k"),
        "XDG_STATE_HOME": str(tmp_path / "s"),
    }
    paths = resolve_paths(env)
    assert paths.data_dir == tmp_path / "d" / "o-jarvis"
    assert paths.state_dir == tmp_path / "s" / "o-jarvis"


def test_dev_origins_only_in_dev_mode(tmp_path: Path) -> None:
    env = {"OJARVIS_HOME": str(tmp_path)}
    assert not set(DEV_ORIGINS) & set(load_config(dev_mode=False, env=env).allowed_origins)
    assert set(DEV_ORIGINS) <= set(load_config(dev_mode=True, env=env).allowed_origins)


def test_dotenv_resolution(tmp_path: Path) -> None:
    paths = resolve_paths({"OJARVIS_HOME": str(tmp_path)})
    explicit = tmp_path / "x.env"
    assert resolve_dotenv(paths, {"OJARVIS_DOTENV": str(explicit)}, False) == explicit
    assert resolve_dotenv(paths, {}, False) is None
    paths.ensure()
    (paths.config_dir / ".env").write_text("A=1\n")
    assert resolve_dotenv(paths, {}, False) == paths.config_dir / ".env"


def test_repo_root_found_from_sources() -> None:
    root = repo_root()
    assert root is not None
    assert (root / "engine" / "pyproject.toml").is_file()


def test_to_iso_is_utc_with_z() -> None:
    moment = datetime(2026, 3, 29, 3, 30, tzinfo=ZoneInfo("Europe/Paris"))
    assert clock.to_iso(moment) == "2026-03-29T01:30:00Z"


def test_utc_now_is_aware() -> None:
    assert clock.utc_now().tzinfo is UTC


def test_system_timezone_from_tz_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "America/Montreal")
    assert clock.system_timezone_name() == "America/Montreal"
    assert clock.local_timezone() == ZoneInfo("America/Montreal")


def test_invalid_timezone_falls_back_to_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "system_timezone_name", lambda: "Pas/UnFuseau")
    assert clock.local_timezone() is UTC
