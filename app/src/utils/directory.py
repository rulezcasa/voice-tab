"""People and groups, so names the user says can be turned into ids."""
from src.db.s2_client import cursor
from src.utils.query import rows_as_dicts


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
