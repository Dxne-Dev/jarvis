"""Transcription par Groq (Whisper large-v3), avec un serveur HTTP simulé."""

from __future__ import annotations

import io
import json
import wave

import httpx
import numpy as np
import pytest

from ojarvis.voice.stt import GROQ_STT_URL, GroqTranscriber, SttError


def answer(request: httpx.Request) -> httpx.Response:
    body = request.content.decode("latin-1")
    assert request.url == httpx.URL(GROQ_STT_URL)
    assert request.headers["Authorization"] == "Bearer gsk-test"
    for field in ('name="model"', "whisper-large-v3", 'name="language"', "fr", "verbose_json"):
        assert field in body
    assert "RIFF" in body  # un vrai fichier WAV
    return httpx.Response(
        200,
        json={
            "text": " Quelle heure est-il ?",
            "segments": [
                {"text": " Quelle heure", "avg_logprob": -0.2, "no_speech_prob": 0.01},
                {"text": " est-il ?", "avg_logprob": -0.4, "no_speech_prob": 0.05},
            ],
        },
    )


async def test_the_sentence_goes_to_groq_in_french_and_comes_back() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as http:
        stt = GroqTranscriber(lambda: "gsk-test", http)
        transcript = await stt.transcribe(np.zeros(16_000, dtype=np.int16))
    assert transcript.text == "Quelle heure est-il ?"
    assert transcript.audio_s == 1.0
    assert transcript.avg_logprob == -0.4  # la note du segment le moins sûr
    assert transcript.no_speech_prob == 0.05
    assert transcript.reliable


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_a_refusal_is_an_error(status: int) -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(status, json={}))
    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(SttError, match=str(status)):
            await GroqTranscriber(lambda: "gsk-test", http).transcribe(np.zeros(800, np.int16))


async def test_an_unreachable_service_is_an_error() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("réseau coupé")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
        with pytest.raises(SttError, match="injoignable"):
            await GroqTranscriber(lambda: "gsk-test", http).transcribe(np.zeros(800, np.int16))


async def test_without_key_nothing_is_sent() -> None:
    sent: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as http:
        stt = GroqTranscriber(lambda: None, http)
        assert not stt.available
        with pytest.raises(SttError, match="absente"):
            await stt.transcribe(np.zeros(800, np.int16))
    assert sent == []


def test_the_audio_is_a_16k_mono_wav() -> None:
    from ojarvis.voice.stt import wav_bytes  # noqa: PLC0415

    data = wav_bytes(np.ones(1600, dtype=np.int16))
    with wave.open(io.BytesIO(data)) as handle:
        assert (handle.getframerate(), handle.getnchannels(), handle.getnframes()) == (
            16_000,
            1,
            1600,
        )
    assert json.dumps({"taille": len(data)})


async def test_a_rate_limit_sets_groq_aside_for_the_time_it_asks() -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(429, headers={"retry-after": "30"}, json={})
    )
    async with httpx.AsyncClient(transport=transport) as http:
        stt = GroqTranscriber(lambda: "gsk-test", http)
        with pytest.raises(SttError, match="30 s"):
            await stt.transcribe(np.zeros(800, np.int16))
    assert not stt.available  # pendant 30 s, les phrases passent par le relais
