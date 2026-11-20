"""Private agent links: each person opens their own agent on their own device with a secret link.

The link carries a token = person id + an HMAC signature, so it can't be guessed or edited to reach someone
else's agent, and nothing has to be stored. Tokens stay valid while AGENT_LINK_SECRET stays the same.
Hand each link only to its owner (python -m scripts.agent_links prints them).
"""
import base64
import hashlib
import hmac
import os

_DEV_SECRET = "keep-tab-dev-only-change-me"


def _secret() -> bytes:
    return (os.getenv("AGENT_LINK_SECRET") or _DEV_SECRET).encode()


def using_dev_secret() -> bool:
    return not os.getenv("AGENT_LINK_SECRET")


def _sig(person_id: int) -> str:
    mac = hmac.new(_secret(), f"agent:{person_id}".encode(), hashlib.sha256).digest()[:12]
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def token(person_id: int) -> str:
    return f"{person_id}.{_sig(person_id)}"


def person_from(tok: str) -> int | None:
    """The person id a token belongs to, or None if it's forged or malformed."""
    try:
        pid_s, sig = tok.split(".", 1)
        pid = int(pid_s)
    except (ValueError, AttributeError):
        return None
    return pid if hmac.compare_digest(sig, _sig(pid)) else None
