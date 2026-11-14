"""Typed errors for the voice-answer flow.

Every error carries a stable machine-readable `code`, an HTTP status and a
SAFE human message. Raw provider exceptions, file paths and tracebacks are
never put in these messages; the API layer sends only code + message.
"""


class VoiceInputError(Exception):
    """Base class: a voice-answer problem that maps cleanly to an HTTP error."""

    code = "voice_error"
    status_code = 400
    message = "The audio could not be processed."

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


# --- Problems with the uploaded audio itself --------------------------------


class EmptyAudioError(VoiceInputError):
    code = "empty_audio"
    status_code = 400
    message = "The uploaded audio is empty."


class AudioTooLargeError(VoiceInputError):
    code = "audio_too_large"
    status_code = 413
    message = "The uploaded audio is larger than the allowed size."


class UnsupportedAudioFormatError(VoiceInputError):
    code = "unsupported_audio_format"
    status_code = 415
    message = "Unsupported audio format. Supported: WebM, Ogg, MP4/M4A, WAV, MP3."


class UnreadableAudioError(VoiceInputError):
    code = "unreadable_audio"
    status_code = 422
    message = "The audio could not be read. It may be corrupted; please record again."


class AudioTooLongError(VoiceInputError):
    code = "audio_too_long"
    status_code = 422
    message = "The recording is longer than the allowed maximum."


class NoSpeechDetectedError(VoiceInputError):
    code = "no_speech_detected"
    status_code = 422
    message = "No speech was detected. Please try again, or type your answer."


# --- Problems with the transcription service --------------------------------


class TranscriptionUnavailableError(VoiceInputError):
    code = "transcription_unavailable"
    status_code = 503
    message = "Speech-to-text is not available on the server right now."


class TranscriptionTimeoutError(VoiceInputError):
    code = "transcription_timeout"
    status_code = 504
    message = "Transcription took too long. Please try again, or type your answer."


class TranscriptionFailedError(VoiceInputError):
    code = "transcription_failed"
    status_code = 502
    message = "Transcription failed. Please try again, or type your answer."