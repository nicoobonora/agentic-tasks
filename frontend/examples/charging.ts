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
  { label: string; source: string; icon: string; doing: string; done: string }
> = {
  "charging.discover_sites": {
    label: "Find charging sites",
    source: "Open Data Hub · e-charging",
    icon: "📍",
    doing: "Finding charging sites",
    done: "Found charging sites",
  },
  "charging.get_inventory": {
    label: "Plug inventory",
    source: "Open Data Hub · e-charging",
    icon: "🔌",
    doing: "Checking plug inventory",
    done: "Checked plug inventory",
  },
  "charging.get_data_quality": {
    label: "Data quality and coverage",
    source: "Observation archive",
    icon: "🩺",
    doing: "Checking data quality",
    done: "Checked data quality",
  },
  "charging.get_usage_summary": {
    label: "Observed usage",
    source: "Observation archive",
    icon: "📊",
    doing: "Reading observed usage",
    done: "Read observed usage",
  },
  "charging.compare_maintenance_windows": {
    label: "Compare maintenance windows",
    source: "Derived metric",
    icon: "🛠️",
    doing: "Comparing maintenance windows",
    done: "Compared maintenance windows",
  },
  "charging.request_forecast": {
    label: "Demand forecast",
    source: "Forecast model",
    icon: "📈",
    doing: "Forecasting demand",
    done: "Forecast demand",
  },
  "charging.get_operational_inputs": {
    label: "Operational inputs",
    source: "Simulated business data",
    icon: "📋",
    doing: "Reading operational inputs",
    done: "Read operational inputs",
  },
  "charging.assess_expansion": {
    label: "Assess expansion",
    source: "Derived metric",
    icon: "🏗️",
    doing: "Assessing expansion",
    done: "Assessed expansion",
  },
  "charging.get_evidence": {
    label: "Re-read evidence",
    source: "Evidence log",
    icon: "🔎",
    doing: "Re-reading evidence",
    done: "Re-read evidence",
  },
};
