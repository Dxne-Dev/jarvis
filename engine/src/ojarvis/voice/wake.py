"""Mot de réveil « Hey Jarvis » : openWakeWord en local, puis vérification si le score hésite.

openWakeWord est entraîné sur l'anglais : prononcé « à la française », « Jarvis » obtient
souvent un score moyen. Dans ce cas, les deux dernières secondes sont transcrites en local
et l'on cherche « Jarvis » dans le texte, même mal orthographié. Rien ne quitte la machine.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Protocol

from ojarvis.core.downloads import PinnedFile
from ojarvis.voice.audio import Pcm

OWW_BASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"
WAKE_FILES: dict[str, PinnedFile] = {
    "hey_jarvis_v0.1.onnx": PinnedFile(
        f"{OWW_BASE}/hey_jarvis_v0.1.onnx",
        "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
        1_271_370,
    ),
    "melspectrogram.onnx": PinnedFile(
        f"{OWW_BASE}/melspectrogram.onnx",
        "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
        1_087_958,
    ),
    "embedding_model.onnx": PinnedFile(
        f"{OWW_BASE}/embedding_model.onnx",
        "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
        1_326_578,
    ),
}


class WakeDetector(Protocol):
    def score(self, pcm: Pcm) -> float: ...

    def reset(self) -> None: ...


class OpenWakeWord:
    """Score de « Hey Jarvis » pour chaque trame de 80 ms (environ 4 ms de calcul ici)."""

    def __init__(self, folder: Path) -> None:
        from openwakeword.model import Model  # noqa: PLC0415

        self._model: Any = Model(
            wakeword_models=[str(folder / "hey_jarvis_v0.1.onnx")],
            inference_framework="onnx",
            melspec_model_path=str(folder / "melspectrogram.onnx"),
            embedding_model_path=str(folder / "embedding_model.onnx"),
        )
        self._name = next(iter(self._model.models))

    def score(self, pcm: Pcm) -> float:
        return float(self._model.predict(pcm)[self._name])

    def reset(self) -> None:
        self._model.reset()


_TARGETS = ("jarvis", "jarvi", "djarvis", "jervis")
_INTERJECTIONS = {"hey", "he", "hei", "eh", "et", "e", "ok", "okay", "o", "ah", "hai", "hi"}
_TOKEN = re.compile(r"[a-z]+")
_ELISION = re.compile(r"^[bcdfghjklmnpqrstvwxz]{1,2}$")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _looks_like_jarvis(candidate: str, threshold: float = 0.75) -> bool:
    if len(candidate) < 4:
        return False
    return any(SequenceMatcher(None, candidate, t).ratio() >= threshold for t in _TARGETS)


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(_fold(text))]


def find_wake(text: str, *, within: int = 4) -> tuple[int, int] | None:
    """Position (début, fin) de « Jarvis » dans les premiers mots, même écorché.

    Deux mots voisins sont aussi essayés collés : Whisper écrit parfois « j'arvi » ou
    « j'ai revi » pour « Jarvis » dit à la française.
    """
    tokens = _tokens(text)[:within]
    for i, (word, start, end) in enumerate(tokens):
        if _looks_like_jarvis(word):
            return start, end
        if i + 1 < len(tokens):
            nxt, _, nxt_end = tokens[i + 1]
            # Seulement une élision (« j' », « d' ») : « à Jarvis » reste « à » + « Jarvis ».
            # Plus exigeant aussi : « j'avais » ne doit pas passer pour « Jarvis ».
            if _ELISION.match(word) and _looks_like_jarvis(word + nxt, threshold=0.85):
                return start, nxt_end
    return None


def mentions_jarvis(text: str) -> bool:
    return find_wake(text) is not None


def strip_wake_words(text: str) -> str:
    """Retire « Hey Jarvis » (et ses variantes) du début d'une transcription."""
    found = find_wake(text)
    if found is None:
        return text.strip()
    _, end = found
    prefix = _tokens(text[: found[0]])
    # Un « Hey » mal entendu (« him », « pay ») : un seul mot court devant « Jarvis ».
    misheard_hey = len(prefix) == 1 and len(prefix[0][0]) <= 4
    if not misheard_hey and any(word not in _INTERJECTIONS for word, _, _ in prefix):
        return text.strip()
    # `_fold` garde la longueur des caractères latins : les positions valent pour `text`.
    rest = text[end:] if len(_fold(text)) == len(text) else text
    return rest.lstrip(" ,.;:!?-—…'’\"").strip()
