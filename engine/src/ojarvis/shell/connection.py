"""Le fichier de connexion du mode shell : le terminal rejoint le moteur déjà lancé par l'app.

Choix d'Octave (26/10/2026) : le moteur écrit son port et le jeton de session (tiré par la
coque à chaque lancement) dans `$XDG_RUNTIME_DIR/o-jarvis/`, un dossier en mémoire, lisible
par ton seul compte (dossier 0700, fichier 0600). Le fichier change à chaque démarrage et
disparaît à l'arrêt : seul un programme qui tourne déjà sous ton compte peut le lire.

Son nom porte l'empreinte du dossier de données : un moteur d'essai (`OJARVIS_HOME`) n'écrase
jamais celui de l'app, et le terminal trouve le moteur des mêmes données que lui.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ojarvis.config import APP_DIR_NAME, Paths

#: Poignée de main du moteur (voir `ojarvis.__main__`), lue aussi par le terminal.
READY_PREFIX = "OJARVIS_READY "
EXIT_LOCKED = 3
EXIT_BAD_TOKEN = 4


@dataclass(frozen=True, slots=True)
class EngineInfo:
    port: int
    pid: int
    token: str
    version: str

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def info_path(paths: Paths, env: Mapping[str, str] | None = None) -> Path | None:
    """Où ce moteur publie sa connexion ; None sans dossier d'exécution (`XDG_RUNTIME_DIR`)."""
    env = os.environ if env is None else env
    runtime = env.get("XDG_RUNTIME_DIR")
    if not runtime:
        return None
    digest = hashlib.sha256(str(paths.data_dir.resolve()).encode()).hexdigest()[:12]
    return Path(runtime) / APP_DIR_NAME / f"moteur-{digest}.json"


def write_info(path: Path, info: EngineInfo) -> None:
    """Écrit d'un coup (fichier temporaire puis renommage), lisible par toi seul."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{info.pid}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(
            {"port": info.port, "pid": info.pid, "token": info.token, "version": info.version},
            handle,
        )
    temporary.replace(path)


def read_info(path: Path) -> EngineInfo | None:
    """Le moteur publié, s'il est sûr de le lire : un fichier à toi, que personne d'autre ne
    peut lire, et un processus encore vivant. Sinon None (le terminal lancera son moteur)."""
    try:
        status = path.stat()
    except OSError:
        return None
    if status.st_uid != os.getuid() or status.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        info = EngineInfo(
            port=int(data["port"]),
            pid=int(data["pid"]),
            token=str(data["token"]),
            version=str(data.get("version", "")),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return info if _alive(info.pid) else None


def remove_info(path: Path, pid: int) -> None:
    """Efface la connexion à l'arrêt, seulement si c'est bien la sienne."""
    info = read_info(path)
    if info is None or info.pid == pid:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def python_module(module: str, *, frozen_as: str | None = None) -> list[str]:
    """Lancer un module d'O-jarvis avec ce même Python. Le moteur empaqueté (PyInstaller)
    n'a pas de « -m » : le terminal y est la sous-commande `shell`, le moteur le programme
    seul."""
    if getattr(sys, "frozen", False):
        return [sys.executable, frozen_as] if frozen_as else [sys.executable]
    return [sys.executable, "-m", module]
