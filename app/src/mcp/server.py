"""Tab's MCP server: ledger writes as tools, questions as read-only SQL, context in the system prompt."""
import functools
import json
import re
from datetime import date, timedelta

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src.core import directory, query
from src.core.expenses import ledger
from src.core.expenses.categories import MODEL_CATEGORIES
from src.core.expenses.category import classify

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

SCHEMA = """\
people(id, name, is_me BOOLEAN, aliases JSON)
groups_(id, name, aliases JSON)
group_members(group_id, person_id)
expenses(id, created_at DATETIME, spent_on DATE, amount DECIMAL(10,2), currency CHAR(3), description,
         merchant, category, group_id NULL, status, is_demo BOOLEAN)
expense_shares(expense_id, person_id, paid DECIMAL(10,2), owed DECIMAL(10,2))
balances(person_id, name, net)   -- view: SUM(paid - owed); positive = is owed, negative = owes

- Every expense has share rows, personal ones too. A person's spending is SUM(owed) from expense_shares.
- category = 'settlement' rows are repayments: exclude them from spending, never from balances.
- is_demo rows are seeded sample history; include them.
- expenses.embedding is the meaning of "description · category · merchant". Never select it; only use it as
  DOT_PRODUCT(e.embedding, :search) to rank rows, passing the words to match in the `search` argument.
- Write dates as 'YYYY-MM-DD' literals worked out from today's date. Never use CURDATE(), NOW()
  or CURRENT_DATE: the database clock is UTC, not the user's time zone.
- Amounts the user mentions ("spent 30") mean expenses.amount, not their share.
- "Yesterday", "last week" etc. mean when the money was spent: filter on spent_on, never created_at
  (created_at is only when it was logged; something from yesterday may be logged today)."""

def examples(today: date) -> str:
    """Example questions with SQL, using literal dates worked out from the user's today."""
    this_month = today.replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    monday = today - timedelta(days=today.weekday())
    return f"""\
Q: how much did I spend on cabs last month?
SELECT SUM(s.owed) FROM expense_shares s JOIN expenses e ON e.id = s.expense_id JOIN people p ON p.id = s.person_id
WHERE p.is_me AND e.category = 'transport' AND e.spent_on >= '{last_month}' AND e.spent_on < '{this_month}'

Q: how much did I spend on uber yesterday?
search = "uber"
SELECT e.description, e.merchant, s.owed, DOT_PRODUCT(e.embedding, :search) AS score FROM expenses e
JOIN expense_shares s ON s.expense_id = e.id JOIN people p ON p.id = s.person_id AND p.is_me
WHERE e.spent_on = '{today - timedelta(days=1)}' AND e.category <> 'settlement' ORDER BY score DESC LIMIT 5
(Then keep only the rows that really are Uber and add up their owed. No matching row means $0.)

Q: what did I spend 30 on yesterday?
SELECT e.description, e.merchant, e.amount FROM expenses e
JOIN expense_shares s ON s.expense_id = e.id JOIN people p ON p.id = s.person_id AND p.is_me
WHERE e.spent_on = '{today - timedelta(days=1)}' AND e.amount = 30 AND e.category <> 'settlement'

Q: what did Sam and I split this week?
SELECT e.spent_on, e.description, e.amount FROM expenses e
JOIN expense_shares a ON a.expense_id = e.id JOIN people pa ON pa.id = a.person_id AND pa.is_me
JOIN expense_shares b ON b.expense_id = e.id JOIN people pb ON pb.id = b.person_id AND pb.name = 'Sam'
WHERE e.category <> 'settlement' AND e.spent_on >= '{monday}' ORDER BY e.spent_on

Q: who owes me?
SELECT b.name, b.net FROM balances b JOIN people p ON p.id = b.person_id
WHERE NOT p.is_me AND b.net < 0 ORDER BY b.net"""


def system_prompt() -> str:
    """Everything the agent needs up front: rules, today's date, schema, categories, people and groups."""
    people = [{k: p[k] for k in ("id", "name", "is_me", "aliases")} for p in directory.people()]
    groups = [{k: g[k] for k in ("id", "name", "aliases", "member_ids")} for g in directory.groups()]
    cats = "\n".join(f"- {c}: {d}" for c, d in MODEL_CATEGORIES.items())
    return f"""You are Tab, a voice expense ledger. Turn what the user says into tool calls, then answer in one short sentence.

Today is {ledger.today().isoformat()}.

Rules
- Recording, changing or undoing money goes through log_expense, edit_expense, record_settlement and delete_expense. Never write SQL for that.
- Questions about spending, history or balances: write one SELECT for the `query` tool.
- Questions about a kind of thing or a place ("uber", "coffee", "stuff for the apartment"): filter in WHERE first
  (dates, me), then rank with `search` and ORDER BY DOT_PRODUCT(e.embedding, :search) DESC LIMIT 5. The top rows
  are candidates, not answers: keep only the ones that match, then add them up yourself.
- Use person and group ids from the lists below. If a name matches more than one person, or nobody, ask instead of guessing.
- `description` is what was bought, in a few words ("groceries", "Uber to the office"), never the user's sentence.
  If the user didn't say what it was for ("I spent 20 yesterday"), call no tool: reply exactly
  "What should I log this for?" and log it, with everything they said before, once they answer.
- "Split with Sam" means Sam and me both owe a share (participant_ids includes me). "I paid for Sam" means only Sam owes.
- A group name ("roommates") means all of its member_ids as participant_ids, and its id as group_id.
- Dates: work out the actual date from today's date and pass it as `spent_on` (YYYY-MM-DD); leave it out for today.
- Leave `category` out unless it is obvious; the ledger picks one. Never use 'settlement'; use record_settlement.
- Corrections ("actually it was 45") call last_expense, then edit_expense on that id.
- Money comes back as strings. Balances: positive = is owed, negative = owes.

Schema
{SCHEMA}

Example queries
{examples(ledger.today())}

Categories
{cats}

People
{json.dumps(people)}

Groups
{json.dumps(groups)}
"""


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
