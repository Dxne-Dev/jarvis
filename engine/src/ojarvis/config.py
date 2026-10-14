"""Configuration statique du moteur : chemins XDG, mode développement, origines autorisées."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR_NAME = "o-jarvis"

# Origines de l'interface : app empaquetée (WebKitGTK) et serveur Vite en développement.
TAURI_ORIGINS = ("tauri://localhost", "http://tauri.localhost")
DEV_ORIGINS = ("http://localhost:1420", "http://127.0.0.1:1420")


@dataclass(frozen=True, slots=True)
class Paths:
    data_dir: Path
    config_dir: Path
    cache_dir: Path
    state_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ojarvis.db"

    @property
    def logs_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def lock_path(self) -> Path:
        return self.state_dir / "engine.lock"

    def ensure(self) -> None:
        for directory in (
            self.data_dir,
            self.config_dir,
            self.cache_dir,
            self.state_dir,
            self.logs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)


def _xdg(env: Mapping[str, str], var: str, default: str) -> Path:
    value = env.get(var)
    return Path(value) if value else Path.home() / default


def resolve_paths(env: Mapping[str, str] | None = None) -> Paths:
    """`OJARVIS_HOME` regroupe tout sous un dossier (tests, essais) ; sinon dossiers XDG."""
    env = os.environ if env is None else env
    home = env.get("OJARVIS_HOME")
    if home:
        base = Path(home)
        return Paths(base / "data", base / "config", base / "cache", base / "state")
    return Paths(
        data_dir=_xdg(env, "XDG_DATA_HOME", ".local/share") / APP_DIR_NAME,
        config_dir=_xdg(env, "XDG_CONFIG_HOME", ".config") / APP_DIR_NAME,
        cache_dir=_xdg(env, "XDG_CACHE_HOME", ".cache") / APP_DIR_NAME,
        state_dir=_xdg(env, "XDG_STATE_HOME", ".local/state") / APP_DIR_NAME,
    )


def repo_root() -> Path | None:
    """Racine du dépôt quand le moteur tourne depuis les sources, sinon None."""
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / "engine" / "pyproject.toml").is_file():
        return candidate
    return None


def resolve_dotenv(paths: Paths, env: Mapping[str, str], dev_mode: bool) -> Path | None:
    """`.env` de développement : variable `OJARVIS_DOTENV`, sinon racine du dépôt, sinon config."""
    explicit = env.get("OJARVIS_DOTENV")
    if explicit:
        return Path(explicit)
    root = repo_root()
    if dev_mode and root is not None and (root / ".env").is_file():
        return root / ".env"
    candidate = paths.config_dir / ".env"
    return candidate if candidate.is_file() else None


@dataclass(frozen=True, slots=True)
class EngineConfig:
    paths: Paths
    dev_mode: bool = False
    dotenv_path: Path | None = None
    log_level: str = "INFO"
    allowed_origins: tuple[str, ...] = TAURI_ORIGINS
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
    extra: Mapping[str, str] = field(default_factory=dict)


def load_config(*, dev_mode: bool, env: Mapping[str, str] | None = None) -> EngineConfig:
    env = os.environ if env is None else env
    paths = resolve_paths(env)
    origins = TAURI_ORIGINS + (DEV_ORIGINS if dev_mode else ())
    return EngineConfig(
        paths=paths,
        dev_mode=dev_mode,
        dotenv_path=resolve_dotenv(paths, env, dev_mode),
        log_level=env.get("OJARVIS_LOG_LEVEL", "DEBUG" if dev_mode else "INFO").upper(),
        allowed_origins=origins,
    )
