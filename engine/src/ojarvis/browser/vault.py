"""Coffre des sessions du navigateur de Jarvis : chiffré sur disque, domaine par domaine.

Le navigateur de Jarvis ne garde rien entre deux lancements : ses cookies vivent ici,
chiffrés (Fernet) avec une clé dérivée de la clé locale du trousseau. Seuls les domaines
que tu as autorisés y entrent (connexion dans sa fenêtre, ou import depuis ton navigateur).
Ni les cookies ni leur valeur ne sont jamais envoyés à un modèle ou à l'interface.
"""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ojarvis.core.errors import InvalidInputError, UnavailableError
from ojarvis.core.logs import get_logger

log = get_logger(__name__)

_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

State = dict[str, Any]


def normalize_domain(raw: str) -> str:
    """« https://www.GitHub.com/x » → « github.com ». Refuse ce qui n'est pas un domaine."""
    text = raw.strip().lower()
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text).split("/", 1)[0].split(":", 1)[0]
    text = text.lstrip(".")
    text = text.removeprefix("www.")
    if not _DOMAIN.match(text):
        raise InvalidInputError("Domaine invalide (exemple : github.com).", code="invalid_domain")
    return text


def cookie_domain(cookie: dict[str, Any]) -> str:
    return str(cookie.get("domain", "")).lstrip(".").lower()


def in_domain(host: str, domain: str) -> bool:
    """`host` est le domaine lui-même ou l'un de ses sous-domaines."""
    host = host.lstrip(".").lower()
    return host == domain or host.endswith("." + domain)


def related(host: str, domain: str) -> bool:
    """Cookie utile au domaine : posé sur lui, un sous-domaine, ou un domaine parent
    (mail.google.com a besoin des cookies de .google.com)."""
    host = host.lstrip(".").lower()
    return in_domain(host, domain) or (bool(host) and in_domain(domain, host))


def parents(domain: str) -> list[str]:
    """« mail.google.com » → [« mail.google.com », « google.com »]."""
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(len(labels) - 1)]


def _origin_host(origin: str) -> str:
    return re.sub(r"^[a-z]+://", "", origin.lower()).split("/", 1)[0].split(":", 1)[0]


def filter_state(state: State, domains: Iterable[str]) -> State:
    """Ne garde que les cookies et le stockage local des domaines autorisés."""
    allowed = tuple(domains)
    return {
        "cookies": [
            c
            for c in state.get("cookies", [])
            if any(related(cookie_domain(c), d) for d in allowed)
        ],
        "origins": [
            o
            for o in state.get("origins", [])
            if any(related(_origin_host(str(o.get("origin", ""))), d) for d in allowed)
        ],
    }


class CookieVault:
    def __init__(self, path: Path, local_key: Callable[[], str | None]) -> None:
        self._path = path
        self._local_key = local_key

    def _fernet(self) -> Fernet:
        secret = self._local_key()
        if not secret:
            raise UnavailableError(
                "Coffre du navigateur indisponible (trousseau fermé).", code="vault_unavailable"
            )
        key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=b"ojarvis-navigateur"
        ).derive(secret.encode("utf-8"))
        return Fernet(base64.urlsafe_b64encode(key))

    def load(self) -> State:
        if not self._path.exists():
            return {"cookies": [], "origins": []}
        try:
            raw = self._fernet().decrypt(self._path.read_bytes())
        except InvalidToken:
            # Clé locale changée (trousseau réinitialisé) : les sessions sont perdues, pas lisibles.
            log.warning("browser_vault_unreadable")
            return {"cookies": [], "origins": []}
        data = json.loads(raw)
        return {"cookies": list(data.get("cookies", [])), "origins": list(data.get("origins", []))}

    def save(self, state: State) -> None:
        payload = json.dumps(
            {"cookies": state.get("cookies", []), "origins": state.get("origins", [])},
            ensure_ascii=False,
        ).encode("utf-8")
        token = self._fernet().encrypt(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(token)
        tmp.replace(self._path)

    def domains(self) -> set[str]:
        return {cookie_domain(c) for c in self.load()["cookies"]} - {""}

    def count(self, domain: str) -> int:
        return sum(1 for c in self.load()["cookies"] if related(cookie_domain(c), domain))

    def merge(self, cookies: list[dict[str, Any]]) -> None:
        """Ajoute (ou remplace) des cookies : même nom, même domaine, même chemin."""
        state = self.load()
        fresh = {(c["name"], cookie_domain(c), c.get("path", "/")) for c in cookies}
        kept = [
            c
            for c in state["cookies"]
            if (c["name"], cookie_domain(c), c.get("path", "/")) not in fresh
        ]
        state["cookies"] = kept + cookies
        self.save(state)

    def replace_domains(self, state: State, domains: Iterable[str]) -> None:
        """Après un passage du navigateur : on garde son état, limité aux domaines autorisés."""
        self.save(filter_state(state, domains))

    def absorb(self, state: State, domain: str) -> int:
        """Après une connexion : les sessions du domaine remplacent les anciennes."""
        fresh = filter_state(state, [domain])
        current = self.load()
        current["cookies"] = [
            c for c in current["cookies"] if not related(cookie_domain(c), domain)
        ] + fresh["cookies"]
        current["origins"] = [
            o
            for o in current["origins"]
            if not related(_origin_host(str(o.get("origin", ""))), domain)
        ] + fresh["origins"]
        self.save(current)
        return len(fresh["cookies"])

    def remove_domain(self, domain: str) -> int:
        state = self.load()
        before = len(state["cookies"])
        state["cookies"] = [c for c in state["cookies"] if not related(cookie_domain(c), domain)]
        state["origins"] = [
            o
            for o in state["origins"]
            if not related(_origin_host(str(o.get("origin", ""))), domain)
        ]
        self.save(state)
        return before - len(state["cookies"])
