# OpenPay AI
## Product Requirements Document (PRD)

**Version:** 1.0  
**Status:** Hackathon MVP  
**Product Type:** Open-source AI-powered payment orchestration platform  
**Target Build Time:** 3 hours  
**Primary Users:** Developers, merchants, fintech teams, and payment operations teams

---

## 1. Executive Summary

OpenPay AI is an open-source payment orchestration platform designed to make payment processing more intelligent, transparent, and resilient. It provides a unified interface for initiating payments, selecting payment providers, tracking outcomes, analyzing failures, and monitoring performance.

Its differentiator is a deterministic routing engine that evaluates provider availability, transaction costs, success rates, and configurable rules. An open-weight language model explains routing decisions, failure patterns, and operational recommendations.

For the hackathon MVP, providers are simulated. This demonstrates routing, provider failures, recovery, transaction analytics, and AI-assisted investigation without processing real money.

**Vision:** Build open-source, developer-friendly payment orchestration infrastructure that is transparent, extensible, and AI-assisted.

## 2. Problem Statement

Merchants commonly integrate with multiple payment providers to improve payment acceptance, manage costs, and reduce dependency on a single provider. However, managing multiple providers introduces several challenges:

- **Payment failures:** Provider outages, timeouts, and declines can interrupt transactions.
- **Fragmented integrations:** Different providers expose different APIs and response formats.
- **Limited routing intelligence:** Choosing providers based on cost, health, and historical performance requires additional infrastructure.
- **Difficult troubleshooting:** Payment teams need to investigate failures across providers and transaction states.
- **Limited transparency:** Developers need clear explanations of routing decisions and payment outcomes.
- **Operational overhead:** Monitoring success rates, provider health, and failure trends can require separate tools.

OpenPay AI aims to provide a unified orchestration layer that addresses these problems through deterministic routing, standardized payment interfaces, observability, and AI-assisted analysis.

## 3. Product Goals

### 3.1 Primary goals

1. Provide a unified API for creating and tracking payment attempts.
2. Demonstrate intelligent routing across multiple payment providers.
3. Simulate provider degradation and recover eligible transactions through alternative providers.
4. Maintain an auditable history of payment state transitions and routing decisions.
5. Display transaction metrics and provider performance in a dashboard.
6. Use an open-weight LLM to explain payment failures and routing decisions.
7. Provide a reproducible, locally runnable demonstration using open-source software.

### 3.2 Non-goals for the MVP

- Processing real-money transactions.
- Storing or processing real card numbers, CVVs, or bank credentials.
- Implementing settlement, payouts, or merchant onboarding.
- Implementing a production-grade fraud detection model.
- Integrating every major payment provider.
- Building a distributed, multi-region production deployment.
- Allowing an LLM to authorize, decline, or route live payments autonomously.

## 4. Target Users

### Merchant developer
Wants a single API for payment creation and status tracking without coupling the application to one provider.

### Payment operations analyst
Wants to understand provider failures, transaction outcomes, and performance trends.

### Fintech platform engineer
Wants configurable routing policies, provider adapters, idempotency, and a clear audit trail.

### Hackathon judge or evaluator
Wants to see a working end-to-end demonstration of payment orchestration, measurable results, and a meaningful application of open-weight AI.

## 5. Core Value Proposition

OpenPay AI combines three capabilities in one developer-friendly platform:

- **Orchestrate:** Integrate with multiple payment providers through a unified interface.
- **Optimize:** Choose providers using transparent routing rules and performance metrics.
- **Explain:** Use AI to summarize failures and explain routing decisions using recorded transaction evidence.

The MVP demonstrates these capabilities with simulated providers. Future versions can connect to authorized provider sandboxes and, subject to the required approvals, live integrations.

## 6. Functional Requirements

### FR-01: Payment creation

The platform must expose an API for creating a payment.

Example request:

```json
{
  "order_id": "order_1001",
  "amount": 1499.00,
  "currency": "INR",
  "payment_method": "UPI"
}
```

Requirements:

- Generate a unique internal payment ID.
- Validate the amount, currency, and required fields.
- Accept an idempotency key.
- Prevent duplicate payment creation when a request is retried with the same key and payload.
- Return the payment ID, status, and selected provider.

### FR-02: Unified provider interface

Implement a common interface for simulated payment providers.

Each provider must support:

- Initiating a payment attempt.
- Returning a success, failure, or timeout outcome.
- Reporting simulated processing cost and latency.
- Exposing a health status.
- Recording the provider's response for auditing.

For the MVP, implement two providers: Provider A and Provider B. Provider behavior must be configurable so the demo can reproduce failures and recovery scenarios.

### FR-03: Intelligent payment routing

The routing engine must select an eligible provider using configurable, deterministic rules.

Inputs may include:

- Provider availability.
- Recent success rate.
- Estimated processing cost.
- Simulated latency.
- Supported currency and payment method.
- Merchant routing preferences.

MVP routing rules:

1. Exclude providers marked unhealthy.
2. Exclude providers that do not support the payment requirements.
3. Prefer the eligible provider with the best configured routing score.
4. Record the candidates, decision factors, and selected provider.
5. Use a deterministic fallback when the preferred provider is unavailable.

### FR-04: Payment state management

Every payment must have a defined state:

- `CREATED` — payment record created.
- `PROCESSING` — a payment attempt is in progress.
- `SUCCEEDED` — payment attempt succeeded.
- `FAILED` — payment could not be completed.
- `PENDING` — outcome remains unresolved.
- `REQUIRES_REVIEW` — transaction requires manual investigation.

State transitions must be validated. The platform must not mark a payment as successful merely because a request timed out or a provider response was missing.

The MVP should maintain an attempt-level history so the final payment status can be understood alongside previous provider outcomes.

### FR-05: Failure recovery and retry

When a provider fails, the platform must:

1. Record the failure reason.
2. Update the relevant provider metrics.
3. Determine whether a retry is permitted.
4. Select an eligible alternative provider when safe.
5. Record each attempt and the final outcome.

Retries must be bounded by a configurable attempt limit.

A timeout may represent an unknown payment outcome rather than a definitive failure. In a real integration, the system must reconcile the original attempt before creating another potentially chargeable attempt. The simulator should demonstrate this distinction.

### FR-06: Transaction dashboard

Provide a dashboard showing:

- Total transactions.
- Successful and failed transactions.
- Overall success rate.
- Total simulated transaction value.
- Provider-wise success rates.
- Provider latency and simulated costs.
- Recent payment attempts.
- Failure reasons.
- Routing decisions and retry history.

The dashboard must support filtering by status and provider.

### FR-07: AI payment copilot

Provide a natural-language interface for explaining transaction behavior and summarizing operational metrics.

Example questions:

- Why did this payment fail?
- Why was Provider B selected?
- Which provider has the highest success rate?
- What changed after Provider A became unhealthy?
- What are the most common failure reasons?
- What actions could improve payment reliability?

The AI copilot must:

- Use transaction records and routing logs as evidence.
- Distinguish recorded facts from hypotheses.
- Explain routing decisions using actual recorded inputs.
- Avoid inventing transaction outcomes or provider metrics.
- Recommend investigation steps rather than executing sensitive actions.
- Disclose when available data is insufficient.

The LLM must not determine the authoritative payment state or fabricate financial records.

### FR-08: Audit trail

Record the following events:

- Payment created.
- Routing decision made.
- Provider attempt initiated.
- Provider response received.
- Retry initiated.
- Payment state changed.
- AI explanation requested.

Each event should include a timestamp, relevant payment or attempt identifier, and structured details.

### FR-09: Demo data and simulation controls

Provide a way to generate sample transactions and simulate provider health changes.

The demo should support:

- Generating a sample batch of transactions.
- Configuring provider success and failure probabilities.
- Marking a provider healthy or unhealthy.
- Running the same test scenario before and after a provider failure.
- Resetting the simulation for repeatable demonstrations.

All simulated financial amounts and outcomes must be clearly labeled as simulated.

## 7. Non-functional Requirements

### Performance

- Payment simulation should return promptly under normal local conditions.
- Dashboard metrics should refresh without requiring a full application restart.
- LLM response time must not block core payment processing.

### Reliability

- Payment and attempt states must remain consistent.
- Idempotency must prevent duplicate payment creation for repeated requests.
- Retries must have explicit limits.
- Routing decisions and provider responses must be auditable.

### Security

- Use synthetic transaction data only.
- Never store raw payment card details or CVVs.
- Validate all external inputs.
- Keep credentials and configuration in environment variables.
- Do not expose internal stack traces or secrets in API responses.
- Treat LLM-generated text as untrusted output.

### Maintainability

- Separate routing logic, provider adapters, payment state management, and AI analysis.
- Use typed request and response models.
- Keep business rules testable without the LLM.
- Use environment-based configuration.

### Open-source and local execution

- Use open-source frameworks and libraries.
- Support local model inference through Ollama.
- Document setup and execution steps.
- Pin dependencies where practical and respect the licenses of selected components and model weights.

## 8. Proposed Technical Architecture

### Technology stack

| Component | Technology | Purpose |
|---|---|---|
| Backend API | Python + FastAPI | Payment and orchestration endpoints |
| Validation | Pydantic | Request and response validation |
| Database | SQLite for MVP | Payments, attempts, providers, audit logs |
| Data processing | pandas | Transaction analytics |
| Dashboard | Streamlit | Merchant and operations UI |
| AI runtime | Ollama | Local model inference |
| AI model | Qwen3 open-weight model | Explanations and summaries |
| Testing | pytest | Routing, state, and API tests |
| Packaging | Docker, optional | Reproducible local execution |

The selected Qwen3 model size should depend on available memory and hardware. The core payment workflow must work even when the AI model is unavailable.

### High-level architecture

```text
                 Merchant / Demo UI
                         |
                         v
                  FastAPI Gateway
                         |
                         v
                Payment Orchestrator
                         |
             +-----------+-----------+
             |           |           |
             v           v           v
         Validator    Router     State Manager
                         |
                  +------+------+
                  |             |
                  v             v
              Provider A    Provider B
              (Simulator)   (Simulator)
                  |             |
                  +------+------+
                         |
                         v
               Payment Attempt Logs
                         |
                  +------+------+
                  |             |
                  v             v
              Database      Analytics
                                |
                         +------+------+
                         |             |
                         v             v
                    Dashboard     AI Copilot
                                  (Ollama)
```

### Architectural principles

- The orchestration engine owns payment state.
- Provider adapters normalize different provider responses.
- Routing uses deterministic code, not free-form LLM output.
- The AI copilot reads relevant structured records and explains them.
- The dashboard is a presentation layer, not the source of truth.
- The database stores the authoritative payment and attempt history.

## 9. API Specification

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/payments` | Create and initiate a payment |
| `GET` | `/api/v1/payments/{payment_id}` | Retrieve payment status and details |
| `GET` | `/api/v1/payments/{payment_id}/attempts` | Retrieve provider attempt history |
| `GET` | `/api/v1/providers` | List providers and health metrics |
| `PATCH` | `/api/v1/providers/{provider_id}/health` | Change simulated provider health |
| `GET` | `/api/v1/analytics/summary` | Retrieve payment metrics |
| `POST` | `/api/v1/ai/explain/{payment_id}` | Generate an AI explanation |
| `POST` | `/api/v1/demo/seed` | Generate synthetic demo transactions |

### Example payment request

```json
{
  "order_id": "order_1001",
  "amount": 1499.00,
  "currency": "INR",
  "payment_method": "UPI"
}
```

### Example payment response

```json
{
  "payment_id": "pay_001",
  "order_id": "order_1001",
  "amount": 1499.00,
  "currency": "INR",
  "status": "SUCCEEDED",
  "selected_provider": "provider_b",
  "attempt_count": 2,
  "simulated": true
}
```

This response represents a simulated successful payment. Actual values must be derived from recorded payment and attempt data.

## 10. Data Model

### Payments

- `id`
- `order_id`
- `amount`
- `currency`
- `payment_method`
- `status`
- `idempotency_key`
- `created_at`
- `updated_at`

### Payment attempts

- `id`
- `payment_id`
- `provider_id`
- `attempt_number`
- `status`
- `failure_code`
- `latency_ms`
- `simulated_cost`
- `created_at`
- `completed_at`

### Providers

- `id`
- `name`
- `is_healthy`
- `supported_currencies`
- `supported_payment_methods`
- `configured_cost`
- `simulated_success_rate`
- `average_latency_ms`

### Audit events

- `id`
- `payment_id`
- `attempt_id`
- `event_type`
- `event_payload`
- `created_at`

The MVP schema may be simplified, but parent payments, individual attempts, and routing decisions must remain distinguishable.

## 11. AI Design

### Model responsibility

The open-weight model acts as a payment operations copilot. It does not process payments or make authoritative financial decisions.

### Input context

The backend should retrieve relevant information before invoking the model:

- Payment metadata.
- Provider attempt sequence.
- Recorded failure codes.
- Provider health at the time of routing.
- Actual routing scores and selection reasons.
- Relevant aggregate metrics.

### Output structure

The model should return a structured explanation containing:

- `summary`: concise explanation.
- `evidence`: supporting facts from the records.
- `possible_causes`: hypotheses, clearly identified.
- `recommended_actions`: investigation steps.
- `confidence_note`: limitations or missing evidence.

The backend must validate the response and ensure the model cannot modify payment records through its explanation workflow.

### Fallback behavior

If the model is unavailable, return a deterministic explanation based on recorded failure codes and routing logs. The payment API and dashboard must continue to function.

## 12. User Experience and Main Screens

- **Overview dashboard:** Transaction volume, success rate, failed payments, provider performance, and recent activity.
- **Transactions:** Searchable and filterable payment table, with a detailed view for each payment.
- **Payment details:** Payment state, provider attempt timeline, routing decision, failure details, and AI explanation.
- **Provider health:** Simulated availability, latency, success rate, cost, and controls to simulate an outage.
- **AI copilot:** Questions about a specific payment or the current simulation's aggregate performance.

For the three-hour build, these screens can be implemented as sections or tabs in a single Streamlit application.

## 13. Three-Hour MVP Scope

### Must-have

- [ ] FastAPI application with payment creation and retrieval.
- [ ] Two simulated payment providers.
- [ ] Deterministic provider routing.
- [ ] Provider failure simulation and bounded retry logic.
- [ ] Payment attempt history and idempotency.
- [ ] SQLite persistence.
- [ ] Dashboard with transaction and provider metrics.
- [ ] AI explanation using a locally hosted open-weight model, if available.
- [ ] Synthetic data and repeatable demo scenarios.

### Should-have

- [ ] CSV export.
- [ ] Interactive provider health controls.
- [ ] Dashboard filtering.
- [ ] AI-generated aggregate incident summaries.
- [ ] Docker Compose setup.

### Could-have

- [ ] Provider-specific adapter templates.
- [ ] Redis-based caching.
- [ ] Webhook simulation.
- [ ] Prometheus metrics.
- [ ] PostgreSQL migration.
- [ ] Sandbox integration with an actual payment provider.

### Explicitly out of scope

- Live payment processing.
- Real card data.
- Production-grade fraud prevention.
- Settlement and reconciliation with banks.
- Autonomous AI-controlled financial actions.
- Production-grade distributed infrastructure.

## 14. Acceptance Criteria

1. A user can create a payment through the API or demo UI.
2. Every payment has a unique identifier and a valid state.
3. The routing engine selects an eligible provider using documented rules.
4. A simulated provider failure is recorded accurately.
5. An eligible retry can use an alternative provider without silently creating duplicate payment records.
6. The payment and its individual attempts can be inspected.
7. Dashboard metrics match persisted simulation data.
8. The AI copilot explains a payment using recorded evidence.
9. The application remains usable when the LLM is offline.
10. The demo can be repeated from a clean initial state.
11. All simulated transactions are clearly identified as simulated.
12. Core routing and state-management tests pass.

## 15. Demo Scenario

The primary hackathon demonstration should take approximately 90 seconds.

1. **Normal operation:** Generate 100 synthetic transactions while both providers are healthy. Show baseline metrics.
2. **Simulate provider degradation:** Mark Provider A as unhealthy or configure it to return a high rate of simulated failures.
3. **Demonstrate intelligent routing:** Initiate additional payments. The router selects eligible alternatives based on the configured policy.
4. **Inspect a failed attempt:** Show the original provider attempt, failure reason, retry decision, and final payment status.
5. **Ask the AI copilot:** “Why did the system switch providers, and what was the impact on payment success?”
6. **Show the engineering value:** Explain that state transitions, routing, idempotency, and audit logging are deterministic and independently testable.

## 16. Success Metrics

- **Functional coverage:** All must-have workflows work end-to-end.
- **Routing correctness:** Every selected provider satisfies configured eligibility rules.
- **Auditability:** Every simulated provider attempt and routing decision is recorded.
- **Data consistency:** Dashboard metrics agree with persisted transaction data.
- **Idempotency:** Repeated requests with the same key and payload do not create duplicate payment records.
- **AI grounding:** Explanations reference actual records and distinguish facts from hypotheses.
- **Resilience:** Core workflows continue when the model is unavailable.
- **Reproducibility:** The same configured simulation can be run repeatedly.

## 17. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Model download exceeds the build window | Download the model early or complete the core MVP before adding AI. |
| Limited laptop resources | Use a smaller quantized model and make AI optional. |
| Routing logic becomes too complex | Start with transparent weighted rules and provider eligibility checks. |
| Duplicate payments during retries | Use idempotency, bounded retries, and explicit handling of unknown outcomes. |
| AI invents explanations | Supply structured evidence and validate generated output. |
| Dashboard consumes too much time | Use Streamlit and a single-page layout. |
| Demo results are inconsistent | Provide deterministic scenarios and configurable random seeds. |
| Simulation is mistaken for real processing | Label all transactions and providers as simulated. |

## 18. Future Roadmap

### Phase 1 — Hackathon MVP
Simulated providers, deterministic routing, payment tracking, analytics, and an AI operations copilot.

### Phase 2 — Provider sandbox integrations
Introduce provider adapters, authenticated sandbox requests, webhook verification, provider-specific idempotency, and reconciliation of ambiguous payment outcomes.

### Phase 3 — Production-oriented orchestration
Introduce PostgreSQL, migrations, asynchronous processing, robust event handling, distributed observability, access controls, secrets management, and operational runbooks.

### Phase 4 — Advanced intelligence
Explore historical performance-based routing, explainable cost optimization, anomaly detection, and merchant-configurable policies. Any automated changes to production routing should require guardrails, validation, and appropriate approval.

### Phase 5 — Open-source ecosystem
Publish documented adapter interfaces, example integrations, a contributor guide, architecture decisions, and a deployment guide.

## 19. Open-source Strategy

- Use a clearly understood open-source license, such as Apache-2.0, subject to review.
- Document third-party dependency and model-weight licenses separately.
- Keep provider-specific logic behind a common adapter interface.
- Provide a `.env.example` without real credentials.
- Include synthetic demo data and a straightforward startup guide.
- Avoid implying affiliation with Razorpay or any other payment provider.

## 20. Final Product Definition

**OpenPay AI is an open-source payment orchestration prototype that demonstrates intelligent provider selection, failure recovery, transaction observability, and AI-assisted payment operations using deterministic payment logic and open-weight language models.**

The MVP will prove the core workflow through simulated providers and synthetic transactions. Its architecture will leave room for sandbox integrations and future production-oriented capabilities without pretending that a three-hour prototype is production-ready.

**Hackathon positioning:**  
> An open-source, AI-assisted payment orchestration layer that helps developers understand payment failures, optimize provider selection, and build more resilient payment experiences.

## Appendix: Recommended Build Order

1. **Payment engine:** FastAPI, SQLite, two simulated providers, routing, and idempotency.
2. **Failure recovery:** Provider health toggles, retry rules, and an auditable attempt history.
3. **Dashboard:** Transactions, success rate, provider comparison, and payment details.
4. **AI copilot:** Local Qwen3 explanations grounded in payment records.
5. **Polish:** Sample dataset, README, startup commands, and demo script.

**Scope rule:** If time runs short, ship the complete payment workflow and dashboard first. AI should enhance a working payment orchestration engine, not prevent the core demo from running.
