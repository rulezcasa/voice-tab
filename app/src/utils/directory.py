"""People and groups, so names the user says can be turned into ids."""
import json

from src.db.s2_client import cursor, to_vector, transaction
from src.model.embeddings import embed
from src.utils.query import rows_as_dicts


class DirectoryError(ValueError):
    """Bad input for a person or group. The message is safe to show the user."""


def people() -> list[dict]:
    """Everyone (me first) with id, name, is_me and aliases."""
    with cursor() as cur:
        cur.execute("SELECT id, name, is_me, aliases FROM people ORDER BY is_me DESC, name")
        rows = rows_as_dicts(cur, json_cols=("aliases",))
    for r in rows:
        r["is_me"] = bool(r["is_me"])
        r["aliases"] = r["aliases"] or []
    return rows


def groups() -> list[dict]:
    """Every group with id, name, aliases and member person ids."""
    with cursor() as cur:
        cur.execute("SELECT id, name, aliases FROM groups_ ORDER BY name")
        rows = rows_as_dicts(cur, json_cols=("aliases",))
        cur.execute("SELECT group_id, person_id FROM group_members")
        members: dict[int, list[int]] = {}
        for gid, pid in cur.fetchall():
            members.setdefault(gid, []).append(pid)
    for r in rows:
        r["aliases"] = r["aliases"] or []
        r["member_ids"] = members.get(r["id"], [])
    return rows


def create_group(name: str, member_ids: list[int], aliases: list[str] | None = None) -> dict:
    """New group with these members. I am always a member. Returns it like groups() does."""
    name = (name or "").strip()
    if not name:
        raise DirectoryError("group needs a name")
    aliases = [a.strip() for a in (aliases or []) if a and a.strip()]
    try:  # same idea as people: embed name + aliases so spoken names can match; NULL if SIE is down
        vec = to_vector(embed([" · ".join([name, *aliases])])[0])
    except Exception:
        vec = None

    with transaction() as cur:
        cur.execute("SELECT id FROM groups_ WHERE LOWER(name) = LOWER(%s)", (name,))
        if cur.fetchone():
            raise DirectoryError(f"a group called {name!r} already exists")
        cur.execute("SELECT id FROM people WHERE is_me LIMIT 1")
        me = cur.fetchone()
        ids = list(dict.fromkeys([*([me[0]] if me else []), *member_ids]))
        if ids:
            cur.execute(f"SELECT id FROM people WHERE id IN ({','.join(['%s'] * len(ids))})", ids)
            missing = set(ids) - {r[0] for r in cur.fetchall()}
            if missing:
                raise DirectoryError(f"unknown person id(s): {sorted(missing)}")
        cur.execute(
            "INSERT INTO groups_ (name, aliases, embedding) VALUES (%s, %s, %s)",
            (name, json.dumps(aliases), vec),
        )
        gid = cur.lastrowid
        if ids:
            cur.executemany("INSERT INTO group_members (group_id, person_id) VALUES (%s, %s)", [(gid, i) for i in ids])
    return {"id": gid, "name": name, "aliases": aliases, "member_ids": ids}
