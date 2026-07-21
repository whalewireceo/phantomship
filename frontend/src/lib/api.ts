import type {
  AnalysisResponse,
  Stats,
  Threat,
  ThreatDetail,
  Vessel,
  Zone,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

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
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  stats: () => jget<Stats>("/stats"),
  vessels: () => jget<{ vessels: Vessel[]; count: number }>("/vessels"),
  threats: () => jget<{ threats: Threat[]; count: number }>("/threats"),
  threat: (id: string) => jget<ThreatDetail>(`/threats/${id}`),
  analysis: (id: string) =>
    jpost<AnalysisResponse>(`/threats/${id}/analysis`),
  zones: () => jget<{ zones: Zone[] }>("/zones"),
};
