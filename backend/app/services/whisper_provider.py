"""Local speech-to-text with faster-whisper (the one real provider).

faster-whisper is OPTIONAL (requirements-whisper.txt) and imported lazily, so the
API and test suite run without it. If it is missing, or the model cannot be
loaded (e.g. first-run download fails), transcription reports
`transcription_unavailable` instead of crashing.

Audio is written to a private temporary directory only for the duration of one
call and is always deleted afterwards (including on errors). Nothing is stored
permanently and audio content is never logged.
"""

import os
import tempfile
import threading
from typing import Any, Callable, Optional

from app import config
from app.services.transcription_errors import (
    TranscriptionFailedError,
    TranscriptionUnavailableError,
    UnreadableAudioError,
    VoiceInputError,
)
from app.services.transcription_service import TranscriptionClient, TranscriptionResult


def _default_model_factory() -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionUnavailableError(
            "Speech-to-text is not installed on the server (see requirements-whisper.txt)."
        ) from exc
    try:
        # CPU + int8 keeps it runnable on ordinary laptops without a GPU.
        return WhisperModel(config.WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    except Exception as exc:
        raise TranscriptionUnavailableError("The speech-to-text model could not be loaded.") from exc


class WhisperTranscriptionClient(TranscriptionClient):
    def __init__(self, model_factory: Optional[Callable[[], Any]] = None) -> None:
        self._model_factory = model_factory or _default_model_factory
        self._model: Any = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    self._model = self._model_factory()
                except VoiceInputError:
                    raise
                except Exception as exc:
                    raise TranscriptionUnavailableError("The speech-to-text model could not be loaded.") from exc
            return self._model

    def transcribe(self, audio: bytes, audio_format: str) -> TranscriptionResult:
        model = self._get_model()

        with tempfile.TemporaryDirectory(prefix="voice_answer_") as tmp_dir:
            path = os.path.join(tmp_dir, f"answer.{audio_format}")
            with open(path, "wb") as handle:
                handle.write(audio)

            # faster-whisper decodes inside this call, so an exception here means
            # the audio could not be decoded (verified: undecodable bytes raise
            # a bare TypeError). vad_filter drops silence so a silent recording
            # yields an empty transcript instead of an invented phrase.
            try:
                segments, info = model.transcribe(path, vad_filter=True)
            except VoiceInputError:
                raise
            except Exception as exc:
                raise UnreadableAudioError() from exc

            # Segments are produced lazily; failures here are transcription failures.
            try:
                text = " ".join(segment.text.strip() for segment in segments).strip()
                duration = float(info.duration)
            except Exception as exc:
                raise TranscriptionFailedError() from exc

        return TranscriptionResult(text=text, duration_seconds=duration)