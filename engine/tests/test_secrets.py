from __future__ import annotations

from pathlib import Path

import keyring
import pytest
from keyring.backends import fail, null

from ojarvis.core.errors import InvalidInputError, NotFoundError, UnavailableError
from ojarvis.db.engine import Database
from ojarvis.db.migrate import upgrade_to_head
from ojarvis.security.redaction import REDACTOR
from ojarvis.security.secrets import (
    CATALOG,
    LOCAL_KEY_NAME,
    KeyringBackend,
    MemoryBackend,
    SecretStore,
    parse_dotenv,
)
from ojarvis.services import UnavailableBackend


@pytest.fixture
def store(tmp_path: Path) -> SecretStore:
    db_path = tmp_path / "t.db"
    upgrade_to_head(db_path)
    return SecretStore(Database(db_path), MemoryBackend())


def test_catalog_matches_the_brief() -> None:
    # Les 12 noms du brief, plus GROQ_API_KEY (transcription, décidée avec Octave le 15/10)
    # et MODEL_API_KEY (Meta, le nom de ses propres exemples, ajouté le 26/10).
    assert [s.name for s in CATALOG] == [
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "MODEL_API_KEY",
        "CARTESIA_API_KEY",
        "GROQ_API_KEY",
        "TAVILY_API_KEY",
        "GITHUB_TOKEN",
        "NOTION_TOKEN",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_ID",
    ]


def test_parse_dotenv_keeps_only_allowed_non_empty(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "# commentaire",
                "DEEPSEEK_API_KEY=sk-abc   # commentaire en fin de ligne",
                "OPENAI_API_KEY=          # vide",
                'NOTION_TOKEN="ntn_entre_guillemets"',
                "export TAVILY_API_KEY=tvly-xyz",
                "AWS_SECRET_ACCESS_KEY=jamais-importee",
                "ligne invalide",
            ]
        ),
        encoding="utf-8",
    )
    values = parse_dotenv(env, {s.name for s in CATALOG})
    assert values == {
        "DEEPSEEK_API_KEY": "sk-abc",
        "NOTION_TOKEN": "ntn_entre_guillemets",
        "TAVILY_API_KEY": "tvly-xyz",
    }


def test_set_get_delete_and_status(store: SecretStore) -> None:
    store.set("DEEPSEEK_API_KEY", "  sk-valeur-de-test  ")
    assert store.get("DEEPSEEK_API_KEY") == "sk-valeur-de-test"
    status = {s.name: s for s in store.status()}
    assert status["DEEPSEEK_API_KEY"].configured
    assert status["DEEPSEEK_API_KEY"].source == "ui"
    assert not status["OPENAI_API_KEY"].configured
    store.delete("DEEPSEEK_API_KEY")
    assert store.get("DEEPSEEK_API_KEY") is None
    assert not {s.name: s for s in store.status()}["DEEPSEEK_API_KEY"].configured


def test_set_feeds_the_redactor(store: SecretStore) -> None:
    store.set("TAVILY_API_KEY", "valeur-a-masquer-partout")
    assert "valeur-a-masquer-partout" not in REDACTOR.redact("x valeur-a-masquer-partout")


@pytest.mark.parametrize("value", ["", "   ", "a\nb", "a\rb", "a\0b", "x" * 5000])
def test_invalid_values_are_refused(store: SecretStore, value: str) -> None:
    with pytest.raises(InvalidInputError):
        store.set("DEEPSEEK_API_KEY", value)


def test_unknown_names_are_refused(store: SecretStore) -> None:
    with pytest.raises(NotFoundError):
        store.set("AWS_SECRET_ACCESS_KEY", "x")
    with pytest.raises(NotFoundError):
        store.get("STRIPE_SECRET_KEY")


def test_import_only_adds_missing(store: SecretStore, tmp_path: Path) -> None:
    store.set("DEEPSEEK_API_KEY", "saisie-dans-l-interface")
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=depuis-env\nNOTION_TOKEN=ntn-env\nSTRIPE_KEY=non\n")
    imported = store.import_dotenv(env)
    assert imported == ["NOTION_TOKEN"]
    assert store.get("DEEPSEEK_API_KEY") == "saisie-dans-l-interface"
    assert {s.name: s for s in store.status()}["NOTION_TOKEN"].source == "env"
    assert store.import_dotenv(tmp_path / "absent.env") == []


def test_local_key_generated_once(store: SecretStore) -> None:
    store.ensure_local_key()
    first = store.get(LOCAL_KEY_NAME)
    store.ensure_local_key()
    assert first is not None
    assert len(first) >= 40
    assert store.get(LOCAL_KEY_NAME) == first


def test_record_check_is_kept_and_redacted(store: SecretStore) -> None:
    store.set("GITHUB_TOKEN", "ghp_" + "a" * 36)
    store.record_check("GITHUB_TOKEN", ok=False, detail="refus ghp_" + "a" * 36, latency_ms=12)
    status = {s.name: s for s in store.status()}["GITHUB_TOKEN"]
    assert status.last_check_ok is False
    assert status.last_check_latency_ms == 12
    assert status.last_check_detail is not None
    assert "aaaa" not in status.last_check_detail


def test_load_into_redactor_keeps_existing_values(store: SecretStore) -> None:
    store.set("CARTESIA_API_KEY", "sk_car_valeur_chargee")
    REDACTOR.set_values(["jeton-de-session-deja-connu"])
    store.load_into_redactor()
    assert "sk_car_valeur_chargee" not in REDACTOR.redact("sk_car_valeur_chargee")
    assert "jeton-de-session-deja-connu" not in REDACTOR.redact("jeton-de-session-deja-connu")


def test_unavailable_backend_refuses_writes() -> None:
    backend = UnavailableBackend()
    assert backend.get("X") is None
    with pytest.raises(UnavailableError):
        backend.set("X", "y")
    with pytest.raises(UnavailableError):
        backend.delete("X")


@pytest.mark.parametrize("unusable", [fail.Keyring, null.Keyring])
def test_keyring_backend_refuses_unusable(
    monkeypatch: pytest.MonkeyPatch, unusable: type[object]
) -> None:
    instance = unusable()
    monkeypatch.setattr(keyring, "get_keyring", lambda: instance)
    with pytest.raises(UnavailableError):
        KeyringBackend()


@pytest.mark.real
def test_real_secret_service_roundtrip() -> None:
    backend = KeyringBackend()
    key = "OJARVIS_TEST_ROUNDTRIP"
    backend.set(key, "valeur-temporaire")
    try:
        assert backend.get(key) == "valeur-temporaire"
    finally:
        backend.delete(key)
    assert backend.get(key) is None
