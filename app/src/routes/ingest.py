"""POST /api/ingest: audio or text in -> whisper -> agent -> what the UI shows (steps, reply, receipt, balances)."""
import asyncio
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.agents import agent
from src.core.expenses import ledger
from src.model import stt
from src.model.sl_client import MODELS

router = APIRouter(prefix="/api")

_WRITES = {"log_expense", "edit_expense", "record_settlement", "delete_expense"}


def _short(model: str) -> str:
    return model.split("/")[-1]


def _say(c: dict) -> str:
    """One plain-language progress line for a tool call."""
    r, a = c["result"], c["args"] if isinstance(c["args"], dict) else {}
    if not c["ok"]:
        return f"Hit a snag: {r}"
    e = (r or {}).get("expense") if isinstance(r, dict) else None
    match c["tool"]:
        case "query":
            return f"Searched your expenses for “{a['search']}”" if a.get("search") else "Looked it up"
        case "last_expense":
            return f"Found your last one: {r['description']}" if r else "No recent expense to change"
        case "log_expense":
            return f"Saved {e['description']} · ${e['amount']}"
        case "edit_expense":
            return f"Updated {e['description']} · ${e['amount']}"
        case "record_settlement":
            return f"Recorded: {e['description']}"
        case "delete_expense":
            return f"Removed {r['deleted']['description']}"
    return c["tool"]


def _steps(transcribe_ms: int | None, transcript: str, calls: list[dict]) -> list[dict]:
    steps = []
    if transcribe_ms is not None:
        steps.append({"step": "transcribe", "say": "Heard you", "model": _short(MODELS["stt"]),
                      "detail": transcript, "ms": transcribe_ms})
    for c in calls:
        if c["think_ms"]:
            steps.append({"step": "think", "say": "Worked out what to do", "model": _short(MODELS["generate"]),
                          "detail": c["tool"], "ms": c["think_ms"]})
        detail = c["args"].get("sql", "") if c["tool"] == "query" and isinstance(c["args"], dict) else str(c["args"])
        steps.append({"step": c["tool"], "say": _say(c), "model": "singlestore", "detail": detail, "ms": c["ms"]})
    return steps


def _receipt(calls: list[dict]) -> dict | None:
    """The card for the last expense the agent saved or changed, in the UI's Receipt shape."""
    for c in reversed(calls):
        if c["ok"] and c["tool"] in _WRITES - {"delete_expense"}:
            e = c["result"]["expense"]
            return {
                "description": e["description"], "amount": e["amount"], "category": e["category"],
                "group": e["group_name"], "spent_on": e["spent_on"], "logged_at": e["created_at"],
                "shares": [{k: s[k] for k in ("name", "is_me", "paid", "owed")} for s in e["shares"]],
            }
    return None


@router.post("/ingest")
async def ingest(
    audio: UploadFile | None = File(None), text: str | None = Form(None), session_id: str = Form("default"),
):
    """Voice (audio file) or typed text. Returns transcript, reply, steps, receipt and everyone's balances."""
    transcribe_ms = None
    if audio is not None:
        data = await audio.read()
        t = time.perf_counter()
        try:
            transcript = await asyncio.to_thread(stt.transcribe, data, stt.audio_format(audio.content_type, audio.filename))
        except Exception as e:
            raise HTTPException(502, f"transcription failed: {type(e).__name__}: {e}") from e
        transcribe_ms = int((time.perf_counter() - t) * 1000)
    else:
        transcript = (text or "").strip()

    if not transcript:
        return {"transcript": "", "reply": "I didn't catch that. Try again?", "steps": [], "receipt": None,
                "split_with": [], "asking": True, "people": ledger.balances()}

    try:
        out = await agent.run(session_id, transcript)
    except Exception as e:
        raise HTTPException(502, f"agent failed: {type(e).__name__}: {e}") from e

    receipt = _receipt(out["calls"])
    wrote = any(c["ok"] and c["tool"] in _WRITES for c in out["calls"])
    return {
        "transcript": transcript,
        "reply": out["reply"],
        "steps": _steps(transcribe_ms, transcript, out["calls"]),
        "receipt": receipt,
        "split_with": [s["name"] for s in receipt["shares"] if not s["is_me"]] if receipt else [],
        "asking": not wrote and out["reply"].rstrip().endswith("?"),
        "people": ledger.balances(),
    }


@router.post("/ingest/reset")
def reset(session_id: str = Form("default")):
    """Forget this session's conversation (a fresh start for clarifying questions)."""
    agent.reset(session_id)
    return {"ok": True}
