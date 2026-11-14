import {
  ApiError,
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
  function advance(r: Run) {
    setTimeout(() => {
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
      const m = message(r, role, texts[role]);
      if (role === "analyst") {
        r.proposal_version++;
        m.proposal_version = r.proposal_version;
        r.proposal = {
          version: r.proposal_version,
          created_at: now(),
          status: "draft",
          summary: `Prima proposta: ${r.task.title}. ${r.cycle > 1 ? "Preferenza ricevuta: " + r.evidence.at(-1)?.text : "In attesa di concordare il dettaglio."}`,
          recommended_actions: [
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
          evidence_ids: [],
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
            ? "Quali unità e vincoli operativi vuoi confermare? (Dialogo simulato)"
            : "Quanto deve essere dettagliata la prima versione?",
          explanation: "La risposta guiderà la revisione della proposta.",
          options: [
            {
              id: "short",
              label: r.capability_profile
                ? "Definire perimetro e punti di ricarica"
                : "Sintetica",
              explanation: "Una checklist essenziale da rivedere insieme.",
            },
            {
              id: "detailed",
              label: r.capability_profile
                ? "Raccogliere prima i dati mancanti"
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
      emit(r);
      if (r.state === "running") advance(r);
    }, delay);
  }
  return {
    artifact: async () => {
      throw new Error("Il mock locale non produce prove analitiche reali.");
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
