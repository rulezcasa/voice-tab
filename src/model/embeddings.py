from src.model.sl_client import MODELS, Item, sie


def embed(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """bge-m3 dense vectors (1024 dims). One SIE call for the whole list."""
    res = sie.encode(MODELS["embed"], [Item(text=t) for t in texts], is_query=is_query)
    return [[float(x) for x in r["dense"]] for r in res]


def expense_embed_text(description: str, category: str, merchant: str | None) -> str:
    """Text that gets embedded for an expense: "tomato · groceries · Safeway"."""
    return " · ".join(p for p in (description, category, merchant) if p)
