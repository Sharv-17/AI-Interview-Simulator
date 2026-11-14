"""Validation of uploaded audio (size and real content type).

Filenames and the declared MIME type are NOT trusted: the container format is
identified from the file's leading bytes ("magic bytes"). This proves the file
LOOKS like a supported container; it does not prove the audio decodes. Decoding
problems are reported later by the transcription step as `unreadable_audio`.
"""

from typing import BinaryIO, Optional

from app import config
from app.services.transcription_errors import (
    AudioTooLargeError,
    EmptyAudioError,
    UnsupportedAudioFormatError,
)

_CHUNK_BYTES = 64 * 1024


def read_upload_limited(file: BinaryIO, max_bytes: Optional[int] = None) -> bytes:
    """Read an upload fully, but stop as soon as it exceeds the size limit.

    Reads in chunks so an oversized file is never loaded into memory whole.
    """
    limit = config.MAX_AUDIO_UPLOAD_BYTES if max_bytes is None else max_bytes
    chunks = []
    total = 0
    while True:
        chunk = file.read(_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AudioTooLargeError()
        chunks.append(chunk)
    return b"".join(chunks)


def detect_audio_format(data: bytes) -> Optional[str]:
    """Return 'webm', 'ogg', 'wav', 'mp4', 'mp3', or None if unrecognised."""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"  # EBML header (WebM / Matroska)
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[4:8] == b"ftyp":
        return "mp4"  # MP4 / M4A
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


def validate_audio(data: bytes) -> str:
    """Return the detected format, or raise a typed error for empty/unsupported audio."""
    if len(data) == 0:
        raise EmptyAudioError()
    audio_format = detect_audio_format(data)
    if audio_format is None:
        raise UnsupportedAudioFormatError()
    return audio_format