import "./style.css";
import { ApiError, createClient, type Run } from "./client";
import { createMockClient, tasks } from "./mock";

const env = (import.meta as ImportMeta & { env: Record<string, string> }).env;
const remote = env.VITE_DATA_SOURCE === "api";
const mode = env.VITE_RUN_MODE === "model" ? "model" : "mock";
const api = remote
  ? createClient(env.VITE_API_BASE_URL || "")
  : createMockClient();
const root = document.querySelector<HTMLDivElement>("#app")!;
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
function proposal(r: Run) {
  const p = r.proposal;
  if (!p) return "";
  return `<section class="proposal"><div class="eyebrow">${p.status === "draft" ? "Bozza" : p.status === "conditional" ? "Proposta condizionata" : "Proposta finale"} · v${p.version}${p.version !== r.proposal_version ? " · versione precedente" : ""}</div><h3>${esc(p.summary)}</h3>${p.recommended_actions.map((a) => `<div class="action"><strong>${esc(a.title)}</strong><p>${esc(a.description)}</p><small>${esc(a.rationale)}</small></div>`).join("")}<h4>Rischi</h4>${p.risks.length ? `<ul>${p.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p>Nessun rischio segnalato.</p>"}<h4>Questioni irrisolte</h4>${p.unresolved_questions.length ? `<ul>${p.unresolved_questions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "<p>Nessuna questione segnalata.</p>"}${r.state === "proposal_ready" ? `<label>Il tuo nome<input data-field="actor" maxlength="200" value="${esc(draft(r).actor)}"></label><button data-approve ${busy.has(r.id) || (r.objections ?? []).some((o) => o.status === "open" && o.blocking) ? "disabled" : ""}>Approva proposta</button><p class="muted">L’approvazione riguarda il documento. Nessuna azione verrà eseguita.${(r.objections ?? []).some((o) => o.status === "open" && o.blocking) ? " Prima occorre risolvere le obiezioni bloccanti." : ""}</p>` : ""}${r.approval ? `<p class="approved-note">Approvata da ${esc(r.approval.actor)} · nessuna azione eseguita.</p>` : ""}</section>`;
}
function detail(r: Run) {
  const q = r.question,
    d = draft(r);
  return `<div class="detail-header"><span class="badge ${r.state}">${labels[r.state]}</span><h2>${esc(r.task.title)}</h2><details data-disclosure="context"><summary>Dettagli del task e fonti</summary><p>${esc(r.task.description)}</p><p>${esc(r.task.context || "Nessun contesto aggiuntivo.")}</p><small>Modalità ${esc(r.mode)}${r.model ? " · " + esc(r.model) : ""} · ciclo ${r.cycle} · round ${r.round}/${r.max_rounds}</small><p>${esc(r.notice)}</p><p>Input forniti dall’utente, non certificazioni esterne.</p>${(r.evidence ?? []).map((e) => `<article><strong>${esc(e.name)}</strong> · ${esc(e.origin)}<p>${esc(e.text || "Riferimento non letto")}</p>${e.url ? `<p>${esc(e.url)}</p>` : ""}</article>`).join("")}</details>${remote && connection.get(r.id)?.includes("connessione") ? `<p class="muted" role="status">${esc(connection.get(r.id))}</p>` : ""}</div>
  <div class="conversation">${(r.messages ?? []).length ? (r.messages ?? []).map((m) => `<article class="message ${m.actor}"><header><strong>${esc(actors[m.actor])}</strong></header><p>${esc(m.content.text)}</p><details data-disclosure="message-${esc(m.id)}"><summary>Motivazione e ipotesi</summary><p>${esc(m.content.explanation)}</p>${m.content.applicability === "not_applicable" ? '<p class="muted">Ruolo non applicabile a questa valutazione</p>' : ""}${m.content.claims.map((c) => `<p class="claim"><b>${{ supported: "Supportato da input · non verificato esternamente", assumption: "Ipotesi", estimate: "Stima" }[c.basis]}</b> — ${esc(c.statement)}${c.evidence_ids.length ? " · fonti: " + c.evidence_ids.map(esc).join(", ") : ""}</p>`).join("")}</details></article>`).join("") : '<p class="muted">Il task è stato preso in carico. In attesa del primo turno.</p>'}${r.state === "running" ? `<p class="working"><span></span>${esc(actors[r.next_role])} sta lavorando…</p>` : ""}</div>
  ${(r.objections ?? []).length ? `<section class="objections"><h3>Obiezioni</h3>${(r.objections ?? []).map((o) => `<p><strong>${esc(o.concern)}</strong> · ${o.status === "open" ? "Aperta" : "Risolta"}${o.blocking ? " · bloccante" : ""}<br>${esc(o.explanation)}${o.resolution ? "<br>Risoluzione: " + esc(o.resolution.explanation) : ""}</p>`).join("")}</section>` : ""}
  ${r.state === "awaiting_input" && q ? `<form class="question"><div class="eyebrow">Intervento richiesto · ${q.reason === "round_limit" ? "Limite round raggiunto" : "Domanda degli agenti"}</div><h3>${esc(q.text)}</h3><p>${esc(q.explanation)}</p><details data-disclosure="identity"><summary>Rispondi come ${esc(d.actor)}</summary><label>Il tuo nome<input data-field="actor" maxlength="200" required value="${esc(d.actor)}"></label></details><label>Scelta<select data-field="option"><option value="">Scrivi una risposta oppure scegli…</option>${q.options.map((o) => `<option value="${esc(o.id)}" ${d.option === o.id ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select></label>${d.option ? `<p class="option-help">${esc(q.options.find((o) => o.id === d.option)?.explanation)}</p>` : ""}<label>Risposta libera<textarea data-field="text" maxlength="10000" placeholder="Aggiungi indicazioni per gli agenti…">${esc(d.text)}</textarea></label><button type="submit" ${busy.has(r.id) ? "disabled" : ""}>Invia risposta e riprendi</button>${q.reason === "round_limit" && r.proposal ? `<button type="button" class="secondary" data-finalize ${busy.has(r.id) ? "disabled" : ""}>Finalizza mantenendo i disaccordi</button><p>Non risolve le obiezioni e non certifica le ipotesi.</p>` : ""}</form>` : ""}
  ${r.state === "failed" ? `<section class="failure"><h3>Elaborazione interrotta</h3><p>${esc(r.error?.message || "Errore non specificato")}</p><button data-retry ${busy.has(r.id) ? "disabled" : ""}>Riprova il turno</button></section>` : ""}
  ${proposal(r)}`;
}
function render() {
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
  root.innerHTML = `<main class="board"><aside class="column backlog" aria-label="Ticket disponibili"><div class="column-title"><h2>Ticket</h2><span>${pending.length}</span></div><p class="column-help">Trascina un ticket agli agenti.</p><div class="cards">${pending.map((t) => `<article class="task-card" draggable="${!busy.has(t.id)}" data-task="${t.id}"><span class="grip" aria-hidden="true">⠿</span><h3>${esc(t.task.title)}</h3><button class="start-button" data-start="${t.id}" aria-label="Avvia task: ${esc(t.task.title)}" title="Avvia task" ${busy.has(t.id) ? "disabled" : ""}>${busy.has(t.id) ? "…" : "↗"}</button></article>`).join("") || '<p class="empty-small">Tutti i ticket sono assegnati.</p>'}</div></aside><section class="column workspace" aria-label="Area di lavoro" data-drop><div class="workspace-heading"><h1>Agenti</h1><span class="environment">${remote ? `API · modalità ${mode}` : "Mock locale · nessuna chiamata AI"}</span></div>${error ? `<div class="error" role="alert">${esc(error)} <button data-dismiss class="secondary">Chiudi</button></div>` : ""}${activeRuns.length ? `<nav class="active-runs" aria-label="Task in lavorazione">${activeRuns.map(card).join("")}${r?.state === "awaiting_input" ? '<button class="reply-shortcut" data-reply>Rispondi ↓</button>' : ""}</nav>` : ""}<div class="detail">${r ? detail(r) : '<div class="empty"><span class="empty-icon" aria-hidden="true">↘</span><h2>Assegna il primo ticket</h2><p>Trascinalo qui, oppure premi ↗ sul ticket.<br>Gli agenti ne discuteranno e ti chiederanno ciò che serve.</p><small>Demo con ticket fittizi e dialoghi simulati.</small></div>'}</div><div class="drop-overlay" aria-hidden="true">Rilascia il ticket per iniziare</div></section><aside class="column results" aria-label="Task completati"><div class="column-title"><h2>Completati</h2><span>${done.length}</span></div><p class="column-help">Proposte approvate</p>${done.map(card).join("") || '<p class="empty-small">I task completati appariranno qui.</p>'}</aside></main>`;
  root
    .querySelectorAll<HTMLDetailsElement>("details[data-disclosure]")
    .forEach((el) => {
      el.open = disclosures.has(el.dataset.disclosure);
    });
  const panel = root.querySelector(".detail")!;
  panel.scrollTop = scroll;
  if (field) {
    const el = root.querySelector<HTMLInputElement | HTMLTextAreaElement>(
      `[data-field="${field}"]`,
    );
    el?.focus({ preventScroll: true });
    if (el && selection && selection[0] !== null && selection[1] !== null)
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
  if (!d.actor.trim() || (!d.option && !d.text.trim())) {
    error = "Inserisci il tuo nome e scegli un’opzione o scrivi una risposta.";
    render();
    return;
  }
  const payload = {
    proposal_version: r.proposal_version,
    question_id: r.question.id,
    actor: d.actor.trim(),
    option_id: d.option || null,
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
  if (el.dataset.start) start(el.dataset.start);
  if (el.dataset.select) {
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
