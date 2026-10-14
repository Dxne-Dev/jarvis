from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from ojarvis.core.logs import configure_logging, get_logger
from ojarvis.security.redaction import MASK, REDACTOR, Redactor


def test_known_values_are_masked() -> None:
    redactor = Redactor()
    redactor.set_values(["valeur-super-secrete-123", "court"])
    text = "clé=valeur-super-secrete-123 et court"
    assert redactor.redact(text) == f"clé={MASK} et court"  # trop court : laissé tel quel


def test_longest_value_wins() -> None:
    redactor = Redactor()
    redactor.set_values(["abcdef", "abcdefghij"])
    assert redactor.redact("x abcdefghij y") == f"x {MASK} y"


@pytest.mark.parametrize(
    "secret",
    [
        "Bearer abcdefghijklmnop",
        "sk-" + "a" * 30,
        "sk_car_" + "b" * 20,
        "ghp_" + "c" * 36,
        "github_pat_" + "d" * 40,
        "ntn_" + "e" * 40,
        "tvly-" + "f" * 30,
        "GOCSPX-" + "g" * 24,
        "1234567890:AA" + "h" * 33,
        "bot1234567890:AA" + "i" * 33,
        "AKIA" + "Z" * 16,
    ],
)
def test_key_formats_are_masked(secret: str) -> None:
    assert secret not in Redactor().redact(f"avant {secret} après")


def test_redact_obj_walks_structures() -> None:
    redactor = Redactor()
    redactor.set_values(["mot-de-passe-xyz"])
    data = {"a": ["mot-de-passe-xyz", 3], "b": {"c": "ok mot-de-passe-xyz"}}
    assert redactor.redact_obj(data) == {"a": [MASK, 3], "b": {"c": f"ok {MASK}"}}


def test_add_value_extends_set() -> None:
    redactor = Redactor()
    redactor.add_value("premiere-valeur")
    redactor.add_value("seconde-valeur")
    assert redactor.redact("premiere-valeur seconde-valeur") == f"{MASK} {MASK}"


def test_logs_never_contain_secrets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log_file = tmp_path / "engine.log"
    configure_logging("DEBUG", log_file=log_file)
    REDACTOR.set_values(["cle-tres-secrete-42"])
    log = get_logger("test")
    log.info("appel", url="https://api.telegram.org/bot1234567890:AA" + "x" * 33 + "/getMe")
    log.info("valeur cle-tres-secrete-42", detail={"k": "cle-tres-secrete-42"})
    logging.getLogger("bibliotheque").warning("Bearer abcdefghijklmnopqrstuvwxyz")
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = log_file.read_text(encoding="utf-8") + capsys.readouterr().err
    assert "cle-tres-secrete-42" not in content
    assert "abcdefghijklmnopqrstuvwxyz" not in content
    assert ":AA" + "x" * 33 not in content
    first = json.loads(log_file.read_text(encoding="utf-8").splitlines()[0])
    assert first["event"] == "appel"
    assert first["level"] == "info"
    assert "timestamp" in first


def test_noisy_http_loggers_are_quiet() -> None:
    configure_logging("DEBUG")
    assert logging.getLogger("httpx").level == logging.WARNING
