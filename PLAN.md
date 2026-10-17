# OpenPay AI — Build Plan v3

Source: [OpenPay_AI_PRD.md](OpenPay_AI_PRD.md). Re-baselined at **16:25**; status refreshed **16:51**. Build stop **17:55**, rehearsal 17:55–18:00.

## What changed

| Area | v1 | v3 | Why |
|---|---|---|---|
| AI runtime | Local Qwen (77 s/answer measured) | **GLM 5.3 via Ollama cloud model `glm-5.3:cloud`** (18 s uncapped, target <10 s with `num_predict: 400`) | Same local Ollama API, inference on Ollama's servers. GLM weights are MIT, so PRD "open-weight" holds. PRD §7 "local inference" becomes "Ollama runtime", noted in README |
| AI UX | Free-text chat, inline call, 30 s timeout | **Two fixed buttons**; rule-based answer instantly, GLM swapped in async | PRD: LLM must not block core processing. Demo never stalls |
| Dashboard | Streamlit, 5 tabs | **HTML + CSS + TypeScript**, bundled by Bun, served by FastAPI at `/ui`, 3 views | No Python UI framework, no second server, no CORS. Costs ~10 min more than Streamlit; paid for by the cuts below |
| Orchestrator | 3 stories | **1 slice** | Providers, router and retry are only testable together |
| Scenarios | `POST /demo/scenario/{name}` | Dashboard buttons calling `PATCH /providers/{id}/health` | One less endpoint |
| Backup demo | — | `demo.sh` curl script | If the UI breaks on stage |

## Locked decisions

| Decision | Choice |
|---|---|
| Backend | FastAPI + SQLAlchemy/SQLite (done). New deps: none required for the UI |
| Frontend | `dashboard/index.html`, `dashboard/styles.css`, `dashboard/src/{api,render,main}.ts`. Build: `bun build dashboard/src/main.ts --outdir dashboard/dist --watch`. Serve: `app.mount("/ui", StaticFiles(directory="dashboard", html=True))` declared **after** the API routes. Charts: Chart.js from cdnjs `<script>` tag, `declare const Chart: any` in TS. No npm install, no tsconfig, no framework |
| Frontend data path | `fetch` to same-origin `/api/v1/...` only. Types in `api.ts` mirror `app/schemas.py` field for field. Never reads the DB |
| AI runtime | Ollama `POST http://localhost:11434/api/chat`, model `glm-5.3:cloud` (pulled, machine signed in). Env `OPENPAY_OLLAMA_URL`, `OPENPAY_OLLAMA_MODEL`. Options `format: "json"`, `stream: false`, `options: {num_predict: 400, temperature: 0.2}`, timeout 30 s. No API key in the app |
| AI output | **Strip ``` fences before `json.loads`** (measured: model wraps JSON in a code block even in JSON mode). Validate with Pydantic: `summary`, `evidence[]`, `possible_causes[]`, `recommended_actions[]`, `confidence_note`. Any failure → rule-based result. Response carries `source: "glm-5.3" \| "rule-based"` |
| Determinism | `random.Random(f"{seed}:{payment_id}:{attempt_no}")` per attempt |
| Timeout semantics | Provider `TIMEOUT` → payment `PENDING`, **no retry**. Demonstrates the unknown-outcome distinction |
| Retry classes | `PROVIDER_ERROR`, `PROVIDER_DOWN` → retry on next eligible provider. `DECLINED`, `INSUFFICIENT_FUNDS` → `FAILED`. Bounded by `MAX_ATTEMPTS=2` |

**Cut:** Streamlit, pandas, Docker Compose, Redis, Prometheus, Postgres, webhooks, sandbox integration, free-text AI chat, circuit breaker, CSV export (replaced by a 5-line client-side CSV download if time remains).

## Status at 16:51 (commit 303ef2c)

| Story | State |
|---|---|
| S0 Scaffold, config, health, SQLite | ✅ |
| S1.1 Schema and models (+ `timeout_rate`, `routing_decision`) | ✅ |
| S1.4 State machine with audit | ✅ |
| S1.6 Idempotency (200 replay, 409 conflict) | ✅ |
| E1 S1.a providers, S1.b router, S1.c orchestrator + retry | ✅ CP1 passed 16:44 |
| E2 S2.a PATCH health, S2.b seed/reset, S2.c list + summary, S2.d static mount | ✅ CP2 passed 16:44 |
| S5.a tests | ✅ 27 passing |
| E3 dashboard | ❌ only the hello placeholder at `/ui/` |
| E4 AI copilot | ❌ no `app/ai.py`, explain endpoint 404; Ollama defaults sit in `config.py` |
| S5.b `demo.sh` | ❌ |
| S5.c README | ❌ still describes the first commit |

Verified by running reset → seed 100 → PATCH A unhealthy → seed 50: all 50 new payments routed to B; a retried payment shows attempt 1 on A `PROVIDER_ERROR`, attempt 2 on B `SUCCEEDED`, routing decision stored on both. About 17 min ahead of the CP2 gate.

Notes for E3: attempt rows carry the failure code as the attempt `status` (e.g. `PROVIDER_ERROR`), so TS types should match the API, not the plan's `FAILED` label. Seed mixes INR and USD; the summary splits value by currency, so the KPI should use the INR bucket or say "mixed".

## Timeline

| Window | Epic | Gate |
|---|---|---|
| ✅ done 16:44 | E1 Orchestrator slice | **CP1:** `curl POST /payments` returns a routed, retried, persisted payment with `selected_provider` and `attempt_count` |
| ✅ done 16:44 | E2 Control, analytics, static mount | **CP2:** seed 100 → PATCH A unhealthy → seed 50; summary shifts to B. `/ui/` serves a hello page |
| 16:51–17:30 | E3 Dashboard (HTML/CSS/TS) | **CP3:** full §15 demo runs in the browser without AI |
| 17:30–17:45 | E4 AI copilot | **CP4:** Explain returns rule-based instantly, GLM answer replaces it; works with Ollama stopped |
| 17:45–17:55 | E5 demo.sh, README, one rehearsal (tests already green) | `demo.sh` runs from reset, README matches the repo |

**Scope rules:**
- CP1 slips past 17:05 → E4 ships rule-based only (skip S4.b).
- CP3 slips past 17:50 → skip E4, demo the rule-based explanation from the payment detail view.
- E3 running long → drop the Transactions view; the payment detail view takes a payment ID typed into an input.

---

## Epics and stories

### E1 — Orchestrator slice (30 min) · ✅ done

- **S1.a Simulated providers (9). ✅** `app/providers.py`: `simulate_attempt(provider, payment, rng) -> AttemptResult(status, failure_code, latency_ms, cost)`. Outcome draw: `success_rate` → SUCCESS; `timeout_rate` → TIMEOUT; remaining mass 70/30 `PROVIDER_ERROR` / `DECLINED`. Unhealthy → `PROVIDER_DOWN`. Latency = `average_latency_ms ± 30%`. Cost = `amount * configured_cost`. No sleeping. Add `timeout_rate` column (default 0.02); delete `openpay.db` to recreate.
  AC: Same seed → same outcomes.
- **S1.b Router (7). ✅** `app/router.py`, pure: filter unhealthy → filter unsupported currency/method → score `0.6*recent_success − 0.3*cost_norm − 0.1*latency_norm` → highest wins, ties by id. Returns `RoutingDecision{candidates, excluded: {id: reason}, scores, selected, weights}`. Recent success = last 50 attempts, else configured rate.
  AC: Unit-testable with no DB.
- **S1.c Orchestrator + retry (14). ✅** `app/orchestrator.py::process_payment(db, payment, seed)`: `CREATED→PROCESSING`; loop ≤ `MAX_ATTEMPTS` routing with `exclude=tried`; persist attempt with `routing_decision` JSON; audit `ROUTING_DECISION_MADE`, `PROVIDER_ATTEMPT_INITIATED`, `PROVIDER_RESPONSE_RECEIVED`, `RETRY_INITIATED`; map outcomes per the retry table; no candidate → `FAILED / NO_ELIGIBLE_PROVIDER`. Call it from `create_payment_endpoint` so POST returns the finished payment. Extend `PaymentOut` with `selected_provider`, `attempt_count`, `simulated: true`.
  AC: A fails `PROVIDER_ERROR` → B succeeds → one payment, two attempts, `SUCCEEDED`.

### E2 — Control, analytics, static mount (13 min) · ✅ done

- **S2.a `PATCH /api/v1/providers/{id}/health` (3). ✅** Body `{is_healthy?, success_rate?, timeout_rate?}`. Audits `PROVIDER_HEALTH_CHANGED` (the incident summary splits before/after on this).
- **S2.b `POST /api/v1/demo/seed {count, seed}`, `POST /api/v1/demo/reset` (4). ✅** Seed runs real payments through `process_payment` with varied amounts, currencies and methods. Reset truncates tables and reseeds default providers.
- **S2.c `GET /api/v1/payments?status=&provider=&limit=` and `GET /api/v1/analytics/summary` (4). ✅** Summary: totals, success rate, simulated value, per-provider `{success_rate, avg_latency_ms, total_cost, attempts}`, failure-code counts, retry count, `simulated: true`.
  AC: Numbers equal SQL counts (AC-7).
- **S2.d Static mount (2). ✅** `dashboard/index.html` with "hello", `app.mount("/ui", StaticFiles(directory="dashboard", html=True))` after all routes. `dashboard/dist/` in `.gitignore`.

### E3 — Dashboard in HTML/CSS/TS (37 min) · ⏳ critical path

Dark single page, left sidebar of controls, three views switched by nav buttons (no router). Red banner on every view: **SIMULATED — no real money**. Overview auto-refreshes every 3 s via `setInterval`; every control action triggers an immediate refresh.

- **S3.a `api.ts` + `index.html` skeleton + `styles.css` (8).** Interfaces `Provider`, `Payment`, `Attempt`, `Summary`, `Explanation` mirroring `schemas.py`. Typed helpers `getJSON<T>(url)`, `postJSON<T>(url, body)`, `patchJSON<T>`. Layout: `<aside>` controls, `<main>` with three `<section data-view>` blocks, CSS grid, KPI card class, table class, badge class per status (`SUCCEEDED` green, `FAILED` red, `PENDING` amber).
- **S3.b Overview view + controls (12).** KPI row from summary (total, succeeded, failed, success %, ₹ value). Two Chart.js bar charts: per-provider success rate, failure-code counts. Sidebar: A/B health toggles (checkbox → PATCH), success-rate range inputs (change → PATCH), buttons **Seed 100**, **Degrade A** (rate 0.2), **Outage A** (unhealthy), **Reset**. Buttons disable while a request is in flight.
- **S3.c Transactions view (6).** Table from the list endpoint: id, order, amount, method, status badge, provider, attempts, created. Two `<select>` filters (status, provider) re-fetch with query params. Row click → payment detail view.
- **S3.d Payment detail + Copilot view (11).** Header with status badge and amount. Attempt timeline table (#, provider, outcome, failure code, latency, cost). Routing decision table per attempt (candidate, score, excluded reason). Audit events list. Two buttons: **Explain this payment**, **Summarize incident**. Result card renders Summary / Evidence / Hypotheses / Actions / Confidence with a `source` badge. Click → POST, render rule-based immediately, then poll GET every 2 s up to 30 s until `source === "glm-5.3"`, then stop.

### E4 — AI copilot on GLM 5.3 (10 min)

- **S4.a Evidence + rule-based explainer (5).** `app/ai.py::build_payment_evidence(id)` → compact dict (payment, attempts, routing decisions, provider health at routing time, summary). `build_incident_evidence()` → summary before vs after the last `PROVIDER_HEALTH_CHANGED`. `rule_based_explanation(evidence)` → five-field structure from failure codes and routing log, `source: "rule-based"`. `POST /api/v1/ai/explain/{payment_id}` and `POST /api/v1/ai/incident` return it immediately, audit `AI_EXPLANATION_REQUESTED`, and enqueue the GLM call. `GET /api/v1/ai/explain/{payment_id}` returns the latest cached result.
- **S4.b GLM call (5).** httpx POST to `OLLAMA_URL/api/chat` with the options above. System prompt: answer only from EVIDENCE, label hypotheses, state when data is insufficient, never invent amounts or outcomes, **respond with raw JSON and no markdown**. Strip fences → `json.loads` → Pydantic. On any exception, timeout, or connection error keep the rule-based result. Run as a FastAPI `BackgroundTask`, cache by payment id in a module dict. One warm-up call at startup, swallowed on failure.
  AC: With Ollama stopped the UI shows the rule-based answer and no error (AC-9).

### E5 — Tests, demo script, README (5 min + rehearsal)

- **S5.a Tests (3). ✅** Router: unhealthy excluded, unsupported currency excluded, higher score wins. Orchestrator: A fails → B succeeds gives 2 attempts; timeout → `PENDING` with 1 attempt; attempts ≤ `MAX_ATTEMPTS`. Existing 6 stay green.
- **S5.b `demo.sh` (1).** reset → seed 100 → summary → PATCH A unhealthy → seed 50 → summary → list `?status=SUCCEEDED` and pick one with `attempt_count == 2` → attempts → ai/explain.
- **S5.c README (1).** Fix status. Run: `uv run uvicorn app.main:app --reload` and `bun build dashboard/src/main.ts --outdir dashboard/dist --watch`. Open `http://127.0.0.1:8000/ui/`. `.env` is optional; every setting has a default in `config.py`. Mention `OPENPAY_OLLAMA_URL` and `OPENPAY_OLLAMA_MODEL` as overrides only for running the copilot against a different Ollama host or model tag. Note GLM 5.3 is open-weight, served through Ollama's cloud runtime; any local Ollama tag is a drop-in.

## 90-second demo (PRD §15 mapped to clicks)

1. **Reset → Seed 100.** Overview: both healthy, A takes most traffic because it scores higher.
2. **Outage A** toggle. Audit event recorded.
3. **Seed 50.** Overview: new traffic on B, success rate holds. Point at the provider chart.
4. **Transactions → filter provider B** → open a payment with 2 attempts. Show attempt 1 on A `PROVIDER_ERROR` or `PROVIDER_DOWN`, routing table excluding A, attempt 2 on B `SUCCEEDED`.
5. **Summarize incident.** Rule-based appears instantly; GLM 5.3 answer replaces it in a few seconds. Read the evidence list, point at the `source` badge.
6. **Close:** routing, state machine, idempotency and audit are deterministic Python with tests; the model only explains recorded evidence and cannot touch payment state.

## Parallel lanes (if two people)

| Lane | Stories |
|---|---|
| Backend | E1 → E2 → S4.a → S4.b → S5.a |
| Frontend | S2.d → E3 against mock JSON matching `app/schemas.py` (swap to live at CP1) → S5.b/c |

Contract to agree before splitting: `PaymentOut` (+ `selected_provider`, `attempt_count`), list endpoint shape, summary shape, five-field `Explanation` shape.

## Stretch (only after CP4)

1. Client-side CSV download of the transactions table.
2. Auto circuit breaker: provider unhealthy when its last-20 success rate drops below 50%.
3. Before/after chart around the health-change timestamp.
