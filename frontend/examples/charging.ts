import type { Task } from '../client';
import type { components } from '../charging-api-types';
type S = components['schemas'];
/** Optional example data, separate from the generic orchestrator/client. */
export function createChargingClient(baseUrl = 'http://localhost:8000') {
  async function get<T>(path: string): Promise<T> {
    const response = await fetch(`${baseUrl}/examples/charging${path}`);
    if (!response.ok) throw new Error(`Charging data HTTP ${response.status}`);
    return response.json() as Promise<T>;
  }
  return {
    task: () => get<Task>('/task'),
    sites: (source = 'Neogy-AMPECO') => get<S['Site'][]>(`/api/v1/sites?source=${encodeURIComponent(source)}`),
    plugs: (id: string) => get<S['Plug'][]>(`/api/v1/plugs?site_id=${encodeURIComponent(id)}`),
    quality: () => get<S['Quality'][]>('/api/v1/quality'),
    analysis: () => get<S['AnalysisBundle'][]>('/api/v1/analysis'),
    live: (refresh = false) => get<S['LiveData']>(`/api/v1/live?refresh=${refresh}`),
  };
}
