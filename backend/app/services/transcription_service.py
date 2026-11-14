"""Speech-to-text service for voice answers (Stage 3.8).

This module only turns audio into text. It never evaluates an answer, never
touches interview state and never updates competency: the transcript is handed
back to the candidate to review/edit, and only the text they submit goes
through the existing POST /interview/{id}/answer pipeline.

The interview engine does not know which provider is used. A provider is any
TranscriptionClient; the real one is app/services/whisper_provider.py. Tests
supply their own fake client — there is deliberately NO fake/placeholder client
in the application code, so the running app can never return a made-up
transcript.
"""

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Optional

from app import config
from app.services.transcription_errors import (
    AudioTooLongError,
    NoSpeechDetectedError,
    TranscriptionFailedError,
    TranscriptionTimeoutError,
    VoiceInputError,
)


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    duration_seconds: Optional[float] = None


class TranscriptionClient(ABC):
    """Interface any speech-to-text provider must implement."""

    @abstractmethod
    def transcribe(self, audio: bytes, audio_format: str) -> TranscriptionResult:
        """Return the transcript. Raise a VoiceInputError subclass on known failures."""
        raise NotImplementedError


_default_client: Optional[TranscriptionClient] = None


def get_transcription_client() -> TranscriptionClient:
    """Return the shared real provider (created lazily; the model loads on first use)."""
    global _default_client
    if _default_client is None:
        from app.services.whisper_provider import WhisperTranscriptionClient

        _default_client = WhisperTranscriptionClient()
    return _default_client


def transcribe_audio(
    audio: bytes,
    audio_format: str,
    client: Optional[TranscriptionClient] = None,
    timeout_seconds: Optional[float] = None,
) -> TranscriptionResult:
    """Transcribe audio with a timeout, normalising every failure to a typed error.

    - Provider's own typed errors pass through unchanged.
    - Anything unexpected becomes TranscriptionFailedError (details never leak).
    - A blank transcript is an error (NoSpeechDetectedError), never an empty answer.
    - Audio that decodes to longer than the allowed recording is rejected.

    Limitation: on timeout the worker thread cannot be force-killed; the caller
    gets a 504 immediately and the thread finishes (and cleans up) in the background.
    """
    provider = client if client is not None else get_transcription_client()
    timeout = config.TRANSCRIPTION_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(provider.transcribe, audio, audio_format)
    try:
        result = future.result(timeout=timeout)
    except FutureTimeoutError:
        raise TranscriptionTimeoutError() from None
    except VoiceInputError:
        raise
    except Exception as exc:
        raise TranscriptionFailedError() from exc
    finally:
        executor.shutdown(wait=False)

    max_seconds = config.MAX_RECORDING_SECONDS + config.RECORDING_DURATION_TOLERANCE_SECONDS
    if result.duration_seconds is not None and result.duration_seconds > max_seconds:
        raise AudioTooLongError()

    text = (result.text or "").strip()
    if not text:
        raise NoSpeechDetectedError()
    return TranscriptionResult(text=text, duration_seconds=result.duration_seconds)