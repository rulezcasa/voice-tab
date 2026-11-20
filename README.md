# Tab

Tab is a voice-first expense ledger and group hangout planner. The React web app sends text or recorded speech to a FastAPI backend. The backend transcribes audio, uses an agent to interpret requests, and records expenses and shares in SingleStore. It also has logic for finding meetup times and venues that fit a group's availability and travel constraints.

## What it can do

- Record expenses, split them across people, edit or delete them, and record repayments.
- Answer expense questions with read-only SQL and semantic search over expense descriptions.
- Show current and per-group balances, expense history, and receipts.
- Recommend nearby places for a group through the Hangout panel, using OpenStreetMap data.
- Coordinate meetup options using shared free time, venue preferences, travel estimates, weather, and costs. The coordinator and meetup storage code live in `app/src/core/meetups/`.
- Stream ledger and meetup changes to connected clients through server-sent events.
- Expose the agent's tools through an optional MCP endpoint.

## Project layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI app setup, startup lifecycle, and route mounting |
| `app/src/routes/` | HTTP endpoints for the API, voice/text ingest, and live events |
| `app/src/agents/` | Agent loop, system prompt, speech-to-text integration, and hangout language model |
| `app/src/mcp/server.py` | Tool registry used by the in-process agent and optional MCP clients |
| `app/src/core/expenses/` | Expense ledger, share calculations, categories, and settle-up logic |
| `app/src/core/meetups/` | Meetup planning, travel calculations, weather, database access, and voting storage |
| `app/src/core/people/personal_agent.py` | Private profile and calendar checks used by the meetup coordinator |
| `app/src/db/schema.sql` | SingleStore tables and views |
| `app/scripts/` | Database setup and demo data scripts |
| `webapp/` | React + TypeScript frontend |

## Requirements

- Python 3.10 or newer
- Node.js and npm
- A SingleStore database
- A Superlinked SIE endpoint and API key for inference and embeddings

The weather integration uses Open-Meteo without an API key. If it cannot reach the service, it uses a fallback forecast.

## Configure and run the backend

From the repository root:

```sh
cd app
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `app/.env` with the SingleStore connection values and `SL_BASE_URL` / `SL_API_KEY`. The app reads this file at startup. Keep `.env` private; it contains credentials.

Create the schema and seed demo data:

```sh
python -m scripts.reset_db
python -m scripts.seed
```

`reset_db` drops and recreates the configured database's tables. To use a separate Firedrill database, pass `--db tab_drill` to both scripts. If you configure `SS_READONLY_USER`, `python -m scripts.reset_db --grant` grants that account read access to the agent's approved tables; the private `availability` table is excluded.

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

## API overview

All application routes use the `/api` prefix.

| Route | Purpose |
| --- | --- |
| `GET /api/health` | Check SingleStore and SIE connectivity |
| `POST /api/ingest` | Process uploaded audio or typed text with the agent |
| `POST /api/ingest/reset` | Clear an agent conversation session |
| `GET /api/balances` | Return each person's current net balance |
| `GET /api/balances/groups` | Return balances grouped by household or friend group |
| `GET /api/expenses` | List recent expenses |
| `POST /api/expenses` | Create an expense from structured input |
| `GET /api/expenses/{id}` | Get an expense and its shares |
| `PATCH /api/expenses/{id}` | Edit an expense |
| `DELETE /api/expenses/{id}` | Delete an expense |
| `POST /api/settlements` | Record a repayment |
| `POST /api/groups` | Create a group |
| `POST /api/hangout` | Recommend real places for a group's Hangout panel |
| `GET /api/live` | Subscribe to live ledger and meetup events using SSE |

The optional MCP server is mounted at `/mcp`. The agent itself calls MCP tools directly in the backend process; it does not require a separate MCP service.

## Data and privacy

The database keeps expense shares as ledger rows and calculates balances through a view. Meetup profile fields and busy blocks are used by the private-personal-agent code when evaluating options. Busy labels are not used by the planner. The agent's SQL is restricted to read-only queries, and the read-only database account is not granted access to `availability`.

## Live event stream

Open a stream in one terminal:

```sh
curl -N http://localhost:8000/api/live
```

The stream sends a connection snapshot and then JSON events when ledger or meetup data changes. It sends a keep-alive comment every 15 seconds. Expense changes can be made through the API or the agent in another terminal.

## Demo data

The seed script creates sample people, groups, venues, availability, and expense history. Dates are relative to the current date so examples such as the recent Wednesday cab expense continue to work. It also creates a past confirmed meetup and linked expense history for the planner's cost-learning step.
