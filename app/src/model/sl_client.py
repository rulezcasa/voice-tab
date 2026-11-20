"""Superlinked SIE connection: the one place the app talks to the models."""
from sie_sdk import Item, SIEClient  # noqa: F401  (Item re-exported for callers)

from src import config

MODELS = {
    "stt": "openai/whisper-large-v3-turbo",
    "embed": "BAAI/bge-m3",
    "generate": "Qwen/Qwen3.5-4B",
}

sie = SIEClient(config.SL_BASE_URL, api_key=config.SL_API_KEY, remote="forbid", timeout_s=600)
