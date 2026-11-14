# Implementation progress

Authorized by the user on 2026-11-14. Work proceeds in plan order.
Software tests and real-data analytical validation are separate outcomes.

## Step 01 — verified baseline

Initial working tree clean. Python and numerical dependencies installed.
`make test`: 48 passed, TypeScript passed. `npm run build`: passed.
Initial `npm run test:frontend`: 2 passed, 3 failed because Vite inherited local
API/model settings. Fixed test isolation in `playwright.config.ts`: explicit local
mock configuration and no reuse of unrelated running servers. No source refresh,
model inference or deliberate production database mutation was performed.

Read-only SQLite inspection: 51 sites (8 Neogy, 43 Neogy-AMPECO), 669197
observations, valid times 2024-11-19T16:00:07.317Z–2026-11-14T00:22:16.057Z.
Latest forecast by ID: forecast:8f13d5ee-141b-43c7-a1d6-9ff31885d673,
generated 2026-11-14T01:07:32.509936Z; zero inference calls; all three sites
unavailable due to insufficient coverage/recent observations. Existing 120-minute
gap and 25% target thresholds retained. No real forecasting usefulness established.

## Checklist

| Step | Status | Main files / evidence |
|---|---|---|
| 01 Baseline | verified | Baseline above; Playwright isolation |
| 02 Profiles/contracts | implemented, offline verified | models.py, capabilities.py, profiles.py, generated contracts/types |
| 03 Durable tools/evidence/jobs | implemented, controlled verified | tools.py, jobs.py; immutable/scoped/replay/concurrency tests |
| 04 Discovery tools | implemented, controlled verified | examples/charging/tools.py; bounded/ambiguous/empty queries |
| 05 Metrics/maintenance windows | implemented, controlled verified | examples/charging/metrics.py; exposure, gaps, local time, windows |
| 06 Readiness diagnosis | verified on local archive | scripts/charging_readiness.py, charging-readiness.json |
| 07 Request-based forecasts | implemented, numerical tests verified | forecast.py, service.py; subsets, policy, lazy weights, leakage tests |
| 08 Forecast jobs | implemented, recovery verified | jobs.py; fake-clock >180 seconds and real process restart |
| 09 Agent tool loop | implemented, controlled and live protocol exercised | investigation.py, providers.py; call IDs, budgets, correction |
| 10 Evidence enforcement | implemented, negative tests verified | examples/charging/validation.py; live invalid claims rejected |
| 11 Operational inputs | implemented, controlled verified | operations.py, import_operational.py; unknown/simulated/Decimal totals |
| 12 Goal tickets | implemented, browser verified | frontend/tasks.ts; no hidden attachments |
| 13 Investigation UI | implemented, browser verified | main.ts/client.ts; immutable evidence, jobs, actual forecast method |
| 14 HTTP end-to-end tests | verified with controlled provider/predictor | frontend/integration; both goals, human decision, revision, restart |
| 15 Optional live validation | executed; maintenance usefulness failed | Live reports below; Timestral adapter verified separately |
| 16 Compatibility/handoff | offline verified; live limits retained | README/guides, operator steps below |

## Verification log

- Baseline browser rerun after isolation: 5 passed.
- Step 02: additive profile, evidence metadata, metric/tool/job/turn contracts;
  regenerated JSON schemas and TypeScript. 50 Python tests and typecheck passed.
- Step 03: immutable artifacts stored separately in existing additive document
  namespace, logical call replay, stale attachment guard and run-scoped retrieval.
  51 Python tests and typecheck passed. Durable scheduling remains step 08 work.
- Step 04: typed discovery/inventory/quality/evidence handlers. No free-form SQL.
  Six focused capability/discovery tests passed. Bolzano uses documented context
  bounding box, not an assertion of municipal membership.
- Step 05: positive-capacity exposure, observed starts, point-hours, historical
  windows with four comparable dates. 12 discovery/numerical tests passed,
  including insufficient observations, zero capacity and Rome DST date deduplication.

## Integration work (steps 06–14)

- Read-only readiness command completed for all 51 source-scoped sites. Five
  discovery/readiness tests passed; retained conservative reconstruction policy.
- Request-based forecasts accept supported site subsets, explicit cutoff and
  service threshold; analysis 1.1 permits subsets while old 1.0 remains valid.
  19 foundation/forecast tests passed; later lazy-loading regression fixed.
- Numerical jobs run in bounded subprocesses, with durable leases, heartbeat,
  deadlines, explicit failure and restart claim recovery. Source capture uses
  SQLite backup, never a naive active WAL file copy. Snapshot mismatch fails.
- Provider tool loop persists native call IDs and outputs separately from run
  snapshots. At most 10 provider calls / 8 tools per role and 2 forecast jobs per
  cycle. Controlled loop, correction and protocol tests pass.
- Metric equality, unit, site, period and available-result checks apply through
  the common publication validator, including agent_port. This is structural
  verification, not proof that a prose conclusion is semantically warranted.
- Versioned operational records/import and expansion arithmetic preserve missing
  constraints and simulated classifications. Controlled totals/unknowns pass.
- Goal catalog separated from local mock implementation; generic failure fixtures
  remain explicit test fixtures. Payload selects charging profile without data.
- UI shows persisted tool state, exact artifact details and proposal versions;
  no unavailable curve is fabricated. Production build passes.
- Real HTTP/SSE browser suite added with temporary SQLite, controlled provider,
  isolated numerical subprocess and deterministic predictor. Initial browser
  attempt reached proposals but timed out clicking a collapsed evidence detail;
  test now expands the detail before clicking. Both scenarios subsequently passed, including restart during the forecast job.
- Full Python suite at this point: 62 passed, no numerical skips.

## Live evaluation and limits

Real discussion provider: configured `gpt-5.6-luna`, 2026-11-14. All smoke runs
used a SQLite backup in a temporary directory, not the production discussion DB.
No human answers, approvals or source refreshes were synthesized. See
[investigation-live.json](investigation-live.json) for the initial three scenarios.

- Expansion: reached a precise human question about units and scope. No retrieval
  before that question; autonomous continuation after an actual business answer
  remains unverified live. The controlled E2E exercises that continuation.
- Unrelated poetry request: correctly explained charging scope and asked for a
  relevant reformulation; no unrelated generic completion or tool execution.
- Maintenance: the real provider selected discovery, quality and window tools.
  It did not reliably produce valid final numerical citations. Iterations exposed
  and fixed argument-correction replay, timestamp-schema clarity, pointer unit
  normalization and citation handle usability. The final recorded live attempt
  still failed the strict numerical-claim gate. No invalid contribution was
  published. This is **not a passed live usefulness evaluation**.
- [investigation-live-final.json](investigation-live-final.json) records the last
  evaluated attempt: 5 provider attempts, reported successful-response usage
  74,700 input / 4,287 output tokens. Earlier attempts did not record full usage;
  their cost must not be inferred from this single run. No total billing claim.
- [timestral-implementation-smoke.json](timestral-implementation-smoke.json): real
  cached-weight Timestral inference succeeded, output shape 2×168×3. It was not
  published as a usable forecast. Real coverage remains insufficient.

Rubric: live retrieval/tool selection was demonstrated for maintenance; scope and
human clarification were demonstrated for the other goals. Citation reliability
failed. Full live Operations/Finance/Critic discussion, resolution after real human
answers, and complete business recommendations remain unverified. Controlled
fixtures exercise those software transitions, not LLM semantic quality.

## Operator walkthrough and evidence traces

1. Start `make api`, then Vite in API mode. Choose mock explicitly for a scripted
   demonstration, or model with configured credentials for real discussion.
2. Start either goal-only ticket. The outgoing request contains the charging
   profile and goal text, with no attached dataset or frozen analysis.
3. Answer only the actual human question using real business information. Missing
   budget, permits, quotes, geography, units or maintenance records stay unknown.
4. Open Indagine e prove: each tool shows normalized parameters and persisted
   status. Open the exact cited artifact; check source dates, units, coverage,
   method and limitations. Generation time is not forecast origin.
5. For unavailable analyses, inspect reasons and decide whether to acquire data or
   supply operational records. Do not interpret missing forecasts as zero demand.
6. Review objections and proposal versions. Approval records document approval
   only; no purchase, dispatch, control action or external message is executed.

Controlled expansion trace: goal → clarify points/scope → discover_sites →
get_data_quality → get_usage_summary → assess_expansion (missing constraints
remain unknown) → critic objection → analyst revision → proposal → approval.
Controlled maintenance trace: goal → clarify scope → discovery/quality/usage →
request_forecast → durable job and backend crash/recovery → seasonal_naive wins
against the deterministic test predictor → compare_maintenance_windows →
revision → proposal. Artifact links resolve to the exact run-scoped calculation.
Both test datasets and predictors are explicitly synthetic.

## Remaining analytical/business boundaries

Real forecast usefulness is **not validated**. Identity joins and historical
capacity remain unresolved; no thresholds were relaxed to force recommendations.
Only the three previously supported AC groups can be forecast; DC/new-site
forecast validation and forecasts beyond 168 hours are outside this delivery.
Bolzano means the documented context bounding box, not certified municipal limits.

Operational records are optional explicit imports, not an enterprise integration.
Working-calendar/dependency scheduling is conservative calendar-day arithmetic;
physical installation feasibility, tax applicability, equipment requirements and
business facts require verification. The system reports unknown/conditional.
Metrics enforce identity/equality, not semantic entailment of arbitrary prose.
No claim is made that all conceivable phrasing or deployment-scale concurrency is
covered by this demo's tests. Multi-user auth, deployment, global run search and
execution remain outside scope, as required by the plan.

## Final verification

- `make test`: **66 passed**, including numerical tests; TypeScript passed.
- `npm run build`: passed.
- `npm run test:frontend`: **5 passed** (local simulator/controlled HTTP).
- `npm run test:integration`: **2 passed** (real HTTP/SSE, temporary DB,
  deterministic predictor; keyboard, narrow screen, revision, refresh, forced
  backend restart, stale approval and exact artifact retrieval).
- `make contracts`: passed; a second export had **zero hash drift** across JSON
  contracts and generated TypeScript.
- `git diff --check`: passed. Narrow-screen browser screenshot inspected.
- Read-only production metadata audit: latest discussion creation remained
  2026-11-14T03:38:11Z, predating this implementation's baseline/progress log.
  No test discussion was added to the production DB; no source refresh occurred.
- No required offline numerical checks skipped. Live end-to-end discussion after
  real human answers and real-data analytical forecast validation remain
  **unverified**, with the failed live citation evaluation retained above.

Final architecture keeps the registration/composition root generic (`profiles.py`)
and charging dispatch, numerical capture, metric presentation and evidence policy
under `examples/charging/`. Latest regressions include actual provider correction
for malformed tool arguments, pointer/dotted metric path equivalence and lazy
weight initialization on insufficient input. Subsequent offline fixes are not
represented as a passed live quality rerun.
