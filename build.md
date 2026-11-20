# Tab — build plan (One day hackathon)

- This is a tentative build plan, changes can be made to this as we build.
- The goal is make a functioning product and any advanced features can be moved out of scope.
- One key standout point is the UI - it shouldnt a generic webapp demo, make the UI creative and give it a real ambient agent kind of a feel.

---

## 1. Architecture

```
 ┌──────────────┐   audio/text    ┌──────────────────────── FastAPI ─────────────────────────┐
 │ Trigger agent│ ──────────────▶ │ /ingest                                                  │
 │   (TBD)      │                 │  1 transcribe ─▶ 2 agent (system prompt: schema, people, │
 └──────────────┘                 │                  groups, categories, today) ─▶ tools:    │
        ▲                         │                                                          │
        │ answer / question       │   LOG / EDIT / SETTLE / UNDO ─▶ ledger tools (MCP)       │
        └──────────────────────── │       log_expense · edit_expense · record_settlement ·   │
                                  │       delete_expense · last_expense                      │
                                  │   QUERY ─▶ `query` tool: one read-only SELECT            │
                                  └──────────────┬──────────────────────────────┬────────────┘
                                                 │                              │
                                      Superlinked SIE (models)         SingleStore (people, groups,
                                      whisper · bge-m3 · qwen          expenses, shares,
                                                                       vectors + full-text)
```

**Design rules**
- **The agent decides, code does the math.** The agent picks the tool and fills its fields; money math and balances are deterministic Python.
- **Never guess a person or an amount.** Low confidence or ambiguity means a clarifying question, not a guess.
- **We own the ledger.** No Splitwise or other outside expense service. Expenses, shares and balances live in our own SingleStore tables.
- **Writes go through the ledger, reads are SQL.** The agent changes money only via the ledger tools (they keep shares exact); questions are answered with one read-only SELECT (`SS_READONLY_USER`, SELECT-only check).
- **No audit trail for now.** Add it back once the app works end to end.

---

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python, FastAPI, `pydantic`, `mcp` | Fast to build; SIE has a Python SDK |
| Inference | `sie-sdk` (SIE Serverless) | Sponsor; one API for all the small models |
| DB | `singlestoredb` Python client | Sponsor; SQL + vector + full-text in one place |
| Money | `decimal.Decimal` | No float rounding errors |
| Frontend | Ambient agent like interactive UI with phone responiveness | No build step |


`.env`
```
SL_BASE_URL=...
SL_API_KEY=...
SS_HOST=...  SS_PORT=3306  SS_USER=...  SS_PASSWORD=...  SS_DATABASE=tab
TZ=America/Los_Angeles
```

**Code layout**
```
webapp/                  # PWA: Vite + React + TS. cd webapp && npm run dev (dummy data for now)
app/                     # backend. Run from here: cd app && fastapi dev main.py
  .env                   # backend config (copy from .env.example)
  requirements.txt
  main.py                  # FastAPI entry point: app, startup/shutdown, mounts routes
  src/
    config.py              # reads .env
    routes/
      api.py               # all HTTP endpoints (APIRouter); logic stays in core/
    db/
      s2_client.py         # ONLY place that connects to SingleStore: cursor(), transaction(), to_vector()
      schema.sql
    model/
      sl_client.py         # ONLY place that creates the SIE client + model IDs (Relay off)
      embeddings.py        # embed(), expense_embed_text()
    core/
      directory.py         # people and groups (for the system prompt)
      query.py             # read-only SELECT check + run (text-to-SQL)
      expenses/
        ledger.py          # the only code that writes expenses and shares
        splits.py          # who paid / who owes
        categories.py      # fixed category list
        category.py        # classify(): nearest category by bge-m3
    mcp/server.py          # MCP: ledger tools + `query` tool + `system` prompt; mounted at /mcp
    utils/                 # shared helpers: sql.py (rows -> dicts)
  scripts/                 # check_s2, check_sie, seed  (run as: python -m scripts.<name>)
```
Rule: nothing outside `app/src/db/s2_client.py` and `app/src/model/sl_client.py` opens its own database or SIE connection.

---

## 3. Data model (SingleStore)


```sql
CREATE TABLE people (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(100),
  is_me         BOOLEAN DEFAULT FALSE,      -- the account owner
  aliases       JSON,                       -- ["Sammy","S"]
  embedding     VECTOR(1024)
);

CREATE TABLE groups_ (
  id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
  name               VARCHAR(100),          -- "Apt 4B"
  aliases            JSON,                  -- ["roommates","roomies","flatmates","the apartment"]
  embedding          VECTOR(1024)
);

CREATE TABLE group_members (group_id BIGINT, person_id BIGINT, PRIMARY KEY (group_id, person_id));

CREATE TABLE expenses (
  id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at            DATETIME DEFAULT NOW(),
  spent_on              DATE,
  amount                DECIMAL(10,2),
  currency              CHAR(3) DEFAULT 'USD',
  description           VARCHAR(255),
  merchant              VARCHAR(120),
  category              VARCHAR(40),    -- one of the fixed categories below; 'settlement' = a repayment
  group_id              BIGINT NULL,        -- NULL = personal
  status                VARCHAR(20),        -- logged | needs_clarification | failed
  embedding             VECTOR(1024),
  FULLTEXT USING VERSION 2 (description, merchant)
);

CREATE TABLE expense_shares (
  expense_id BIGINT, person_id BIGINT, paid DECIMAL(10,2), owed DECIMAL(10,2),
  PRIMARY KEY (expense_id, person_id)
);

-- Balances are computed, not stored: SUM(paid - owed) per person from expense_shares.
-- Positive = they are owed money, negative = they owe.
CREATE VIEW balances AS
  SELECT person_id, SUM(paid - owed) AS net
  FROM expense_shares GROUP BY person_id;
-- Settlements are included here on purpose: they are what bring a balance back to 0.
-- Spending totals ("how much did I spend...") must filter out category = 'settlement'.


```

**Seed script** (`seed.py`):
- Insert yourself (`is_me = TRUE`), the teammates and two Alexes (Chen, Park) into `people`, with aliases and embeddings.
- Insert group "Apt 4B" 
- Insert about 30 **demo** expenses over the past 3 weeks so recall queries have data. Include a $20 cab last Wednesday and a few Uber/Lyft rides. Label them as demo data.

### Categories (fixed list)

The agent may pass a category; if it doesn't, the ledger picks the nearest one from this list by bge-m3 similarity. Python checks the label is in the list.

| Category | Covers |
|---|---|
| `groceries` | Supermarket, Costco, Trader Joe's |
| `dining` | Restaurants, takeout, coffee, bars |
| `transport` | Cabs, Uber/Lyft, transit, gas, parking |
| `rent` | Rent, deposits |
| `utilities` | Electricity, water, internet, phone |
| `household` | Cleaning supplies, furniture, repairs |
| `shopping` | Clothes, electronics, general purchases |
| `entertainment` | Movies, concerts, games, events |
| `travel` | Flights, hotels, Airbnb |
| `health` | Pharmacy, doctor, gym |
| `subscriptions` | Netflix, Spotify, software |
| `other` | Fallback when no category is close enough |
| `settlement` | **Set by code only, never by the model.** A repayment between people |

### Settlements (no extra table)

"Sam paid me back 13.33" is stored as a normal expense with `category = 'settlement'`:
- `expenses`: amount 13.33, description "Sam paid me back", `group_id` of the shared group.
- `expense_shares`: Sam `paid = 13.33, owed = 0`; me `paid = 0, owed = 13.33`.

Sam's balance goes back to 0, the original expense and everyone else's shares stay untouched, and there's a dated record of the repayment. Spending totals exclude `settlement`; balances include it.

---

## 4. The pipeline, step by step

### Step 1: Voice/test input (suitable SIE model)
- The client proceses voice or text input.
- The agent decides what to do from the `system` prompt (schema, people, groups, categories, today's date) and calls tools on the MCP server (`app/src/mcp/server.py`):
  - log an expense → `log_expense`; correct the last one → `last_expense` + `edit_expense`; "Sam paid me back" → `record_settlement`; undo → `delete_expense`
  - ask about past spending or balances → `query` with one read-only SELECT (text-to-SQL)
- Category: the agent may pass one; if it doesn't, `log_expense` picks the nearest fixed category (see §3) by embedding. Below the threshold → `other`.
- Dates: the agent works out the date from today's date in the system prompt and passes `spent_on` as YYYY-MM-DD.
- Fields the agent fills for `log_expense`:
```json
{
  "amount": "number",
  "currency": "string",
  "description": "string",
  "merchant": "string",
  "date_phrase": "string",
  "split_with": ["string"],
  "split_type": "equal | custom | none",
  "custom_shares": [{"who": "string", "share": "string"}]
}
```

### Step 2: Resolve people and groups 
For each `split_with` phrase:
1. Exact\Regex or alias match in SQL (`JSON_ARRAY_CONTAINS_STRING(aliases, ?)` or a name match).
3. A group expands to its members via `group_members`.
4. **More than one candidate above the threshold** (two Alexes) → keep the half-built expense in session state and return "Alex Chen or Alex Park?"
5. **If not sure** → ask "Who's Jordan? Not in your contacts."

Default: "split with X" **includes me** as an equal participant.

**Clarifying questions live in memory, not the database.** The question and the answer happen in the same session, but they arrive as two separate requests. The server keeps a dict `sessions[session_id] = {draft_expense, open_question}`. The next message in that session answers the question, the draft is completed and saved, and the entry is cleared. A server restart loses an unanswered question, which is acceptable for the demo.

### Step 3: Math (pure Python)
```python
from decimal import Decimal, ROUND_DOWN
def equal_split(total: Decimal, n: int) -> list[Decimal]:
    base = (total / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    rem = int((total - base * n) * 100)           # leftover cents
    return [base + Decimal("0.01") if i < rem else base for i in range(n)]
# 40.00 / 3 -> [13.34, 13.33, 13.33]; assert sum == total
```
---

## 10. Optional add-ons (only after the above works)

**Airbyte reconciliation (~45 min):** put an exported card-statement CSV in a Google Sheet → Airbyte source → destination SingleStore (or any MySQL-compatible destination; SingleStore speaks the MySQL protocol, so check what Airbyte offers at kickoff) → `transactions` table. After each log, match on date ±1 day and amount ±$5 plus merchant similarity, then show "You said $40, Safeway charged $43.17. Update?" as an audit card.

**Persona (~30 min):** one-time verification of the account owner. Before posting any expense that bills other people above a threshold (e.g. $100), check that verification status, and record "verified human: yes, inquiry id" in the audit trail.

**Receipt photo (~30 min):** SIE OCR (`glm-ocr` / `lightonocr`) → text handed to the agent like a spoken utterance.

---