# Agentic Tasks — multi-agent discussion of a task

A service that takes a task written in natural language (title, description, optional context and attachments) and has a small group of agents with different roles discuss it. The agents propose, challenge and revise a draft until they reach a proposal, or they stop and ask a person for a decision. The result is a **versioned proposal** with recommended actions, risks and open issues, linked to the evidence that supports it.

**Actions are never executed.** The system produces a document to review and approve; approval applies to the document, not to execution.

## What it does

1. A user submits a task through the API or the web UI.
2. Four roles take turns in every round:
   - **Analyst**: proposes a concrete draft and revises it based on objections and human answers.
   - **Operations**: assesses feasibility, dependencies and operational constraints.
   - **Finance**: assesses costs and economic impact, or declares itself not applicable with a reason.
   - **Critic**: challenges unsupported claims, opens and resolves objections, and decides whether a revision or a question to the operator is needed.
3. If information is missing or a choice is required, the critic pauses the run with a **dynamic question** (with options). The human answer is recorded as evidence and the discussion resumes.
4. The outcome is a proposal with actions, risks, open issues, version and source messages. Earlier drafts remain available.

```
task ─▶ analyst ─▶ operations ─▶ finance ─▶ critic ─┬─▶ final proposal ─▶ approval (document only)
           ▲                                         ├─▶ revision (next round)
           └───────────── human answer ◀─────────────┴─▶ question to the operator
```

## The idea

A single model answering a request tends to produce a plausible but poorly checked plan. Here the answer comes from a structured exchange between different perspectives, under a few precise rules:

- **Roles with distinct responsibilities.** Only the critic can resolve objections or interrupt the cycle with a question, and it must always explain why.
- **Explicit evidence.** Every `supported` claim must cite evidence actually present in the run; anything else is declared an `assumption` or `estimate`. Invented references are rejected.
- **Human in the loop.** When a decision or missing business data is needed, the system asks instead of inventing it. Missing budgets, permits or quotes stay "unknown".
- **Transparency.** Explicit distinction between `model` and `mock` mode, real and simulated data, verified results and assumptions. No silent fallback to mock on errors.
- **Generic orchestration.** The engine knows no domain. Domain knowledge (data, tools, evidence rules) is added through optional *capability profiles*.

The project includes a complete example profile: **EV charging stations** in the Bolzano area, using public [Open Data Hub](https://opendatahub.com/) data from South Tyrol, analysis tools and local forecasts with Timestral.

## Technical implementation

### Architecture

| Component | Technology | Role |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic | `/api/v2` API, discussion worker, SSE |
| Persistence | SQLite (WAL) | Runs, events, idempotent commands, leases, artifacts |
| Models | OpenAI Responses API with Structured Outputs | Agent turns in `model` mode |
| Frontend | TypeScript, Vite | Workspace to start tasks, follow the discussion, answer and approve |
| Contracts | Generated OpenAPI and JSON Schema | TypeScript types generated with `openapi-typescript` |
| Forecasting (optional) | Timestral, PyTorch, NumPy | Local numerical pipeline for the charging example |

### Discussion engine (`backend/acs/`)

| File | Responsibility |
| --- | --- |
| `models.py` | Generic contract: tasks, evidence, turns, messages, objections, questions, proposals, commands |
| `providers.py` | Roles, prompts, real OpenAI adapter and deterministic mock provider |
| `discussion.py` | Bounded cycles, reference validation, versions, questions, persistence |
| `investigation.py` | Tool loop for capability profiles (calls, budgets, corrections) |
| `profiles.py`, `capabilities.py`, `tools.py` | Profile and tool registration, immutable artifacts |
| `jobs.py`, `recovery.py` | Durable numerical jobs in subprocesses, leases, heartbeat, restart recovery |
| `api.py` | HTTP, SSE and the worker in the FastAPI lifespan |
| `db.py` | SQLite schema and turn leases |

**Structured turns.** Each agent returns a schema-validated `AgentTurn`: message type, applicability, public explanation, evidence references, claims, objections, resolutions, draft or question. The server assigns IDs, timestamps, versions and links. No private reasoning is requested.

**Limits and corrections.** Each cycle has 1 to 6 rounds (default 3). An invalid schema or a non-existent citation gets a single correction attempt. After two failures the content is kept as an explicit assumption, stripped of invalid citations, and the critic receives an objection. Refusals and network errors produce a declared-unavailable turn, never an invented result. The number of model calls per cycle is capped.

**Durability and concurrency.** Each turn acquires a 180-second lease in a short transaction. The model call happens outside the transaction. The result is applied only if version, role and lease are still valid, so a late response is discarded. On restart the worker resumes running runs. Requests are idempotent (`idempotency_key`), and `proposal_version` rejects answers or approvals on stale versions. The full state of each run is stored as a snapshot and streamed over SSE.

**Evidence.** Task, context and attachments are frozen with a SHA256 hash. A URL-only attachment is `reference_only`: it is not downloaded or treated as a read source.

### Example profile: charging stations (`backend/acs/examples/charging/`)

With `capability_profile=charging`, agents can use typed read-only and calculation tools (no free-form queries, no model-triggered downloads): `discover_sites`, `get_inventory`, `get_data_quality`, `get_evidence`, `get_usage_summary`, `compare_maintenance_windows`, `request_forecast`, `get_operational_inputs`, `assess_expansion`.

- **Data.** Plug status time series from Open Data Hub, stored as compressed raw responses with checksums and normalized conservatively: gaps are not filled and censored episodes are flagged.
- **Numerical evidence.** Numbers cited by agents must match persisted metrics (same value, unit, site and period). This is a structural check, not proof that the prose is semantically correct.
- **Forecasts.** `request_forecast` starts jobs in separate subprocesses. Timestral is compared against a weekly baseline through backtesting. If data coverage is insufficient, the result is `unavailable` with reasons, never simulated values.
- **Operational inputs.** Quotes, permits, budgets and calendars can be imported as versioned records, classified as `verified`, `simulated` or `assumed`.

The workspace offers three goals without attachments (`frontend/tasks.ts`): add 20 charging stations by 1 March 2027, plan maintenance in Bolzano, and pick a 2-hour maintenance window at BZ_PIAVE_01.

## Quick start

Requirements: Python 3.12+ and Node 22+.

```sh
make setup        # virtualenv, Python and npm dependencies
make api          # backend at http://localhost:8000 (Swagger: /docs)
npm run dev       # Vite frontend, in another terminal
```

Without credentials, the backend uses **mock** mode: a deterministic fixture, always labeled as such, that calls no model. To use a real model, set these in `.env` or `.env.local` (loaded automatically by the server):

```dotenv
OPENAI_API_KEY=your-key
ACS_MODEL=model-name-with-structured-outputs
VITE_RUN_MODE=model
```

Shell variables take precedence, then `.env.local`, then `.env`. Restart the server after changes, and never use the `VITE_` prefix for the key. Explicitly requesting `mode=model` without configuration returns `503`. See `.env.example` for the other options.

API example:

```sh
curl http://localhost:8000/api/v2/runs \
  -H 'Content-Type: application/json' \
  -d '{"task":{"title":"Volunteer guide","description":"Propose a short guide for welcoming library volunteers."},"mode":"mock","max_rounds":3,"idempotency_key":"volunteers-1"}'
```

Then read `GET /api/v2/runs/{id}` or follow `GET /api/v2/runs/{id}/events` (SSE). When `state=awaiting_input`, answer with `POST /api/v2/runs/{id}/answers`. To approve a proposal: `POST /api/v2/runs/{id}/approve`.

### Charging example data and forecasts

```sh
make download          # download Open Data Hub data (requires Internet)
make prepare           # offline rebuild of derived tables
make forecast-setup    # optional dependencies (Timestral, PyTorch)
make forecast          # local backtest and publication, no OpenAI key needed
```

Data API: `/examples/charging/api/v1`, with a separate Swagger at `/examples/charging/docs`.

## Verification

```sh
make contracts                 # regenerate OpenAPI, JSON Schema and TypeScript types
make test                      # pytest + typecheck
npm run test:frontend          # Playwright with the local simulator
npm run test:integration       # real HTTP/SSE, temporary DB, controlled provider/predictor
.venv/bin/python -m scripts.smoke_discussion --mode mock
```

With a configured server, `--mode model` makes real, potentially billed calls.

### Status and known limits

Software transitions (questions, revisions, restart during jobs, idempotency) are verified with a controlled provider and predictor. Live runs with a real model showed correct tool selection and relevant questions, but **numerical citation reliability did not pass the check**. Also, **real forecast usefulness is not validated**: with the current data, coverage is insufficient and the sites are `unavailable`. Details are in [IMPLEMENTATION-PROGRESS.md](docs/IMPLEMENTATION-PROGRESS.md).

Out of scope: multi-user authentication, deployment, execution of proposed actions and enterprise integrations.

## Documentation

The guides are written in Italian.

- [Backend](docs/BACKEND.md): configuration, discussion cycle, persistence, errors and tests.
- [Frontend](docs/FRONTEND.md): generic client, questions, versions and SSE.
- [Charging example](docs/CHARGING.md): data, normalization, tools, Timestral forecasts and limits.
- Contracts: [OpenAPI](contracts/openapi.json), [agent turns](contracts/agent-turn.schema.json), [events](contracts/events.schema.json). Client: [client.ts](frontend/client.ts) and [generated types](frontend/api-types.ts).
- [AGENTS.md](AGENTS.md): instructions for AI agents working on the repository.

## Authors

- Nico Bonora
- Vittorio Matteo Covini
- Paolo Pinto

Copyright (C) 2026 Nico Bonora, Vittorio Matteo Covini, Paolo Pinto.
Distributed under the GNU AGPL v3 license (see [LICENSE](LICENSE)).
