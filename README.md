# Keep - Tab

**A voice-first agent for shared money and shared plans.**

> "I paid 40 bucks for groceries today, split with my roommates."

Keep Tab works out who "roommates" means, splits $40 three ways to the cent, records it, and your roommates' phones show their new balances right away. No forms, no app switching, no settling up from memory at the end of the month.

## The problem (facing this as a student living with a bunch of roomates)

Shared expenses don't usually get lost because the math is hard. They get lost because **logging them is a chore**. Logging one grocery run in a typical split-expense app takes five steps: open the app, pick the group, type the description and amount, choose who's in and how to split, and fix the date. That's a lot of friction for a $40 receipt, so people put it off and then forget.

Keep Tab handles both chores with one interface: say what happened or what you want, and the agent does the bookkeeping.

## What Keep - Tab does (Usage Examples)

| You say | Tab does |
| --- | --- |
| "I paid 40 for groceries, split with my roommates." | Resolves "roommates" to the group, splits $40 as $13.34 / $13.33 / $13.33, records it, and pushes new balances to every open phone. |
| "Spent 20 on a cab." | Logs a personal $20 Transport expense for today. Nobody else sees it. |
| "How much have I spent on rides this month?" | Uses vector search to match cab, Uber and Lyft by meaning, then totals them. |

It also does the following:

- **Hangout recommendations.** Everyone drops a pin and sets a travel time and budget. Tab suggests real nearby places from OpenStreetMap that the whole group can reach and afford.
- **Meetup coordination.** Finds times when everyone is free and venues that fit each person's travel and budget limits, using multiple user aware agents that talk to each other and come to an agreement

## Architecture

### Sponsor tools
| Tool | What we use it for |
| --- | --- |
| **Superlinked SIE** | Serves the small, task-specific models behind one inference API: `whisper-large-v3-turbo` for speech-to-text, `bge-m3` for embeddings, and `Qwen3.5-4B` for the agent's reasoning and tool calls. |
| **SingleStore** | The single store for both data and embeddings. It holds people, groups, expenses, shares, balances, meetups and venues, plus `VECTOR(1024)` bge-m3 embeddings and full-text indexes, so exact filters and semantic search run in the same SQL query. |
| **Firedrill** | Simulation of the multi-agent meetup flow: per-person agents negotiate times and venues against a separate database (`tab_drill`), so we can check how they behave and what each one shares before running it on real data. |

```
┌──────────────────────────────── React web app (webapp/) ─────────────────────────────────┐
│   push-to-talk / text box      balances · history · receipts       map + Hangout panel   │
└──────────┬───────────────────────────────▲─────────────────────────────────┬─────────────┘
       audio / text                   SSE events                  pins, budgets, minutes, note
           │                               │                                 │
┌──────────▼───────────────────────────────▲──────── FastAPI (app/) ─────────▼─────────────┐
│  POST /api/ingest                    GET /api/live              POST /api/hangout        │
│   ├─ 1. whisper: speech → text        ▲ in-memory fan-out        ├─ Qwen: note → words   │
│   └─ 2. agent loop (Qwen, ≤5 rounds)  │ (core/live.py)           ├─ OpenStreetMap search │
│         prompt: schema, people,       │                          │  (Photon / Overpass)  │
│         groups, categories, today     │                          ├─ reach + budget filter│
│              │                        │                          └─ Qwen: pick + why     │
│              ▼  MCP tools             │                                                  │
│   ┌──────────────────┬──────────────┐ │        Meetup coordinator (core/meetups/)        │
│   │ WRITE            │ READ         │ │         ├─ personal agent per member:            │
│   │ log_expense      │ query: one   │ │         │  private profile → shared constraints  │
│   │ edit_expense     │ read-only    │ │         ├─ overlap free time, midpoint search    │
│   │ record_settlement│ SELECT +     │ │         ├─ private per-venue checks, weather     │
│   │ delete_expense   │ bge-m3       │ │         └─ fairness score → top 3 for voting     │
│   │ last_expense     │ vector search│ │                                                  │
│   └────────┬─────────┴──────┬───────┘ │                                                  │
│            ▼                │         │                                                  │
│   ledger.py: Decimal splits,│ ────────┘ publish on every write                           │
│   one transaction per write │                                                            │
└────────────┬────────────────┴────────────────────────────────────────────────────────────┘
             ▼
┌──────────────────────── SingleStore ────────────────────────┐  ┌─── Superlinked SIE ────┐
│ people · groups · expenses · expense_shares · balances view │  │ whisper-large-v3-turbo │
│ VECTOR(1024) embeddings + full-text                         │  │ bge-m3 (embeddings)    │
│ meetups · venues · availability (private: not readable by   │  │ Qwen3.5-4B (agent)     │
│ the agent's read-only SQL user)                             │  │                        │
└─────────────────────────────────────────────────────────────┘  └────────────────────────┘
```


### Design principles we followed

- **The model decides, code does the math.** Qwen only picks a tool and fills in its arguments. Splits, rounding, balances, travel times and scoring are deterministic Python.
- **Never guess a person or an amount.** When a name or number is ambiguous, Tab asks a clarifying question.
- **Writes go through the ledger, reads are SQL.** Money only changes through the ledger tools, which keep shares exact. Questions are answered with one read-only SELECT, run as a database user that can only read approved tables.
- **Small models, one inference API.** Speech, embeddings and reasoning are three task-specific models served by Superlinked SIE keeping it lightweight and inexpensive
- **One database for exact and fuzzy questions.** SingleStore stores the ledger rows and their vectors, so "$20 last Wednesday" (filters) and "rides" (similarity) can run as the same query.


## Project layout
```
voice-tab/
├── app/                         # Python backend
│   ├── main.py                  # FastAPI app entry point
│   ├── .env.example             # Environment variable template
│   ├── requirements.txt         # Python dependencies
│   ├── scripts/                 # Database setup and demo seeding
│   └── src/
│       ├── agents/              # Agent loop, prompts, speech, and hangout models
│       ├── core/
│       │   ├── expenses/        # Ledger, splits, categories, and settle-up
│       │   ├── meetups/         # Meetup planning, venues, weather, and voting
│       │   └── people/          # Private profile and calendar checks
│       ├── db/                  # Database client and schema
│       ├── mcp/                 # Agent tool registry and MCP endpoint
│       ├── model/               # Model and speech integrations
│       ├── routes/              # API endpoints, ingest, and live events
│       └── utils/               # SQL queries and people/group helpers
└── webapp/                      # React + TypeScript frontend
    ├── package.json             # Frontend dependencies and scripts
    ├── vite.config.ts           # Vite config and API proxy
    └── src/
        ├── App.tsx              # Main React app
        ├── components/          # Hangout, ledger, map, people, receipt, and UI
        ├── hooks/               # Recording and hangout hooks
        ├── lib/                 # API client, types, formatting, and map helpers
        ├── orb/                 # Voice orb animation
        └── styles/               # Global styles₹
```

## Requirements

- Python 3.10 or newer
- Node.js and npm
- A SingleStore database
- A Superlinked SIE endpoint and API key for inference and embeddings


## Configure and run the backend

From the repository root:

```sh
cd app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `app/.env` with the SingleStore connection values and `SL_BASE_URL` / `SL_API_KEY`. The app reads this file at startup. Keep `.env` private; it contains credentials.d.

Start the API from the `app/` directory:

```sh
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API is at `http://localhost:8000`. FastAPI's interactive endpoint reference is at `http://localhost:8000/docs`.

## Run the web app

In a second terminal, from the repository root:

```sh
cd webapp
npm install
npm run dev
```

Open the Vite URL printed in the terminal. Its development server proxies `/api` requests to `http://localhost:8000`. For microphone access from another device, use HTTPS or localhost; the Vite server is configured to listen on the network.


## Limitations (starting point for our future scope)

- Today Tab is a web app you open and press a button in. We see it becoming an **ambient assistant like Siri**, built into a native mobile app and always one phrase away
- Improved latency and streaming enhancements so that conversations flow naturally
- Persistent sessions the live event bus from in-process memory to Redis, or SingleStore pipelines, so the backend can scale past one process and survive restarts.
- Bank and receipt reconciliation where card transactions or emailed receipts can be synced and flag mismatches, for example: "You said $40, Safeway charged $43.17."




