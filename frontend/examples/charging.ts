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
    label: "Cerca siti di ricarica",
    source: "Open Data Hub · e-charging",
  },
  "charging.get_inventory": {
    label: "Inventario prese",
    source: "Open Data Hub · e-charging",
  },
  "charging.get_data_quality": {
    label: "Qualità e copertura dati",
    source: "Archivio osservazioni",
  },
  "charging.get_usage_summary": {
    label: "Utilizzo osservato",
    source: "Archivio osservazioni",
  },
  "charging.compare_maintenance_windows": {
    label: "Confronta finestre di manutenzione",
    source: "Metrica derivata",
  },
  "charging.request_forecast": {
    label: "Previsione domanda",
    source: "Modello di forecast",
  },
  "charging.get_operational_inputs": {
    label: "Input operativi",
    source: "Dati aziendali simulati",
  },
  "charging.assess_expansion": {
    label: "Valuta espansione",
    source: "Metrica derivata",
  },
  "charging.get_evidence": {
    label: "Rilegge una prova",
    source: "Registro prove",
  },
};
