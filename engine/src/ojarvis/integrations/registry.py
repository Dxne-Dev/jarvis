"""Le registre officiel des serveurs MCP : chercher, choisir comment lancer, lancer isolé.

- Recherche : https://registry.modelcontextprotocol.io (API v0).
- Lancement, du plus isolé au moins isolé :
  * Docker : un conteneur par serveur, sans privilèges ni tes fichiers, mémoire bornée, son
    propre volume (un serveur ne peut pas toucher au cache d'un autre) ;
  * bubblewrap : les paquets npm (npx) ou Python (uvx) de ta machine, lancés dans un espace
    qui ne voit ni ton dossier personnel ni tes clés (il garde l'accès au réseau) ;
  * en ligne : un service hébergé par l'éditeur, en https, vers une adresse publique.
- Toujours une version précise : jamais « latest ».

Ce que dit le registre (noms, descriptions) est une donnée : montrée, jamais exécutée ; les
identifiants de paquets sont vérifiés avant de devenir des arguments (jamais de shell).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx

REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0/servers"
NODE_IMAGE = "node:24.21.0-alpine3.24"
UV_IMAGE = "ghcr.io/astral-sh/uv:0.11.22-python3.12-trixie-slim"

Kind = Literal["npm", "pypi", "oci", "remote"]
#: Ordre de préférence : sur ta machine d'abord (isolé), en ligne en dernier.
PREFERENCE: tuple[Kind, ...] = ("npm", "pypi", "oci", "remote")

_NPM = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
_PYPI = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_OCI = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+|@sha256:[a-f0-9]{64})$")
_VERSION = re.compile(r"^[0-9][A-Za-z0-9.+-]*$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RegistryError(RuntimeError):
    """Le registre ne répond pas, ou rend une fiche inutilisable."""


@dataclass(frozen=True)
class EnvVar:
    name: str
    description: str
    required: bool
    secret: bool
    default: str | None = None
    #: Valeur imposée par l'éditeur (ex. le mode de transport) : jamais demandée.
    value: str | None = None


@dataclass(frozen=True)
class InstallOption:
    kind: Kind
    #: Paquet npm ou Python, image Docker, ou adresse du service en ligne.
    identifier: str
    version: str
    env: tuple[EnvVar, ...] = ()
    args: tuple[str, ...] = ()
    #: Pourquoi on ne peut pas l'installer (None : c'est possible).
    problem: str | None = None

    @property
    def label(self) -> str:
        if self.kind == "npm":
            return f"paquet npm {self.identifier}@{self.version}"
        if self.kind == "pypi":
            return f"paquet Python {self.identifier}=={self.version}"
        if self.kind == "oci":
            return f"image Docker {self.identifier}"
        return f"service en ligne {self.identifier}"

    @property
    def where(self) -> str:
        if self.kind == "remote":
            return f"en ligne, chez {urlsplit(self.identifier).hostname}"
        return "sur ce PC, isolé (sans tes fichiers, avec accès à Internet)"

    def asked(self) -> list[EnvVar]:
        """Les réglages à te demander (ceux que l'éditeur n'impose pas)."""
        return [v for v in self.env if v.value is None]

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "identifier": self.identifier,
            "version": self.version,
            "env": [vars(v) for v in self.env],
            "args": list(self.args),
            "problem": self.problem,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> InstallOption:
        return cls(
            kind=data["kind"],
            identifier=data["identifier"],
            version=data["version"],
            env=tuple(EnvVar(**v) for v in data.get("env", [])),
            args=tuple(data.get("args", [])),
            problem=data.get("problem"),
        )


@dataclass(frozen=True)
class RegistryEntry:
    name: str
    title: str
    description: str
    version: str
    repository: str | None
    website: str | None
    options: tuple[InstallOption, ...] = field(default_factory=tuple)

    def best(self, runtimes: Runtimes) -> InstallOption | None:
        """La façon de le lancer qu'on préfère, parmi celles possibles sur cette machine."""
        usable = [o for o in self.options if o.problem is None and runtimes.can_run(o)]
        return min(usable, key=lambda o: PREFERENCE.index(o.kind)) if usable else None

    def why_not(self, runtimes: Runtimes) -> str:
        if not self.options:
            return "aucune façon de le lancer n'est décrite"
        problems = [o.problem for o in self.options if o.problem]
        if len(problems) == len(self.options):
            return problems[0] or "inutilisable"
        return runtimes.missing()


# --------------------------------------------------------------------------- lecture du registre


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _env(raw: Any) -> EnvVar | None:
    if not isinstance(raw, dict):
        return None
    name = _text(raw.get("name"), 80)
    if not _ENV_NAME.match(name):
        return None
    default, value = raw.get("default"), raw.get("value")
    return EnvVar(
        name=name,
        description=_text(raw.get("description"), 300),
        required=raw.get("isRequired") is True,
        secret=raw.get("isSecret") is True,
        default=str(default)[:500] if isinstance(default, str | int | float) else None,
        value=str(value)[:500] if isinstance(value, str | int | float) else None,
    )


def _arguments(raw: Any) -> tuple[list[str], str | None]:
    """Arguments fixes (valeur ou valeur par défaut) ; un argument obligatoire sans valeur
    n'est pas encore pris en charge."""
    args: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        value = item.get("value") or item.get("default")
        kind = item.get("type")
        name = _text(item.get("name"), 80)
        if value is None:
            if item.get("isRequired") is True:
                return [], f"il demande l'argument « {name or '?'} », pas encore pris en charge"
            continue
        if kind == "named" and name:
            args += [name if name.startswith("-") else f"--{name}", str(value)[:300]]
        elif kind == "positional":
            args.append(str(value)[:300])
    return args, None


def _package(raw: dict[str, Any]) -> InstallOption | None:
    registry = raw.get("registryType")
    if registry not in ("npm", "pypi", "oci"):
        return None
    identifier = _text(raw.get("identifier"), 200)
    version = _text(raw.get("version"), 64)
    raw_transport = raw.get("transport")
    transport: dict[str, Any] = raw_transport if isinstance(raw_transport, dict) else {}
    env = tuple(v for v in map(_env, raw.get("environmentVariables") or []) if v is not None)
    args, problem = _arguments(
        [*(raw.get("runtimeArguments") or []), *(raw.get("packageArguments") or [])]
    )
    if transport.get("type", "stdio") != "stdio":
        problem = "il se lance comme un serveur web : Jarvis ne lance que les serveurs stdio"
    kind: Kind = registry
    if kind == "npm" and not _NPM.match(identifier):
        problem = "nom de paquet npm inattendu"
    elif kind == "pypi" and not _PYPI.match(identifier):
        problem = "nom de paquet Python inattendu"
    elif kind == "oci":
        if not _OCI.match(identifier) or identifier.endswith(":latest"):
            problem = "image Docker sans version précise"
        version = version or identifier.rsplit(":", 1)[-1]
    if kind != "oci" and not _VERSION.match(version):
        problem = "version non précisée (« latest ») : Jarvis n'installe que des versions fixes"
    return InstallOption(kind, identifier, version, env, tuple(args), problem)


def _remote(raw: dict[str, Any]) -> InstallOption | None:
    if raw.get("type") != "streamable-http":
        return None
    url = _text(raw.get("url"), 300)
    problem = None
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        problem = "adresse non chiffrée (https exigé)"
    elif raw.get("headers"):
        problem = "il demande une authentification par en-tête, pas encore prise en charge"
    return InstallOption("remote", url, "", (), (), problem)


def parse_entry(item: Any) -> RegistryEntry | None:
    server = item.get("server") if isinstance(item, dict) else None
    if not isinstance(server, dict):
        return None
    name = _text(server.get("name"), 200)
    if not name:
        return None
    options: list[InstallOption] = []
    for raw in server.get("packages") or []:
        option = _package(raw) if isinstance(raw, dict) else None
        if option is not None:
            options.append(option)
    for raw in server.get("remotes") or []:
        option = _remote(raw) if isinstance(raw, dict) else None
        if option is not None:
            options.append(option)
    repository = server.get("repository")
    return RegistryEntry(
        name=name,
        title=_text(server.get("title"), 120) or name.rsplit("/", 1)[-1],
        description=_text(server.get("description"), 500),
        version=_text(server.get("version"), 64),
        repository=_text(repository.get("url"), 300) if isinstance(repository, dict) else None,
        website=_text(server.get("websiteUrl"), 300) or None,
        options=tuple(options),
    )


async def search(http: httpx.AsyncClient, query: str, *, limit: int = 20) -> list[RegistryEntry]:
    """Dernières versions des serveurs dont le nom contient `query`."""
    params: dict[str, str | int] = {
        "search": query.strip()[:100],
        "limit": limit,
        "version": "latest",
    }
    try:
        response = await http.get(REGISTRY_URL, params=params, timeout=20.0)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RegistryError(f"le registre MCP ne répond pas ({type(exc).__name__})") from exc
    items = payload.get("servers") if isinstance(payload, dict) else None
    entries = [parse_entry(i) for i in items or []]
    return [e for e in entries if e is not None]


async def fetch(http: httpx.AsyncClient, name: str, version: str) -> RegistryEntry:
    """Une version précise d'un serveur."""
    url = f"{REGISTRY_URL}/{quote(name, safe='')}/versions/{quote(version, safe='')}"
    try:
        response = await http.get(url, timeout=20.0)
        if response.status_code == 404:
            raise RegistryError(f"« {name} » v{version} est introuvable dans le registre")
        response.raise_for_status()
        entry = parse_entry(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise RegistryError(f"le registre MCP ne répond pas ({type(exc).__name__})") from exc
    if entry is None:
        raise RegistryError("fiche du registre illisible")
    return entry


# --------------------------------------------------------------------------- lancement isolé


@dataclass(frozen=True)
class Runtimes:
    """Ce qui permet de lancer un serveur sur cette machine."""

    docker: str | None = None
    bwrap: str | None = None
    npx: str | None = None
    uvx: str | None = None

    def can_run(self, option: InstallOption) -> bool:
        if option.kind == "remote":
            return True
        if option.kind == "oci":
            return self.docker is not None
        if self.docker is not None:
            return True
        tool = self.npx if option.kind == "npm" else self.uvx
        return self.bwrap is not None and tool is not None

    def runner(self, option: InstallOption) -> str:
        if option.kind == "remote":
            return "en_ligne"
        return "docker" if self.docker is not None else "bubblewrap"

    def missing(self) -> str:
        if self.docker is None and self.bwrap is None:
            return "ni Docker ni bubblewrap : impossible de l'isoler sur cette machine"
        return "Docker est nécessaire pour ce serveur (il est arrêté ou absent)"


def docker_target(
    option: InstallOption, server_id: str, env: Mapping[str, str], *, docker: str
) -> Any:
    from mcp import StdioServerParameters  # noqa: PLC0415

    base = [
        "run",
        "-i",
        "--rm",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "512m",
        "--pids-limit",
        "256",
    ]
    volume = f"ojarvis-mcp-{server_id}"
    if option.kind == "npm":
        image = [
            "--user",
            "node",
            "-v",
            f"{volume}:/home/node",
            "-e",
            "npm_config_update_notifier=false",
        ]
        command = [NODE_IMAGE, "npx", "-y", f"{option.identifier}@{option.version}"]
    elif option.kind == "pypi":
        image = ["-v", f"{volume}:/root/.cache"]
        command = [UV_IMAGE, "uvx", f"{option.identifier}@{option.version}"]
    else:
        image = []
        command = [option.identifier]
    # Les valeurs passent par l'environnement du seul processus Docker, jamais en argument.
    names = [arg for name in env for arg in ("-e", name)]
    return StdioServerParameters(
        command=docker,
        args=[*base, *image, *names, *command, *option.args],
        env={**_base_env(), **env},
    )


def bubblewrap_target(
    option: InstallOption, home: Path, env: Mapping[str, str], *, runtimes: Runtimes
) -> Any:
    """npx ou uvx de ta machine, dans un espace qui ne voit que `home` (le dossier du serveur)."""
    from mcp import StdioServerParameters  # noqa: PLC0415

    if runtimes.bwrap is None:
        raise RuntimeError("bubblewrap absent")
    if option.kind == "npm" and runtimes.npx is not None:
        # npx vit dans l'installation de Node (souvent sous ~/.nvm) : montée en lecture seule.
        mounts = ["--ro-bind", str(Path(runtimes.npx).parent.parent), "/opt/runtime"]
        command = ["/opt/runtime/bin/npx", "-y", f"{option.identifier}@{option.version}"]
    elif option.kind == "pypi" and runtimes.uvx is not None:
        uvx = Path(runtimes.uvx).resolve()
        mounts = ["--ro-bind", str(uvx), "/opt/runtime/uvx"]
        if uvx.with_name("uv").exists():
            mounts += ["--ro-bind", str(uvx.with_name("uv")), "/opt/runtime/uv"]
        command = ["/opt/runtime/uvx", f"{option.identifier}@{option.version}"]
    else:
        raise RuntimeError(f"impossible de lancer un {option.label} sans Docker")
    home.mkdir(parents=True, exist_ok=True)
    args = [
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "usr/sbin",
        "/sbin",
        *_etc_mounts(),
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",  # noqa: S108 - un /tmp neuf et vide dans l'espace isolé
        *mounts,
        "--bind",
        str(home),
        "/home/mcp",
        "--setenv",
        "HOME",
        "/home/mcp",
        "--setenv",
        "PATH",
        "/opt/runtime/bin:/opt/runtime:/usr/bin:/bin",
        "--setenv",
        "UV_CACHE_DIR",
        "/home/mcp/.cache/uv",
        "--setenv",
        "npm_config_update_notifier",
        "false",
        "--chdir",
        "/home/mcp",
        "--",
        *command,
        *option.args,
    ]
    # Les valeurs des réglages passent par l'environnement, jamais par la ligne de commande.
    return StdioServerParameters(command=runtimes.bwrap, args=args, env={**_base_env(), **env})


def remote_target(option: InstallOption) -> str:
    return option.identifier


def _etc_mounts() -> list[str]:
    """Ce qu'il faut de /etc pour résoudre les noms et vérifier les certificats https."""
    out: list[str] = []
    for path in (
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/nsswitch.conf",
        "/etc/ssl",
        "/etc/ca-certificates",
    ):
        if os.path.exists(path):
            out += ["--ro-bind", path, path]
    return out


def _base_env() -> dict[str, str]:
    return {k: os.environ[k] for k in ("PATH", "LANG") if k in os.environ}
