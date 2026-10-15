"""Briques du pipeline vocal : fin de phrase, mot de réveil, phrases à dire, audio."""

from __future__ import annotations

import numpy as np
import pytest

from ojarvis.voice.audio import FRAME_S, RATE, level, resample
from ojarvis.voice.sentences import SentenceSplitter
from ojarvis.voice.vad import Endpoint, EndpointConfig, Endpointer
from ojarvis.voice.wake import find_wake, mentions_jarvis, strip_wake_words

# ---------------------------------------------------------------- fin de phrase


def drive(endpointer: Endpointer, probs: list[float], start: float = 0.0) -> list[Endpoint]:
    events: list[Endpoint] = []
    for index, prob in enumerate(probs, start=1):
        event = endpointer.update(prob, start + index * FRAME_S, FRAME_S)
        if event != Endpoint.NONE:
            events.append(event)
        if event in (Endpoint.END, Endpoint.TIMEOUT):
            break  # le pipeline arrête d'écouter ici
    return events


def test_endpointer_finds_start_pause_and_end() -> None:
    endpointer = Endpointer(EndpointConfig(hangover_s=0.4, pause_s=0.16, min_speech_s=0.16))
    events = drive(endpointer, [0.0, 0.9, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert events == [Endpoint.START, Endpoint.PAUSE, Endpoint.END]
    assert endpointer.speech_start_at == pytest.approx(FRAME_S)
    assert endpointer.last_voice_at == pytest.approx(5 * FRAME_S)


def test_endpointer_resumes_when_speech_comes_back() -> None:
    endpointer = Endpointer(EndpointConfig(hangover_s=0.4, pause_s=0.16, min_speech_s=0.16))
    events = drive(endpointer, [0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.9, 0.9])
    assert events == [Endpoint.START, Endpoint.PAUSE, Endpoint.RESUME]


def test_endpointer_ignores_a_click_and_times_out() -> None:
    endpointer = Endpointer(EndpointConfig(min_speech_s=0.16, no_speech_timeout_s=1.0))
    endpointer.reset(0.0)
    events = drive(endpointer, [0.9] + [0.0] * 14)
    assert events == [Endpoint.TIMEOUT]


def test_endpointer_cuts_very_long_speech() -> None:
    endpointer = Endpointer(EndpointConfig(min_speech_s=0.08, max_utterance_s=1.0))
    events = drive(endpointer, [0.9] * 20)
    assert events[:2] == [Endpoint.START, Endpoint.END]


# ---------------------------------------------------------------- mot de réveil


@pytest.mark.parametrize(
    "text",
    [
        "Hey Jarvis, quelle heure est-il ?",
        "Et Jarvi, quelle heure est-il ?",
        "Hey, Jervus, quelle est la capitale du Bénin ?",
        "Hé, Jervis, quelle aurait-il ?",
        "Et j'arvi, combien font 12 fois 8 ?",
        "Et j'avis, explique-moi ce qu'est un trou noir.",
        "Hey Jarvisse !",
    ],
)
def test_jarvis_is_found_even_misspelled(text: str) -> None:
    assert mentions_jarvis(text)


@pytest.mark.parametrize(
    "text",
    [
        "Je pense qu'il va pleuvoir ce soir.",
        "J'avais un rendez-vous au jardin.",
        "Le service est fermé le lundi.",
        "Travis arrive demain.",
        "Bonjour, comment ça va ?",
        "",
    ],
)
def test_ordinary_sentences_are_not_the_wake_word(text: str) -> None:
    assert not mentions_jarvis(text)


def test_jarvis_far_in_the_sentence_is_not_a_wake_word() -> None:
    assert find_wake("Je regardais un film hier soir avec Jarvis") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hey Jarvis, quelle heure est-il ?", "quelle heure est-il ?"),
        ("Et j'arvi, combien font 12 fois 8 ?", "combien font 12 fois 8 ?"),
        ("Jarvis. Rappelle-moi d'appeler Paul.", "Rappelle-moi d'appeler Paul."),
        ("Hey Jarvis.", ""),
        ("Quelle heure est-il ?", "Quelle heure est-il ?"),
        ("Dis à Jarvis de partir", "Dis à Jarvis de partir"),
    ],
)
def test_wake_words_are_removed_from_the_request(text: str, expected: str) -> None:
    assert strip_wake_words(text) == expected


# ---------------------------------------------------------------- phrases à dire


def feed_all(splitter: SentenceSplitter, chunks: list[str]) -> list[str]:
    out: list[str] = []
    for chunk in chunks:
        out.extend(splitter.feed(chunk))
    return out + splitter.flush()


def test_sentences_come_out_as_soon_as_they_end() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("Il est dix ") == []
    assert splitter.feed("heures. Tu veux ") == ["Il est dix heures."]
    assert splitter.feed("un rappel ?") == []
    assert splitter.flush() == ["Tu veux un rappel ?"]


def test_first_clause_leaves_early_for_a_long_sentence() -> None:
    splitter = SentenceSplitter(first_clause_chars=40)
    out = splitter.feed("Pour un dîner rapide ce soir, je te propose une omelette aux herbes ")
    assert out == ["Pour un dîner rapide ce soir,"]


def test_markdown_lists_and_numbers_are_spoken_cleanly() -> None:
    text = "Voici **trois** idées :\n1. Une omelette.\n2. Des pâtes.\n\nIl est 10 h 30."
    out = feed_all(SentenceSplitter(), [text[i : i + 7] for i in range(0, len(text), 7)])
    assert out == ["Voici trois idées :", "Une omelette.", "Des pâtes.", "Il est 10 h 30."]


def test_abbreviations_and_decimals_do_not_split() -> None:
    out = feed_all(SentenceSplitter(), ["M. Dupont mesure 1.85 m, etc. ", "Voilà."])
    assert out == ["M. Dupont mesure 1.85 m, etc. Voilà."]


def test_symbols_alone_are_not_spoken() -> None:
    assert feed_all(SentenceSplitter(), ["---\n", "**", "\n"]) == []


def test_very_long_text_without_punctuation_is_cut_on_a_space() -> None:
    splitter = SentenceSplitter(max_chars=50, first_clause_chars=1000)
    out = splitter.feed("mot " * 20)
    assert out
    assert all(len(piece) <= 50 for piece in out)


# ---------------------------------------------------------------- audio


def test_level_maps_loudness_to_zero_one() -> None:
    assert level(np.zeros(1280, dtype=np.int16)) == 0.0
    loud = (20000 * np.sin(np.linspace(0, 100, 1280))).astype(np.int16)
    quiet = (loud // 100).astype(np.int16)
    assert 0.8 < level(loud) <= 1.0
    assert 0.0 < level(quiet) < level(loud)


def test_resample_keeps_duration() -> None:
    audio = np.zeros(24_000, dtype=np.int16)
    assert len(resample(audio, 24_000, RATE)) == RATE
    assert resample(audio, RATE, RATE) is audio
