"""Les applications installées : les trouver, les ouvrir, les fermer.

- Index : les fichiers `.desktop` des dossiers XDG (applications du système, Flatpak,
  Snap, les tiennes), comme le fait le menu d'Ubuntu ; les entrées cachées sont ignorées.
  Les noms sont traduits comme dans le menu : `Name[fr]`, sinon le catalogue gettext que
  l'entrée désigne (sous Ubuntu, la plupart : « Calculator » y devient « Calculatrice »).
- Ouvrir : `gtk-launch <identifiant>` (GLib), qui marche sous Wayland comme sous X11 ;
  jamais un shell, jamais la commande `Exec` interprétée par Jarvis.
- Fermer : seulement tes processus dont l'exécutable correspond à l'application, par
  SIGTERM (l'application peut demander d'enregistrer) ; jamais la session ni Jarvis.
  Quand l'application démarre par un script (Chrome, LibreOffice, VS Code), le programme
  qui tourne porte un autre nom : on le reconnaît à son dossier, celui du script.
"""

from __future__ import annotations

import asyncio
import functools
import gettext
import os
import re
import shlex
import shutil
import signal
import unicodedata
from collections.abc import Callable
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
#: Dossiers communs à beaucoup de programmes : jamais le dossier propre d'une application.
SHARED_DIRS = frozenset(
    Path(d)
    for d in (
        "/",
        "/bin",
        "/sbin",
        "/opt",
        "/snap",
        "/tmp",  # noqa: S108 - un dossier partagé, pas un fichier temporaire
        "/usr",
        "/usr/bin",
        "/usr/sbin",
        "/usr/games",
        "/usr/lib",
        "/usr/lib64",
        "/usr/libexec",
        "/usr/share",
        "/usr/local",
        "/usr/local/bin",
        "/usr/local/lib",
        "/usr/local/share",
    )
)
_FIELD_CODES = re.compile(r"%[fFuUdDnNickvm]")
_DOMAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")
LOCALE_DIRS = (Path("/usr/share/locale-langpack"), Path("/usr/share/locale"))


@dataclass(frozen=True)
class AppEntry:
    id: str  # « org.gnome.Calculator »
    name: str  # nom affiché, traduit comme dans le menu
    exec_name: str  # exécutable (« gnome-calculator »)
    path: Path
    keywords: tuple[str, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)  # nom d'origine (« Calculator »)
    command: str = ""  # programme lancé, tel qu'écrit dans `Exec` (nom ou chemin)

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


def _languages() -> tuple[str, ...]:
    """Langues du système (règles de gettext), puis le français : Jarvis parle français."""
    wanted = os.environ.get("LANGUAGE", "").split(":")
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(variable):
            wanted.append(os.environ[variable])
            break
    out: list[str] = []
    for item in [*wanted, "fr"]:
        code = item.split(".")[0].split("@")[0]
        for candidate in (code, code.split("_")[0]):
            if candidate and candidate not in ("C", "POSIX") and candidate not in out:
                out.append(candidate)
    return tuple(out)


@functools.lru_cache(maxsize=256)
def _translator(
    domain: str, languages: tuple[str, ...], locale_dirs: tuple[Path, ...]
) -> Callable[[str], str]:
    """Traduction d'un catalogue gettext (le premier dossier qui l'a gagne)."""
    if not _DOMAIN.fullmatch(domain):  # le nom finit dans un chemin : rien d'autre
        return str
    for directory in locale_dirs:
        try:
            catalog = gettext.translation(domain, directory, languages=list(languages))
        except OSError:
            continue
        return catalog.gettext
    return str


def _parse(
    path: Path, desktop: str, locale_dirs: tuple[Path, ...] = LOCALE_DIRS
) -> AppEntry | None:
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
    try:
        command = [t for t in shlex.split(_FIELD_CODES.sub("", values["Exec"])) if t]
    except ValueError:
        return None
    while command and (command[0] == "env" or "=" in command[0]):
        command = command[1:]
    exec_name = Path(command[0]).name if command else ""
    domain = values.get("X-GNOME-Gettext-Domain") or values.get("X-Ubuntu-Gettext-Domain")
    translate = _translator(domain, _languages(), locale_dirs) if domain else str

    def local(key: str) -> str:
        """`Clé[fr]`, sinon la traduction du catalogue (jamais celle de "" : l'en-tête)."""
        own = values.get(f"{key}[fr]") or values.get(f"{key}[fr_FR]")
        original = values.get(key, "")
        return own or (translate(original) if original else "")

    original = values.get("Name") or path.stem
    name = local("Name") or original
    keywords = [*local("Keywords").split(";"), local("GenericName"), values.get("GenericName", "")]
    return AppEntry(
        path.name.removesuffix(".desktop"),
        name,
        exec_name,
        path,
        tuple(dict.fromkeys(k for k in keywords if k)),
        (original,) if original != name else (),
        command[0] if command else "",
    )


def index(
    dirs: list[Path] | None = None, locale_dirs: tuple[Path, ...] = LOCALE_DIRS
) -> dict[str, AppEntry]:
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
            entry = _parse(path, desktop, locale_dirs)
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
        names = [_fold(n) for n in (entry.name, entry.id, entry.exec_name, *entry.aliases)]
        words = [_fold(k) for k in entry.keywords]
        if wanted in names:
            score = 100
        elif any(n.startswith(wanted) for n in names):
            score = 80
        elif any(wanted in n for n in names):
            score = 60
        elif wanted in words:
            score = 40
        elif any(wanted in w for w in words):  # « navigateur » dans « navigateur web »
            score = 20
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
        "--",  # un identifiant qui commence par « - » n'est jamais lu comme une option
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


async def open_url(url: str) -> None:
    """Ouvre l'adresse dans ton navigateur par défaut (détaché de Jarvis)."""
    await _xdg_open(url, "ton navigateur", "Ton navigateur ne s'est pas ouvert.")


async def open_folder(folder: Path) -> None:
    """Ouvre le dossier dans le gestionnaire de fichiers."""
    await _xdg_open(str(folder), "le dossier", "Le dossier ne s'est pas ouvert.")


async def _xdg_open(target: str, what: str, failure: str) -> None:
    opener = shutil.which("xdg-open")
    if opener is None:
        raise UnavailableError(f"xdg-open absent : impossible d'ouvrir {what}.")
    process = await asyncio.create_subprocess_exec(
        opener,
        target,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    code = await asyncio.wait_for(process.wait(), 15)
    if code != 0:
        raise UnavailableError(failure)


def app_root(entry: AppEntry) -> Path | None:
    """Le dossier propre à l'application, quand elle démarre par un script.

    `google-chrome` lance `/opt/google/chrome/chrome`, `libreoffice` lance `soffice.bin` :
    le programme qui tourne est rangé à côté du script (ou au-dessus de son dossier `bin`).
    """
    command = entry.command
    found = command if os.path.isabs(command) else shutil.which(command) if command else None
    if not found:
        return None
    real = Path(found).resolve()
    try:
        with real.open("rb") as handle:
            if handle.read(2) != b"#!":
                return None  # un vrai programme : son nom suffit
    except OSError:
        return None
    root = real.parent.parent if real.parent.name == "bin" else real.parent
    home = Path.home()
    if root in SHARED_DIRS or home in (root, root.parent) or len(root.parts) < 3:
        return None  # dossier partagé (/usr/bin, ~/Téléchargements…) : trop large
    return root


@dataclass(frozen=True)
class _Process:
    pid: int
    name: str  # argv[0] sans son chemin
    exe: Path | None  # programme réellement exécuté


def _scan(proc: Path = Path("/proc")) -> list[_Process]:
    """Tes processus, jamais Jarvis lui-même ni un processus protégé."""
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
        try:
            exe: Path | None = Path(os.readlink(entry / "exe"))
        except OSError:
            exe = None
        name = Path(raw).name if raw else ""
        names = {name.casefold(), exe.name.casefold() if exe else ""}
        if not names & PROTECTED:
            found.append(_Process(int(entry.name), name, exe))
    return found


def _matching(processes: list[_Process], exec_name: str, root: Path | None) -> list[int]:
    if not exec_name or exec_name.casefold() in PROTECTED:
        return []
    return sorted(
        p.pid
        for p in processes
        if exec_name in (p.name, p.exe.name if p.exe else "")
        or (root is not None and p.exe is not None and p.exe.parent == root)
    )


def _processes(exec_name: str, proc: Path = Path("/proc"), root: Path | None = None) -> list[int]:
    """Tes processus de ce programme (par son nom, ou rangés dans le dossier `root`)."""
    return _matching(_scan(proc), exec_name, root)


def running(
    apps: dict[str, AppEntry], proc: Path = Path("/proc")
) -> list[tuple[AppEntry, list[int]]]:
    processes = _scan(proc)
    out = []
    for entry in apps.values():
        pids = _matching(processes, entry.exec_name, app_root(entry))
        if pids:
            out.append((entry, pids))
    return out


def same_program(apps: dict[str, AppEntry], entry: AppEntry) -> list[AppEntry]:
    """Les autres entrées du menu qui lancent le même programme (elles se ferment ensemble)."""
    root = app_root(entry)
    return [
        other
        for other in apps.values()
        if other.id != entry.id
        and (other.exec_name == entry.exec_name or (root is not None and app_root(other) == root))
    ]


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
    pids = _processes(entry.exec_name, root=app_root(entry))
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
