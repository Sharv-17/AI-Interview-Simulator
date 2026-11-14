"""Stage 3.8 tests: audio upload, transcription, and integration with the
existing answer pipeline. No microphone, no real model, no network: transcription
is replaced by fake clients, and "audio" is a few bytes with a valid container
header."""

import io
import os
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import interview as interview_api
from app.main import app
from app.services.audio_validation import detect_audio_format, read_upload_limited, validate_audio
from app.services.interview_engine import interview_engine
from app.services.transcription_errors import (
    AudioTooLargeError,
    TranscriptionUnavailableError,
    UnreadableAudioError,
)
from app.services.transcription_service import TranscriptionClient, TranscriptionResult, transcribe_audio
from app.services.whisper_provider import WhisperTranscriptionClient

client = TestClient(app)

WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
SPOKEN = "Binary search halves the search space each step, so it runs in O(log n) time."


class FakeClient(TranscriptionClient):
    """Test double. Never used by the application itself."""

    def __init__(self, text=SPOKEN, duration=5.0, error=None, delay=0.0):
        self.text, self.duration, self.error, self.delay = text, duration, error, delay
        self.calls = 0

    def transcribe(self, audio, audio_format):
        self.calls += 1
        if self.delay:
            threading.Event().wait(self.delay)
        if self.error is not None:
            raise self.error
        return TranscriptionResult(text=self.text, duration_seconds=self.duration)


@pytest.fixture
def use_fake(monkeypatch):
    def _install(**kwargs):
        fake = FakeClient(**kwargs)
        monkeypatch.setattr(interview_api, "get_transcription_client", lambda: fake)
        return fake

    return _install


def _start():
    response = client.post(
        "/interview/start",
        json={"topic": "Algorithms", "difficulty": "easy", "question_count": 3},
    )
    interview = response.json()
    assert interview["current_question_id"] is not None
    return interview


def _transcribe(interview, audio=WEBM, question_id=None, filename="answer.webm", mime="audio/webm"):
    return client.post(
        f"/interview/{interview['interview_id']}/transcribe",
        data={"question_id": question_id or interview["current_question_id"]},
        files={"audio": (filename, audio, mime)},
    )


def _error_code(response):
    return response.json()["detail"]["code"]


def _assert_state_untouched(interview):
    session = interview_engine.get_interview(interview["interview_id"])
    assert session.answers == []
    assert session.answered_question_ids == set()
    assert session.competency_state.get_all() == {}
    assert session.current_question_id == interview["current_question_id"]


# ---------------------------------------------------------------------------
# Audio handling
# ---------------------------------------------------------------------------


def test_valid_audio_upload_returns_transcript(use_fake):
    use_fake()
    interview = _start()
    response = _transcribe(interview)
    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == SPOKEN
    assert body["duration_seconds"] == 5.0
    assert body["interview_id"] == interview["interview_id"]
    assert body["question_id"] == interview["current_question_id"]


def test_empty_audio_upload_is_rejected(use_fake):
    fake = use_fake()
    interview = _start()
    response = _transcribe(interview, audio=b"")
    assert response.status_code == 400
    assert _error_code(response) == "empty_audio"
    assert fake.calls == 0


def test_unsupported_format_is_rejected_by_content_not_filename(use_fake):
    fake = use_fake()
    interview = _start()
    # Claims to be audio/webm and named .webm, but the bytes are plain text.
    response = _transcribe(interview, audio=b"this is definitely not audio data", filename="a.webm")
    assert response.status_code == 415
    assert _error_code(response) == "unsupported_audio_format"
    assert fake.calls == 0


def test_oversized_upload_is_rejected_before_transcription(use_fake, monkeypatch):
    fake = use_fake()
    interview = _start()
    monkeypatch.setattr(config, "MAX_AUDIO_UPLOAD_BYTES", 1000)
    response = _transcribe(interview, audio=WEBM + b"\x00" * 200_000)
    assert response.status_code == 413
    assert _error_code(response) == "audio_too_large"
    assert fake.calls == 0


def test_read_upload_limited_stops_at_the_limit():
    with pytest.raises(AudioTooLargeError):
        read_upload_limited(io.BytesIO(b"x" * 5000), max_bytes=1000)
    assert read_upload_limited(io.BytesIO(b"x" * 1000), max_bytes=1000) == b"x" * 1000


def test_streaming_size_check_still_applies_when_content_length_is_small(use_fake, monkeypatch):
    """The middleware only sees the declared length; the read loop is the real guard."""
    fake = use_fake()
    interview = _start()
    monkeypatch.setattr(config, "MAX_AUDIO_UPLOAD_BYTES", 100)
    # Just over the limit but well within the middleware's overhead allowance.
    response = _transcribe(interview, audio=WEBM + b"\x00" * 500)
    assert response.status_code == 413
    assert _error_code(response) == "audio_too_large"
    assert fake.calls == 0


def test_malformed_audio_is_reported_as_unreadable(use_fake):
    use_fake(error=UnreadableAudioError())
    interview = _start()
    response = _transcribe(interview)
    assert response.status_code == 422
    assert _error_code(response) == "unreadable_audio"


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"\x1a\x45\xdf\xa3rest", "webm"),
        (b"OggSrest", "ogg"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav"),
        (b"\x00\x00\x00\x18ftypmp42", "mp4"),
        (b"ID3\x03rest", "mp3"),
        (b"\xff\xfbrest", "mp3"),
        (b"plain text", None),
        (b"", None),
    ],
)
def test_audio_format_is_detected_from_content(data, expected):
    assert detect_audio_format(data) == expected


def test_validate_audio_rejects_empty_and_unknown():
    assert validate_audio(WEBM) == "webm"
    with pytest.raises(Exception) as empty:
        validate_audio(b"")
    assert empty.value.code == "empty_audio"
    with pytest.raises(Exception) as unknown:
        validate_audio(b"nope nope nope")
    assert unknown.value.code == "unsupported_audio_format"


def test_missing_audio_field_is_a_validation_error():
    interview = _start()
    response = client.post(
        f"/interview/{interview['interview_id']}/transcribe",
        data={"question_id": interview["current_question_id"]},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Whisper provider (with a fake model): temp-file cleanup and error mapping
# ---------------------------------------------------------------------------


class _Segment:
    def __init__(self, text):
        self.text = text


class _Info:
    duration = 7.5


class FakeModel:
    def __init__(self, segments=("  Hello ", "world  "), fail_on_call=None):
        self.segments, self.fail_on_call = segments, fail_on_call
        self.seen_path = None
        self.existed_during_call = None

    def transcribe(self, path, **kwargs):
        self.seen_path = path
        self.existed_during_call = os.path.exists(path)
        self.vad_filter = kwargs.get("vad_filter")
        if self.fail_on_call:
            raise self.fail_on_call
        return iter(_Segment(t) for t in self.segments), _Info()


def test_whisper_provider_joins_segments_and_cleans_up_temp_file():
    model = FakeModel()
    result = WhisperTranscriptionClient(model_factory=lambda: model).transcribe(WEBM, "webm")
    assert result.text == "Hello world"
    assert result.duration_seconds == 7.5
    assert model.existed_during_call is True
    assert model.vad_filter is True
    assert not os.path.exists(model.seen_path)
    assert not os.path.exists(os.path.dirname(model.seen_path))


def test_whisper_provider_cleans_up_even_when_decoding_fails():
    model = FakeModel(fail_on_call=TypeError("bad audio"))
    with pytest.raises(UnreadableAudioError):
        WhisperTranscriptionClient(model_factory=lambda: model).transcribe(WEBM, "webm")
    assert not os.path.exists(os.path.dirname(model.seen_path))


def test_whisper_provider_reports_missing_library_as_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # makes `import` fail
    with pytest.raises(TranscriptionUnavailableError):
        WhisperTranscriptionClient().transcribe(WEBM, "webm")


def test_whisper_provider_reports_model_load_failure_as_unavailable():
    def broken():
        raise RuntimeError("download blocked: secret-path-detail")

    with pytest.raises(TranscriptionUnavailableError) as caught:
        WhisperTranscriptionClient(model_factory=broken).transcribe(WEBM, "webm")
    assert "secret-path-detail" not in caught.value.message


# ---------------------------------------------------------------------------
# Transcription outcomes
# ---------------------------------------------------------------------------


def test_empty_transcription_is_an_error_not_an_empty_answer(use_fake):
    use_fake(text="   ")
    interview = _start()
    response = _transcribe(interview)
    assert response.status_code == 422
    assert _error_code(response) == "no_speech_detected"


def test_provider_failure_returns_502_without_leaking_details(use_fake):
    use_fake(error=RuntimeError("secret-internal-detail /srv/models/x"))
    interview = _start()
    response = _transcribe(interview)
    assert response.status_code == 502
    assert _error_code(response) == "transcription_failed"
    assert "secret-internal-detail" not in response.text


def test_transcription_timeout_returns_504(use_fake, monkeypatch):
    use_fake(delay=0.5)
    monkeypatch.setattr(config, "TRANSCRIPTION_TIMEOUT_SECONDS", 0.05)
    interview = _start()
    response = _transcribe(interview)
    assert response.status_code == 504
    assert _error_code(response) == "transcription_timeout"


def test_unavailable_provider_returns_503(use_fake):
    use_fake(error=TranscriptionUnavailableError())
    interview = _start()
    response = _transcribe(interview)
    assert response.status_code == 503
    assert _error_code(response) == "transcription_unavailable"


def test_audio_longer_than_the_limit_is_rejected(use_fake):
    use_fake(duration=config.MAX_RECORDING_SECONDS + config.RECORDING_DURATION_TOLERANCE_SECONDS + 30)
    interview = _start()
    response = _transcribe(interview)
    assert response.status_code == 422
    assert _error_code(response) == "audio_too_long"


def test_transcribe_audio_normalises_unexpected_errors():
    with pytest.raises(Exception) as caught:
        transcribe_audio(WEBM, "webm", client=FakeClient(error=ValueError("boom")), timeout_seconds=5)
    assert caught.value.code == "transcription_failed"


# ---------------------------------------------------------------------------
# Integration with the existing interview pipeline
# ---------------------------------------------------------------------------


def test_transcription_changes_no_interview_state(use_fake):
    use_fake()
    interview = _start()
    assert _transcribe(interview).status_code == 200
    _assert_state_untouched(interview)


def test_failed_transcription_does_not_evaluate_or_update_competency(use_fake):
    use_fake(error=RuntimeError("provider down"))
    interview = _start()
    assert _transcribe(interview).status_code == 502
    _assert_state_untouched(interview)
    competency = client.get(f"/interview/{interview['interview_id']}/competency")
    assert competency.json() == {}


def test_reviewed_transcript_enters_the_existing_evaluation_pipeline(use_fake):
    use_fake()
    interview = _start()
    transcript = _transcribe(interview).json()["transcript"]

    edited = transcript + " It needs the input to be sorted first."
    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={
            "question_id": interview["current_question_id"],
            "answer_text": edited,
            "answer_source": "voice",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer_source"] == "voice"
    assert body["evaluation"]["question_type"] == "conceptual"
    assert body["competency_update"]["questions_attempted"] == 1

    session = interview_engine.get_interview(interview["interview_id"])
    assert len(session.answers) == 1
    # The EDITED text is what was evaluated and stored, not the raw transcript.
    assert session.answers[0]["answer_text"] == edited
    assert session.answers[0]["answer_source"].value == "voice"


def test_text_answers_still_work_and_default_to_text_source():
    interview = _start()
    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": "A typed answer with some substance."},
    )
    assert response.status_code == 200
    assert response.json()["answer_source"] == "text"


def test_invalid_answer_source_is_rejected():
    interview = _start()
    response = client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": "x", "answer_source": "telepathy"},
    )
    assert response.status_code == 422


def test_competency_is_updated_only_once_per_question(use_fake):
    use_fake()
    interview = _start()
    payload = {"question_id": interview["current_question_id"], "answer_text": SPOKEN, "answer_source": "voice"}
    first = client.post(f"/interview/{interview['interview_id']}/answer", json=payload)
    second = client.post(f"/interview/{interview['interview_id']}/answer", json=payload)
    assert first.status_code == 200
    assert second.status_code == 409

    session = interview_engine.get_interview(interview["interview_id"])
    assert len(session.answers) == 1
    (state,) = session.competency_state.get_all().values()
    assert state.questions_attempted == 1


# ---------------------------------------------------------------------------
# Session / question association
# ---------------------------------------------------------------------------


def test_transcribe_unknown_interview_returns_404(use_fake):
    use_fake()
    response = client.post(
        "/interview/does-not-exist/transcribe",
        data={"question_id": "q-0001"},
        files={"audio": ("a.webm", WEBM, "audio/webm")},
    )
    assert response.status_code == 404


def test_recording_cannot_be_attributed_to_another_question(use_fake):
    fake = use_fake()
    interview = _start()
    response = _transcribe(interview, question_id="q-9999")
    assert response.status_code == 400
    assert fake.calls == 0


def test_transcribe_is_rejected_for_inactive_interview(use_fake):
    from app.schemas.interview import InterviewStatus

    fake = use_fake()
    interview = _start()
    interview_engine.get_interview(interview["interview_id"]).status = InterviewStatus.COMPLETED
    response = _transcribe(interview)
    assert response.status_code == 409
    assert fake.calls == 0


def test_transcribe_is_rejected_after_the_question_was_answered(use_fake):
    fake = use_fake()
    interview = _start()
    client.post(
        f"/interview/{interview['interview_id']}/answer",
        json={"question_id": interview["current_question_id"], "answer_text": "Answered already."},
    )
    response = _transcribe(interview)
    assert response.status_code == 409
    assert fake.calls == 0


def test_health_still_works():
    assert client.get("/health").json() == {"status": "ok"}