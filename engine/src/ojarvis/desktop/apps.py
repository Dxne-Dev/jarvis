"""Les applications installées : les trouver, les ouvrir, les fermer.

- Index : les fichiers `.desktop` des dossiers XDG (applications du système, Flatpak,
  Snap, les tiennes), comme le fait le menu d'Ubuntu ; les entrées cachées sont ignorées.
- Ouvrir : `gtk-launch <identifiant>` (GLib), qui marche sous Wayland comme sous X11 ;
  jamais un shell, jamais la commande `Exec` interprétée par Jarvis.
- Fermer : seulement tes processus dont l'exécutable correspond à l'application, par
  SIGTERM (l'application peut demander d'enregistrer) ; jamais la session ni Jarvis.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import shutil
import signal
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ojarvis.core.errors import NotFoundError, UnavailableError

#: Ce qu'on ne ferme jamais : la session graphique, le système, Jarvis lui-même.
PROTECTED = frozenset(
    {
        "gnome-shell",
        "xwayland",
        "xorg",
        "systemd",
        "dbus-daemon",
        "pipewire",
        "wireplumber",
        "gnome-session-binary",
        "o-jarvis",
        "ojarvis",
        "python",
        "python3",
        "bash",
        "sh",
        # Lanceurs partagés par plusieurs applications : les fermer fermerait tout.
        "flatpak",
        "flatpak-session-helper",
        "bwrap",
        "snap",
        "env",
    }
)
_FIELD_CODES = re.compile(r"%[fFuUdDnNickvm]")


@dataclass(frozen=True)
class AppEntry:
    id: str  # « org.gnome.Calculator »
    name: str  # nom affiché, en français si l'entrée le donne
    exec_name: str  # exécutable (« gnome-calculator »)
    path: Path
    keywords: tuple[str, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.id})"


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in folded if not unicodedata.combining(c)).strip()


def application_dirs() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [home / "applications"]
    dirs += [Path(d) / "applications" for d in data_dirs.split(":") if d]
    dirs += [
        Path("/var/lib/flatpak/exports/share/applications"),
        home / "flatpak/exports/share/applications",
        Path("/var/lib/snapd/desktop/applications"),
    ]
    seen: list[Path] = []
    for directory in dirs:
        if directory not in seen:
            seen.append(directory)
    return seen


def _parse(path: Path, desktop: str) -> AppEntry | None:
    values: dict[str, str] = {}
    section = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
            continue
        if section != "[Desktop Entry]" or "=" not in stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        values.setdefault(key.strip(), value.strip())
    if values.get("Type") != "Application" or values.get("NoDisplay") == "true":
        return None
    if values.get("Hidden") == "true" or not values.get("Exec"):
        return None
    only = values.get("OnlyShowIn")
    if only and desktop and not any(d in only.split(";") for d in desktop.split(":")):
        return None
    name = values.get("Name[fr]") or values.get("Name[fr_FR]") or values.get("Name") or path.stem
    try:
        command = [t for t in shlex.split(_FIELD_CODES.sub("", values["Exec"])) if t]
    except ValueError:
        return None
    while command and (command[0] == "env" or "=" in command[0]):
        command = command[1:]
    exec_name = Path(command[0]).name if command else ""
    keywords = values.get("Keywords[fr]") or values.get("Keywords") or ""
    return AppEntry(
        path.name.removesuffix(".desktop"),
        name,
        exec_name,
        path,
        tuple(k for k in keywords.split(";") if k),
    )


def index(dirs: list[Path] | None = None) -> dict[str, AppEntry]:
    """Applications visibles dans le menu, par identifiant (la première trouvée gagne)."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    apps: dict[str, AppEntry] = {}
    for directory in dirs if dirs is not None else application_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.desktop")):
            app_id = path.name.removesuffix(".desktop")
            if app_id in apps:
                continue
            entry = _parse(path, desktop)
            if entry is not None:
                apps[app_id] = entry
    return apps


def find(apps: dict[str, AppEntry], query: str) -> AppEntry:
    """L'application qui correspond le mieux à un nom (« calculatrice », « firefox »…)."""
    wanted = _fold(query)
    if not wanted:
        raise NotFoundError("Nom d'application vide.")
    scored: list[tuple[int, AppEntry]] = []
    for entry in apps.values():
        names = [_fold(entry.name), _fold(entry.id), _fold(entry.exec_name)]
        words = [_fold(k) for k in entry.keywords]
        if wanted in names:
            score = 100
        elif any(n.startswith(wanted) for n in names):
            score = 80
        elif any(wanted in n for n in names):
            score = 60
        elif wanted in words:
            score = 40
        else:
            continue
        scored.append((score, entry))
    if not scored:
        raise NotFoundError(f"Aucune application ne s'appelle « {query} ».")
    scored.sort(key=lambda item: (-item[0], item[1].name))
    best = scored[0]
    rivals = [e for s, e in scored[1:] if s == best[0]]
    if rivals and best[0] < 100:
        options = ", ".join(e.name for e in [best[1], *rivals][:5])
        raise NotFoundError(f"Plusieurs applications correspondent à « {query} » : {options}.")
    return best[1]


async def launch(entry: AppEntry) -> int:
    """Ouvre l'application (détachée de Jarvis) ; rend le numéro du lanceur."""
    launcher = shutil.which("gtk-launch")
    if launcher is None:
        raise UnavailableError("gtk-launch absent : impossible d'ouvrir une application.")
    process = await asyncio.create_subprocess_exec(
        launcher,
        entry.id,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    code = await asyncio.wait_for(process.wait(), 15)
    if code != 0:
        raise UnavailableError(f"L'application « {entry.name} » ne s'est pas ouverte.")
    return process.pid


def _processes(exec_name: str, proc: Path = Path("/proc")) -> list[int]:
    """Tes processus dont l'exécutable s'appelle `exec_name` (jamais ceux protégés)."""
    if not exec_name or exec_name.casefold() in PROTECTED:
        return []
    uid = os.getuid()
    me = {os.getpid(), os.getppid()}
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) in me:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            raw = (entry / "cmdline").read_bytes().split(b"\0")[0].decode(errors="replace")
        except OSError:
            continue
        if raw and Path(raw).name == exec_name:
            found.append(int(entry.name))
    return sorted(found)


def running(
    apps: dict[str, AppEntry], proc: Path = Path("/proc")
) -> list[tuple[AppEntry, list[int]]]:
    out = []
    for entry in apps.values():
        pids = _processes(entry.exec_name, proc)
        if pids:
            out.append((entry, pids))
    return out


def _alive(pid: int) -> bool:
    """Toujours là ? (un processus terminé mais pas encore ramassé — « zombie » — ne compte pas)."""
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as handle:
            state = handle.read().rsplit(")", 1)[-1].split()[0]
    except (OSError, IndexError):
        return False
    return state not in ("Z", "X")


async def close(entry: AppEntry, *, wait_s: float = 5.0) -> tuple[int, int]:
    """SIGTERM à ses processus ; rend (fermés, encore ouverts)."""
    pids = _processes(entry.exec_name)
    if not pids:
        raise NotFoundError(f"« {entry.name} » n'est pas ouverte.")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = asyncio.get_running_loop().time() + wait_s
    remaining = pids
    while remaining and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.2)
        remaining = [p for p in remaining if _alive(p)]
    return len(pids) - len(remaining), len(remaining)
