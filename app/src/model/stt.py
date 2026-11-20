"""Speech to text with whisper on SIE."""
from sie_sdk.types import AudioInput

from src.model.sl_client import MODELS, Item, sie

# Browser MediaRecorder mime types -> SIE audio format hints.
_FORMATS = {"webm": "webm", "ogg": "ogg", "mp4": "mp4", "m4a": "m4a", "mpeg": "mp3", "mp3": "mp3", "wav": "wav", "x-wav": "wav"}


def audio_format(content_type: str | None, filename: str | None = None) -> str:
    """'audio/webm;codecs=opus' -> 'webm'. Falls back to the file extension, then webm."""
    sub = (content_type or "").split(";")[0].split("/")[-1].strip().lower()
    if sub in _FORMATS:
        return _FORMATS[sub]
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return _FORMATS.get(ext, "webm")


def transcribe(audio: bytes, fmt: str) -> str:
    """Audio bytes -> transcript text ('' if nothing was said)."""
    r = sie.extract(MODELS["stt"], Item(audio=AudioInput(data=audio, format=fmt)))
    return ((r.get("data") or {}).get("text") or "").strip()
