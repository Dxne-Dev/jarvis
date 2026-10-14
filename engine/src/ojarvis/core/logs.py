"""Logs structurés (JSON) avec ID de corrélation, filtrés contre les fuites de secrets.

La sortie standard est réservée à la poignée de main avec l'app : les logs vont sur
stderr et dans un fichier tournant.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

from ojarvis.core.context import current_correlation_id
from ojarvis.security.redaction import REDACTOR

# Bibliothèques bavardes : le client HTTP écrit les URL complètes (le jeton Telegram y figure).
_QUIET_LOGGERS = ("httpx", "httpcore", "hpack", "asyncio", "alembic.runtime.migration")


def _add_correlation_id(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    correlation_id = current_correlation_id()
    if correlation_id and "correlation_id" not in event_dict:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def _redact(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    redacted: dict[str, Any] = REDACTOR.redact_obj(dict(event_dict))
    return redacted


def configure_logging(
    level: str = "INFO", *, log_file: Path | None = None, json_console: bool = True
) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_correlation_id,
        structlog.processors.format_exc_info,
        _redact,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    json_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )
    console_formatter = (
        json_formatter
        if json_console
        else structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=False),
            ],
        )
    )
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(console_formatter)
    root.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(json_formatter)
        root.addHandler(file_handler)
    root.setLevel(level)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
