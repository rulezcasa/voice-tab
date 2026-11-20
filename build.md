# Tab — build plan (One day hackathon)

- This is a tentative build plan, changes can be made to this as we build.
- The goal is make a functioning product and any advanced features can be moved out of scope.
- One key standout point is the UI - it shouldnt a generic webapp demo, make the UI creative and give it a real ambient agent kind of a feel.

---

## 1. Architecture

```
 ┌──────────────┐   audio/text    ┌────────────────────────────── FastAPI ─────────────────────────────┐
 │ Trigger agent│ ──────────────▶ │ /ingest                                                             │
 │   (TBD)      │                 │  1 transcribe ─▶ 2 route intent ─┬─▶ LOG   ─▶ 3 extract ─▶ 4 resolve│
 └──────────────┘                 │                                  │           people ─▶ 5 math ─▶    │
        ▲                         │                                  │           6 confidence gate ─▶   │
        │ answer / question       │                                  │           7 save ─▶ 8 balances   │
        └──────────────────────── │                                  ├─▶ QUERY ─▶ filters + vector ─▶   │
                                  │                                  │           rerank ─▶ answer       │
                                  │                                  ├─▶ EDIT  ─▶ update last expense   │
                                  │                                  └─▶ SETTLE ─▶ settlement expense   │
                                  │  every step ─▶ audit_events                                         │
                                  └───────────────┬───────────────────────────────┬─────────────────────┘
                                                  │                               │
                                       Superlinked SIE (models)          SingleStore (people, groups,
                                       whisper · gliclass · gliner2      expenses, shares, audit_events,
                                       bge-m3 · reranker · qwen          vectors + full-text)
```

**Design rules**
- **Models extract and classify; code decides.** Money math, date math and balances are deterministic Python.
- **Never guess a person or an amount.** Low confidence or ambiguity means a clarifying question, not a guess.
- **We own the ledger.** No Splitwise or other outside expense service. Expenses, shares and balances live in our own SingleStore tables.
- **Everything leaves a trace.** Each step writes an `audit_events` row *before* returning.

---

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python, FastAPI, `httpx`, `pydantic` | Fast to build; SIE has a Python SDK |
| Inference | `sie-sdk` (SIE Serverless) | Sponsor; one API for all the small models |
| DB | `singlestoredb` Python client | Sponsor; SQL + vector + full-text in one place |
| Dates | `dateparser` (with a base date in the user's time zone) | Handles "yesterday", "last Wed" and so on |
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
main.py                  # FastAPI entry point. Run: fastapi dev main.py
src/
  config.py              # reads .env
  db/
    s2_client.py         # ONLY place that connects to SingleStore: cursor(), transaction(), to_vector()
    schema.sql
  model/
    sl_client.py         # ONLY place that creates the SIE client + model IDs (Relay off)
    embeddings.py        # embed(), expense_embed_text()
  core/
    categories.py        # fixed category list
    money.py             # equal_split()
scripts/                 # check_s2, check_sie, seed  (run as: python -m scripts.<name>)
```
Rule: nothing outside `src/db/s2_client.py` and `src/model/sl_client.py` opens its own database or SIE connection.

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

CREATE TABLE utterances (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  created_at  DATETIME DEFAULT NOW(),
  transcript  TEXT,
  intent      VARCHAR(20)                   -- log | query | edit | settle | other
);

CREATE TABLE expenses (
  id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
  utterance_id          BIGINT,
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

CREATE TABLE audit_events (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  utterance_id  BIGINT,
  expense_id    BIGINT NULL,
  step          VARCHAR(40),                -- transcribe | route | extract | resolve | math | gate | store | balances | query
  model         VARCHAR(80) NULL,
  input         JSON,
  output        JSON,
  confidence    FLOAT NULL,
  latency_ms    INT,
  created_at    DATETIME(6) DEFAULT NOW(6)
);

```

**Seed script** (`seed.py`):
- Insert yourself (`is_me = TRUE`), the teammates and two Alexes (Chen, Park) into `people`, with aliases and embeddings.
- Insert group "Apt 4B" 
- Insert about 30 **demo** expenses over the past 3 weeks so recall queries have data. Include a $20 cab last Wednesday and a few Uber/Lyft rides. Label them as demo data.

### Categories (fixed list)

The model never invents a category. It picks one label from this list (zero-shot classification with gliclass on SIE); Python checks the label is in the list.

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
| `other` | Fallback when the classifier's confidence is low |
| `settlement` | **Set by code only, never by the model.** A repayment between people |

### Settlements (no extra table)

"Sam paid me back 13.33" is stored as a normal expense with `category = 'settlement'`:
- `expenses`: amount 13.33, description "Sam paid me back", `group_id` of the shared group.
- `expense_shares`: Sam `paid = 13.33, owed = 0`; me `paid = 0, owed = 13.33`.

Sam's balance goes back to 0, the original expense and everyone else's shares stay untouched, and there's a dated record of the repayment. Spending totals exclude `settlement`; balances include it.

---

## 4. The pipeline, step by step

Wrap each step in an `audit()` helper that times it and writes an `audit_events` row.

```python
async def audit(utt_id, step, model, inp, fn):
    t = time.perf_counter()
    out, conf = await fn()
    db.insert_audit(utt_id, step, model, inp, out, conf, int((time.perf_counter()-t)*1000))
    return out, conf
```

### Step 1: Voice/test input (suitable SIE model)
- The client proceses voice or text input.
- Route intent : log an expense, ask about past spending, correct the last expense, record a settlement ("Sam paid me back"). This can be text-to-sql or MCP tools with the agent dynamically calls. 
- Category: classify the description into one of the fixed categories (see §3). Below the confidence threshold → `other`.
- Out extracted fieds :
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

**Receipt photo (~30 min):** SIE OCR (`glm-ocr` / `lightonocr`) → the same extraction step.

---