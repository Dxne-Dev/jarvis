"""Texte brut à partir de markdown : aperçus de l'historique et phrases lues à voix haute."""

from __future__ import annotations

import re

_FENCE = re.compile(r"^\s*(```|~~~).*$", re.MULTILINE)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_LINE_MARKERS = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d{1,3}[.)]\s+)", re.MULTILINE)
_EMPHASIS = (
    re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1"),
    re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"),
    re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])"),
    re.compile(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])"),
)
_CODE = re.compile(r"`([^`]*)`")
_SPACES = re.compile(r"\s+")


def plain_text(markdown: str) -> str:
    """Retire la syntaxe markdown courante et ramène le texte sur une seule ligne."""
    text = _FENCE.sub("", markdown)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _LINE_MARKERS.sub("", text)
    for pattern in _EMPHASIS:
        text = pattern.sub(lambda m: m.group(m.lastindex or 0), text)
    text = _CODE.sub(r"\1", text)
    return _SPACES.sub(" ", text).strip()
