# OpenPay AI

OpenPay AI is a hackathon MVP for **simulated** payment orchestration: deterministic provider routing, bounded retries, an auditable attempt history, a live dashboard, and an AI copilot that explains recorded evidence. It does not process real money or store card data.

## What works today

- **Payment engine:** two simulated providers, eligibility and score-based routing, retry on provider errors, timeout parked as `PENDING` with no retry, idempotency keys, validated state machine, full audit trail.
- **Control and analytics API:** provider health toggles, deterministic demo seeding, reset, filtered payment list, metrics summary.
- **Dashboard:** HTML, CSS and TypeScript served by the API at `/ui/` with overview, transactions, and payment detail views.
- **AI copilot:** explains a payment or a provider incident from the recorded evidence. A rule-based answer returns instantly; a model answer (Gemini via API, or GLM 5.3 via Ollama) replaces it a few seconds later. The model never touches payment state.
- **Tests:** 36 passing.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- [Bun](https://bun.sh) to bundle the dashboard TypeScript
- Internet access for the Chart.js CDN used by the dashboard charts

## Quick start

Two terminals.

**Terminal 1: API and dashboard server**

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

**Terminal 2: dashboard bundle, rebuilt on every save**

```bash
bun build dashboard/src/main.ts --outdir dashboard/dist --watch
```

Then open:

| URL | What |
|---|---|
| http://127.0.0.1:8000/ui/ | Dashboard |
| http://127.0.0.1:8000/docs | Interactive API docs |

For a one-off build without watch mode, drop `--watch`.

## Demo flow

In the dashboard sidebar:

1. **Reset**, then **Seed 100**. Both providers healthy; Provider A takes most traffic because it scores higher.
2. Toggle **Provider A** unhealthy (or click **Outage A**).
3. **Seed 50**. New traffic routes to Provider B.
4. Open **Transactions**, filter by Provider B, click a payment with 2 attempts. Attempt 1 failed on A, attempt 2 succeeded on B, and the routing decision for each attempt is shown.

The whole flow, including both copilot answers, as one script (API must be running):

```bash
./demo.sh
```

The same steps as individual `curl` calls:

```bash
B=http://127.0.0.1:8000/api/v1
curl -s -X POST $B/demo/reset
curl -s -X POST $B/demo/seed -H 'Content-Type: application/json' -d '{"count":100,"seed":42}'
curl -s -X PATCH $B/providers/provider_a/health -H 'Content-Type: application/json' -d '{"is_healthy":false}'
curl -s -X POST $B/demo/seed -H 'Content-Type: application/json' -d '{"count":50,"seed":7}'
curl -s $B/analytics/summary
curl -s "$B/payments?provider=provider_b&limit=20"
```

Create a single simulated payment:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/payments \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-key' \
  -d '{"order_id":"order_1001","amount":1499.00,"currency":"INR","payment_method":"UPI"}'
```

Repeating that request with the same key returns the same payment with status 200. Changing the payload under the same key returns 409.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/payments` | Create, route, and process a payment |
| `GET` | `/api/v1/payments` | List payments; filters `status`, `provider`, `limit` |
| `GET` | `/api/v1/payments/{id}` | Payment with attempts |
| `GET` | `/api/v1/payments/{id}/attempts` | Attempt history with routing decisions |
| `GET` | `/api/v1/payments/{id}/events` | Audit events |
| `GET` | `/api/v1/providers` | Providers with config and health |
| `PATCH` | `/api/v1/providers/{id}/health` | Set `is_healthy`, `success_rate`, `timeout_rate` |
| `GET` | `/api/v1/analytics/summary` | Totals, success rate, per-provider metrics, failure codes |
| `POST` | `/api/v1/demo/seed` | Run `count` synthetic payments through the real orchestrator, deterministic by `seed` |
| `POST` | `/api/v1/demo/reset` | Wipe data and restore default providers |
| `POST` | `/api/v1/ai/explain/{id}` | Rule-based explanation now; schedules model enrichment |
| `GET` | `/api/v1/ai/explain/{id}` | Latest cached explanation (rule-based until the model answers) |
| `POST` | `/api/v1/ai/incident` | Before/after summary around the last provider health change |
| `GET` | `/api/v1/ai/incident` | Latest cached incident summary |
| `GET` | `/api/v1/ai/status` | Which model backend is active |

## Tests

```bash
uv run pytest
```

## Configuration

A `.env` file is optional. Every setting has a default in `app/config.py`. Copy `.env.example` to `.env` to change the database path, log level, retry limit (`OPENPAY_MAX_ATTEMPTS`), or simulation seed (`OPENPAY_SIM_SEED`).

The AI copilot picks its backend from `OPENPAY_LLM_PROVIDER`:

| Value | Behaviour |
|---|---|
| `auto` (default) | Gemini when `OPENPAY_GEMINI_API_KEY` is set, otherwise Ollama |
| `gemini` | Google Gemini via REST, model from `OPENPAY_GEMINI_MODEL` (default `gemini-3.8-flash`) |
| `ollama` | Local Ollama at `OPENPAY_OLLAMA_URL`, model from `OPENPAY_OLLAMA_MODEL` (default `glm-5.3:cloud`, an open-weight model served through Ollama's hosted runtime; any local tag works) |
| `none` | Rule-based explanations only |

Whatever the backend, the API answers immediately with a deterministic rule-based explanation and swaps in the validated model answer when it arrives. If the model is slow, offline, or returns invalid JSON, the rule-based answer stands and nothing else is affected. Model output is validated against a fixed schema and is never used to change payment records.

Keep the Gemini key in `.env` only; it is gitignored.

## Project layout

```
app/
  main.py            FastAPI routes and /ui static mount
  orchestrator.py    state transitions, attempts, retry loop
  router.py          eligibility filter and scoring (pure functions)
  providers.py       simulated provider outcomes (seeded RNG)
  payment_service.py creation, idempotency, state machine, audit helper
  analytics.py       summary metrics
  demo.py            seed and reset
  ai.py              evidence builders, rule-based explainer, Gemini/Ollama clients, cache
  models.py          SQLAlchemy tables
  schemas.py         Pydantic request/response models
dashboard/
  index.html, styles.css
  src/api.ts         typed fetch layer mirroring schemas.py
  src/render.ts      DOM and chart rendering
  src/main.ts        views, controls, polling
tests/
```

## Safety

All amounts, providers, and outcomes are simulated and labelled as such in every API response. No card data is ever stored.
