"""Découpe la réponse du modèle, au fil de l'eau, en morceaux prêts à être dits.

Le premier morceau part le plus tôt possible (une proposition suffit) : c'est lui qui
fixe le délai avant que Jarvis commence à parler. Le markdown est retiré avant la voix.
"""

from __future__ import annotations

import re

from ojarvis.core.text import plain_text

# Fin de phrase : ponctuation forte suivie d'un espace ou d'un retour à la ligne.
_SENTENCE_END = re.compile(r"(?<=[.!?…:;])[\"»)\]]*\s+|\n+")
_ABBREVIATIONS = ("M.", "Mme.", "Dr.", "St.", "etc.", "cf.", "p.", "ex.", "env.", "av.", "apr.")
_CLAUSE = re.compile(r",\s+")
_LIST_MARKER = re.compile(r"(?:^|\n)\s*\d{1,3}[.)]$")


class SentenceSplitter:
    def __init__(self, *, first_clause_chars: int = 40, max_chars: int = 240) -> None:
        self._buffer = ""
        self._first = True
        self._first_clause_chars = first_clause_chars
        self._max_chars = max_chars

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        out: list[str] = []
        while True:
            cut = self._next_cut()
            if cut is None:
                break
            piece, self._buffer = self._buffer[:cut], self._buffer[cut:]
            self._emit(piece, out)
        return out

    def flush(self) -> list[str]:
        out: list[str] = []
        piece, self._buffer = self._buffer, ""
        self._emit(piece, out)
        return out

    def _emit(self, piece: str, out: list[str]) -> None:
        spoken = plain_text(piece)
        if spoken.strip(" .,;:!?…-—*_#>`") and any(c.isalnum() for c in spoken):
            out.append(spoken)
            self._first = False

    def _next_cut(self) -> int | None:
        buffer = self._buffer
        for match in _SENTENCE_END.finditer(buffer):
            head = buffer[: match.start()].rstrip()
            if head.endswith(_ABBREVIATIONS):
                continue
            if _LIST_MARKER.search(head):
                continue  # « 3. » en tête de ligne : numéro de liste, pas une fin de phrase
            return match.end()
        if self._first and len(buffer) >= self._first_clause_chars:
            clauses = list(_CLAUSE.finditer(buffer))
            if clauses and clauses[-1].start() >= 12:
                return clauses[-1].end()
        if len(buffer) >= self._max_chars:
            space = buffer.rfind(" ", 0, self._max_chars)
            return space + 1 if space > 0 else self._max_chars
        return None
