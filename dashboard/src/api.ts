// Typed API layer. Types mirror app/schemas.py field for field.
// The dashboard only ever talks to same-origin /api/v1 — it never reads the DB.

const BASE = "/api/v1";

export interface Provider {
  id: string;
  name: string;
  is_healthy: boolean;
  supported_currencies: string[];
  supported_payment_methods: string[];
  configured_cost: number;
  simulated_success_rate: number;
  timeout_rate: number;
  average_latency_ms: number;
}

export interface ProviderHealthUpdate {
  is_healthy?: boolean;
  success_rate?: number;
  timeout_rate?: number;
}

export interface RoutingDecision {
  candidates: string[];
  excluded: Record<string, string>;
  scores: Record<string, number>;
  selected: string | null;
  weights: Record<string, number>;
  providers_health: Record<
    string,
    { is_healthy: boolean; success_rate: number; timeout_rate: number }
  >;
}

export interface Attempt {
  id: string;
  payment_id: string;
  provider_id: string;
  attempt_number: number;
  // Carries the outcome itself: SUCCEEDED, PROVIDER_ERROR, PROVIDER_DOWN,
  // DECLINED, TIMEOUT (and PROCESSING transiently).
  status: string;
  failure_code: string | null;
  latency_ms: number | null;
  simulated_cost: number | null;
  routing_decision: RoutingDecision | null;
  created_at: string;
  completed_at: string | null;
}

export interface Payment {
  id: string;
  order_id: string;
  amount: number;
  currency: string;
  payment_method: string;
  status: string;
  idempotency_key: string | null;
  created_at: string;
  updated_at: string;
  selected_provider: string | null;
  attempt_count: number;
  simulated: boolean;
  attempts: Attempt[];
}

export interface ProviderSummary {
  success_rate: number;
  avg_latency_ms: number | null;
  total_cost: number;
  attempts: number;
}

export interface Summary {
  simulated: boolean;
  totals: Record<string, number>;
  success_rate: number;
  simulated_value: number;
  value_by_currency: Record<string, number>;
  per_provider: Record<string, ProviderSummary>;
  failure_codes: Record<string, number>;
  retry_count: number;
}

export interface AuditEvent {
  id: number;
  payment_id: string | null;
  attempt_id: string | null;
  event_type: string;
  event_payload: Record<string, unknown>;
  created_at: string;
}

export interface Explanation {
  summary: string;
  evidence: string[];
  possible_causes: string[];
  recommended_actions: string[];
  confidence_note: string;
  source: "glm-5.3" | "rule-based";
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const payload = await response.json();
      if (payload && typeof payload.detail === "string") detail += ` ${payload.detail}`;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function getJSON<T>(url: string): Promise<T> {
  return request<T>("GET", url);
}

export function postJSON<T>(url: string, body?: unknown): Promise<T> {
  return request<T>("POST", url, body ?? {});
}

export function patchJSON<T>(url: string, body: unknown): Promise<T> {
  return request<T>("PATCH", url, body);
}

// ---- Endpoint helpers ----

export const api = {
  providers: () => getJSON<Provider[]>(`${BASE}/providers`),
  patchHealth: (id: string, body: ProviderHealthUpdate) =>
    patchJSON<Provider>(`${BASE}/providers/${id}/health`, body),

  summary: () => getJSON<Summary>(`${BASE}/analytics/summary`),

  payments: (params: { status?: string; provider?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    if (params.provider) query.set("provider", params.provider);
    query.set("limit", String(params.limit ?? 200));
    return getJSON<Payment[]>(`${BASE}/payments?${query}`);
  },
  payment: (id: string) => getJSON<Payment>(`${BASE}/payments/${id}`),
  events: (id: string) => getJSON<AuditEvent[]>(`${BASE}/payments/${id}/events`),

  seed: (count: number, seed?: number) =>
    postJSON<{ seeded: number; seed: number; outcomes: Record<string, number> }>(
      `${BASE}/demo/seed`,
      { count, seed }
    ),
  reset: () => postJSON<{ reset: boolean }>(`${BASE}/demo/reset`),

  explain: (id: string) => postJSON<Explanation>(`${BASE}/ai/explain/${id}`),
  incident: () => postJSON<Explanation>(`${BASE}/ai/incident`),
  cachedExplanation: (id: string) => getJSON<Explanation>(`${BASE}/ai/explain/${id}`),
  cachedIncident: () => getJSON<Explanation>(`${BASE}/ai/incident`),
};