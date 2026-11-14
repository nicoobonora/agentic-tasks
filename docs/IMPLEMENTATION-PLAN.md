# Implementation plan: evidence-driven charging agents

Status: planning only. No implementation is authorized by this document alone.
Prepared 2026-11-14 against the current repository. Execute the numbered steps
in order once implementation is requested. Reinspect the repository before
starting; filenames marked “new” below are proposed, not existing capabilities.

## 1. Intended outcome and boundaries

The user starts a goal-only ticket, for example:

- “We want to add 20 charging stations by March 1, 2027.”
- “When should we perform maintenance on charging stations in the Bolzano area?”

The ticket does not contain a dataset, an analysis, a predetermined conclusion,
or a long instruction template. The server provides the charging workspace's
capabilities. Agents discover relevant sites and data, request calculations and
forecasts when appropriate, inspect the results, debate alternatives, and ask
humans for business decisions or unavailable external information.

The final proposal identifies evidence, dates, uncertainties, prerequisites and
unresolved decisions. Approval approves the proposal only. No procurement,
maintenance dispatch, equipment control, or external messages are executed.

“Source of truth” means authoritative records for the fields actually observed,
with provenance and quality limits. ODH status observations are not ground truth
for unmet demand, physical faults, official sessions, energy, future usage,
installation feasibility or costs. Derived estimates remain estimates.

Keep the orchestration domain-neutral. Charging profiles, tool implementations,
metrics and decision rules belong under `backend/acs/examples/charging/`.
Retain generic runs for regression tests and other workspaces. The charging
workspace must not silently act as a generic chatbot for unrelated tasks.

Not part of this delivery: arbitrary task-creation forms, global run search,
multi-user authentication, a plugin marketplace, a workflow designer, a Mistral
chat-provider migration, or production deployment. Record these separately;
do not use them to expand this implementation. Timestral is the forecasting
model; the existing OpenAI adapter remains the discussion provider.

## 2. Starting point and known constraints

Reusable code:

- `backend/acs/discussion.py`: bounded turns, versions, questions, approval,
  idempotency, leases and persistent state.
- `backend/acs/providers.py`: role prompts and structured model responses.
- `backend/acs/db.py`, `api.py`, `agent_port.py`: persistence, worker, SSE,
  and a second message-publication path that must obey the same checks.
- `backend/acs/examples/charging/`: data APIs, provenance, quality,
  forecasting, capacity analysis and scenario catalog.
- `frontend/main.ts`, `client.ts`: discussion workspace and API transport.
- Existing Python and Playwright suites and contract-export commands.

Gaps and constraints verified during planning:

- The frontend's tickets come from `frontend/mock.ts`, even in API mode.
- Agents cannot request data or tools. Context consists of the task, attached
  evidence, discussion, proposal and objections.
- Evidence origins currently cover only user input, reference URLs and human
  answers. Tool-derived evidence needs a real contract extension.
- The charging task endpoint supplies a frozen snapshot only when explicitly
  called; it is not a tool-use implementation.
- Forecast `run()` currently uses three hard-coded sites, an AC <=22 kW subset,
  and horizons of 1–168 hours. It cannot justify a March 2027 demand forecast
  from November 2026. Do not silently extend predictions by repeated chaining.
- The latest inspected real artifact has usable-target fractions of roughly
  12.6%, 16.2%, and 0%; all three sites are unavailable. It records zero model
  inference calls. This is a baseline observation, not an eternal property.
- The forecasting capacity threshold is 90%, while the simulated catalog uses
  95%. Expose and reconcile the policy explicitly; never mix the two silently.
- The current lease is 180 seconds. A multi-call turn or a forecast can exceed
  it; long work cannot simply be inserted inside the existing `generate()`.
- Mock and model modes must remain visibly distinct. A real forecast can select
  the seasonal baseline; that result must not be labeled a Timestral win.

## 3. Execution rules for the implementing agent

1. Read `AGENTS.md`, `docs/BACKEND.md`, `docs/FRONTEND.md` and
   `docs/CHARGING.md` before the corresponding work. Preserve user changes.
2. Complete one numbered step at a time. Run its relevant tests and fix failures
   before advancing. A blocked external input does not justify fabricated data.
3. Keep a progress log with status, changed files, commands/results, remaining
   limitations and decisions. Use pending/in progress/implemented/verified;
   distinguish software verification from validation on real data.
4. Use temporary databases for tests and smoke runs. Never clear the user's
   database, replace real observations with fixtures, or run destructive resets.
5. Baseline tests must not call paid models, download datasets or load large
   model weights implicitly. Isolate live checks in explicitly invoked targets.
   Any unavailable external validation is reported as unverified, not passed.
6. Regenerate schemas/types whenever a public contract changes. The prior note
   deferring frontend type regeneration does not justify stale contracts during
   this authorized future implementation. Do not hand-edit generated files.
7. No repeated approval requests for routine authorized coding. Missing domain
   facts are runtime questions or explicit limitations. Pause dependent work
   only when a material requirement genuinely cannot be determined.
8. Do not claim that an LLM citation check proves semantic truth. Enforce the
   measurable parts deterministically and evaluate the rest with a rubric.

## 4. Step-by-step implementation

### Step 01 — Record a reproducible baseline

Actions:

- Inspect the working tree, installed dependencies, current contracts and tests.
- Run `make test`, `npm run build`, and `npm run test:frontend`.
- Read the local data in read-only mode: record source/date ranges, site counts,
  latest forecast IDs, model calls and availability without exposing secrets or
  copying private discussion text into reports.
- Add `docs/IMPLEMENTATION-PROGRESS.md` with the baseline and this plan's checklist.

Acceptance/tests:

- Every baseline failure or skip is recorded with its cause.
- No database mutation, external model call or data refresh occurs.
- Later tests can distinguish a pre-existing failure from a regression.

### Step 02 — Define the charging workspace profile and contracts

Likely files: `models.py`, new generic profile/tool models, new
`examples/charging/profile.py`, contract exporter, generated client types.

Actions:

- Add an optional generic capability-profile identifier to run creation;
  preserve the current generic behavior when omitted. The charging workspace
  selects the charging profile independently of the ticket wording.
- Persist the selected profile ID/version in the run. Unknown profiles fail
  validation; a model cannot choose arbitrary capabilities by naming them.
- Define models for tool requests, tool outcomes, tool-call records, analytical
  jobs, structured metric references and evidence metadata.
- Tool outcomes distinguish `available`, `unavailable`, `needs_clarification`
  and execution error. Jobs use queued/running/succeeded/failed. A succeeded
  job can produce an unavailable analytical result.
- Include IDs, run/turn linkage, normalized parameters, times, source/snapshot
  fingerprints, method/version, units, limitations and immutable result links.
- Preserve old persisted runs and clients with additive defaults. Version any
  unavoidable breaking artifact change explicitly.
- Keep charging-specific tool argument schemas outside generic Run/AgentTurn.

Acceptance/tests:

- Old runs still deserialize; an old generic CreateRun still works.
- Unknown tool/profile, extra arguments and invalid dates/units are rejected.
- Evidence origins distinguish observations, derived metrics, forecasts,
  human preferences and simulated business inputs.
- `make contracts`, typecheck and schema/export consistency checks pass.

### Step 03 — Persist tools, evidence and jobs safely

Likely files: `db.py`, new `tools.py`/`jobs.py`, `discussion.py`, `api.py`.

Actions:

- Add non-destructive persistence for tool calls, immutable artifacts, job
  status and resumable per-role turn progress. Use explicit schema migration
  or idempotent additive initialization; retain existing records.
- Store large artifacts separately. Run snapshots carry bounded summaries and
  references, not all observations or hourly series on every SSE event.
- Tie every result attachment to an expected run cycle, role and turn token.
- Define content hashes and cache keys using normalized inputs, source snapshot,
  implementation/model version, policy parameters and forecast origin.
- Publish tool/job progress through existing snapshots with additive fields.
  Add read endpoints for paginated tool history and scoped artifact detail.
- Define replay semantics: retries reuse a persisted logical tool call; changed
  data or parameters create a distinct result. Cache never means “latest wins.”

Acceptance/tests:

- Concurrent duplicate requests produce one logical job/result attachment.
- Crash before/after result commit does not duplicate evidence or lose a job.
- Changed data, cutoff, threshold or model revision invalidates cached reuse.
- An artifact from another run cannot be used as evidence without an explicit,
  provenance-preserving attachment operation.
- Status and SSE stay responsive while work is pending; snapshots are bounded.

### Step 04 — Implement read-only charging discovery tools

New module: `examples/charging/tools.py` with typed handlers.

Initial tools:

- `charging.discover_sites`: resolve site IDs, source, area and coordinates.
- `charging.get_inventory`: charging points/connectors, metadata and dates.
- `charging.get_data_quality`: observation coverage, gaps, source freshness,
  missing fields and known normalization assumptions.
- `charging.get_evidence`: bounded detail for authorized evidence references.

Actions:

- Use parameterized queries and controlled argument schemas; never expose
  arbitrary SQL, shell, file paths, unrestricted URLs or executable expressions.
- Resolve areas through verified metadata or documented geographic boundaries.
  Return candidate matches for ambiguous names instead of guessing.
- Return explicit empty/no-data results; distinguish absent inventory from zero
  capacity. Separate legacy/current sources and flag unvalidated identity joins.
- Take consistent snapshots and record valid time, source transaction time,
  acquisition time and query time as appropriate.
- Make raw reads bounded/paginated; compute aggregates outside the language model.

Acceptance/tests:

- Known/unknown/ambiguous areas, duplicate names, empty DB and stale inventory.
- SQL-like input remains a literal argument; oversized queries are rejected.
- Different sources are never silently merged by site name.
- Returned evidence hashes resolve to the records used in the result.
- The selected area returns only the intended sites; missing coordinates are
  reported rather than silently assigning membership.

### Step 05 — Implement observed metrics and maintenance-window analysis

New module: `examples/charging/metrics.py`; reuse normalization/reconstruction.

Actions:

- Implement deterministic coverage-aware occupancy and operational-capacity
  summaries, observed start counts, and local hour/day-of-week profiles.
- Preserve unknown intervals, censored episodes and zero-capacity distinctions.
  Do not rename observed starts as official sessions or observed unmet demand.
- Add `charging.get_usage_summary` and `charging.compare_maintenance_windows`.
- Window analysis accepts sites, duration, permitted dates/hours and constraints.
  Compare expected disruption only on adequate comparable observations; show
  sample counts, coverage, timezone and ranking rationale.
- Return historical-pattern suggestions as such. Scheduling a future specific
  date may require a forecast or an explicit conditional assumption.
- Separate “least disruptive time” from “equipment is due for maintenance.”
  The latter requires equipment rules, faults or maintenance records.

Acceptance/tests:

- Hand-calculable fixtures verify aggregation and window ranking.
- Unknown periods do not become zero-demand windows; gaps are never bridged
  beyond the declared rule; fully unavailable sites are not “ideal quiet sites.”
- Europe/Rome daylight-saving transitions, midnight-spanning windows, partial
  groups, censored durations and fewer than four comparable dates are covered.
- Missing maintenance records yield unknown need, not a fabricated due date.
- Output changes predictably when known input utilization changes.

### Step 06 — Diagnose real-data readiness before changing thresholds

Actions:

- Produce a reproducible report by site/source/period: observation cadence, gaps,
  eligible AC points, coverage lost to each check, recent usable hours and
  comparable-date support. Separate acquisition gaps from preprocessing loss.
- Investigate physical identities and capacity changes across legacy/current
  feeds; preserve unresolved mappings as unresolved.
- Measure sensitivity to alternative gap assumptions without selecting the
  value that makes a desired recommendation possible.
- Define an operational data-refresh procedure using existing download tools:
  explicit date ranges, source limits, retries, cache semantics and provenance.
  Agents may report stale data; the first delivery need not allow arbitrary
  model-triggered internet downloads.
- Document evidence-backed revisions to reconstruction if justified. Version
  methods and invalidate affected caches. Otherwise retain unavailable results.

Acceptance/tests:

- Fixture gaps and missing points produce expected diagnostic reason counts.
- No future observations/revisions enter a cutoff-based reconstruction.
- Any reconstruction change has before/after metrics and focused regressions.
- Report states whether real data is usable. “Pipeline implemented” is never
  recorded as “real forecast validated” solely because tests pass.

### Step 07 — Refactor forecasting into a reusable request-based service

Likely files: `forecast.py`, `forecast_models.py`, `scripts/forecast_charging.py`,
`analysis_contract.py`, charging models and their tests.

Actions:

- Refactor `run()` to accept explicit supported site IDs, cutoff, history,
  horizon and policy parameters. Preserve CLI defaults and existing artifacts.
- Separate input capture, eligibility checks, inference, backtest, scenario
  calculation and publication. Initialize model weights lazily, only when needed.
- Support site subsets without assuming every result has the old three-site/four-
  cell structure. Inspect the existing analysis validator before changing it;
  either extend it compatibly or introduce a versioned dynamic-scope artifact.
- Keep the supported 168-hour maximum initially. Reject out-of-range forecasts
  with a clear reason; do not turn a seven-day model into a March demand forecast.
- Treat the March date as a delivery deadline unless the user explicitly asks
  for demand at that date. Long-term demand modeling is a separate validated
  extension, not an unannounced part of this delivery.
- Make service thresholds explicit and consistent across scenario calculations,
  policy, input fingerprints and explanations. Handle 90% versus 95% openly.
- Select Timestral versus baseline using existing no-leakage backtesting rules.
  Return both scores, actual selected method and actual inference-call count.
- Attach analysis by `analysis_id`, never by independently taking “latest.”

Acceptance/tests:

- One site, multiple sites, unsupported DC group, no eligible points and unknown
  IDs produce correct results without accidental expansion of scope.
- Deterministic predictors exercise successful forecasting and scenarios.
- Insufficient data causes zero inference calls, no fabricated points and an
  explicit unavailable result. Missing dependencies/model errors are errors.
- Forecast outside 1–168 hours is rejected; current date and generation date
  cannot silently replace the requested forecast origin.
- Baseline victory, partial site availability, 90%/95% policies, quantile units,
  paired artifact IDs and contract compatibility are tested.
- Existing leakage/censoring/backtest tests continue to pass.

### Step 08 — Add durable on-demand forecast jobs

Actions:

- Register `charging.request_forecast` as a controlled analytical tool. Job
  creation is a mutation; do not start inference from an HTTP GET.
- Implement a separate bounded numerical worker/process so PyTorch does not
  block the API event loop or monopolize discussion worker threads.
- A request returns a job reference. Persist the waiting turn, release its
  short-lived worker lease, and resume the same role when the job completes.
- Keep Run state `running` with explicit pending-tool metadata unless a new
  public state is demonstrably needed. Waiting for computation is not a human
  question. The scheduler must not repeatedly call the LLM while waiting.
- Add job leases/heartbeats, recovery rules, deadlines, configurable concurrency
  and explicit retry behavior. Define shutdown behavior for active inference.
- Publish forecast and linked analysis atomically. A late job may retain its
  artifact, but cannot attach it to an obsolete cycle/turn or change approval.

Acceptance/tests:

- Job exceeds 180 seconds in a fake-clock test without losing or duplicating
  the discussion turn; avoid real sleeps in unit tests.
- Concurrent requests deduplicate correctly; other discussions and SSE respond.
- Restart with queued/running/finished-but-unattached jobs recovers safely.
- Timeout, process failure, unavailable data and missing weights have distinct
  outcomes. Failure never falls back to synthetic predictions.
- Human resumption/retry/version changes prevent stale result publication.
- No duplicate UI polling requests cause additional forecast work.

### Step 09 — Implement the bounded agent tool-use loop

Likely files: `providers.py`, `discussion.py`, generic tool registry and models.

Actions:

- Extend the provider interface to return either typed tool requests or a final
  AgentTurn. Keep tool requests distinct from public role messages.
- Integrate the model provider's supported tool protocol; inspect current
  official protocol documentation at implementation time. Test call IDs and
  result correlation explicitly; never parse commands from free-form prose.
- Persist each requested tool and feed its result back to the requesting role.
  Subsequent roles receive a shared evidence index and relevant summaries and
  may retrieve details or request their own calculations.
- A role advances only after its validated final contribution. An analytical
  job suspends/resumes that role; it does not consume a review round by itself.
- Enforce budgets in code: start with at most 8 tool requests and 10 provider
  requests per role turn, including corrections; cap expensive unique forecast
  jobs at 2 per cycle. Make limits configurable within hard maximums and report
  the new worst-case cycle cost. This replaces the old two-call cost formula.
- Maintain bounded wall-clock deadlines, result sizes, context sizes and tool
  concurrency. Detect repeated equivalent requests using normalized keys.
- On budget exhaustion, surface an explicit incomplete assessment/human choice
  or error. Never silently declare consensus.
- Preserve native provider failures and the bounded correction behavior; do not
  switch a failed model call to mock.

Acceptance/tests:

- Controlled provider requests discovery -> quality -> usage -> final message.
- Forecast request -> persisted wait -> result -> same-role continuation works.
- No-tool generic task still works; unrelated tasks cannot use charging tools
  without the profile. Unknown tools and malformed args never execute.
- Repeated tool calls hit cache/budget; parallel calls are correlated correctly.
- All provider/tool calls count toward budgets, including corrections/retries.
- Retrieved text cannot expand permissions or override role instructions.
- Restart after a tool result preserves context without duplicate messages.

### Step 10 — Enforce evidence-backed charging conclusions

Actions:

- Write charging-profile instructions covering scope, discovery, source
  limitations, units, tool selection and when clarification is necessary.
- Require retrieval before site-specific factual conclusions. A supplied human
  preference cannot stand in for observed utilization or forecast output.
- Add structured references for decision-critical numerical claims: evidence
  ID, metric path, value, unit, site and period. Validate these against immutable
  tool artifacts with an explicit numerical tolerance policy.
- Link proposal actions to supporting evidence and assumptions. Forecast claims
  must reference an available result with matching site and horizon.
- Enforce these checks through every publication path, including agent_port.
- Critic must address evidence sufficiency, competing interpretations and open
  objections. Domain evaluation should check whether explanations actually
  support the conclusion, beyond merely existing evidence IDs.
- A conditional proposal may recommend collecting data or verifying capacity.
  It must not use “conditional” to bypass blocking unsupported investment claims.

Acceptance/tests:

- Invented evidence IDs, mismatched units/sites/periods, altered numerical values,
  unavailable forecasts and stale results cannot support numerical assertions.
- A citation to unrelated evidence fails the structured metric check.
- A human answer saying “assume it is working” remains an assumption.
- Mock evidence and simulated prices cannot become observed facts.
- Blocking objections still prevent approval, including through alternate APIs.
- Irrelevant task receives a scope explanation/clarification in charging mode;
  the same task remains usable in generic mode.

### Step 11 — Add operational inputs and decision-specific analysis

New domain models/services; reuse catalog only with its simulated labels.

Actions:

- Define optional versioned records for verified connection capacity, permits,
  lead times, quotes, budgets, working calendars, maintenance history, fault
  reports and equipment maintenance requirements. Each carries provenance,
  effective dates and real/simulated/assumed classification.
- Provide validated import/read tools for available records. Missing facts
  remain missing; do not manufacture an enterprise integration.
- For expansion, clarify “20 stations” versus chargers/points/sites, geography,
  budget, service target and deadline. Treat 20 as a business target, not a
  quantity already supported by demand.
- Compute quantities/costs/lead-time dependencies with deterministic services.
  Show whether constraints are satisfied, violated or unknown; distinguish
  optional demand-based allocation from deadline feasibility.
- For maintenance, combine low-disruption windows with verified duration,
  operational constraints and equipment requirements when available.
- Forecast only if the decision needs future usage and the requested horizon is
  supported. Lack of a forecast is not always a blocker for inventory questions.

Acceptance/tests:

- Charger-to-point conversion cannot silently assume one-to-one equivalence.
- Missing permits/quotes/maintenance history result in unknown feasibility/need.
- Controlled business fixtures verify totals, tax basis and dependency dates.
- Contradictory deadlines, required outage durations and budget constraints are
  surfaced, not resolved through fabricated facts.
- Synthetic end-to-end feasible/infeasible plans are labeled synthetic.
- An unsupported March demand request does not reuse a seven-day forecast.

### Step 12 — Replace demo tickets with goal-only charging goals

Likely files: new `frontend/tasks.ts`, `frontend/main.ts`, `frontend/mock.ts`.

Actions:

- Separate the ticket catalog from the mock client's implementation.
- Provide two tickets: expansion by March 1, 2027 and maintenance in Bolzano.
  Use short goals without attached data or predetermined recommendations.
- Select the charging capability profile at workspace/run configuration level.
  Do not call the old snapshot task endpoint to prefill hidden attachments.
- Preserve explicit local mock versus API model configuration. Mock scenarios
  must be visibly scripted; keep generic/failure fixtures in tests as needed.
- Update stale demo documentation so the previously prepared attachment-based
  JSON is identified as an earlier manual fixture, not the target architecture.

Acceptance/tests:

- Inspect the outgoing create-run payload: goal text, charging profile and no
  dataset attachments. No live queries occur in local mock mode.
- In API model mode, real server tool requests appear after task submission.
- Existing multi-run, drag/drop, keyboard start and retry behavior still works.
- No task creation form is added as an incidental scope expansion.

### Step 13 — Show investigation, forecasts and evidence in the UI

Likely files: `frontend/main.ts`, `client.ts`, `examples/charging.ts`, styles/types.

Actions:

- Show tool activity, selected sites/date ranges, job progress, cached reuse,
  completed results, unavailable reasons and execution errors.
- Provide expandable evidence details and clickable claim-to-evidence links.
  Display observation dates, source freshness, coverage, units and origin.
- Render forecast points only when available; otherwise show the reason.
  Display actual selected method, prediction horizon, backtest and limitations.
- Distinguish model discussion from forecasting method. Avoid presenting a
  current generation timestamp as a current-data forecast origin.
- Keep input drafts/focus intact during SSE updates. Resume display after refresh
  using server-persisted tool state, not frontend timers that invent progress.
- Expose proposal versions sufficiently to see changes prompted by evidence.
  Preserve blocking objections and approval semantics.

Acceptance/tests:

- Pending/succeeded/unavailable/failed forecast states render accurately.
- Unavailable is never a zero curve; baseline selected is not labeled Timestral.
- Evidence links open the exact cited artifact, not the latest unrelated result.
- SSE reconnect, polling fallback and page refresh do not restart tools/jobs.
- Keyboard access, narrow-screen layout, long text, escaping untrusted content,
  and draft preservation pass browser tests.

### Step 14 — Add real frontend-to-backend integration tests

Actions:

- Add a Playwright project that starts Vite and Uvicorn with a temporary DB,
  a controlled provider and deterministic numerical predictor. Control provider
  injection only in test configuration; do not expose a public bypass endpoint.
- Exercise actual HTTP, SSE, persistence and job scheduling. Keep the existing
  local simulator tests, but label their different assurance level.
- Add two end-to-end paths plus critical negative cases from the matrix below.

Acceptance/tests:

- Expansion: goal only -> clarify units/scope -> retrieve data -> inspect
  calculations/forecast where needed -> disagreement/revision -> proposal.
- Maintenance: goal only -> resolve area -> inspect quality/usage -> request
  forecast if appropriate -> compare windows -> conditional recommendation.
- Both include verifiable evidence links and at least one human decision.
- Backend restart during a job and browser refresh preserve progress.
- Demonstrably stale approval and unavailable-data cases remain protected.

### Step 15 — Run optional live validations and evaluate usefulness

Actions:

- Add explicit smoke commands for real model discussion and real Timestral.
  Do not make these part of ordinary unit tests. Use an isolated run database
  with a consistent read-only source snapshot or SQLite backup, not a naive
  copy of an active WAL database.
- Run when credentials/dependencies and authorized external access are available.
  Record model/version, time, data snapshot, tool trace, forecast origin,
  backtest, actual inference calls, limitations and estimated/observed usage.
- Validate actual model tool selection on both tickets and an unrelated task.
- If real observations fail checks, validate honest unavailable behavior and
  retain the blocker. A separate synthetic-series Timestral test proves the
  integration path only, never real forecasting usefulness.
- Evaluate public explanations with the rubric below; do not require exact
  wording or deterministic live-model transcripts.

Acceptance/tests:

- The real model actually retrieves data; tool trace proves the evidence path.
- At least one forecast-enabled integration test proves inference was invoked
  on eligible input, separately from real-data availability.
- Results are classified as controlled-test verified, live-protocol verified,
  or real-data analytically validated. Missing live checks are explicit.
- No API keys, sensitive prompt contents or credentials enter test artifacts.

### Step 16 — Final compatibility, documentation and handoff

Actions:

- Update README, BACKEND, FRONTEND, CHARGING and the progress log for the final
  architecture. Include setup for numerical workers/dependencies, invocation,
  deadlines/budgets, restart behavior and all unavailable/error states.
- Run `make contracts`, `make test`, `npm run build`, all frontend projects and
  `git diff --check`. Confirm a second contract export has no unintended drift.
- Provide the demo operator steps and an evidence trace from each scenario.
- List implemented versus externally blocked analytical/business capabilities.
  Do not mark the real-data outcome complete because synthetic fixtures pass.

Acceptance:

- All required offline tests pass; numerical tests actually run in the numerical
  validation environment. Skips and optional live checks are reported separately.
- Both goal-only tickets work through the real API with shared evidence.
- Existing generic behavior and persisted runs remain compatible.
- No hidden fixture answers, silent mock fallbacks or unreported scope changes.

## 5. Acceptance matrix

| Scenario | Expected behavior | Test layer |
|---|---|---|
| Goal only, no attachments | Agent retrieves its own evidence | Provider integration + E2E |
| Unknown/ambiguous area | Return candidates or ask a precise question | Tool unit + E2E |
| Empty/stale local data | Explain absence/staleness; no invented utilization | Tool + discussion |
| Historical usage question | Compute observed metrics without unnecessary forecast | Provider integration |
| Eligible near-term forecast | Create job, run predictor, inspect result, cite artifact | Job + E2E |
| Real insufficient coverage | Return unavailable and explicit next requirements | Real-data report + smoke |
| Baseline wins backtest | Show seasonal baseline as selected | Numerical + UI |
| Forecast beyond supported horizon | Explain limitation, no extrapolation disguised as output | Contract + discussion |
| Source data changes | New fingerprint; old run retains its evidence | Persistence |
| Tool/model/job failure | Explicit error/retry; no replacement with mock | Integration |
| Duplicate request/restart | One logical result; no duplicate contribution | Concurrency + recovery |
| Unsupported numeric assertion | Reject metric reference or preserve blocking objection | Validation |
| Human preference contradicts data | Preference remains a preference, not a fact | Discussion |
| Maintenance need lacks records | Suggest investigation; do not diagnose equipment | Domain integration |
| Expansion lacks business inputs | Conditional plan with named missing constraints | Domain integration |
| Unrelated goal in charging profile | Clarify scope rather than generic completion | Provider evaluation |
| Unrelated goal in generic profile | Existing generic workflow continues | Regression |
| Browser refresh during inference | Resume progress; no extra forecast submission | E2E |
| User approves proposal | Record approval; execute no external action | E2E |

## 6. Live-model quality rubric

Assess each scenario against these criteria, with supporting trace references:

1. Retrieved the relevant sites and period before making factual conclusions.
2. Used analytical tools for quantitative claims rather than inventing numbers.
3. Requested forecasting only when relevant and within supported scope.
4. Correctly interpreted availability, freshness, method and uncertainty.
5. Operations and Finance identified real constraints and missing inputs.
6. Critic challenged a concrete weakness; revision addressed it or left it open.
7. Human questions concern unresolved choices/facts and do not repeat answers.
8. Final actions are supported or explicitly conditional, with traceable evidence.
9. No simulated catalog data or synthetic series is described as real evidence.
10. No execution, maintenance diagnosis or future feasibility is falsely asserted.

Any fabricated decision-critical number, hidden simulated input, unsupported
forecast horizon or false execution claim fails the scenario regardless of how
polished the proposal sounds. Record other shortcomings and rerun only the
relevant evaluations after changes. Passing this rubric on a few examples is
not a guarantee of general model reliability.

## 7. Milestones and completion criteria

- **Milestone A — evidence-aware backend:** Steps 01–06. Tools and reproducible
  observed metrics exist; agents are not yet claimed to use them autonomously.
- **Milestone B — autonomous investigation:** Steps 07–11. Agents can request
  tools and forecasting, share results and enforce structured evidence rules.
- **Milestone C — integrated demo:** Steps 12–14. Two goal-only tickets run
  through the actual frontend/backend with traceable analytical activity.
- **Milestone D — validated handoff:** Steps 15–16. Offline tests pass, live
  checks are recorded accurately and real-data/business limitations are explicit.

Software completion permits an honest unavailable result. Business readiness
for expansion or maintenance recommendations additionally requires suitable
observations, validated methods and the missing operational inputs. Report those
as separate outcomes; never collapse them into a single “100% done.”
