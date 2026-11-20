"""Are the SIE models reachable?   python -m scripts.check_sie"""
import time

from src.model.embeddings import embed
from src.model.sl_client import MODELS, sie


def timed(label, fn):
    t = time.perf_counter()
    try:
        out = fn()
        print(f"  ok   {label:<34} {int((time.perf_counter() - t) * 1000):>6} ms  {out}")
        return True
    except Exception as e:
        print(f"  FAIL {label:<34} {int((time.perf_counter() - t) * 1000):>6} ms  {type(e).__name__}: {e}")
        return False


def main() -> None:
    ok = timed(f"embed ({MODELS['embed']})", lambda: f"{len(embed(['test'])[0])} dims")
    ok &= timed(f"chat ({MODELS['generate']})", lambda: repr(sie.chat_completions(
        MODELS["generate"], [{"role": "user", "content": "Say hi in one word."}], max_tokens=10, temperature=0,
    )["choices"][0]["message"].get("content")))
    ok &= timed(f"metadata ({MODELS['stt']})", lambda: "found" if sie.get_model(MODELS["stt"]) else "missing")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
