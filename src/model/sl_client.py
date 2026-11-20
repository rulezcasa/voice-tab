"""Superlinked SIE connection: the one place the app talks to the models.

Usage:
    from src.model.sl_client import sie, MODELS
    sie.extract(MODELS["extract"], Item(text="..."), labels=[...])

remote="forbid" disables SIE Relay, so requests are never forwarded to a partner
provider (voice clips and expense text stay with SIE).
"""
from sie_sdk import Item, SIEClient  # noqa: F401  (Item re-exported for callers)

from src import config

MODELS = {
    "stt": "openai/whisper-large-v3-turbo",
    "classify": "knowledgator/gliclass-instruct-large-v1.0",
    "extract": "fastino/gliner2-large-v1",
    "embed": "BAAI/bge-m3",
    "rerank": "Qwen/Qwen3-Reranker-0.6B",
    "generate": "Qwen/Qwen3.5-4B",
}

sie = SIEClient(config.SL_BASE_URL, api_key=config.SL_API_KEY, remote="forbid", timeout_s=600)
