"""Import des cookies d'un domaine depuis Chrome, Chromium ou Brave, sur ta demande.

Rien n'est lu sans ton action dans Réglages > Navigateur, et seulement pour le domaine
choisi. Format des navigateurs de la famille Chromium sous Linux :
- la base `Cookies` (SQLite) chiffre chaque valeur en AES-128-CBC ;
- préfixe `v10` : clé fixe connue ; préfixe `v11` : mot de passe rangé par le navigateur
  dans le trousseau du système (« Chrome Safe Storage », « Brave Safe Storage »…) ;
- depuis la version 24 du schéma, la valeur déchiffrée commence par l'empreinte SHA-256
  du domaine, retirée ici.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ojarvis.browser.vault import parents, related
from ojarvis.core.errors import NotFoundError, UpstreamError
from ojarvis.core.logs import get_logger

log = get_logger(__name__)

#: navigateur → (nom affiché, dossier de configuration, application dans le trousseau)
BROWSERS: dict[str, tuple[str, str, str]] = {
    "chrome": ("Google Chrome", ".config/google-chrome", "chrome"),
    "chromium": ("Chromium", ".config/chromium", "chromium"),
    "brave": ("Brave", ".config/BraveSoftware/Brave-Browser", "brave"),
}
_CHROME_EPOCH_OFFSET_S = 11_644_473_600
_SAME_SITE = {0: "None", 1: "Lax", 2: "Strict"}


@dataclass(frozen=True)
class BrowserSource:
    id: str  # « chrome:Default »
    browser: str
    profile: str
    label: str
    cookies_path: Path


def _profile_names(root: Path) -> dict[str, str]:
    """Noms des profils affichés par le navigateur (seulement leur nom, rien d'autre)."""
    try:
        state = json.loads((root / "Local State").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cache = state.get("profile", {}).get("info_cache", {})
    return {k: str(v.get("name", k)) for k, v in cache.items() if isinstance(v, dict)}


def find_sources(home: Path) -> list[BrowserSource]:
    sources: list[BrowserSource] = []
    for browser, (title, folder, _) in BROWSERS.items():
        root = home / folder
        if not root.is_dir():
            continue
        names = _profile_names(root)
        for profile in sorted(root.iterdir()):
            if not (profile.name == "Default" or profile.name.startswith("Profile ")):
                continue
            path = next(
                (p for p in (profile / "Network" / "Cookies", profile / "Cookies") if p.is_file()),
                None,
            )
            if path is None:
                continue
            shown = names.get(profile.name, profile.name)
            sources.append(
                BrowserSource(
                    f"{browser}:{profile.name}", browser, profile.name, f"{title} — {shown}", path
                )
            )
    return sources


def find_source(home: Path, source_id: str) -> BrowserSource:
    for source in find_sources(home):
        if source.id == source_id:
            return source
    raise NotFoundError("Navigateur ou profil introuvable.")


def derive_key(password: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=b"saltysalt", iterations=1).derive(  # noqa: S303
        password
    )


def encrypt_value(plain: bytes, key: bytes, prefix: bytes = b"v10") -> bytes:
    """Chiffre comme Chromium (sert aux tests et à vérifier le déchiffrement)."""
    padder = padding.PKCS7(128).padder()
    data = padder.update(plain) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
    return prefix + encryptor.update(data) + encryptor.finalize()


def decrypt_value(
    encrypted: bytes, *, keys: dict[bytes, list[bytes]], host_key: str, meta_version: int
) -> str | None:
    prefix = encrypted[:3]
    for key in keys.get(prefix, []):
        decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        try:
            data = decryptor.update(encrypted[3:]) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            plain = unpadder.update(data) + unpadder.finalize()
        except ValueError:
            continue
        if meta_version >= 24 and plain[:32] == hashlib.sha256(host_key.encode()).digest():
            plain = plain[32:]
        try:
            return plain.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def safe_storage_password(application: str) -> bytes | None:
    """Mot de passe que le navigateur a rangé dans le trousseau du système (s'il y en a un)."""
    try:
        import secretstorage  # noqa: PLC0415
    except ImportError:  # pragma: no cover - dépendance de keyring sous Linux
        return None
    try:
        connection = secretstorage.dbus_init()
    except Exception:
        log.warning("secret_service_unavailable")
        return None
    with contextlib.closing(connection):
        try:
            collection = secretstorage.get_default_collection(connection)
            if collection.is_locked():
                collection.unlock()
            for item in collection.search_items({"application": application}):
                return bytes(item.get_secret())
        except Exception:
            log.warning("browser_password_unavailable", application=application)
    return None


def _to_playwright(row: sqlite3.Row, value: str) -> dict[str, Any]:
    expires = int(row["expires_utc"] or 0)
    same_site = _SAME_SITE.get(int(row["samesite"]), "Lax")
    secure = bool(row["is_secure"])
    if same_site == "None" and not secure:
        same_site = "Lax"
    return {
        "name": row["name"],
        "value": value,
        "domain": row["host_key"],
        "path": row["path"] or "/",
        "expires": (expires / 1_000_000 - _CHROME_EPOCH_OFFSET_S) if expires else -1,
        "httpOnly": bool(row["is_httponly"]),
        "secure": secure,
        "sameSite": same_site,
    }


def read_cookies(
    source: BrowserSource, domain: str, *, password: bytes | None
) -> list[dict[str, Any]]:
    """Cookies utiles au domaine (lui, ses sous-domaines, ses parents), déchiffrés, au format
    de Playwright.

    La base est copiée d'abord : le navigateur peut être ouvert et la verrouiller.
    """
    keys: dict[bytes, list[bytes]] = {
        b"v10": [derive_key(b"peanuts")],
        b"v11": [derive_key(password)] if password else [],
    }
    keys[b"v11"].append(derive_key(b""))
    with tempfile.TemporaryDirectory(prefix="ojarvis-cookies-") as tmp:
        copy = Path(tmp) / "Cookies"
        try:
            shutil.copyfile(source.cookies_path, copy)
            for suffix in ("-wal", "-journal"):
                extra = source.cookies_path.with_name(source.cookies_path.name + suffix)
                if extra.exists():
                    shutil.copyfile(extra, copy.with_name(copy.name + suffix))
        except OSError as exc:
            raise UpstreamError("Base de cookies du navigateur illisible.") from exc
        connection = sqlite3.connect(copy)
        connection.row_factory = sqlite3.Row
        try:
            meta = dict(connection.execute("SELECT key, value FROM meta").fetchall())
            version = int(meta.get("version", 0) or 0)
            hosts = [h for parent in parents(domain) for h in (parent, "." + parent)]
            marks = ", ".join("?" for _ in hosts)
            rows = connection.execute(
                "SELECT host_key, name, value, encrypted_value, path, expires_utc, is_secure, "  # noqa: S608
                f"is_httponly, samesite FROM cookies WHERE host_key IN ({marks}) "
                "OR host_key LIKE ?",
                (*hosts, "%." + domain),
            ).fetchall()
        except sqlite3.Error as exc:
            raise UpstreamError("Format de base de cookies inconnu.") from exc
        finally:
            connection.close()
    cookies: list[dict[str, Any]] = []
    unreadable = 0
    for row in rows:
        if not related(row["host_key"], domain):
            continue
        encrypted = bytes(row["encrypted_value"] or b"")
        if encrypted:
            value = decrypt_value(
                encrypted, keys=keys, host_key=row["host_key"], meta_version=version
            )
        else:
            value = row["value"]
        if value is None:
            unreadable += 1
            continue
        cookies.append(_to_playwright(row, value))
    if unreadable and not cookies:
        raise UpstreamError("Cookies chiffrés illisibles (trousseau du navigateur inaccessible).")
    return cookies
