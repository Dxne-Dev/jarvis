"""Les états du pipeline vocal (veille, écoute, réflexion, parole), ses réglages, et les
phrases dites quand le modèle ou la transcription ne répond pas.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from ojarvis.voice.vad import EndpointConfig

SPOKEN_LLM_ERROR = "Je n'arrive pas à joindre le modèle pour l'instant. Réessaie dans un moment."

SPOKEN_STT_ERROR = "Je n'ai pas pu transcrire ta phrase. Réessaie dans un moment."


class VoiceState(enum.StrEnum):
    OFF = "off"
    IDLE = "idle"  # en veille : seul le mot de réveil est écouté, en local
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"


@dataclass
class VoiceConfig:
    wake_threshold: float = 0.5
    #: Score « hésitant » : au-dessus, les 2 dernières secondes sont vérifiées par transcription.
    wake_candidate: float = 0.15
    verify_wake: bool = True
    verify_window_s: float = 2.0
    #: Audio gardé avant le début détecté de la phrase, pour ne pas couper la première syllabe.
    preroll_s: float = 0.35
    #: Après une réponse, Jarvis écoute encore ce temps-là sans mot de réveil (0 = jamais).
    follow_up_s: float = 6.0
    #: Interrompre Jarvis en parlant (sinon, seulement en redisant « Hey Jarvis »).
    barge_in: bool = True
    barge_in_s: float = 0.4
    barge_in_threshold: float = 0.7
    #: Une nouvelle conversation commence après ce silence entre deux tours.
    conversation_idle_s: float = 600.0
    endpoint: EndpointConfig = field(default_factory=EndpointConfig)
