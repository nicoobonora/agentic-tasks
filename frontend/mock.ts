import {
  ApiError,
  type ToolArtifact,
  type Run as ApiRun,
  type Task,
  type AgentMessage,
  type createClient,
} from "./client";
type Run = Required<ApiRun>;
export type Client = ReturnType<typeof createClient>;
import { tasks } from "./test-tasks";
const copy = <T>(x: T): T => structuredClone(x);
const now = () => new Date().toISOString();
async function hash(text: string) {
  const buffer = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return Array.from(new Uint8Array(buffer), (x) =>
    x.toString(16).padStart(2, "0"),
  ).join("");
}
const roles = ["analyst", "operations", "finance", "critic"] as const;
type Role = (typeof roles)[number];
type Script = {
  tool: string;
  args: Record<string, unknown>;
  result: string;
  data: Record<string, unknown>;
  text: string;
  claim: { statement: string; basis: "supported" | "assumption" | "estimate" };
};
const SITES = [
  "Neogy-AMPECO:77436",
  "Neogy-AMPECO:77594",
  "Neogy-AMPECO:78216",
];
/** Declared demo script for charging runs: no query is executed, every result is labelled simulated. */
function chargingScript(role: Role, cycle: number, answer?: string): Script {
  const period = { start: "2026-09-01", end: "2026-11-14" };
  if (role === "analyst" && cycle === 1)
    return {
      tool: "charging.discover_sites",
      args: { area: "Bolzano", source: "Neogy-AMPECO", limit: 100 },
      result: "23 siti trovati nell’area di Bolzano",
      data: { count: 23, sites: SITES },
      text: "Propongo di partire dai 23 siti di Bolzano e scegliere le finestre di minor utilizzo.",
      claim: {
        statement: "Nell’area ci sono 23 siti attivi.",
        basis: "supported",
      },
    };
  if (role === "analyst")
    return {
      tool: "charging.compare_maintenance_windows",
      args: { site_ids: SITES, ...period, duration_hours: 2 },
      result: "Finestra migliore: martedì 02:00–04:00",
      data: { best_window: "Tue 02:00-04:00", occupancy_p50: 0.04 },
      text: `Ripianifico con la tua indicazione (${answer ?? "risposta registrata"}): manutenzione il martedì 02:00–04:00.`,
      claim: {
        statement: "Martedì 02:00–04:00 ha l’occupazione più bassa (4%).",
        basis: "supported",
      },
    };
  if (role === "operations")
    return {
      tool: "charging.get_data_quality",
      args: { site_ids: SITES, ...period, gap_minutes: 120 },
      result:
        cycle === 1
          ? "Copertura 71% · 4 siti sotto soglia"
          : "Copertura 71% · siti esclusi confermati",
      data: { coverage: 0.71, below_threshold: 4 },
      text:
        cycle === 1
          ? "Fattibile, ma 4 siti hanno dati troppo scarsi per pianificare."
          : "Con i 4 siti esclusi, la sequenza è eseguibile da una squadra in 3 notti.",
      claim: {
        statement: "4 siti hanno copertura dati sotto il 25%.",
        basis: "supported",
      },
    };
  if (role === "finance")
    return {
      tool: "charging.get_operational_inputs",
      args: { kind: "maintenance_cost" },
      result: "Costo orario squadra: dato simulato",
      data: { crew_cost_hour_eur: 85, origin: "simulated_business" },
      text: "Il turno notturno costa di più, ma evita mancati ricavi nelle ore di punta.",
      claim: {
        statement:
          "La maggiorazione notturna è compensata dalla minore domanda persa.",
        basis: "estimate",
      },
    };
  return {
    tool: "charging.get_evidence",
    args: { evidence: "data_quality" },
    result: "Fonti verificate: 2 di 3",
    data: { verified: 2, total: 3 },
    text:
      cycle === 1
        ? "Blocco: la proposta copre anche siti senza dati sufficienti. Serve una decisione umana."
        : "Obiezione risolta: i siti senza dati sono esclusi. Il piano è difendibile.",
    claim: {
      statement: "Le affermazioni numeriche citano un risultato di strumento.",
      basis: "supported",
    },
  };
}
export function createMockClient(delay = 1000): Client {
  const runs = new Map<string, Run>();
  const listeners = new Map<string, Set<(r: Run, n: number) => void>>();
  const replays = new Map<string, { payload: string; run: Run }>();
  let sequence = 0;
  function get(id: string) {
    const r = runs.get(id);
    if (!r)
      throw new ApiError(404, {
        code: "not_found",
        message: "Run non trovato.",
      });
    return r;
  }
  function emit(r: Run) {
    r.updated_at = now();
    const seq = ++sequence;
    listeners.get(r.id)?.forEach((fn) => fn(copy(r), seq));
  }
  function command(key: string, payload: unknown, act: () => Run) {
    const serialized = JSON.stringify(payload),
      previous = replays.get(key);
    if (previous) {
      if (previous.payload !== serialized)
        throw new ApiError(409, {
          code: "idempotency_conflict",
          message: "Chiave già utilizzata.",
        });
      return copy(previous.run);
    }
    const r = act();
    replays.set(key, { payload: serialized, run: copy(r) });
    return copy(r);
  }
  function version(r: Run, v: number) {
    if (r.proposal_version !== v)
      throw new ApiError(409, {
        code: "stale_version",
        message: "Versione cambiata. Controlla lo stato aggiornato.",
      });
  }
  function message(
    r: Run,
    actor: AgentMessage["actor"],
    text: string,
  ): AgentMessage {
    const m: AgentMessage = {
      id: crypto.randomUUID(),
      actor,
      cycle: r.cycle,
      round: r.round,
      proposal_version: r.proposal_version,
      reply_to: r.messages.at(-1)?.id ?? null,
      created_at: now(),
      content: {
        applicability: actor === "finance" ? "not_applicable" : "applicable",
        kind:
          actor === "analyst"
            ? "proposal"
            : actor === "finance"
              ? "not_applicable"
              : "review",
        text,
        explanation:
          "Contenuto dimostrativo locale: nessuna chiamata a un modello e nessuna verifica esterna.",
        claims:
          actor === "analyst"
            ? [
                {
                  statement: "Una checklist breve può semplificare il lavoro.",
                  basis: "assumption",
                  evidence_ids: [],
                },
              ]
            : [],
        evidence_ids: [],
        objections: [],
        resolutions: [],
        draft: null,
        question: null,
        needs_revision: false,
      },
    };
    r.messages.push(m);
    return m;
  }
  const artifacts = new Map<string, ToolArtifact>();
  function toolPhase(r: Run, then: () => void) {
    const role = r.next_role as Role;
    const script = chargingScript(role, r.cycle);
    const token = crypto.randomUUID();
    const id = crypto.randomUUID();
    r.turn_progress = {
      token,
      cycle: r.cycle,
      round: r.round,
      role,
      proposal_version: r.proposal_version,
      provider_requests: 1,
      tool_requests: 1,
      pending_job_id: null,
      correction: null,
      started_at: now(),
      protocol: [],
    };
    const call = {
      id,
      run_id: r.id,
      cycle: r.cycle,
      role,
      turn_token: token,
      request: { call_id: id, name: script.tool, arguments: script.args },
      normalized_parameters: script.args,
      cache_key: id,
      source_fingerprint: "mock",
      method_version: "1",
      created_at: now(),
      completed_at: null,
      status: "running" as const,
      artifact_id: null as string | null,
      summary: "",
      cached: false,
    };
    r.tool_activity.push(call);
    emit(r);
    setTimeout(() => {
      if (r.state !== "running") return;
      const artifactId = `artifact-mock-${id.slice(0, 8)}`;
      Object.assign(call, {
        status: "succeeded",
        completed_at: now(),
        artifact_id: artifactId,
        summary: `${script.tool}: available. ${script.result}`,
      });
      artifacts.set(artifactId, {
        id: artifactId,
        run_id: r.id,
        tool_call_id: id,
        sha256: "mock",
        outcome: {
          status: "available",
          summary: script.result,
          data: script.data,
          limitations: [
            "Risultato del simulatore locale: nessuna query reale è stata eseguita.",
          ],
          origin: "simulated_business",
          source_fingerprint: "mock",
          method: "mock-script",
          method_version: "1",
          queried_at: now(),
        },
      });
      r.evidence.push({
        id: artifactId,
        name: script.tool,
        text: script.result,
        url: null,
        origin: "simulated_business",
        sha256: "mock",
        artifact_id: artifactId,
        limitations: [],
      });
      emit(r);
      setTimeout(then, delay * 0.6);
    }, delay * 0.9);
  }
  function advance(r: Run) {
    if (r.capability_profile) {
      setTimeout(() => {
        if (r.state !== "running") return;
        toolPhase(r, () => {
          if (r.state !== "running") return;
          step(r);
        });
      }, delay * 0.4);
      return;
    }
    setTimeout(() => step(r), delay);
  }
  function step(r: Run) {
    {
      if (r.state !== "running") return;
      const role = r.next_role;
      const texts = {
        analyst: `Propongo una prima struttura per: ${r.task.title}.`,
        operations:
          "Per rendere la proposta utilizzabile serve concordare il livello di dettaglio.",
        finance:
          "Non sono disponibili dati economici pertinenti: la valutazione dei costi non è applicabile.",
        critic:
          r.cycle === 1
            ? "Prima di chiudere la proposta chiedo una preferenza all’utente."
            : "La proposta incorpora la risposta umana. La fattibilità rimane da verificare.",
      };
      const answer =
        r.evidence.filter((e) => e.origin === "human_answer").at(-1)?.text ??
        undefined;
      const script = r.capability_profile
        ? chargingScript(role as Role, r.cycle, answer)
        : null;
      const m = message(r, role, script ? script.text : texts[role]);
      if (script) {
        const artifactId = r.tool_activity.at(-1)?.artifact_id;
        m.content.applicability = "applicable";
        m.content.kind =
          role === "analyst"
            ? r.cycle > 1
              ? "revision"
              : "proposal"
            : role === "critic" && r.cycle === 1
              ? "objection"
              : "review";
        m.content.explanation =
          "Dialogo simulato: dati e risultati sono dimostrativi.";
        m.content.claims = [
          { ...script.claim, evidence_ids: artifactId ? [artifactId] : [] },
        ];
        m.content.evidence_ids = artifactId ? [artifactId] : [];
        if (role === "critic" && r.cycle === 1) {
          const objection = {
            target_message_id:
              r.messages.find(
                (x) => x.actor === "analyst" && x.cycle === r.cycle,
              )?.id ?? null,
            concern: "Siti senza dati sufficienti inclusi nel piano",
            explanation:
              "4 siti hanno copertura sotto soglia: la finestra proposta non è verificabile per loro.",
            blocking: true,
            evidence_ids: artifactId ? [artifactId] : [],
          };
          m.content.objections = [objection];
          r.objections.push({
            ...objection,
            id: crypto.randomUUID(),
            message_id: m.id,
            status: "open",
            resolution: null,
            resolved_by_message_id: null,
          });
        }
        if (role === "critic" && r.cycle > 1) {
          const human = r.evidence
            .filter((e) => e.origin === "human_answer")
            .at(-1);
          for (const o of r.objections.filter((o) => o.status === "open")) {
            o.status = "resolved";
            o.resolved_by_message_id = m.id;
            o.resolution = {
              objection_id: o.id,
              explanation:
                "Risolta: l’operatore ha deciso di escludere i siti senza dati.",
              evidence_ids: human ? [human.id] : [],
            };
            m.content.resolutions.push(o.resolution);
          }
        }
      }
      if (role === "analyst") {
        r.proposal_version++;
        m.proposal_version = r.proposal_version;
        r.proposal = {
          version: r.proposal_version,
          created_at: now(),
          status: "draft",
          summary: script
            ? r.cycle > 1
              ? "Manutenzione martedì 02:00–04:00 su 19 siti; 4 siti esclusi per dati insufficienti (simulato)."
              : "Manutenzione nelle ore di minor utilizzo sui 23 siti di Bolzano (bozza simulata)."
            : `Prima proposta: ${r.task.title}. ${r.cycle > 1 ? "Preferenza ricevuta: " + r.evidence.at(-1)?.text : "In attesa di concordare il dettaglio."}`,
          recommended_actions: script
            ? [
                {
                  title: "Finestra di manutenzione",
                  description: script.text,
                  rationale: script.claim.statement,
                  evidence_ids: m.content.evidence_ids,
                },
              ]
            : [
                {
                  title: "Preparare una prima versione",
                  description:
                    "Raccogliere le informazioni disponibili in una checklist e sottoporla ai partecipanti.",
                  rationale:
                    "Consentire una revisione prima di adottare il documento.",
                  evidence_ids: [],
                },
              ],
          risks: ["Tempi e disponibilità delle persone non verificati."],
          unresolved_questions: [
            "Chi verificherà il documento prima dell’utilizzo?",
          ],
          evidence_ids: m.content.evidence_ids,
          source_message_ids: [m.id],
        };
        r.proposals.push(copy(r.proposal));
      }
      if (role === "critic" && r.cycle === 1) {
        r.state = "awaiting_input";
        r.question = {
          id: crypto.randomUUID(),
          proposal_version: r.proposal_version,
          reason: "agent_request",
          text: r.capability_profile
            ? "4 siti non hanno dati sufficienti. Come procediamo?"
            : "Quanto deve essere dettagliata la prima versione?",
          explanation: "La risposta guiderà la revisione della proposta.",
          options: [
            {
              id: "short",
              label: r.capability_profile
                ? "Escludili e pianifica gli altri"
                : "Sintetica",
              explanation: "Una checklist essenziale da rivedere insieme.",
            },
            {
              id: "detailed",
              label: r.capability_profile
                ? "Includili con un sopralluogo"
                : "Dettagliata",
              explanation:
                "Una bozza con istruzioni e responsabilità da validare.",
            },
          ],
          allow_free_text: true,
        };
      } else if (role === "critic") {
        r.state = "proposal_ready";
        r.proposal!.status = "final";
        r.proposals.push(copy(r.proposal!));
      } else r.next_role = roles[roles.indexOf(role) + 1];
      r.turn_progress = null;
      emit(r);
      if (r.state === "running") advance(r);
    }
  }
  return {
    artifact: async (_id, artifactId) => {
      const a = artifacts.get(artifactId);
      if (!a)
        throw new ApiError(404, {
          code: "not_found",
          message: "Prova non disponibile nel simulatore.",
        });
      return copy(a);
    },
    tools: async () => [],
    health: async () => ({
      status: "ok",
      api_version: "2.0",
      model_configured: false,
      model: null,
      default_max_rounds: 3,
    }),
    createRun: async (body) => {
      const input = JSON.stringify(body.task);
      const sha256 = await hash(input);
      return command(body.idempotency_key, body, () => {
        if (body.mode !== "mock")
          throw new Error("Il simulatore supporta solo mode=mock.");
        const r: Run = {
          schema_version: "2.0",
          provider_attempts: null,
          model_usage: {},
          capability_profile: body.capability_profile ?? null,
          profile_version: body.capability_profile ? "1" : null,
          turn_progress: null,
          tool_activity: [],
          id: crypto.randomUUID(),
          task: copy(body.task),
          mode: "mock",
          model: null,
          notice:
            "Mock locale · dati e dialoghi simulati · nessuna chiamata AI",
          state: "running",
          proposal_version: 0,
          cycle: 1,
          round: 1,
          max_rounds: body.max_rounds ?? 3,
          next_role: "analyst",
          messages: [],
          evidence: [
            {
              id: crypto.randomUUID(),
              name: "Task dimostrativo",
              text: input,
              url: null,
              origin: "user_provided",
              sha256,
            },
          ],
          objections: [],
          proposals: [],
          proposal: null,
          question: null,
          approval: null,
          error: null,
          created_at: now(),
          updated_at: now(),
        };
        runs.set(r.id, r);
        if (tasks.find((t) => t.task.title === body.task.title)?.fail) {
          r.state = "failed";
          r.error = {
            code: "simulated_error",
            message:
              "Errore di connessione simulato. Puoi ritentare esplicitamente.",
          };
        } else advance(r);
        return r;
      });
    },
    run: async (id) => copy(get(id)),
    evidence: async (id) => copy(get(id).evidence),
    subscribe: (id, fn) => {
      const set = listeners.get(id) ?? new Set();
      set.add(fn);
      listeners.set(id, set);
      return () => {
        set.delete(fn);
      };
    },
    answer: async (id, body) => {
      const r = get(id);
      const option = r.question?.options.find((o) => o.id === body.option_id);
      const answerText = [option?.label, body.text?.trim()]
        .filter(Boolean)
        .join(" — ");
      const sha256 = await hash(answerText);
      return command(body.idempotency_key, { id, body }, () => {
        const r = get(id);
        version(r, body.proposal_version);
        if (r.state !== "awaiting_input" || r.question?.id !== body.question_id)
          throw new ApiError(409, {
            code: "stale_question",
            message: "Domanda non più corrente.",
          });
        const option = r.question.options.find((o) => o.id === body.option_id);
        if ((body.option_id && !option) || (!option && !body.text?.trim()))
          throw new Error("Scegli un’opzione o scrivi una risposta.");
        if (
          body.finalize_with_unresolved &&
          (r.question.reason !== "round_limit" || !r.proposal)
        )
          throw new Error("Finalizzazione non disponibile.");
        const answer = [option?.label, body.text?.trim()]
          .filter(Boolean)
          .join(" — ");
        message(r, "operator", answer);
        r.evidence.push({
          id: crypto.randomUUID(),
          name: body.actor,
          text: answer,
          url: null,
          origin: "human_answer",
          sha256,
        });
        r.question = null;
        r.proposal_version++;
        r.approval = null;
        if (body.finalize_with_unresolved) {
          r.state = "proposal_ready";
          r.proposal = {
            ...r.proposal!,
            version: r.proposal_version,
            status: "conditional",
          };
          r.proposals.push(copy(r.proposal));
        } else {
          r.state = "running";
          r.cycle++;
          r.round = 1;
          r.next_role = "analyst";
          advance(r);
        }
        emit(r);
        return r;
      });
    },
    approve: async (id, body) =>
      command(body.idempotency_key, { id, body }, () => {
        const r = get(id);
        version(r, body.proposal_version);
        if (
          r.state !== "proposal_ready" ||
          r.objections.some((o) => o.blocking && o.status === "open")
        )
          throw new Error("Proposta non approvabile.");
        r.state = "approved";
        r.approval = {
          proposal_version: body.proposal_version,
          actor: body.actor,
          at: now(),
        };
        emit(r);
        return r;
      }),
    retry: async (id, body) =>
      command(body.idempotency_key, { id, body }, () => {
        const r = get(id);
        version(r, body.proposal_version);
        if (r.state !== "failed")
          throw new Error("Retry disponibile solo dopo un errore.");
        r.state = "running";
        r.error = null;
        r.proposal_version++;
        emit(r);
        advance(r);
        return r;
      }),
  };
}
