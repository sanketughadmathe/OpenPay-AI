# OpenPay AI

OpenPay AI is a hackathon MVP for **simulated** payment orchestration. It does not process real money or store card data.

## Current status

- **Epic 1 complete:** FastAPI, SQLite, configuration, core data models, provider seeding, and a health endpoint.
- **Epic 2 complete:** payment creation, request validation, idempotency, payment retrieval, attempt retrieval, state transitions, and audit logging.

## Quick start

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open the interactive API docs:

```text
http://127.0.0.1:8000/docs
```

Useful checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/providers
```

Create a simulated payment:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/payments \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-key' \
  -d '{"order_id":"order_1001","amount":1499.00,"currency":"INR","payment_method":"UPI"}'
```

## Tests

```bash
uv run pytest
```

## Configuration

Copy `.env.example` to `.env` to override the environment, database URL, and log level. The default local database is `openpay.db`.

## Safety

All payment and provider behavior in this project is simulation-only for the MVP.
