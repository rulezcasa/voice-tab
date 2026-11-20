"""Tab's MCP server: ledger writes as tools, questions as read-only SQL, context in the system prompt."""
import functools
import re
from datetime import date

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src.agents.prompts import system_prompt
from src.core.expenses import ledger
from src.core.expenses.category import classify
from src.utils import query

mcp = MCPServer("tab", instructions="Voice expense ledger. Load the `system` prompt before calling tools.")


def tool(**kw):
    """mcp.tool() that passes ledger and query error messages (safe to show) back to the agent."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (ledger.LedgerError, query.QueryError) as e:
                raise ToolError(str(e)) from e
        return mcp.tool(**kw)(wrapped)
    return deco


def _category(description: str, merchant: str | None) -> str:
    """Nearest fixed category by embedding; 'other' if the model is unreachable."""
    try:
        return classify(" ".join(p for p in (description, merchant) if p))[0]
    except Exception:
        return "other"


# ---------- system prompt (loaded once per conversation, not a tool call) ----------

@mcp.prompt(name="system")
def system() -> str:
    """Tab's system prompt with today's date, schema, categories, people and groups."""
    return system_prompt()


# ---------- questions ----------

@tool(name="query")
def query_ledger(sql: str, search: str | None = None) -> dict:
    """Run one read-only SELECT against the ledger (schema in the system prompt). Returns columns and up to 200 rows. To rank by meaning, pass `search` (e.g. "uber") and use DOT_PRODUCT(e.embedding, :search) in the SQL."""
    return query.run(sql, search)


@tool()
def last_expense() -> dict | None:
    """The expense a correction like 'actually it was 45' refers to."""
    return ledger.last_expense()


# ---------- writes ----------

# A description that is really the spoken sentence ("I spent $20 yesterday"): money, digits, or spend verbs.
_NOT_A_DESCRIPTION = re.compile(r"[$€£₹\d]|\b(spent|spend|paid|bucks|dollars?|expense)\b", re.I)

@tool()
def log_expense(
    amount: str, description: str, category: str | None = None, merchant: str | None = None,
    spent_on: date | None = None, payer_id: int | None = None, participant_ids: list[int] | None = None,
    custom: dict[int, str] | None = None, group_id: int | None = None, currency: str | None = None,
) -> dict:
    """Save a purchase. Defaults: I paid, only I owe, today, category picked from the description. participant_ids = everyone who owes a share (include me if I'm in on it); custom = {person_id: exact owed} for uneven splits."""
    if _NOT_A_DESCRIPTION.search(description or ""):
        raise ledger.LedgerError(
            f"'{description}' is the user's sentence, not what was bought. Don't log yet: "
            "reply \"What should I log this for?\" and log it once they answer"
        )
    return ledger.create_expense(
        amount=amount, description=description, category=category or _category(description, merchant),
        merchant=merchant, spent_on=spent_on, payer_id=payer_id, participant_ids=participant_ids,
        custom=custom, group_id=group_id, currency=currency,
    )


@tool()
def edit_expense(
    expense_id: int, amount: str | None = None, description: str | None = None,
    category: str | None = None, merchant: str | None = None, spent_on: date | None = None,
    payer_id: int | None = None, participant_ids: list[int] | None = None,
    custom: dict[int, str] | None = None, group_id: int | None = None,
) -> dict:
    """Change an expense; omitted fields keep their value. Shares are rebuilt when amount, payer or people change."""
    return ledger.update_expense(
        expense_id, amount=amount, description=description, category=category, merchant=merchant,
        spent_on=spent_on, payer_id=payer_id, participant_ids=participant_ids, custom=custom,
        group_id=group_id,
    )


@tool()
def record_settlement(
    amount: str, from_id: int, to_id: int | None = None, group_id: int | None = None, spent_on: date | None = None,
) -> dict:
    """from_id paid to_id (default: me) back, e.g. 'Sam paid me back 13.33'."""
    return ledger.record_settlement(
        amount=amount, from_id=from_id, to_id=to_id, group_id=group_id, spent_on=spent_on,
    )


@tool()
def delete_expense(expense_id: int) -> dict:
    """Undo: remove an expense and its shares. Returns what was deleted and the new balances."""
    return ledger.delete_expense(expense_id)


if __name__ == "__main__":
    mcp.run()  # stdio: python -m src.mcp.server (from app/)
