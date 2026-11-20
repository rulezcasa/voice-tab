"""The agent loop: Qwen on SIE reads what the user said and calls the MCP tools until it can answer."""
import asyncio
import json
import time

from src.agents.prompts import system_prompt
from src.mcp.server import mcp
from src.model.sl_client import MODELS, sie

MAX_ROUNDS = 5     # model calls per utterance
KEEP_TURNS = 3     # past user turns kept per session (enough to answer a clarifying question)

_sessions: dict[str, list[dict]] = {}  # session_id -> chat history (no system prompt); lost on restart


def _trim(history: list[dict]) -> list[dict]:
    """Keep the last KEEP_TURNS user turns, cutting only at a user message so tool calls stay paired."""
    starts = [i for i, m in enumerate(history) if m["role"] == "user"]
    return history[starts[-KEEP_TURNS]:] if len(starts) > KEEP_TURNS else history


async def _tools() -> list[dict]:
    return [
        {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
        for t in await mcp.list_tools()
    ]


async def _call(name: str, raw_args: str) -> tuple[dict | list | str | None, bool]:
    """Run one MCP tool. Returns (parsed result or error text, ok)."""
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return f"arguments were not valid JSON: {raw_args}", False
    try:
        r = await mcp.call_tool(name, args)  # in-process, tool errors raise instead of returning is_error
    except Exception as e:
        return str(e).removeprefix(f"Error executing tool {name}: "), False
    text = r.content[0].text if r.content else ""
    if r.is_error:
        return text.removeprefix(f"Error executing tool {name}: "), False
    try:
        return json.loads(text) if text else None, True
    except json.JSONDecodeError:
        return text, True


async def run(session_id: str, text: str) -> dict:
    """One utterance in, the agent's reply out, with every tool call it made."""
    history = _trim(_sessions.get(session_id, []) + [{"role": "user", "content": text}])
    tools = await _tools()
    calls: list[dict] = []
    reply = ""

    for _ in range(MAX_ROUNDS):
        messages = [{"role": "system", "content": system_prompt()}] + history
        t = time.perf_counter()
        resp = await asyncio.to_thread(
            sie.chat_completions, MODELS["generate"], messages, tools=tools, temperature=0, max_tokens=800,
        )
        think_ms = int((time.perf_counter() - t) * 1000)
        msg = resp["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []
        history.append({"role": "assistant", "content": msg.get("content"), **({"tool_calls": tool_calls} if tool_calls else {})})

        if not tool_calls:
            reply = (msg.get("content") or "").strip()
            break

        for tc in tool_calls:
            name, raw = tc["function"]["name"], tc["function"].get("arguments") or "{}"
            t = time.perf_counter()
            result, ok = await _call(name, raw)
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = raw
            calls.append({
                "tool": name, "args": args, "ok": ok, "result": result,
                "think_ms": think_ms, "ms": int((time.perf_counter() - t) * 1000),
            })
            think_ms = 0  # one model call can make several tool calls; count its time once
            content = json.dumps(result) if ok else f"ERROR: {result}"
            history.append({"role": "tool", "tool_call_id": tc["id"], "content": content})
    else:
        reply = "Sorry, I got stuck on that one. Try saying it another way?"

    _sessions[session_id] = _trim(history)
    return {"reply": reply, "calls": calls}


def reset(session_id: str) -> None:
    _sessions.pop(session_id, None)
