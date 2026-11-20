"""Read-only SQL for the agent's questions ("how much did I spend on cabs last month?")."""
import re
from datetime import date, datetime
from decimal import Decimal

from src.db.s2_client import cursor, to_vector
from src.model.embeddings import embed

MAX_ROWS = 200

_STRINGS = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"")
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|replace|merge|drop|alter|create|truncate|rename|grant|revoke|into|load|"
    r"call|set|lock|unlock|handler|do|sleep|benchmark|kill|outfile|dumpfile|attach|detach)\b",
    re.I,
)


class QueryError(ValueError):
    """The SQL was refused or failed. The message is safe to show the agent."""


def check(sql: str) -> str:
    """Return the statement if it is a single read-only SELECT, else raise QueryError."""
    sql = sql.strip().rstrip(";").strip()
    bare = _STRINGS.sub("''", sql)  # keywords inside string literals don't count
    if ";" in bare:
        raise QueryError("one statement only")
    if "--" in bare or "/*" in bare or "#" in bare:
        raise QueryError("no SQL comments")
    if not re.match(r"(select|with)\b", bare, re.I):
        raise QueryError("only SELECT queries are allowed")
    bad = _FORBIDDEN.search(bare)
    if bad:
        raise QueryError(f"'{bad.group(0)}' is not allowed in a read-only query")
    return sql


def _plain(v):
    if isinstance(v, Decimal):
        return f"{v:.2f}" if v == v.quantize(Decimal("0.01")) else str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return None
    return v


def _with_search(sql: str, search: str | None) -> tuple[str, list | None]:
    """Swap each :search for the bge-m3 vector of `search`, passed as a query parameter."""
    n = sql.count(":search")
    if search and not n:
        raise QueryError(
            "you passed `search` but the SQL never uses :search. Select the candidate rows "
            "(e.description, e.merchant, s.owed) with ORDER BY DOT_PRODUCT(e.embedding, :search) DESC LIMIT 5, "
            "no SUM; then add up the rows that really match yourself"
        )
    if not n:
        return sql, None
    if not search:
        raise QueryError("the SQL uses :search but no search text was given")
    try:
        vec = to_vector(embed([search], is_query=True)[0])
    except Exception as e:
        raise QueryError(f"couldn't embed the search text ({type(e).__name__})") from e
    # Parameters are %s-formatted, so literal % (LIKE '%x%', DATE_FORMAT) must be doubled first.
    return sql.replace("%", "%%").replace(":search", "(%s :> VECTOR(1024))"), [vec] * n


def run(sql: str, search: str | None = None) -> dict:
    """Run a checked SELECT as the read-only user. :search in the SQL becomes the vector of `search`."""
    sql, params = _with_search(check(sql), search)
    try:
        with cursor(readonly=True) as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description or []]
            rows = cur.fetchmany(MAX_ROWS + 1)
    except Exception as e:
        raise QueryError(f"{type(e).__name__}: {e}") from e
    keep = [i for i, c in enumerate(cols) if c.lower() != "embedding"]
    return {
        "columns": [cols[i] for i in keep],
        "rows": [[_plain(r[i]) for i in keep] for r in rows[:MAX_ROWS]],
        "truncated": len(rows) > MAX_ROWS,
    }
