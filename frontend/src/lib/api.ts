import type {
  AnalysisResponse,
  Stats,
  Threat,
  ThreatDetail,
  Vessel,
  Zone,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";
export const MAX_GLOBE_VESSELS = 4000;

async function jget<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return (await r.json()) as T;
}

async function jpost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = "";
    try {
      detail = ((await r.json()) as { detail?: string }).detail ?? "";
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail || `${path}: ${r.status}`);
  }
  return (await r.json()) as T;
}

export const api = {
  stats: () => jget<Stats>("/stats"),
  // A live feed can hold tens of thousands of ships; the globe draws at most
  // this many. The backend sorts flagged vessels first so none are hidden.
  vessels: () =>
    jget<{ vessels: Vessel[]; count: number; total?: number }>(`/vessels?limit=${MAX_GLOBE_VESSELS}`),
  threats: () => jget<{ threats: Threat[]; count: number }>("/threats"),
  threat: (id: string) => jget<ThreatDetail>(`/threats/${encodeURIComponent(id)}`),
  analysis: (id: string) =>
    jpost<AnalysisResponse>(`/threats/${encodeURIComponent(id)}/analysis`),
  zones: () => jget<{ zones: Zone[] }>("/zones"),
};
