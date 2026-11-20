"""Live check: does Qwen fill `when` so the code lands on the right date? One model call per case.

Tools are NOT executed: we read the first tool call Qwen makes, resolve its `when`, and compare.
Nothing is written to the database (the system prompt only reads people and groups).

Run from app/:  python -m tests.live_dates
"""
import asyncio
import json
from datetime import timedelta

from src.agents.agent import _tools
from src.agents.prompts import system_prompt
from src.core import dates
from src.core.expenses import ledger
from src.model.sl_client import MODELS, sie

T = ledger.today()
MON = T - timedelta(days=T.weekday())


def wd(i: int, weeks_back: int = 0):
    """Expected weekday i (0 = Monday): most recent past one, or the one in a previous Mon-Sun week."""
    if weeks_back:
        return MON - timedelta(weeks=weeks_back) + timedelta(days=i)
    return T - timedelta(days=(T.weekday() - i) % 7 or 7)


first_of_month = T.replace(day=1)
last_month_end = first_of_month - timedelta(days=1)

CASES = [  # (what the user says, expected (start, end))
    ("I spent 10 dollars on Uber, last week wednesday", (wd(2, 1),) * 2),
    ("Paid 25 for lunch 10 days ago", (T - timedelta(days=10),) * 2),
    ("Spent 40 on groceries twenty days back", (T - timedelta(days=20),) * 2),
    ("Coffee was 6 bucks yesterday", (T - timedelta(days=1),) * 2),
    ("I bought a 15 dollar movie ticket on Monday", (wd(0),) * 2),
    ("Spent 30 on gas two weeks ago", (T - timedelta(weeks=2),) * 2),
    ("Paid 12 for parking on the 3rd", ((T.replace(day=3) if T.day >= 3 else None),) * 2),
    ("Dinner was 60 on October 28", ((T.replace(month=10, day=28)),) * 2),
    ("How much did I spend last month?", (last_month_end.replace(day=1), last_month_end)),
    ("What did I spend in the past 10 days?", (T - timedelta(days=9), T)),
]


async def main():
    tools = await _tools()
    system = system_prompt()
    passed = 0
    print(f"today = {T} ({dates.say(T)})\n")
    for i, (said, want) in enumerate(CASES, 1):
        resp = await asyncio.to_thread(
            sie.chat_completions, MODELS["generate"],
            [{"role": "system", "content": system}, {"role": "user", "content": said}],
            tools=tools, temperature=0, max_tokens=800,
        )
        msg = resp["choices"][0]["message"]
        call = next(iter(msg.get("tool_calls") or []), None)
        if not call:
            got, when, tool = "no tool call: " + (msg.get("content") or "")[:80], None, "-"
        else:
            tool = call["function"]["name"]
            args = json.loads(call["function"].get("arguments") or "{}")
            when = args.get("when")
            try:
                got = dates.resolve(when, T)
            except Exception as e:
                got = f"error: {e}"
        ok = got == want
        passed += ok
        show = lambda r: r if isinstance(r, str) else (str(r[0]) if r[0] == r[1] else f"{r[0]} .. {r[1]}")
        print(f"{i:2}. {'PASS' if ok else 'FAIL'}  “{said}”")
        print(f"      tool={tool}  when={json.dumps(when)}  got={show(got)}  want={show(want)}")
    print(f"\n{passed} passed, {len(CASES) - passed} failed, {len(CASES)} model calls")


if __name__ == "__main__":
    asyncio.run(main())
