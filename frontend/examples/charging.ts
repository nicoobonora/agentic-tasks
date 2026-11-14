import type { Task } from "../client";
import type { components } from "../charging-api-types";
type S = components["schemas"];
/** Optional example data, separate from the generic orchestrator/client. */
export function createChargingClient(baseUrl = "http://localhost:8000") {
  async function get<T>(path: string): Promise<T> {
    const response = await fetch(`${baseUrl}/examples/charging${path}`);
    if (!response.ok) throw new Error(`Charging data HTTP ${response.status}`);
    return response.json() as Promise<T>;
  }
  return {
    task: () => get<Task>("/task"),
    sites: (source = "Neogy-AMPECO") =>
      get<S["Site"][]>(`/api/v1/sites?source=${encodeURIComponent(source)}`),
    plugs: (id: string) =>
      get<S["Plug"][]>(`/api/v1/plugs?site_id=${encodeURIComponent(id)}`),
    quality: () => get<S["Quality"][]>("/api/v1/quality"),
    forecasts: (limit = 1) =>
      get<S["ForecastBundle"][]>(`/api/v1/forecasts?limit=${limit}`),
    forecast: (id: string) =>
      get<S["ForecastBundle"]>(`/api/v1/forecasts/${encodeURIComponent(id)}`),
    analysis: () => get<S["AnalysisBundle"][]>("/api/v1/analysis"),
    live: (refresh = false) =>
      get<S["LiveData"]>(`/api/v1/live?refresh=${refresh}`),
  };
}

/** Human-readable labels for the charging example tools; unknown tools fall back to their name. */
export const chargingToolLabels: Record<
  string,
  { label: string; source: string }
> = {
  "charging.discover_sites": {
    label: "Find charging sites",
    source: "Open Data Hub · e-charging",
  },
  "charging.get_inventory": {
    label: "Plug inventory",
    source: "Open Data Hub · e-charging",
  },
  "charging.get_data_quality": {
    label: "Data quality and coverage",
    source: "Observation archive",
  },
  "charging.get_usage_summary": {
    label: "Observed usage",
    source: "Observation archive",
  },
  "charging.compare_maintenance_windows": {
    label: "Compare maintenance windows",
    source: "Derived metric",
  },
  "charging.request_forecast": {
    label: "Demand forecast",
    source: "Forecast model",
  },
  "charging.get_operational_inputs": {
    label: "Operational inputs",
    source: "Simulated business data",
  },
  "charging.assess_expansion": {
    label: "Assess expansion",
    source: "Derived metric",
  },
  "charging.get_evidence": {
    label: "Re-read evidence",
    source: "Evidence log",
  },
};
