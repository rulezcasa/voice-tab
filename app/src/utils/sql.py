"""Helpers for reading query results."""
import json


def rows_as_dicts(cur, json_cols: tuple[str, ...] = ()) -> list[dict]:
    """Fetch all rows as dicts; parse the named JSON columns if they came back as strings."""
    names = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        row = dict(zip(names, r))
        for k in json_cols:
            if isinstance(row.get(k), str):
                row[k] = json.loads(row[k])
        out.append(row)
    return out
