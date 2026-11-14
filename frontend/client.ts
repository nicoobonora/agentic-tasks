import type { components } from "./api-types";
type S = components["schemas"];
export type Run = S["Run"];
export type ToolArtifact = S["ToolArtifact"];
export type Task = S["Task"];
export type Proposal = S["Proposal"];
export type AgentMessage = S["Message"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public payload: S["Error"],
  ) {
    super(payload.message);
  }
}

/** Domain-neutral client. Retain a command key for retries; never auto-approve a new version. */
export function createClient(baseUrl = "http://localhost:8000") {
  async function request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${baseUrl}/api/v2${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      throw new ApiError(
        response.status,
        await response
          .json()
          .catch(() => ({ code: "http_error", message: response.statusText })),
      );
    }
    return response.json() as Promise<T>;
  }
  return {
    health: () => request<S["Health"]>("/health"),
    createRun: (body: S["CreateRun"]) => request<Run>("/runs", body),
    run: (id: string) => request<Run>(`/runs/${encodeURIComponent(id)}`),
    artifact: (id: string, artifactId: string) =>
      request<ToolArtifact>(
        `/runs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifactId)}`,
      ),
    tools: (id: string) =>
      request<S["ToolCall"][]>(`/runs/${encodeURIComponent(id)}/tools`),
    evidence: (id: string) =>
      request<S["Evidence"][]>(`/runs/${encodeURIComponent(id)}/evidence`),
    answer: (id: string, body: S["Answer"]) =>
      request<Run>(`/runs/${encodeURIComponent(id)}/answers`, body),
    approve: (id: string, body: S["Approval"]) =>
      request<Run>(`/runs/${encodeURIComponent(id)}/approve`, body),
    retry: (id: string, body: S["Command"]) =>
      request<Run>(`/runs/${encodeURIComponent(id)}/retry`, body),
    subscribe: (
      id: string,
      onSnapshot: (run: Run, sequence: number) => void,
      after = 0,
      onError?: (event: Event) => void,
    ) => {
      let lastSequence = after;
      const stream = new EventSource(
        `${baseUrl}/api/v2/runs/${encodeURIComponent(id)}/events?after=${after}`,
      );
      stream.addEventListener("snapshot", (event: MessageEvent<string>) => {
        const value = JSON.parse(event.data) as { data: Run; sequence: number };
        if (value.sequence <= lastSequence) return;
        lastSequence = value.sequence;
        onSnapshot(value.data, value.sequence);
      });
      if (onError) stream.onerror = onError;
      return () => stream.close();
    },
  };
}
