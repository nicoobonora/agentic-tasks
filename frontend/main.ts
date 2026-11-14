import "./style.css";
import type { components as ChargingComponents } from "./charging-api-types";
import { ApiError, createClient, type Run, type ToolArtifact } from "./client";
import { createMockClient } from "./mock";
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
  running: "In lavorazione",
  awaiting_input: "Serve il tuo intervento",
  proposal_ready: "Da approvare",
  approved: "Approvato",
  failed: "Interrotto",
};
const actors: Record<string, string> = {
  analyst: "Analista",
  operations: "Operations",
  finance: "Finance",
  critic: "Critico",
  operator: "Utente",
  system: "Sistema",
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
const storageKey = `agent-workspace:v1:${env.VITE_API_BASE_URL || "same-origin"}:${mode}`;
function persist() {
  if (remote) {
    try {
      localStorage.setItem(storageKey, JSON.stringify([...taskRuns]));
    } catch {
      /* Storage may be unavailable; server remains authoritative. */
    }
  }
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
      connection.set(id, "Aggiornamenti live");
      accept(r);
    },
    0,
    () => {
      connection.set(id, "Riconnessione live · recupero periodico attivo");
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
          connection.set(id, "Connessione assente · nuovo tentativo tra 5 s");
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
    drafts.set(key, { text: "", option: "", actor: "Operatore" });
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
      persist();
    }
    accept(response);
    watch(response.id);
    accept(await api.run(response.id));
    keys.delete(signature);
  } catch (e) {
    error = e instanceof Error ? e.message : "Operazione non riuscita.";
    if (e instanceof ApiError && e.status === 409 && runs.has(lock)) {
      try {
        accept(await api.run(lock));
      } catch {
        /* Keep error and last known snapshot. */
      }
      error +=
        " Stato ricaricato quando disponibile: controlla e conferma nuovamente la tua scelta.";
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
    max_rounds: 3,
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
  return `<button class="secondary evidence-link" data-evidence="${esc(id)}">Prova ${esc(id.slice(0, 12))}</button>`;
}
function forecastDetail(a: ToolArtifact) {
  if (a.outcome.origin !== "forecast") return "";
  if (a.outcome.status !== "available")
    return `<p>Previsione non disponibile: ${esc(a.outcome.summary)}</p>`;
  const f = a.outcome.data as ChargingComponents["schemas"]["ForecastBundle"];
  if (!f.sites) return "";
  return `<h4>Previsione · origine ${esc(f.forecast_start)} · ${esc(f.horizon_hours)} ore</h4><p>Generata ${esc(f.generated_at)} · analisi ${esc(f.analysis_id)}</p>${f.sites.map((s) => `<article><b>${esc(s.site_name)} · ${esc(s.selected_method ?? s.status)}</b><p>Copertura target: ${esc((s.valid_fraction * 100).toFixed(1))}%</p>${s.status !== "available" ? `<p>${esc(s.reason)}</p>` : `<details data-disclosure="points-${esc(a.id)}-${esc(s.site_id)}"><summary>Quantili orari · richieste/ora stimate</summary><table><thead><tr><th>Ora</th><th>p</th><th>p10</th><th>p50</th><th>p90</th></tr></thead><tbody>${s.points.map((p) => `<tr><td>${esc(p.time)}</td><td>${p.p}</td><td>${p.p10.toFixed(2)}</td><td>${p.p50.toFixed(2)}</td><td>${p.p90.toFixed(2)}</td></tr>`).join("")}</tbody></table></details>`}<details data-disclosure="backtest-${esc(a.id)}-${esc(s.site_id)}"><summary>Backtest e limiti</summary><pre>${esc(JSON.stringify({ backtest: s.backtest, limitations: s.limitations }, null, 2))}</pre></details></article>`).join("")}`;
}
function investigation(r: Run) {
  const calls = r.tool_activity ?? [];
  return `<section class="investigation" aria-label="Indagine e prove"><h3>Indagine e prove</h3>${r.turn_progress?.pending_job_id ? '<p role="status">Calcolo in attesa · il ruolo riprenderà sul risultato persistito.</p>' : ""}${calls.map((c) => `<details data-disclosure="tool-${esc(c.id)}"><summary>${esc(c.request.name)} · ${esc(c.status)}${c.cached ? " · cache verificata" : ""}</summary><p>${esc(c.summary)}</p><pre>${esc(JSON.stringify(c.normalized_parameters, null, 2))}</pre>${c.artifact_id ? evidenceLink(c.artifact_id) : ""}</details>`).join("") || "<p>Nessuna richiesta di strumenti registrata.</p>"}${(
    r.evidence ?? []
  )
    .filter((e) => e.artifact_id)
    .map((e) => {
      const a = artifacts.get(e.artifact_id!);
      if (!a) return "";
      return `<details open data-disclosure="artifact-${esc(e.id)}"><summary>Prova ${esc(e.name)} · ${esc(a.outcome.status)}</summary><p>Origine: ${esc(a.outcome.origin)} · metodo ${esc(a.outcome.method)} · versione ${esc(a.outcome.method_version)}</p><p>${esc(a.outcome.summary)}</p><p>Consultazione: ${esc(a.outcome.queried_at)} (non data delle osservazioni)</p><ul>${(a.outcome.limitations ?? []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>${forecastDetail(a)}<details data-disclosure="raw-${esc(a.id)}"><summary>Dati e provenienza</summary><pre>${esc(JSON.stringify(a.outcome.data, null, 2))}</pre></details></details>`;
    })
    .join("")}</section>`;
}
function proposal(r: Run) {
  const p = r.proposal;
  if (!p) return "";
  return `<section class="proposal"><div class="eyebrow">${p.status === "draft" ? "Bozza" : p.status === "conditional" ? "Proposta condizionata" : "Proposta finale"} · v${p.version}${p.version !== r.proposal_version ? " · versione precedente" : ""}</div><h3>${esc(p.summary)}</h3>${p.recommended_actions.map((a) => `<div class="action"><strong>${esc(a.title)}</strong><p>${esc(a.description)}</p><small>${esc(a.rationale)}</small>${a.evidence_ids.map(evidenceLink).join(" ")}</div>`).join("")}<h4>Rischi</h4>${p.risks.length ? `<ul>${p.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p>Nessun rischio segnalato.</p>"}<h4>Questioni irrisolte</h4>${p.unresolved_questions.length ? `<ul>${p.unresolved_questions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p>Nessuna questione segnalata.</p>"}${r.state === "proposal_ready" ? `<label>Il tuo nome<input data-field="actor" maxlength="200" value="${esc(draft(r).actor)}"></label><button data-approve ${busy.has(r.id) || (r.objections ?? []).some((o) => o.status === "open" && o.blocking) ? "disabled" : ""}>Approva proposta</button><p class="muted">L’approvazione riguarda il documento. Nessuna azione verrà eseguita.${(r.objections ?? []).some((o) => o.status === "open" && o.blocking) ? " Prima occorre risolvere le obiezioni bloccanti." : ""}</p>` : ""}${r.approval ? `<p class="approved-note">Approvata da ${esc(r.approval.actor)} · nessuna azione eseguita.</p>` : ""}</section>`;
}
let drawer = "";
const rolePages = new Map<string, number>();
function rolePanel(r: Run, role: string) {
  const messages = (r.messages ?? []).filter((m) => m.actor === role);
  const index = Math.min(
    rolePages.get(r.id + role) ?? Math.max(0, messages.length - 1),
    Math.max(0, messages.length - 1),
  );
  const m = messages[index];
  const working = r.state === "running" && r.next_role === role;
  return `<section class="agent-panel ${role} ${working ? "is-working" : ""}" aria-label="${actors[role]}">
    <header><span class="role-icon">${role === "critic" ? "✳" : role === "analyst" ? "a" : role === "operations" ? "o" : "f"}</span><h3>${actors[role]}</h3><span class="role-state">${working ? "Al lavoro" : m ? `Round ${m.round} · ciclo ${m.cycle}` : "In attesa"}</span></header>
    <div class="agent-body" data-scroll="${role}" tabindex="0">${m ? `<article class="message ${role}"><p class="public-explanation">${esc(m.content.explanation || m.content.text)}</p>${m.content.applicability === "not_applicable" ? '<span class="muted">Ruolo non applicabile</span>' : ""}<div class="claim-tags">${m.content.claims.some((c) => c.basis === "assumption") ? "<span>Ipotesi presenti</span>" : ""}${m.content.claims.some((c) => c.basis === "estimate") ? "<span>Stime presenti</span>" : ""}</div></article>` : `<p class="placeholder">${working ? "Sta preparando la sua valutazione…" : role === "critic" ? "Esaminerà le proposte, le prove e le ipotesi dei tre ruoli." : "La valutazione di questo ruolo apparirà qui."}</p>`}</div>
    <footer><button class="text-button" data-drawer="history">${m ? "Messaggi e prove ↗" : "Spiegazioni pubbliche"}</button><span class="pager"><button aria-label="Turno precedente ${actors[role]}" data-role-page="${role}" data-index="${index - 1}" ${index <= 0 ? "disabled" : ""}>‹</button><small>${messages.length ? index + 1 : 0}/${messages.length}</small><button aria-label="Turno successivo ${actors[role]}" data-role-page="${role}" data-index="${index + 1}" ${index >= messages.length - 1 ? "disabled" : ""}>›</button></span></footer>
  </section>`;
}
function question(r: Run) {
  const q = r.question,
    d = draft(r);
  if (r.state !== "awaiting_input" || !q) return "";
  return `<form class="question"><label class="question-text" for="answer-option">${esc(q.text)}</label><div class="answer-controls"><select id="answer-option" aria-label="Scelta" data-field="option"><option value="">Scegli una risposta…</option>${q.options.map((o) => `<option value="${esc(o.id)}" ${d.option === o.id ? "selected" : ""}>${esc(o.label)}</option>`).join("")}<option value="__custom" ${d.option === "__custom" ? "selected" : ""}>Scrivi una risposta…</option></select><button type="submit" aria-label="Invia risposta e riprendi" title="Invia risposta" ${busy.has(r.id) ? "disabled" : ""}>↑</button><button type="button" class="text-button" data-drawer="question" aria-label="Dettagli della domanda">ⓘ</button></div>${d.option === "__custom" ? `<textarea aria-label="Risposta libera" data-field="text" maxlength="10000" placeholder="La tua risposta…">${esc(d.text)}</textarea>` : ""}</form>`;
}
function detail(r: Run) {
  return `<div class="detail-header"><div><span class="badge ${r.state}">${labels[r.state]}</span><h2>${esc(r.task.title)}</h2></div><button class="text-button" data-drawer="context" aria-label="Dettagli del task e fonti">ⓘ</button></div>
    ${rolePanel(r, "critic")}<div class="model-grid">${["analyst", "operations", "finance"].map((role) => rolePanel(r, role)).join("")}</div>
    <div class="workspace-tools"><button class="text-button" data-drawer="investigation">Indagine e prove <span>${r.tool_activity?.length ?? 0}</span></button><button class="text-button" data-drawer="objections">Obiezioni <span>${(r.objections ?? []).filter((o) => o.status === "open").length}</span></button><button class="text-button" data-drawer="history">Cronologia</button><span class="live-status">${r.turn_progress?.pending_job_id ? "Calcolo in corso" : esc(connection.get(r.id) || `Round ${r.round}/${r.max_rounds}`)}</span></div>
    ${question(r)}${r.state === "failed" ? `<section class="failure"><p>${esc(r.error?.message)}</p><button data-retry>Riprova il turno</button></section>` : ""}
    <div class="proposal-strip"><span>${r.proposal ? `<b>${r.proposal.status === "conditional" ? "Piano condizionale" : "Proposta"} · v${r.proposal.version}</b><small>${esc(r.proposal.summary)}</small>` : "<small>La proposta prenderà forma con il confronto tra i ruoli.</small>"}</span><button data-drawer="proposal" ${!r.proposal ? "disabled" : ""}>${r.state === "proposal_ready" ? "Rivedi e approva ↗" : "Apri piano ↗"}</button></div>`;
}
function drawerContent(r: Run) {
  if (drawer === "proposal")
    return (
      proposal(r) +
      `<details><summary>Versioni della proposta</summary>${(r.proposals ?? []).map((p) => `<p>v${p.version} · ${esc(p.status)} · ${esc(p.summary)}</p>`).join("")}</details>`
    );
  if (drawer === "investigation") return investigation(r);
  if (drawer === "objections")
    return `<h2>Obiezioni</h2>${(r.objections ?? []).map((o) => `<article><h3>${esc(o.concern)}</h3><span>${o.status === "open" ? "Aperta" : "Risolta"}${o.blocking ? " · bloccante" : ""}</span><p>${esc(o.explanation)}</p>${o.resolution ? `<p>${esc(o.resolution.explanation)}</p>` : ""}</article>`).join("") || "<p>Nessuna obiezione.</p>"}`;
  if (drawer === "question")
    return `<h2>${esc(r.question?.text)}</h2><p>${esc(r.question?.explanation)}</p>${r.question?.options.map((o) => `<h3>${esc(o.label)}</h3><p>${esc(o.explanation)}</p>`).join("") || ""}<label>Il tuo nome<input data-field="actor" value="${esc(draft(r).actor)}" maxlength="200"></label>`;
  if (drawer === "context")
    return `<h2>${esc(r.task.title)}</h2><p>${esc(r.task.description)}</p><p>${esc(r.task.context)}</p><p>${esc(r.notice)}</p><p>${esc(r.mode)} · ${esc(r.model)} · ciclo ${r.cycle}</p>${(r.evidence ?? []).map((e) => `<article><h3>${esc(e.name)}</h3><small>${esc(e.origin)}</small><p>${esc(e.text || e.url)}</p></article>`).join("")}`;
  return `<h2>Messaggi e spiegazioni pubbliche</h2>${(r.messages ?? []).map((m) => `<article class="message ${m.actor}"><h3>${esc(actors[m.actor])} · round ${m.round}</h3><p>${esc(m.content.text)}</p><p>${esc(m.content.explanation)}</p>${m.content.claims.map((c) => `<p><b>${c.basis === "supported" ? "Supportato dalle fonti citate" : c.basis === "assumption" ? "Ipotesi" : "Stima"}</b> · ${esc(c.statement)} ${c.evidence_ids.map(evidenceLink).join(" ")}</p>`).join("")}</article>`).join("")}`;
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
  root.innerHTML = `<main class="board"><aside class="column backlog" aria-label="Ticket disponibili"><div class="column-title"><h2>Ticket</h2><span>${pending.length}</span></div><p class="column-help">Trascina un ticket agli agenti.</p><div class="cards">${pending.map((t) => `<article class="task-card" draggable="${!busy.has(t.id)}" data-task="${t.id}"><span class="grip" aria-hidden="true">⠿</span><h3>${esc(t.task.title)}</h3><button class="start-button" data-start="${t.id}" aria-label="Avvia task: ${esc(t.task.title)}" title="Avvia task" ${busy.has(t.id) ? "disabled" : ""}>${busy.has(t.id) ? "…" : "↗"}</button></article>`).join("") || '<p class="empty-small">Tutti i ticket sono assegnati.</p>'}</div></aside><section class="column workspace" aria-label="Area di lavoro" data-drop><div class="workspace-heading"><h1>Agenti</h1><span class="environment">${remote ? `API · modalità ${mode}` : "Mock locale · nessuna chiamata AI"}</span></div>${error ? `<div class="error" role="alert">${esc(error)} <button data-dismiss class="secondary">Chiudi</button></div>` : ""}${activeRuns.length ? `<nav class="active-runs" aria-label="Task in lavorazione">${activeRuns.map(card).join("")}${r?.state === "awaiting_input" ? '<button class="reply-shortcut" data-reply>Rispondi</button>' : ""}</nav>` : ""}<div class="detail">${r ? detail(r) : '<div class="empty"><span class="empty-icon" aria-hidden="true">↘</span><h2>Assegna il primo ticket</h2><p>Trascinalo qui, oppure premi ↗ sul ticket.<br>Gli agenti ne discuteranno e ti chiederanno ciò che serve.</p><small>Demo con ticket fittizi e dialoghi simulati.</small></div>'}</div><div class="drop-overlay" aria-hidden="true">Rilascia il ticket per iniziare</div></section><aside class="column results" aria-label="Task completati"><div class="column-title"><h2>Completati</h2><span>${done.length}</span></div><p class="column-help">Proposte approvate</p>${done.map(card).join("") || '<p class="empty-small">I task completati appariranno qui.</p>'}</aside></main>`;
  if (drawer && r) {
    root.insertAdjacentHTML(
      "beforeend",
      `<dialog aria-label="Dettagli" class="inspector"><header><span>WORKSPACE / DETTAGLI</span><button data-close-drawer aria-label="Chiudi dettagli">×</button></header><div class="inspector-body" data-scroll="drawer">${drawerContent(r)}</div></dialog>`,
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
    error = "Inserisci il tuo nome e scegli un’opzione o scrivi una risposta.";
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
  if (el.hasAttribute("data-reply")) {
    root.querySelector(".question")?.scrollIntoView({ block: "center" });
    root
      .querySelector<HTMLSelectElement>('[data-field="option"]')
      ?.focus({ preventScroll: true });
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
      error = "Inserisci il tuo nome prima di approvare.";
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
if (remote) {
  void (async () => {
    try {
      const entries: [string, string][] = JSON.parse(
        localStorage.getItem(storageKey) || "[]",
      );
      for (const [taskId, id] of entries) {
        taskRuns.set(taskId, id);
      }
      render();
      for (const [taskId, id] of entries) {
        try {
          const r = await api.run(id);
          selected ??= id;
          accept(r);
          watch(id);
        } catch (e) {
          if (e instanceof ApiError && e.status === 404)
            taskRuns.delete(taskId);
          else {
            watch(id);
            error =
              "Impossibile recuperare alcuni run. Riconnessione in corso.";
          }
        }
      }
      persist();
      render();
    } catch {
      error = "Impossibile leggere il registro locale dei run.";
      render();
    }
  })();
}
