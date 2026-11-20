"""JSON helpers that keep money exact."""
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def json_default(o: Any):
    if isinstance(o, Decimal):
        return str(o)  # keep exact cents, never float
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if hasattr(o, "model_dump"):  # pydantic models
        return o.model_dump()
    if isinstance(o, (set, tuple)):
        return list(o)
    return repr(o)


def to_json(v: Any) -> str | None:
    """None stays NULL; everything else becomes a JSON string."""
    return None if v is None else json.dumps(v, default=json_default)
