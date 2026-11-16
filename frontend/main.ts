import "./style.css";
import type { components as ChargingComponents } from "./charging-api-types";
import { ApiError, createClient, type Run, type ToolArtifact } from "./client";
import { createMockClient } from "./mock";
import { chargingToolLabels } from "./examples/charging";
import { tasks as chargingTasks } from "./tasks";
import { tasks as testTasks } from "./test-tasks";

const env = (import.meta as ImportMeta & { env: Record<string, string> }).env;
const tasks = env.VITE_TEST_CATALOG === "generic" ? testTasks : chargingTasks;
const remote = env.VITE_DATA_SOURCE === "api";
const mode = env.VITE_RUN_MODE === "model" ? "model" : "mock";
const api = remote
  ? createClient(env.VITE_API_BASE_URL || "")
  : createMockClient();
const root = document.querySelector<HTMLDivElement>("#app")!;
const artifacts = new Map<string, ToolArtifact>();
const runs = new Map<string, Run>();
const taskRuns = new Map<string, string>();
const busy = new Set<string>();
const subscriptions = new Map<string, () => void>();
const connection = new Map<string, string>();
const keys = new Map<string, string>();
const drafts = new Map<
  string,
  { text: string; option: string; actor: string }
>();
let selected: string | null = null,
  error = "";
const labels: Record<Run["state"], string> = {
  running: "In progress",
  awaiting_input: "Needs your input",
  proposal_ready: "To approve",
  approved: "Approved",
  failed: "Interrupted",
};
const actors: Record<string, string> = {
  analyst: "Analyst",
  operations: "Operations",
  finance: "Finance",
  critic: "Critic",
  operator: "User",
  system: "System",
};
const esc = (s: unknown) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
const terminal = (r: Run) => r.state === "approved";
// Every page load starts clean: runs are never restored from the browser, so each
// flow can be repeated after a refresh. Remove the registry written by older builds.
try {
  for (const key of Object.keys(localStorage))
    if (key.startsWith("agent-workspace:")) localStorage.removeItem(key);
} catch {
  /* Storage may be unavailable; nothing to clean. */
}
// Readable mode: a per-viewer display preference only (higher contrast, fewer
// secondary details). It never changes runs, commands or what the server stores.
const READABLE_KEY = "acs-readable-mode";
let readable = false;
try {
  readable = localStorage.getItem(READABLE_KEY) === "1";
} catch {
  /* Storage may be unavailable; default to the standard view. */
}
function setReadable(on: boolean) {
  readable = on;
  try {
    localStorage.setItem(READABLE_KEY, on ? "1" : "0");
  } catch {
    /* Preference simply won't persist. */
  }
}
function readableSwitch() {
  return `<button type="button" class="readable-toggle" role="switch" aria-checked="${readable}" data-readable title="${readable ? "Back to the full view" : "Larger text, higher contrast, fewer details"}"><span class="switch-track" aria-hidden="true"><span class="switch-thumb"></span></span><span class="switch-label">Easy read</span></button>`;
}
function accept(r: Run) {
  const current = runs.get(r.id);
  // SSE replay or a slow GET must not replace a newer snapshot.
  if (current && Date.parse(r.updated_at) < Date.parse(current.updated_at))
    return;
  selected ??= r.id;
  runs.set(r.id, r);
  render();
}
function watch(id: string) {
  if (subscriptions.has(id)) return;
  let polling = false;
  const close = api.subscribe(
    id,
    (r) => {
      connection.set(id, "Live updates");
      accept(r);
    },
    0,
    () => {
      connection.set(id, "Reconnecting live · periodic refresh active");
      render();
    },
  );
  // Also reconciles snapshots after a lost SSE connection or idempotent replay.
  const timer = remote
    ? window.setInterval(async () => {
        if (polling) return;
        polling = true;
        try {
          accept(await api.run(id));
        } catch {
          connection.set(id, "No connection · retrying in 5 s");
          render();
        } finally {
          polling = false;
        }
      }, 5000)
    : undefined;
  subscriptions.set(id, () => {
    close();
    clearInterval(timer);
  });
}
window.addEventListener("pagehide", () =>
  subscriptions.forEach((close) => close()),
);
function draft(r: Run) {
  const key = r.question?.id || r.id;
  if (!drafts.has(key))
    drafts.set(key, { text: "", option: "", actor: "Operator" });
  return drafts.get(key)!;
}
async function perform(
  lock: string,
  payload: object,
  action: (key: string) => Promise<Run>,
  taskId?: string,
) {
  if (busy.has(lock)) return;
  const signature = JSON.stringify({ lock, payload });
  const key = keys.get(signature) ?? crypto.randomUUID();
  keys.set(signature, key);
  busy.add(lock);
  error = "";
  render();
  try {
    const response = await action(key);
    if (taskId) {
      taskRuns.set(taskId, response.id);
      selected = response.id;
    }
    accept(response);
    watch(response.id);
    accept(await api.run(response.id));
    keys.delete(signature);
  } catch (e) {
    error = e instanceof Error ? e.message : "Operation failed.";
    if (e instanceof ApiError && e.status === 409 && runs.has(lock)) {
      try {
        accept(await api.run(lock));
      } catch {
        /* Keep error and last known snapshot. */
      }
      error +=
        " State reloaded when available: check and confirm your choice again.";
      keys.delete(signature);
    }
  } finally {
    busy.delete(lock);
    render();
  }
}
function start(taskId: string) {
  const item = tasks.find((t) => t.id === taskId);
  if (!item || taskRuns.has(taskId)) return;
  const payload = {
    task: item.task,
    capability_profile:
      env.VITE_TEST_CATALOG === "generic" ? undefined : ("charging" as const),
    mode: (remote ? mode : "mock") as "model" | "mock",
    // One round per cycle by default: faster iterations; the critic escalates what stays open.
    max_rounds: Math.max(1, Math.min(6, Number(env.VITE_MAX_ROUNDS) || 1)),
  };
  void perform(
    taskId,
    payload,
    (key) => api.createRun({ ...payload, idempotency_key: key }),
    taskId,
  );
}
function card(r: Run) {
  return `<button class="run-card ${selected === r.id ? "selected" : ""}" data-select="${esc(r.id)}"><span class="badge ${r.state}">${labels[r.state]}</span><strong>${esc(r.task.title)}</strong></button>`;
}
function evidenceLink(id: string) {
  return `<button class="secondary evidence-link" data-evidence="${esc(id)}">Evidence ${esc(id.slice(0, 12))}</button>`;
}
function forecastDetail(a: ToolArtifact) {
  if (a.outcome.origin !== "forecast") return "";
  if (a.outcome.status !== "available")
    return `<p>Forecast unavailable: ${esc(a.outcome.summary)}</p>`;
  const f = a.outcome.data as ChargingComponents["schemas"]["ForecastBundle"];
  if (!f.sites) return "";
  return `<h4>Forecast · origin ${esc(f.forecast_start)} · ${esc(f.horizon_hours)} hours</h4><p>Generated ${esc(f.generated_at)} · analysis ${esc(f.analysis_id)}</p>${f.sites.map((s) => `<article><b>${esc(s.site_name)} · ${esc(s.selected_method ?? s.status)}</b><p>Target coverage: ${esc((s.valid_fraction * 100).toFixed(1))}%</p>${s.status !== "available" ? `<p>${esc(s.reason)}</p>` : `<details data-disclosure="points-${esc(a.id)}-${esc(s.site_id)}"><summary>Hourly quantiles · estimated requests/hour</summary><table><thead><tr><th>Hour</th><th>p</th><th>p10</th><th>p50</th><th>p90</th></tr></thead><tbody>${s.points.map((p) => `<tr><td>${esc(p.time)}</td><td>${p.p}</td><td>${p.p10.toFixed(2)}</td><td>${p.p50.toFixed(2)}</td><td>${p.p90.toFixed(2)}</td></tr>`).join("")}</tbody></table></details>`}<details data-disclosure="backtest-${esc(a.id)}-${esc(s.site_id)}"><summary>Backtest and limitations</summary><pre>${esc(JSON.stringify({ backtest: s.backtest, limitations: s.limitations }, null, 2))}</pre></details></article>`).join("")}`;
}
function investigation(r: Run) {
  const calls = r.tool_activity ?? [];
  return `<section class="investigation" aria-label="Tools and evidence"><h2>Tool calls</h2><p class="muted">${r.mode === "mock" ? "Simulator: demo calls, no real query executed." : "Calls recorded by the server: who made them, with which parameters and what they returned."} “data ↗” opens the evidence cited in the claims.</p>${r.turn_progress?.pending_job_id ? '<p role="status">Computation pending · the role will resume from the persisted result.</p>' : ""}${calls.length ? `<ol class="tool-list log">${calls.map((c, i) => (i === 0 || calls[i - 1].cycle !== c.cycle ? `<li class="cycle-sep">Cycle ${c.cycle}${c.cycle > 1 ? " · replanning after the human answer" : ""}</li>` : "") + toolRow(c, true)).join("")}</ol>` : "<p>No tool requests recorded.</p>"}${calls.map((c) => `<details data-disclosure="tool-${esc(c.id)}"><summary>${esc(c.request.name)} · ${esc(c.status)}${c.cached ? " · verified cache" : ""} · full parameters</summary><p>${esc(clip(c.summary, 600))}</p><pre>${esc(JSON.stringify(c.normalized_parameters, null, 2))}</pre>${c.artifact_id ? evidenceLink(c.artifact_id) : ""}</details>`).join("")}${(
    r.evidence ?? []
  )
    .filter((e) => e.artifact_id)
    .map((e) => {
      const a = artifacts.get(e.artifact_id!);
      if (!a) return "";
      return `<details open data-disclosure="artifact-${esc(e.id)}"><summary>Evidence ${esc(e.name)} · ${esc(a.outcome.status)}</summary><p>Origin: ${esc(a.outcome.origin)} · method ${esc(a.outcome.method)} · version ${esc(a.outcome.method_version)}</p><p>${esc(a.outcome.summary)}</p><p>Queried: ${esc(a.outcome.queried_at)} (not the observation date)</p><ul>${(a.outcome.limitations ?? []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>${forecastDetail(a)}<details data-disclosure="raw-${esc(a.id)}"><summary>Data and provenance</summary><pre>${esc(JSON.stringify(a.outcome.data, null, 2))}</pre></details></details>`;
    })
    .join("")}</section>`;
}
function proposal(r: Run) {
  const p = r.proposal;
  if (!p) return "";
  return `<section class="proposal"><div class="eyebrow">${p.status === "draft" ? "Draft" : p.status === "conditional" ? "Conditional proposal" : "Final proposal"} · v${p.version}${p.version !== r.proposal_version ? " · previous version" : ""}</div><h3>${esc(p.summary)}</h3>${p.recommended_actions.map((a) => `<div class="action"><strong>${esc(a.title)}</strong><p>${esc(a.description)}</p><small>${esc(a.rationale)}</small>${a.evidence_ids.map(evidenceLink).join(" ")}</div>`).join("")}<h4>Risks</h4>${p.risks.length ? `<ul>${p.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p>No risks reported.</p>"}<h4>Unresolved questions</h4>${p.unresolved_questions.length ? `<ul>${p.unresolved_questions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p>No questions reported.</p>"}${r.state === "proposal_ready" ? `<label>Your name<input data-field="actor" maxlength="200" value="${esc(draft(r).actor)}"></label><button data-approve ${busy.has(r.id) || (r.objections ?? []).some((o) => o.status === "open" && o.blocking) ? "disabled" : ""}>Approve proposal</button><p class="muted">Approval applies to the document. No action will be executed.${(r.objections ?? []).some((o) => o.status === "open" && o.blocking) ? " Blocking objections must be resolved first." : ""}</p>` : ""}${r.approval ? `<p class="approved-note">Approved by ${esc(r.approval.actor)} · no action executed.</p>` : ""}</section>`;
}
let drawer = "";
const rolePages = new Map<string, number>();
type ToolCall = NonNullable<Run["tool_activity"]>[number];
type Message = NonNullable<Run["messages"]>[number];
const AGENTS = ["analyst", "operations", "finance", "critic"] as const;
const roleMeta: Record<string, { icon: string }> = {
  analyst: { icon: "A" },
  operations: { icon: "O" },
  finance: { icon: "F" },
  critic: { icon: "C" },
};
const kindLabels: Record<string, string> = {
  proposal: "Proposal",
  revision: "Revision",
  review: "Review",
  objection: "Objection",
  not_applicable: "Not applicable",
};
const clip = (text: string, max: number) =>
  text.length > max ? text.slice(0, max - 1).trimEnd() + "…" : text;
/** One or two short sentences: the panel shows the conclusion, the full text stays one click away. */
function headline(text: string) {
  const clean = text.replace(/\s+/g, " ").trim();
  const sentences = clean.split(/(?<=[.!?])\s+(?=[A-ZÀ-Ý“"(])/);
  let out = sentences[0] ?? "";
  if (out.length < 70 && sentences[1]) out += " " + sentences[1];
  return clip(out, 220);
}
function toolName(name: string) {
  return (
    chargingToolLabels[name]?.label ?? name.split(".").pop()!.replace(/_/g, " ")
  );
}
function argValue(key: string, v: unknown): string {
  if (Array.isArray(v))
    return `${v.length} ${/site/.test(key) ? "sites" : "items"}`;
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v))
    return v.slice(0, 10);
  if (v && typeof v === "object") return "{…}";
  return String(v);
}
function argsLabel(params: Record<string, unknown>) {
  return clip(
    Object.entries(params)
      .filter(
        ([k, v]) => !["offset", "limit"].includes(k) && v !== null && v !== "",
      )
      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${argValue(k, v)}`)
      .join(" · "),
    110,
  );
}
function summarizeJson(value: unknown): string {
  if (Array.isArray(value)) return `${value.length} results`;
  if (!value || typeof value !== "object") return String(value);
  return Object.entries(value as Record<string, unknown>)
    .filter(([k]) => !/evidence|fingerprint|reference/.test(k))
    .slice(0, 2)
    .map(([k, v]) =>
      Array.isArray(v)
        ? `${v.length} ${k.replace(/_/g, " ")}`
        : v && typeof v === "object"
          ? k.replace(/_/g, " ")
          : `${k.replace(/_/g, " ")}: ${clip(String(v), 30)}`,
    )
    .join(" · ");
}
/** Tool summaries can be raw JSON; reduce them to one readable result line. */
function resultLabel(c: ToolCall) {
  if (c.status === "queued") return "queued";
  if (c.status === "running") return "running…";
  if (c.status === "failed") return clip(c.summary || "error", 80);
  const match = /^[\w.]+:\s*(\w+)\.\s*([\s\S]*)$/.exec(c.summary || "");
  const status = match?.[1] ?? "available";
  const rest = (match?.[2] ?? c.summary ?? "").trim();
  let text = rest;
  if (/^[[{]/.test(rest)) {
    try {
      text = summarizeJson(JSON.parse(rest));
    } catch {
      const ids = rest.match(/"id":/g)?.length ?? 0;
      text = ids ? `${ids} records` : "data available";
    }
  }
  const prefix =
    status === "available" ? "" : `${status.replace(/_/g, " ")} · `;
  return clip(prefix + (text || "data available"), 80);
}
/** Compact row: icon + one short sentence. Technical name, parameters and source live in the tooltip and the tool log. */
function toolRow(c: ToolCall, withRole = false) {
  const meta = chargingToolLabels[c.request.name];
  const active = c.status === "running" || c.status === "queued";
  const action = meta
    ? active
      ? meta.doing
      : meta.done
    : toolName(c.request.name);
  const sites = (c.normalized_parameters ?? c.request.arguments)?.site_ids;
  const scope = Array.isArray(sites)
    ? ` · ${sites.length} site${sites.length === 1 ? "" : "s"}`
    : "";
  const result = active ? "" : clip(resultLabel(c), 40);
  const tooltip = [
    c.request.name,
    argsLabel(c.normalized_parameters ?? c.request.arguments),
    meta?.source,
    c.status === "failed" ? c.summary : resultLabel(c),
  ]
    .filter(Boolean)
    .join("\n");
  return `<li class="tool-call ${c.status}" title="${esc(tooltip)}"><span class="tool-icon" aria-hidden="true">${meta?.icon ?? "⚙️"}</span><span class="tool-text">${withRole ? `<span class="role-tag ${esc(c.role)}">${esc(actors[c.role] ?? c.role)}</span> ` : ""}${esc(action + scope)}${active ? "…" : ""}${result ? ` <span class="tool-result">· ${esc(result)}</span>` : ""}${c.cached ? ' <em class="cache">cache</em>' : ""}</span>${c.artifact_id ? `<button class="chip" data-evidence="${esc(c.artifact_id)}" title="Open the returned data">data ↗</button>` : ""}</li>`;
}
function messageTools(r: Run, m: Message) {
  const own = (r.messages ?? []).filter((x) => x.actor === m.actor);
  const previous = own[own.indexOf(m) - 1];
  return (r.tool_activity ?? []).filter(
    (c) =>
      c.role === m.actor &&
      c.cycle === m.cycle &&
      Date.parse(c.created_at) <= Date.parse(m.created_at) &&
      (!previous || Date.parse(c.created_at) > Date.parse(previous.created_at)),
  );
}
function sourceChip(r: Run, id: string) {
  const e = (r.evidence ?? []).find((x) => x.id === id);
  if (e?.artifact_id)
    return `<button class="chip" data-evidence="${esc(e.artifact_id)}" title="${esc(e.name)}">${esc(clip(toolName(e.name), 26))} ↗</button>`;
  const label =
    e?.origin === "human_answer"
      ? "Human answer"
      : e
        ? clip(e.name, 22)
        : clip(id, 12);
  return `<button class="chip plain" data-drawer="context" title="${esc(e?.text ?? id)}">${esc(label)}</button>`;
}
const basisLabel = {
  supported: "Data",
  estimate: "Estimate",
  assumption: "Assumption",
};
function claims(r: Run, m: Message) {
  const list = m.content.claims ?? [];
  if (!list.length) return "";
  return `<ul class="claims">${list
    .slice(0, 3)
    .map(
      (c) =>
        `<li><span class="basis ${c.basis}">${basisLabel[c.basis]}</span><span>${esc(clip(c.statement, 140))}</span>${c.evidence_ids
          .slice(0, 2)
          .map((id) => sourceChip(r, id))
          .join("")}</li>`,
    )
    .join(
      "",
    )}${list.length > 3 ? `<li class="more"><button class="text-button" data-drawer="history">+${list.length - 3} claims</button></li>` : ""}</ul>`;
}
type RoleState = { key: string; label: string };
function roleState(r: Run, role: string): RoleState {
  const spoke = (r.messages ?? []).filter(
    (m) => m.actor === role && m.cycle === r.cycle && m.round === r.round,
  );
  const last = spoke.at(-1);
  if (r.state === "running" && r.next_role === role) {
    const tool = (r.tool_activity ?? []).find(
      (c) =>
        c.role === role && (c.status === "running" || c.status === "queued"),
    );
    return { key: "working", label: tool ? "Querying data" : "Working" };
  }
  if (r.state === "failed" && r.next_role === role)
    return { key: "failed", label: "Error" };
  if (last)
    return last.content.applicability === "not_applicable"
      ? { key: "skipped", label: "Not relevant" }
      : last.content.kind === "objection" ||
          last.content.objections.some((o) => o.blocking)
        ? { key: "objected", label: "Objected" }
        : { key: "done", label: "Responded" };
  if (r.state === "running")
    return { key: "waiting", label: "Waiting for turn" };
  if (r.state === "awaiting_input") return { key: "paused", label: "Paused" };
  return { key: "idle", label: "Finished" };
}
function objectionList(r: Run) {
  const list = r.objections ?? [];
  if (!list.length) return "";
  const overruled = r.proposal?.status === "conditional";
  const open = list.filter((o) => o.status === "open").length;
  return `<ul class="objections"><li class="obj-title">Objections · ${open} open · ${list.length - open} resolved</li>${list
    .slice(-3)
    .map(
      (o) =>
        `<li class="${o.status} ${o.blocking ? "blocking" : ""}"><span class="obj-state">${o.status === "open" ? (overruled ? "Overruled" : o.blocking ? "Blocking" : "Open") : "Resolved"}</span><span>${esc(clip(o.concern, 110))}${o.resolution ? `<small>${esc(clip(o.resolution.explanation, 120))}</small>` : ""}</span></li>`,
    )
    .join("")}</ul>`;
}
function rolePanel(r: Run, role: string) {
  const messages = (r.messages ?? []).filter((m) => m.actor === role);
  const index = Math.min(
    rolePages.get(r.id + role) ?? Math.max(0, messages.length - 1),
    Math.max(0, messages.length - 1),
  );
  const m = messages[index];
  const state = roleState(r, role);
  const working = state.key === "working";
  const someoneWorking = r.state === "running";
  const liveTools = working
    ? (r.tool_activity ?? []).filter(
        (c) =>
          c.role === role &&
          c.cycle === r.cycle &&
          (c.turn_token === r.turn_progress?.token ||
            c.status === "running" ||
            c.status === "queued"),
      )
    : [];
  const live = working
    ? `<div class="live-line"><span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>${liveTools.some((c) => c.status === "running" || c.status === "queued") ? "Querying the data…" : liveTools.length ? "Writing the review…" : "Thinking about the plan…"}</div>${liveTools.length ? `<ul class="tool-list">${liveTools.map((c) => toolRow(c)).join("")}</ul>` : ""}`
    : "";
  const tools = m && !working ? messageTools(r, m) : [];
  const body = m
    ? `<article class="message ${role} ${working ? "previous" : ""}"><div class="msg-meta"><span class="kind ${m.content.kind}">${kindLabels[m.content.kind] ?? m.content.kind}</span></div>${tools.length ? `<ul class="tool-list">${tools.map((c) => toolRow(c)).join("")}</ul>` : ""}<p class="headline public-explanation">${esc(headline(m.content.text || m.content.explanation))}</p>${claims(r, m)}${m.content.objections.length ? `<ul class="raised">${m.content.objections.map((o) => `<li class="${o.blocking ? "blocking" : ""}">${o.blocking ? "Blocks" : "Objects"}: ${esc(clip(o.concern, 110))}</li>`).join("")}</ul>` : ""}<details data-disclosure="full-${esc(m.id)}"><summary>Full text</summary><p>${esc(m.content.text)}</p>${m.content.explanation && m.content.explanation !== m.content.text ? `<p class="muted">${esc(m.content.explanation)}</p>` : ""}</details></article>`
    : working
      ? ""
      : `<p class="placeholder">${role === "critic" ? "Will check the other roles' claims and sources and can block the plan." : "Will join when its turn comes."}</p>`;
  return `<section class="agent-panel ${role} state-${state.key} ${working ? "is-working" : someoneWorking ? "is-idle" : ""}" aria-label="${actors[role]}" ${working ? 'aria-busy="true"' : ""}>
    <header><span class="role-icon">${roleMeta[role].icon}</span><span class="role-name"><h3>${actors[role]}</h3></span></header>
    <div class="agent-body" data-scroll="${role}" tabindex="0">${live}${body}${role === "critic" ? objectionList(r) : ""}</div>
    <footer><button class="text-button" data-drawer="history">History ↗</button><span class="pager"><button aria-label="Previous turn ${actors[role]}" data-role-page="${role}" data-index="${index - 1}" ${index <= 0 ? "disabled" : ""}>‹</button><small>${messages.length ? index + 1 : 0}/${messages.length}</small><button aria-label="Next turn ${actors[role]}" data-role-page="${role}" data-index="${index + 1}" ${index >= messages.length - 1 ? "disabled" : ""}>›</button></span></footer>
  </section>`;
}
function question(r: Run) {
  const q = r.question,
    d = draft(r);
  if (r.state !== "awaiting_input" || !q) return "";
  return `<form class="question" data-reason="${esc(q.reason)}"><label class="question-text" for="answer-option">${esc(q.text)}</label><div class="answer-controls"><select id="answer-option" aria-label="Choice" data-field="option"><option value="">Choose an answer…</option>${q.options.map((o) => `<option value="${esc(o.id)}" ${d.option === o.id ? "selected" : ""}>${esc(o.label)}</option>`).join("")}<option value="__custom" ${d.option === "__custom" ? "selected" : ""}>Write an answer…</option></select><button type="submit" aria-label="Send answer and resume" title="Send answer" ${busy.has(r.id) ? "disabled" : ""}>Send ↑</button><button type="button" class="text-button" data-drawer="question" aria-label="Question details">ⓘ</button></div>${d.option === "__custom" ? `<textarea aria-label="Free answer" data-field="text" maxlength="10000" placeholder="Your answer…">${esc(d.text)}</textarea>` : ""}</form>`;
}
function detail(r: Run) {
  return `<div class="detail-header"><h2>${esc(r.task.title)}</h2><button class="plan-button ${r.state === "proposal_ready" || r.state === "approved" ? "highlight" : ""}" data-drawer="proposal" ${!r.proposal ? "disabled" : ""}>${r.state === "proposal_ready" ? "Review and approve ↗" : "Open plan ↗"}</button></div>
    ${rolePanel(r, "critic")}<div class="model-grid">${["analyst", "operations", "finance"].map((role) => rolePanel(r, role)).join("")}</div>
    ${question(r)}${r.state === "failed" ? `<section class="failure"><p>${esc(r.error?.message)}</p><button data-retry>Retry turn</button></section>` : ""}`;
}
function drawerContent(r: Run) {
  if (drawer === "proposal")
    return (
      proposal(r) +
      `<details><summary>Proposal versions</summary>${(r.proposals ?? []).map((p) => `<p>v${p.version} · ${esc(p.status)} · ${esc(p.summary)}</p>`).join("")}</details>`
    );
  if (drawer === "investigation") return investigation(r);
  if (drawer === "objections")
    return `<h2>Objections</h2>${(r.objections ?? []).map((o) => `<article><h3>${esc(o.concern)}</h3><span>Raised by ${esc(actors[(r.messages ?? []).find((m) => m.id === o.message_id)?.actor ?? "critic"])} · ${o.status === "open" ? "Open" : "Resolved"}${o.blocking ? " · blocking" : ""}${o.status === "open" && r.proposal?.status === "conditional" ? " · overruled by the operator" : ""}</span><p>${esc(o.explanation)}</p>${o.resolution ? `<p>${esc(o.resolution.explanation)}</p>` : ""}</article>`).join("") || "<p>No objections.</p>"}`;
  if (drawer === "question")
    return `<h2>${esc(r.question?.text)}</h2><p>${esc(r.question?.explanation)}</p>${r.question?.options.map((o) => `<h3>${esc(o.label)}</h3><p>${esc(o.explanation)}</p>`).join("") || ""}<label>Your name<input data-field="actor" value="${esc(draft(r).actor)}" maxlength="200"></label>`;
  if (drawer === "context")
    return `<h2>${esc(r.task.title)}</h2><p>${esc(r.task.description)}</p><p>${esc(r.task.context)}</p><p>${esc(r.notice)}</p><p>${esc(r.mode)} · ${esc(r.model)} · cycle ${r.cycle}</p>${(r.evidence ?? []).map((e) => `<article><h3>${esc(e.name)}</h3><small>${esc(e.origin)}</small><p>${esc(e.text || e.url)}</p></article>`).join("")}`;
  return `<h2>Messages and public explanations</h2>${(r.messages ?? []).map((m) => `<article class="message ${m.actor}"><h3>${esc(actors[m.actor])} · round ${m.round}</h3><p>${esc(m.content.text)}</p><p>${esc(m.content.explanation)}</p>${m.content.claims.map((c) => `<p><b>${c.basis === "supported" ? "Supported by the cited sources" : c.basis === "assumption" ? "Assumption" : "Estimate"}</b> · ${esc(c.statement)} ${c.evidence_ids.map(evidenceLink).join(" ")}</p>`).join("")}</article>`).join("")}`;
}
function render() {
  const scrollPositions = new Map(
    Array.from(root.querySelectorAll<HTMLElement>("[data-scroll]")).map(
      (el) => [el.dataset.scroll, el.scrollTop],
    ),
  );
  const oldDetail = root.querySelector(".detail");
  const scroll = oldDetail?.scrollTop ?? 0;
  const active = document.activeElement as
    HTMLInputElement | HTMLTextAreaElement | null;
  const field = active?.dataset.field;
  const selection =
    active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement
      ? [active.selectionStart, active.selectionEnd]
      : null;
  const pending = tasks.filter((t) => !taskRuns.has(t.id));
  const activeRuns = [...runs.values()].filter((r) => !terminal(r));
  const done = [...runs.values()].filter((r) => r.state === "approved");
  const r = selected ? runs.get(selected) : undefined;
  const disclosures = new Set(
    Array.from(
      root.querySelectorAll<HTMLDetailsElement>(
        "details[open][data-disclosure]",
      ),
    ).map((el) => el.dataset.disclosure),
  );
  root.innerHTML = `<main class="board"><aside class="column backlog" aria-label="Available tickets"><div class="column-title"><h2>Tickets</h2><span>${pending.length}</span></div><div class="cards">${pending.map((t) => `<article class="task-card" draggable="${!busy.has(t.id)}" data-task="${t.id}"><span class="grip" aria-hidden="true">⠿</span><h3>${esc(t.task.title)}</h3><button class="start-button" data-start="${t.id}" aria-label="Start task: ${esc(t.task.title)}" title="Start task" ${busy.has(t.id) ? "disabled" : ""}>${busy.has(t.id) ? "…" : "↗"}</button></article>`).join("") || '<p class="empty-small">All tickets are assigned.</p>'}</div>${activeRuns.length ? `<nav class="active-runs" aria-label="Tasks in progress">${activeRuns.map(card).join("")}</nav>` : ""}</aside><section class="column workspace" aria-label="Workspace" data-drop>${error ? `<div class="error" role="alert">${esc(error)} <button data-dismiss class="secondary">Close</button></div>` : ""}<div class="detail">${r ? detail(r) : '<div class="empty"><span class="empty-icon" aria-hidden="true">↘</span><h2>Assign the first ticket</h2><p>Drag it here, or press ↗ on the ticket.<br>The agents will discuss it and ask you for what they need.</p><small>Demo with fictional tickets and simulated dialogues.</small></div>'}</div><div class="drop-overlay" aria-hidden="true">Drop the ticket to start</div></section><aside class="column results" aria-label="Completed tasks"><div class="column-title"><h2>Completed</h2><span>${done.length}</span></div><div class="cards">${done.map(card).join("")}</div></aside></main>${readableSwitch()}`;
  document.documentElement.classList.toggle("readable", readable);
  if (drawer && r) {
    root.insertAdjacentHTML(
      "beforeend",
      `<dialog aria-label="Details" class="inspector"><header><span>WORKSPACE / DETAILS</span><button data-close-drawer aria-label="Close details">×</button></header><div class="inspector-body" data-scroll="drawer">${drawerContent(r)}</div></dialog>`,
    );
    const dialog = root.querySelector<HTMLDialogElement>("dialog")!;
    dialog.showModal();
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      drawer = "";
      render();
    });
  }
  root.querySelectorAll<HTMLElement>("[data-scroll]").forEach((el) => {
    el.scrollTop = scrollPositions.get(el.dataset.scroll) ?? 0;
  });
  root
    .querySelectorAll<HTMLDetailsElement>("details[data-disclosure]")
    .forEach((el) => {
      el.open = disclosures.has(el.dataset.disclosure);
    });
  const panel = root.querySelector(".detail")!;
  panel.scrollTop = scroll;
  if (field) {
    const scope = root.querySelector("dialog") || root;
    const el = scope.querySelector<HTMLInputElement | HTMLTextAreaElement>(
      `[data-field="${field}"]`,
    );
    el?.focus({ preventScroll: true });
    if (
      (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) &&
      selection &&
      selection[0] !== null &&
      selection[1] !== null
    )
      el.setSelectionRange(selection[0], selection[1]);
  }
}
root.addEventListener("input", (event) => {
  const target = event.target as HTMLInputElement;
  const r = selected ? runs.get(selected) : undefined;
  if (r && ["text", "actor", "option"].includes(target.dataset.field || ""))
    draft(r)[target.dataset.field as "text" | "actor" | "option"] =
      target.value;
  if (target.dataset.field === "option") render();
});
function answer(finalize = false) {
  const r = selected ? runs.get(selected) : undefined;
  if (!r?.question) return;
  const d = draft(r);
  if (
    !d.actor.trim() ||
    ((!d.option || d.option === "__custom") && !d.text.trim())
  ) {
    error = "Enter your name and choose an option or write an answer.";
    render();
    return;
  }
  const payload = {
    proposal_version: r.proposal_version,
    question_id: r.question.id,
    actor: d.actor.trim(),
    option_id: d.option === "__custom" ? null : d.option || null,
    text: d.text.trim() || null,
    finalize_with_unresolved: finalize,
  };
  void perform(r.id, payload, (key) =>
    api.answer(r.id, { ...payload, idempotency_key: key }),
  );
}
root.addEventListener("submit", (event) => {
  event.preventDefault();
  answer();
});
root.addEventListener("click", (event) => {
  const el = (event.target as HTMLElement).closest<HTMLButtonElement>("button");
  if (!el || el.disabled) return;
  if (el.hasAttribute("data-readable")) {
    setReadable(!readable);
    render();
    root.querySelector<HTMLButtonElement>("[data-readable]")?.focus();
    return;
  }
  if (el.dataset.drawer) {
    drawer = el.dataset.drawer;
    render();
    return;
  }
  if (el.hasAttribute("data-close-drawer")) {
    drawer = "";
    render();
    root.querySelector<HTMLButtonElement>("[data-drawer]")?.focus();
    return;
  }
  if (el.dataset.rolePage && selected) {
    rolePages.set(selected + el.dataset.rolePage, Number(el.dataset.index));
    render();
    return;
  }
  if (el.dataset.start) start(el.dataset.start);
  if (el.dataset.select) {
    drawer = "";
    selected = el.dataset.select;
    render();
    root.querySelector(".detail")!.scrollTop = 0;
  }
  if (el.hasAttribute("data-dismiss")) {
    error = "";
    render();
  }
  if (el.hasAttribute("data-finalize")) answer(true);
  const r = selected ? runs.get(selected) : undefined;
  if (!r) return;
  if (el.dataset.evidence) {
    const id = el.dataset.evidence;
    void api
      .artifact(r.id, id)
      .then((a) => {
        artifacts.set(id, a);
        drawer = "investigation";
        render();
        const detail = root.querySelector<HTMLDetailsElement>(
          `[data-disclosure="artifact-${CSS.escape(id)}"]`,
        );
        if (detail) {
          detail.open = true;
          detail.scrollIntoView({ block: "nearest" });
        }
      })
      .catch((e) => {
        error = String(e);
        render();
      });
  }
  if (el.hasAttribute("data-retry")) {
    const payload = { proposal_version: r.proposal_version };
    void perform(r.id, payload, (key) =>
      api.retry(r.id, { ...payload, idempotency_key: key }),
    );
  }
  if (el.hasAttribute("data-approve")) {
    if (!draft(r).actor.trim()) {
      error = "Enter your name before approving.";
      render();
      return;
    }
    const payload = {
      proposal_version: r.proposal_version,
      actor: draft(r).actor.trim(),
    };
    void perform(r.id, payload, (key) =>
      api.approve(r.id, { ...payload, idempotency_key: key }),
    );
  }
});
root.addEventListener("dragstart", (event) => {
  const card = (event.target as HTMLElement).closest<HTMLElement>(
    "[data-task]",
  );
  if (card && event.dataTransfer) {
    event.dataTransfer.setData("text/plain", card.dataset.task!);
    event.dataTransfer.effectAllowed = "copy";
  }
});
root.addEventListener("dragover", (event) => {
  const zone = (event.target as HTMLElement).closest("[data-drop]");
  if (zone) {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    zone.classList.add("drag-over");
  }
});
root.addEventListener("dragleave", (event) => {
  const zone = (event.target as HTMLElement).closest("[data-drop]");
  if (zone && !zone.contains(event.relatedTarget as Node))
    zone.classList.remove("drag-over");
});
root.addEventListener("drop", (event) => {
  const zone = (event.target as HTMLElement).closest("[data-drop]");
  if (zone) {
    event.preventDefault();
    zone.classList.remove("drag-over");
    start(event.dataTransfer?.getData("text/plain") || "");
  }
});
render();
