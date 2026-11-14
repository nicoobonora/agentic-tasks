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
      result: "23 sites found in the Bolzano area",
      data: { count: 23, sites: SITES },
      text: "I propose starting from the 23 Bolzano sites and choosing the lowest-usage windows.",
      claim: {
        statement: "There are 23 active sites in the area.",
        basis: "supported",
      },
    };
  if (role === "analyst")
    return {
      tool: "charging.compare_maintenance_windows",
      args: { site_ids: SITES, ...period, duration_hours: 2 },
      result: "Best window: Tuesday 02:00–04:00",
      data: { best_window: "Tue 02:00-04:00", occupancy_p50: 0.04 },
      text: `Replanning with your input (${answer ?? "answer recorded"}): maintenance on Tuesday 02:00–04:00.`,
      claim: {
        statement: "Tuesday 02:00–04:00 has the lowest occupancy (4%).",
        basis: "supported",
      },
    };
  if (role === "operations")
    return {
      tool: "charging.get_data_quality",
      args: { site_ids: SITES, ...period, gap_minutes: 120 },
      result:
        cycle === 1
          ? "Coverage 71% · 4 sites below threshold"
          : "Coverage 71% · excluded sites confirmed",
      data: { coverage: 0.71, below_threshold: 4 },
      text:
        cycle === 1
          ? "Feasible, but 4 sites have too little data to plan."
          : "With the 4 sites excluded, one crew can complete the sequence in 3 nights.",
      claim: {
        statement: "4 sites have data coverage below 25%.",
        basis: "supported",
      },
    };
  if (role === "finance")
    return {
      tool: "charging.get_operational_inputs",
      args: { kind: "maintenance_cost" },
      result: "Crew hourly cost: simulated data",
      data: { crew_cost_hour_eur: 85, origin: "simulated_business" },
      text: "The night shift costs more, but avoids lost revenue at peak hours.",
      claim: {
        statement: "The night premium is offset by less lost demand.",
        basis: "estimate",
      },
    };
  return {
    tool: "charging.get_evidence",
    args: { evidence: "data_quality" },
    result: "Sources verified: 2 of 3",
    data: { verified: 2, total: 3 },
    text:
      cycle === 1
        ? "Blocking: the proposal also covers sites without sufficient data. A human decision is needed."
        : "Objection resolved: sites without data are excluded. The plan is defensible.",
    claim: {
      statement: "Numerical claims cite a tool result.",
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
        message: "Run not found.",
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
          message: "Key already used.",
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
        message: "Version changed. Check the updated state.",
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
          "Local demo content: no model calls and no external verification.",
        claims:
          actor === "analyst"
            ? [
                {
                  statement: "A short checklist can simplify the work.",
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
          limitations: ["Local simulator result: no real query was executed."],
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
        analyst: `I propose a first structure for: ${r.task.title}.`,
        operations:
          "To make the proposal usable we need to agree on the level of detail.",
        finance:
          "No relevant financial data is available: the cost assessment is not applicable.",
        critic:
          r.cycle === 1
            ? "Before closing the proposal I am asking the user for a preference."
            : "The proposal incorporates the human answer. Feasibility remains to be verified.",
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
          "Simulated dialogue: data and results are for demonstration only.";
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
            concern: "Sites without sufficient data included in the plan",
            explanation:
              "4 sites have coverage below threshold: the proposed window cannot be verified for them.",
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
                "Resolved: the operator decided to exclude the sites without data.",
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
              ? "Maintenance Tuesday 02:00–04:00 on 19 sites; 4 sites excluded for insufficient data (simulated)."
              : "Maintenance during the lowest-usage hours on the 23 Bolzano sites (simulated draft)."
            : `First proposal: ${r.task.title}. ${r.cycle > 1 ? "Preference received: " + r.evidence.at(-1)?.text : "Waiting to agree on the level of detail."}`,
          recommended_actions: script
            ? [
                {
                  title: "Maintenance window",
                  description: script.text,
                  rationale: script.claim.statement,
                  evidence_ids: m.content.evidence_ids,
                },
              ]
            : [
                {
                  title: "Prepare a first version",
                  description:
                    "Gather the available information into a checklist and share it with the participants.",
                  rationale: "Allow a review before adopting the document.",
                  evidence_ids: [],
                },
              ],
          risks: ["Timing and people's availability not verified."],
          unresolved_questions: [
            "Who will review the document before it is used?",
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
            ? "4 sites do not have sufficient data. How do we proceed?"
            : "How detailed should the first version be?",
          explanation: "The answer will guide the revision of the proposal.",
          options: [
            {
              id: "short",
              label: r.capability_profile
                ? "Exclude them and plan the others"
                : "Concise",
              explanation: "An essential checklist to review together.",
            },
            {
              id: "detailed",
              label: r.capability_profile
                ? "Include them with a site inspection"
                : "Detailed",
              explanation:
                "A draft with instructions and responsibilities to validate.",
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
          message: "Evidence not available in the simulator.",
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
          throw new Error("The simulator only supports mode=mock.");
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
          notice: "Local mock · simulated data and dialogues · no AI calls",
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
              name: "Demo task",
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
            message: "Simulated connection error. You can retry explicitly.",
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
            message: "Question no longer current.",
          });
        const option = r.question.options.find((o) => o.id === body.option_id);
        if ((body.option_id && !option) || (!option && !body.text?.trim()))
          throw new Error("Choose an option or write an answer.");
        if (
          body.finalize_with_unresolved &&
          (r.question.reason !== "round_limit" || !r.proposal)
        )
          throw new Error("Finalization not available.");
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
          throw new Error("Proposal cannot be approved.");
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
          throw new Error("Retry is only available after an error.");
        r.state = "running";
        r.error = null;
        r.proposal_version++;
        emit(r);
        advance(r);
        return r;
      }),
  };
}
