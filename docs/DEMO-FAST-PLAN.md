# Implementation plan: 2-minute data-cited report demo

Status: ready for autonomous execution. Prepared 2026-11-14.
Audience: an implementing agent (Claude Code) working alone, end to end.
Language of code/docs: English for this plan; keep existing Italian UI strings
where they already exist, new demo UI may be English or Italian (pick one, be
consistent).

---

## 0. Why this exists (read first)

The current v2 flow (`backend/acs/discussion.py`, `investigation.py`) is a
durable, round-based debate: 4 roles × up to 3 rounds × up to 10 provider calls
per turn, strict structured-output validation, recovery turns, critic
objections, human questions, versioned proposals and approvals. It is correct
but, for a hackathon demo, it is:

- **slow** — dozens of sequential non-streamed LLM calls; leases, polling worker
  (200 ms tick), 1-second SSE loop; analytical jobs on a 900 MB SQLite;
- **opaque** — the UI only receives whole-run snapshots; nothing shows while a
  model call is in flight;
- **fragile** — the last live run (`docs/investigation-maintenance-final-live.json`)
  failed with `invalid_model_output` (hallucinated evidence id) after a long run.

Target for the demo:

> A task is given → agents pull facts **from the local data through tools** →
> a **report streams live on screen** with **inline citations** that open the
> exact data behind each number → done in **≤ 120 s**, reliably, every time.

Fewer controls: no human questions, no approval gate, no round limit dialog,
no proposal versions. Agents must still get every fact from the data.

---

## 1. Decisions (already made — do not re-litigate)

| Topic | Decision | Rationale |
|---|---|---|
| Orchestration | **Fixed code-driven pipeline**, not free debate: `Researcher (tools) → Writer (streamed) → Reviewer (deterministic check + short LLM note)` | Bounded latency, visible phases, still multi-agent |
| Primary LLM engine | **Claude Agent SDK for Python (`claude-agent-sdk`) using the local Claude Code login** | User has a Claude Code license; no API key needed; native token streaming + in-process custom tools |
| Secondary engine | Existing OpenAI path stays untouched for v2. Do **not** add an OpenAI path to v3 unless Phase 3 time remains | Avoid scope creep |
| Local models | **Not used.** Ollama is not installed; local models are slower and weaker at multi-step tool calling on a laptop | Reliability > novelty |
| Safety net | **`replay` mode**: record the best real run's event stream, replay with original timing, clearly labelled `REPLAY` | Venue Wi-Fi / rate-limit insurance |
| Offline dev | **`mock` mode**: deterministic scripted events, no LLM, labelled `MOCK` | Tests and UI work without spending quota |
| Data access | **Precomputed demo cache** (small SQLite) built from `data/acs.sqlite`; tools read aggregates only | Each tool call < 300 ms |
| Forecasting (Timestral) | **Out of the demo path.** Optionally expose the already-persisted `data/exports/forecast-latest.json` as a read-only evidence item | Current forecasts are `unavailable`; jobs are slow |
| Citations | Every tool result becomes an evidence item `E1..En` with source, query, params, data. Report cites `[E3]`. A **deterministic verifier** checks ids and numbers | Trust without a blocking critic loop |
| v2 flow | **Keep intact** (routes, tests, UI). Demo lives under `/api/v3` and a new UI view | No regressions; existing `make test` must stay green |

### Note on the Claude Code login
Running the Agent SDK on the user's own machine with their logged-in Claude Code
account is fine for a local hackathon demo. If this ever becomes a hosted
product, switch the engine to an `ANTHROPIC_API_KEY` (same SDK, same code path).
Make the engine read `ANTHROPIC_API_KEY` if present and otherwise rely on the
CLI login — no code change needed between the two.

---

## 2. Target architecture

```
frontend (Vite, vanilla TS)
  DemoView ── POST /api/v3/reports ──► backend
           ◄── SSE /api/v3/reports/{id}/stream  (fine-grained events)
           ── GET  /api/v3/reports/{id}/evidence/{eid}

backend/acs/demo/            (new package; v2 untouched)
  cache.py        build + open data/demo_cache.sqlite (read-only at runtime)
  tools.py        6 data tools → return {evidence_id, data, source}
  evidence.py     per-report evidence registry (E1..En), JSON-serialisable
  events.py       pydantic event models + in-memory bus + persistence
  verifier.py     deterministic citation/number check
  pipeline.py     Researcher → Writer → Reviewer orchestration, timeouts
  engines/
    claude_sdk.py Agent SDK adapter (tools as in-process MCP server)
    mock.py       scripted events
    replay.py     replays a recorded events JSONL with timing
  api.py          FastAPI router mounted at /api/v3
scripts/
  build_demo_cache.py
  demo_rehearsal.py
  spike_agent_sdk.py
fixtures/demo/   recorded runs for replay (committed, small)
```

### Event stream contract (`events.py`)
Every SSE message: `id: <seq>`, `event: <type>`, `data: <json>`. Types:

| type | payload |
|---|---|
| `run_started` | `{report_id, task, engine, model, started_at}` |
| `phase` | `{agent: "researcher"\|"writer"\|"reviewer", status: "started"\|"done", elapsed_ms}` |
| `agent_thought` | `{agent, text}` — short public status line ("Looking for the busiest sites in Bolzano"), never chain-of-thought |
| `tool_call` | `{agent, call_id, tool, args}` |
| `tool_result` | `{agent, call_id, evidence_id, summary, latency_ms, status}` |
| `report_delta` | `{text}` — raw Markdown token chunk |
| `verification` | `{citations_total, citations_valid, numbers_checked, numbers_traced, untraced: [..], unknown_ids: [..]}` |
| `review_note` | `{text}` |
| `run_finished` | `{elapsed_ms, status: "ok"\|"partial"\|"error", usage}` |
| `error` | `{code, message}` |

Events are appended to a `demo_events` table (or JSONL under `data/demo_runs/`)
so the SSE endpoint supports `Last-Event-ID` reconnection and so any run can be
saved as a replay fixture. SSE must push immediately (asyncio queue per
subscriber), **not** poll every second like v2.

---

## 3. Execution rules for the implementing agent

1. Read `AGENTS.md`, `docs/BACKEND.md`, `docs/FRONTEND.md`, `docs/CHARGING.md`
   before touching those areas. Preserve unrelated user changes.
2. The working tree has uncommitted user changes on `fe-be-implementation`.
   **Do not stash, revert or overwrite them.** Create branch
   `demo-fast-report` from the current HEAD *after* confirming the tree state
   with `git status`; if the user's changes are still uncommitted, leave them
   in place and only add new files / make additive edits.
3. Never commit `data/`, `.env*`, or secrets. Fixtures in `fixtures/demo/`
   must contain only derived aggregates (no raw observation dumps > 500 KB).
4. LLM budget: live Claude runs are allowed but cap at **~25 live runs total**
   across the whole implementation (spike + rehearsals). Use `mock` for all
   UI/unit work. Never call the OpenAI API.
5. After every phase: run that phase's tests **and** `make test`. Do not start
   the next phase with a red suite. Record results in
   `docs/DEMO-FAST-PROGRESS.md` (phase, what changed, test output summary,
   measured timings, anything skipped and why).
6. If an assumption in this plan is false (e.g. an SDK option name differs),
   adapt minimally, note it in the progress file, continue. Stop and report
   only if a phase's acceptance criteria are impossible.
7. Keep v2 contracts (`contracts/*.json`, `frontend/api-types.ts`) unchanged
   unless you deliberately add v3 to the export; if you do, run
   `make contracts` and commit the regenerated files.

---

## 4. Phases

### Phase 0 — Baseline and spikes (≤ 1 h)

**0.1 Baseline.** Run `make test`, `npm run typecheck`, `npm run test:frontend`.
Record pass counts in the progress file. If anything is already red, note it and
do not try to fix v2 unless trivially caused by your environment.

**0.2 Agent SDK spike** — `scripts/spike_agent_sdk.py`.
- `pip install claude-agent-sdk` into `.venv`; add to a new
  `requirements-demo.txt` (pin the installed version) and a `make demo-setup`
  target.
- Verify against the official docs (https://code.claude.com/docs/en/agent-sdk,
  Python reference) — do not guess names. Expected surface:
  `query(prompt, options)` / `ClaudeSDKClient`, `ClaudeAgentOptions`,
  `@tool` + `create_sdk_mcp_server` for in-process tools,
  `include_partial_messages=True` for token-level `StreamEvent`s,
  options for `system_prompt`, `model`, `max_turns`, `allowed_tools`,
  disabling built-in tools, and not loading filesystem settings
  (`setting_sources`).
- Spike must demonstrate, and print timings for:
  1. auth works with no `ANTHROPIC_API_KEY` set (uses CLI login);
  2. one custom tool (`echo_site_count`) called by the model;
  3. text deltas arrive incrementally (print time-to-first-token and
     inter-chunk timing);
  4. built-in tools (Bash, Read, Write, WebFetch…) are **not** available to the
     agent — assert by asking it to list files and checking no such tool ran;
  5. the project's `CLAUDE.md`/`AGENTS.md` is not injected (settings not
     loaded).
- Benchmark `sonnet` vs `opus` model choice on the spike prompt (3 runs each):
  record TTFT, total time. Default the demo to the fastest model that later
  passes the Phase 7 quality gate; make it configurable via `ACS_DEMO_MODEL`.
- **Fallback** if the Python SDK is unusable: drive the CLI directly —
  `claude -p --output-format stream-json --include-partial-messages
  --mcp-config <file> --allowedTools mcp__demo__* --max-turns N`, with the data
  tools exposed by a tiny stdio MCP server (`backend/acs/demo/mcp_server.py`).
  Same event mapping. Note the choice in the progress file.

**0.3 Data timing baseline.** Time the existing charging computations on the
real DB for the two demo tasks (e.g. `tools.discover`, `metrics.observed` for
10 Bolzano sites over 56 days). Record seconds. This justifies Phase 1.

Acceptance: progress file contains baseline test counts, spike output
(all 5 checks pass or fallback chosen), model timings, data timings.

---

### Phase 1 — Demo data cache (≤ 1.5 h)

`scripts/build_demo_cache.py` → `data/demo_cache.sqlite` (gitignored), built
from `data/acs.sqlite` read-only. Add `make demo-cache`.

Reuse existing logic instead of re-deriving semantics:
`examples/charging/tools.py` (`discover`, `coordinates`, Bolzano bounding box,
`quality`) and `examples/charging/metrics.py` (`observed`,
`reconstruct`) for occupancy. Tables (suggested):

| table | content |
|---|---|
| `meta` | dataset name (Open Data Hub South Tyrol e-mobility), sources, first/last observation, build time, source DB sha/size, analysis window |
| `sites` | id, name, source, lat, lon, in_bolzano_bbox, point_count, max_power_kw, connector types |
| `site_stats` | per site over the analysis window (default last 56 full days before last observation): coverage, exposure_hours, occupancy_fraction, observed_starts, peak local hour, stale flag |
| `site_hourly` | per site × weekday × local hour: occupancy_fraction, exposure_hours, comparable_dates |
| `area_hourly` | same aggregated for the Bolzano bbox and for "all" |
| `quality` | per site: observations, gap_count, median_cadence, latest_observation |

Rules: unknown stays `NULL`, never 0. Store the window and units in `meta`.
Build time on the full DB may be minutes — that's fine, it runs once offline.

Tests (`tests/test_demo_cache.py`): build on a tiny synthetic DB fixture
(reuse patterns from `tests/test_charging_tools.py`); assert table shapes,
NULL-for-unknown, bbox membership, determinism (same input → same bytes
apart from build time).

Acceptance: cache builds on the real DB; file < 20 MB; printed summary shows
site counts (expect ~51 sites, Bolzano subset > 0).

---

### Phase 2 — Data tools + evidence registry (≤ 1.5 h)

`backend/acs/demo/tools.py` — six read-only tools over the cache, each with a
pydantic args model (bounded, no SQL/URLs from the model) and a compact result
(< 4 KB JSON):

1. `dataset_overview()` — sources, date coverage, number of sites/points,
   licence/attribution, analysis window. (Lets the report cite *resources*.)
2. `list_sites(area: "bolzano"|"all", limit≤60)` — id, name, points, power,
   coordinates.
3. `site_utilization(site_ids≤15)` — occupancy fraction, exposure hours,
   observed starts, peak hour, coverage, stale.
4. `rank_sites(metric: "occupancy"|"observed_starts", area, top_n≤15, order)`
   — ranked list; expansion candidates = most saturated.
5. `hourly_profile(scope: "bolzano"|"all"|site_id, weekday?: 0-6)` —
   weekday×hour occupancy grid + the 3 lowest-usage 2-hour windows.
6. `data_quality(site_ids≤15)` — coverage, gaps, staleness.

`backend/acs/demo/evidence.py` — `EvidenceRegistry` per report: each tool
call registers `E<n>` with `{id, tool, args, source: {dataset, table, window,
cache_built_at, db_fingerprint}, summary, data}`. Tool output returned to the
model **includes `evidence_id`** and a one-line `summary`. Identical calls
return the same id (dedupe by args hash).

Tests (`tests/test_demo_tools.py`): each tool on the synthetic cache; arg
validation rejects out-of-range input; evidence ids sequential & deduped;
**every tool < 300 ms on the real cache** (mark this test `@pytest.mark.slow`
and skip if `data/demo_cache.sqlite` is missing).

---

### Phase 3 — Engines and pipeline (≤ 3 h)

**3.1 Events & bus** (`events.py`): pydantic models from §2; `RunBus` with
`publish(event)` (assign seq, persist, fan out to asyncio queues) and
`subscribe(after_seq)` (replay persisted, then live).

**3.2 Engine interface**:
```python
class Engine(Protocol):
    async def run_agent(self, *, agent: str, system: str, prompt: str,
                        tools: list[ToolSpec] | None, max_turns: int,
                        emit: Callable[[Event], Awaitable[None]]) -> str: ...
```
Returns the final text; emits `agent_thought`, `tool_call`, `tool_result`,
`report_delta` while running.

**3.3 `engines/claude_sdk.py`**: wraps the six tools with the SDK `@tool`
decorator inside one in-process MCP server (`demo`); allowed tools =
only `mcp__demo__*`; built-ins disabled; settings sources off;
`include_partial_messages=True`; maps text deltas → `report_delta` (writer) or
`agent_thought` (researcher, throttled to sentence boundaries); maps tool use
→ `tool_call`/`tool_result` (the result side comes from our own tool wrapper,
which also registers evidence). Model from `ACS_DEMO_MODEL`.

**3.4 `engines/mock.py`**: deterministic: calls the real tools on the cache
(so evidence is real), then streams a templated Markdown report built from
those results in ~40-char chunks with small sleeps (configurable speed,
default finishes in ~15 s). Clearly prefixes the report with
`> MOCK — scripted, no AI model`.

**3.5 `engines/replay.py`**: reads `fixtures/demo/<task>.jsonl`, re-emits
events with original inter-event delays × `ACS_DEMO_REPLAY_SPEED`
(default 1.0). Evidence data comes from the fixture. `run_started.engine =
"replay"`, UI shows a `REPLAY` badge.

**3.6 `pipeline.py`** — the three agents:

- **Researcher** (tools, `max_turns≈8`, hard wall-clock budget 50 s):
  system prompt: role, the six tools, "call `dataset_overview` first, then
  the minimum tools needed, prefer parallel calls, stop after ≤ 6 calls",
  output = a terse fact sheet: bullet facts each ending with `[E#]`.
  On timeout: cancel, proceed with evidence collected so far, emit
  `agent_thought` "time budget reached, writing with N evidence items".
- **Writer** (no tools, budget 45 s): input = task + fact sheet + compact
  evidence index (id, tool, summary). Streams Markdown with fixed sections:
  `## Answer` (2-3 sentences), `## Key findings` (bullets with numbers +
  `[E#]`), `## Recommendation`, `## Limitations & unknowns`,
  `## Sources` (list each cited E# → tool, dataset, window). Rules in prompt:
  every number must come from the evidence with its `[E#]`; unknown ≠ zero;
  status observations are occupancy, not energy/sessions/faults.
- **Reviewer**: (a) run `verifier.py` (deterministic, < 100 ms) → emit
  `verification`; (b) one short LLM call (no tools, budget 15 s, may be
  skipped via `ACS_DEMO_REVIEWER=off`) producing a 2-4 bullet `review_note`
  (strongest caveat, any untraced number). Non-blocking: the report is never
  rewritten.

Overall hard cap 120 s → `run_finished.status="partial"` if exceeded, never a
hang. Always emit `run_finished`.

Prompts live in `backend/acs/demo/prompts.py` as constants; keep them short.
Domain wording (charging) lives in the prompts/tools of the demo package only.

Tests (`tests/test_demo_pipeline.py`) with the mock engine and a fake engine:
event order (`run_started` → researcher phase → tool events → writer deltas →
verification → `run_finished`); timeout path yields `partial`; researcher
failure still produces a report saying data was unavailable; replay reproduces
an identical event sequence.

---

### Phase 4 — Citation verifier (≤ 1 h)

`verifier.py`, pure function `verify(markdown, registry) -> Verification`:
- extract `[E\d+]` refs; unknown ids → `unknown_ids`;
- split into sentences/bullets; for each, extract numbers (handle `12.6%`,
  `0.126`, `1,234`, `12,6` Italian decimals, `14:00`/hours, dates); a number
  is **traced** if it appears (with rounding tolerance: same value at the
  displayed precision; % ↔ fraction ×100) anywhere in the `data` of an
  evidence item cited **in the same sentence/bullet**; ignore numbers that
  are section numbers, years in the task text, `E#` ids, and the task's own
  quantities (e.g. "20", "2027");
- untraced numbers → list with the sentence.
UI shows "✓ 14/15 figures traced to data" and highlights untraced ones.

Tests (`tests/test_demo_verifier.py`): table-driven, ≥ 15 cases incl.
percent/fraction, Italian decimals, uncited number, wrong-id citation,
number in a different bullet than its citation.

---

### Phase 5 — API v3 (≤ 1 h)

`backend/acs/demo/api.py`, `APIRouter(prefix="/api/v3")`, included in
`backend/acs/api.py` (one additive line; v2 untouched):

- `POST /api/v3/reports` `{task: str (≤ 2000), preset?: "expansion"|"maintenance", engine?: "claude"|"mock"|"replay"}` → `{report_id}`; starts the pipeline as an `asyncio` task immediately (no polling worker). Default engine: `claude` if the spike's auth check passes at startup, else `mock` (expose which in health).
- `GET /api/v3/reports/{id}/stream` — SSE, push-based, honours `Last-Event-ID`, heartbeat every 10 s, closes after `run_finished`.
- `GET /api/v3/reports/{id}` — final snapshot (task, markdown, evidence index, verification, timings).
- `GET /api/v3/reports/{id}/evidence/{eid}` — full evidence item.
- `GET /api/v3/presets` — the two demo tasks.
- `GET /api/v3/health` — engine availability, model, cache built_at.
- `POST /api/v3/reports/{id}/save-fixture` — dev only (env flag), writes the run's events to `fixtures/demo/<preset>.jsonl`.

Allow `GET`/`POST` CORS as v2 does. Add the v3 OpenAPI to
`scripts/export_contracts.py` only if cheap; otherwise hand-write TS types in
`frontend/demo/types.ts` mirroring §2.

Tests: FastAPI `TestClient` with mock engine — create, stream to completion,
reconnect with `Last-Event-ID` mid-stream gets no duplicates, evidence
endpoint 404 for unknown id.

**Demo tasks** (`GET /api/v3/presets`; also used by rehearsal):
1. **expansion** — "We want to add 20 charging points by 1 March 2027. Using
   the observed usage data, which existing sites/areas show the highest
   saturation and are the best candidates? Give a ranked shortlist with the
   data behind it."
2. **maintenance** — "When should we schedule maintenance on the charging
   stations in the Bolzano area to minimise impact on users? Propose concrete
   weekday/time windows backed by observed usage."
Free-text tasks are accepted too.

---

### Phase 6 — Frontend demo view (≤ 3 h)

New entry `frontend/demo/` (keep `frontend/main.ts` workspace intact). Route:
`index.html?view=demo` or a new `demo.html` Vite entry; make the demo the
default landing when `VITE_DEMO=1`.

Layout (desktop first, must not break at 1280×720 projector resolution):

```
┌ header: task title · engine badge (LIVE/REPLAY/MOCK) · model · ⏱ 00:47 ┐
├───────────────┬────────────────────────────────────┬─────────────────┤
│ Agents        │ Report (streaming Markdown)        │ Evidence panel  │
│ ● Researcher  │ ## Answer …▍                       │ E3 rank_sites   │
│   ↳ rank_sites│ ## Key findings                    │ args, source,   │
│     E3 · 180ms│ - Site X 87% occupancy [E3]        │ window, table   │
│ ○ Writer      │                                    │ of data         │
│ ○ Reviewer    │                                    │                 │
├───────────────┴────────────────────────────────────┴─────────────────┤
│ ✓ 14/15 figures traced to data · review note …                       │
└──────────────────────────────────────────────────────────────────────┘
```

- Start screen: two preset cards + free-text box + "Run" button. One click to
  start.
- Agent lane: phase status dots, live `agent_thought`, each tool call as a row
  (tool, short args, latency, evidence chip). Animate arrival.
- Report: render Markdown incrementally. Use `marked` (pin an exact version)
  and sanitise output (`DOMPurify`, pinned) — or a small in-house renderer for
  headings/lists/bold/tables if dependencies are undesirable. Re-render on
  each delta with `requestAnimationFrame` batching; auto-scroll unless the
  user scrolled up. Replace `[E3]` with clickable chips.
- Evidence panel: on chip click, fetch `/evidence/{eid}`, show tool, args,
  dataset/source/window, summary, and data as a table (first 20 rows).
  Untraced numbers from `verification` get a dotted underline + tooltip.
- Footer: verification summary + reviewer note; total time.
- Errors: visible banner; "Retry" re-posts the same task.

Tests:
- `frontend/tests/demo.spec.ts` (Playwright, against the mock engine via a
  small test server or mocked fetch/EventSource): start preset → agent rows
  appear → report text grows → citation chip opens evidence → verification
  footer shows → finishes < 30 s in mock.
- `npm run typecheck` green.
- Take a screenshot at 1280×720 and inspect it.

---

### Phase 7 — Hardening and rehearsal (≤ 2 h)

1. **Warm-up**: on server start (when engine=claude) run a 1-token no-tool SDK
   call in the background so the first demo run doesn't pay CLI cold-start;
   also open the cache DB once.
2. **`scripts/demo_rehearsal.py`**: runs each preset N times (default 3,
   live) through the HTTP API, prints per run: total time, time-to-first-report
   token, tool calls, evidence count, verification ratio, status. Writes
   `docs/demo-rehearsal.json`.
3. **Quality gate** (must pass on ≥ 5 of 6 live runs):
   - total time ≤ 120 s, first report token ≤ 45 s;
   - ≥ 3 distinct tools called, `dataset_overview` among them;
   - 0 unknown evidence ids; ≥ 90 % of numbers traced;
   - all five report sections present; `Sources` lists every cited id.
   If it fails: tighten prompts (fewer calls, explicit tool order), lower
   `max_turns`, try the other model, reduce Writer verbosity
   (target 250-400 words). Re-run. Record each iteration.
4. **Record fixtures**: save the best passing run per preset to
   `fixtures/demo/expansion.jsonl` and `maintenance.jsonl`; test that replay
   of each completes and passes the verifier.
5. **Kill-switch drill**: with network disabled (or `ACS_DEMO_ENGINE=replay`),
   the demo still runs end to end from fixtures.

---

### Phase 8 — Docs and handoff (≤ 45 min)

- `docs/DEMO-SCRIPT.md`: exact commands (`make demo-setup`, `make demo-cache`,
  `make api`, `VITE_DEMO=1 npm run dev`), pre-flight checklist (Claude login
  valid: `claude -p "ok"`; cache present; health endpoint shows engine=claude),
  a 2-minute talk track keyed to what appears on screen, and the fallback
  procedure (switch to replay with one env var / UI toggle).
- README: short "2-minute demo" section linking the script.
- `docs/DEMO-FAST-PROGRESS.md`: final table of tests, rehearsal stats,
  known limitations (occupancy ≠ demand/energy; Bolzano = bounding box;
  no forecasts in the demo path; replay is a recording).
- Final run: `make test`, `npm run typecheck`, `npm run test:frontend`,
  `pytest tests/test_demo_*`, one live rehearsal of each preset. Report
  results honestly, including anything skipped.

---

## 5. Definition of done

- [ ] `make demo-setup && make demo-cache && make api` + `VITE_DEMO=1 npm run dev` gives a working demo page.
- [ ] Clicking a preset shows agent/tool activity within 3 s and report text within 45 s; finishes ≤ 120 s on ≥ 5/6 rehearsal runs.
- [ ] Every number in the report is cited `[E#]`; clicking a citation shows the exact tool, args, dataset window and data; verifier ≥ 90 % traced.
- [ ] `REPLAY` and `MOCK` modes work offline and are visibly labelled.
- [ ] v2 flow and all pre-existing tests unchanged and green.
- [ ] Docs: `DEMO-SCRIPT.md`, `DEMO-FAST-PROGRESS.md`, README section.

## 6. Explicitly out of scope

Human-in-the-loop questions, approvals, proposal versioning, multi-round
debate, Timestral job execution, OpenAI v3 engine, local models, auth,
deployment, refactoring v2 code.
