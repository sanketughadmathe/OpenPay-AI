"""AI copilot: evidence builders, a deterministic rule-based explainer, and optional LLM enrichment.

Design rules (PRD §11):
- The model only ever sees recorded evidence and only ever returns an explanation.
- The rule-based explanation is always produced first and is the fallback for every failure.
- Nothing here writes payment state.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditEvent, Payment, PaymentAttempt, Provider
from app.schemas import Explanation, LLMExplanation

log = logging.getLogger("openpay.ai")

# ---------------------------------------------------------------------------
# Evidence builders
# ---------------------------------------------------------------------------


def _provider_snapshot(db: Session) -> dict[str, dict[str, Any]]:
    return {
        p.id: {
            "is_healthy": p.is_healthy,
            "configured_success_rate": p.simulated_success_rate,
            "timeout_rate": p.timeout_rate,
            "configured_cost": p.configured_cost,
            "average_latency_ms": p.average_latency_ms,
        }
        for p in db.scalars(select(Provider).order_by(Provider.id))
    }


def build_payment_evidence(db: Session, payment: Payment) -> dict[str, Any]:
    attempts = []
    for a in payment.attempts:
        attempts.append(
            {
                "attempt_number": a.attempt_number,
                "provider_id": a.provider_id,
                "status": a.status,
                "failure_code": a.failure_code,
                "latency_ms": a.latency_ms,
                "simulated_cost": a.simulated_cost,
                "routing_decision": a.routing_decision,
            }
        )
    events = [
        {"event_type": e.event_type, "at": e.created_at.isoformat(), "payload": e.event_payload}
        for e in db.scalars(
            select(AuditEvent)
            .where(AuditEvent.payment_id == payment.id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    ]
    return {
        "kind": "payment",
        "simulated": True,
        "payment": {
            "id": payment.id,
            "order_id": payment.order_id,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "payment_method": payment.payment_method,
            "final_status": payment.status,
            "created_at": payment.created_at.isoformat(),
        },
        "attempts": attempts,
        "providers_now": _provider_snapshot(db),
        "audit_events": events,
    }


def _window_stats(db: Session, *, before: Any | None, after: Any | None) -> dict[str, Any]:
    q = select(Payment.status, func.count()).group_by(Payment.status)
    if before is not None:
        q = q.where(Payment.created_at < before)
    if after is not None:
        q = q.where(Payment.created_at >= after)
    by_status = {s: int(c) for s, c in db.execute(q).all()}
    total = sum(by_status.values())

    pq = (
        select(
            PaymentAttempt.provider_id,
            func.count(),
            func.sum(case((PaymentAttempt.status == "SUCCEEDED", 1), else_=0)),
        )
        .join(Payment, Payment.id == PaymentAttempt.payment_id)
        .group_by(PaymentAttempt.provider_id)
    )
    if before is not None:
        pq = pq.where(Payment.created_at < before)
    if after is not None:
        pq = pq.where(Payment.created_at >= after)
    per_provider = {
        pid: {"attempts": int(n), "success_rate": round(int(ok or 0) / n, 4) if n else 0.0}
        for pid, n, ok in db.execute(pq).all()
    }
    return {
        "payments": total,
        "succeeded": by_status.get("SUCCEEDED", 0),
        "failed": by_status.get("FAILED", 0),
        "pending": by_status.get("PENDING", 0),
        "success_rate": round(by_status.get("SUCCEEDED", 0) / total, 4) if total else None,
        "per_provider": per_provider,
    }


def build_incident_evidence(db: Session) -> dict[str, Any]:
    change = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.event_type == "PROVIDER_HEALTH_CHANGED")
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    )
    if change is None:
        return {
            "kind": "incident",
            "simulated": True,
            "health_change": None,
            "overall": _window_stats(db, before=None, after=None),
            "providers_now": _provider_snapshot(db),
        }
    return {
        "kind": "incident",
        "simulated": True,
        "health_change": {
            "at": change.created_at.isoformat(),
            **change.event_payload,
        },
        "before": _window_stats(db, before=change.created_at, after=None),
        "after": _window_stats(db, before=None, after=change.created_at),
        "providers_now": _provider_snapshot(db),
    }


# ---------------------------------------------------------------------------
# Rule-based explainer (always available)
# ---------------------------------------------------------------------------

_CAUSES: dict[str, str] = {
    "PROVIDER_ERROR": "Hypothesis: a transient error on the provider side (5xx, gateway fault, or capacity).",
    "PROVIDER_DOWN": "Hypothesis: the provider was marked unhealthy, so the simulator rejected the attempt.",
    "TIMEOUT": "Hypothesis: the provider did not answer in time; the real outcome is unknown, not failed.",
    "DECLINED": "Hypothesis: the issuer or provider declined the transaction; retrying elsewhere would not help.",
    "INSUFFICIENT_FUNDS": "Hypothesis: the customer's funding source could not cover the amount.",
    "NO_ELIGIBLE_PROVIDER": "Hypothesis: every provider was excluded by health or support rules at routing time.",
}
_ACTIONS: dict[str, str] = {
    "PROVIDER_ERROR": "Check the provider's status page and your error-rate alert for the same window.",
    "PROVIDER_DOWN": "Confirm who marked the provider unhealthy and whether a circuit breaker should re-test it.",
    "TIMEOUT": "Reconcile the attempt with the provider before any retry to avoid a double charge.",
    "DECLINED": "Review the decline reason code with the provider; consider customer messaging, not retries.",
    "INSUFFICIENT_FUNDS": "No orchestration action; surface a clear message to the customer.",
    "NO_ELIGIBLE_PROVIDER": "Review provider support for this currency and method, and current health flags.",
}


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def rule_based_payment_explanation(evidence: dict[str, Any]) -> Explanation:
    p = evidence["payment"]
    attempts = evidence["attempts"]
    ev: list[str] = []
    causes: list[str] = []
    actions: list[str] = []
    codes_seen: list[str] = []

    for a in attempts:
        line = f"Attempt {a['attempt_number']} on {a['provider_id']}: {a['status']}"
        if a.get("failure_code"):
            line += f" ({a['failure_code']})"
        if a.get("latency_ms") is not None:
            line += f", {a['latency_ms']} ms"
        ev.append(line + ".")
        d = a.get("routing_decision") or {}
        if d:
            scores = d.get("scores") or {}
            ranked = ", ".join(f"{k}={v:.3f}" for k, v in sorted(scores.items(), key=lambda kv: -kv[1]))
            ev.append(f"Routing for attempt {a['attempt_number']} selected {d.get('selected')} (scores: {ranked or 'none'}).")
            for pid, reason in (d.get("excluded") or {}).items():
                ev.append(f"Routing for attempt {a['attempt_number']} excluded {pid}: {reason}.")
        code = a.get("failure_code")
        if code and code not in codes_seen:
            codes_seen.append(code)

    if not attempts:
        codes_seen.append("NO_ELIGIBLE_PROVIDER")
        ev.append("No provider attempt was made; routing found no eligible provider.")

    for code in codes_seen:
        if code in _CAUSES:
            causes.append(_CAUSES[code])
            actions.append(_ACTIONS[code])

    status = p["final_status"]
    last = attempts[-1] if attempts else None
    if status == "SUCCEEDED" and len(attempts) > 1:
        first = attempts[0]
        summary = (
            f"Payment {p['id']} succeeded on {last['provider_id']} on attempt {last['attempt_number']} "
            f"after attempt 1 on {first['provider_id']} failed with {first.get('failure_code')}."
        )
    elif status == "SUCCEEDED" and last:
        summary = f"Payment {p['id']} succeeded on {last['provider_id']} on the first attempt."
    elif status == "PENDING" and last:
        summary = (
            f"Payment {p['id']} is PENDING: attempt {last['attempt_number']} on {last['provider_id']} timed out, "
            "so the outcome is unknown and no retry was made."
        )
    elif status == "FAILED" and last:
        summary = (
            f"Payment {p['id']} failed after {len(attempts)} attempt(s); the last outcome was "
            f"{last.get('failure_code') or last['status']} on {last['provider_id']}."
        )
    elif status == "FAILED":
        summary = f"Payment {p['id']} failed because no provider was eligible at routing time."
    else:
        summary = f"Payment {p['id']} is in state {status} with {len(attempts)} recorded attempt(s)."

    return Explanation(
        summary=summary,
        evidence=ev,
        possible_causes=causes,
        recommended_actions=actions or ["No action needed; the payment completed on the first attempt."],
        confidence_note=(
            "Rule-based explanation built only from recorded attempts, routing decisions and audit events. "
            "Hypotheses are labelled; nothing is inferred beyond the records."
        ),
        source="rule-based",
    )


def rule_based_incident_explanation(evidence: dict[str, Any]) -> Explanation:
    change = evidence.get("health_change")
    if not change:
        overall = evidence["overall"]
        return Explanation(
            summary=(
                f"No provider health change is recorded. Overall success rate is {_pct(overall['success_rate'])} "
                f"across {overall['payments']} payments."
            ),
            evidence=[
                f"{pid}: {s['attempts']} attempts, success {_pct(s['success_rate'])}"
                for pid, s in overall["per_provider"].items()
            ],
            possible_causes=[],
            recommended_actions=["Use the provider controls to simulate an outage, then ask again."],
            confidence_note="Insufficient data: there is no before/after window without a recorded health change.",
            source="rule-based",
        )

    before, after = evidence["before"], evidence["after"]
    pid = change.get("provider_id", "?")
    what = ", ".join(
        f"{k} {v['before']} → {v['after']}" for k, v in change.items() if isinstance(v, dict)
    )
    ev = [f"Health change on {pid} at {change['at']}: {what}."]
    ev.append(
        f"Before: {before['payments']} payments, success {_pct(before['success_rate'])}; "
        f"after: {after['payments']} payments, success {_pct(after['success_rate'])}."
    )
    for prov in sorted(set(before["per_provider"]) | set(after["per_provider"])):
        b = before["per_provider"].get(prov, {"attempts": 0, "success_rate": None})
        a = after["per_provider"].get(prov, {"attempts": 0, "success_rate": None})
        ev.append(
            f"{prov}: attempts {b['attempts']} → {a['attempts']}, success {_pct(b['success_rate'])} → {_pct(a['success_rate'])}."
        )

    shifted_to = [
        prov for prov, s in after["per_provider"].items() if prov != pid and s["attempts"] > 0
    ]
    summary = (
        f"After {pid} changed ({what}), the router sent new traffic to {', '.join(shifted_to) or 'no other provider'}; "
        f"success rate moved from {_pct(before['success_rate'])} to {_pct(after['success_rate'])}."
    )
    return Explanation(
        summary=summary,
        evidence=ev,
        possible_causes=[
            "Hypothesis: eligibility rules excluded the changed provider, so scoring selected the remaining one.",
        ],
        recommended_actions=[
            "Confirm the alternative provider's cost and latency are acceptable for the shifted volume.",
            "Decide when to re-enable the changed provider and whether a circuit breaker should do it automatically.",
        ],
        confidence_note=(
            "Windows are split on the most recent PROVIDER_HEALTH_CHANGED event by payment creation time. "
            "Rule-based; no model inference."
        ),
        source="rule-based",
    )


def rule_based_explanation(evidence: dict[str, Any]) -> Explanation:
    if evidence.get("kind") == "incident":
        return rule_based_incident_explanation(evidence)
    return rule_based_payment_explanation(evidence)


# ---------------------------------------------------------------------------
# LLM enrichment (optional, never authoritative)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a payment operations copilot for a SIMULATED payment orchestration system. "
    "Answer ONLY from the EVIDENCE JSON. Never invent amounts, outcomes, providers or metrics. "
    "Separate recorded facts (evidence) from hypotheses (possible_causes). "
    "Recommend investigation steps, never actions that move money. "
    "If evidence is insufficient, say so in confidence_note. "
    "Respond with a single JSON object with keys: summary, evidence, possible_causes, "
    "recommended_actions, confidence_note. No markdown, no code fences."
)

_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "evidence": {"type": "ARRAY", "items": {"type": "STRING"}},
        "possible_causes": {"type": "ARRAY", "items": {"type": "STRING"}},
        "recommended_actions": {"type": "ARRAY", "items": {"type": "STRING"}},
        "confidence_note": {"type": "STRING"},
    },
    "required": ["summary", "evidence", "possible_causes", "recommended_actions", "confidence_note"],
}

_QUESTIONS = {
    "payment": "Explain why this payment ended in its final status, why each provider was chosen, and what to investigate.",
    "incident": "Explain why the system switched providers after the health change and what the impact on payment success was.",
}


def _user_prompt(evidence: dict[str, Any]) -> str:
    question = _QUESTIONS["incident" if evidence.get("kind") == "incident" else "payment"]
    return f"QUESTION: {question}\n\nEVIDENCE:\n{json.dumps(evidence, default=str)}"


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
    return m.group(1) if m else text


def _parse(text: str) -> LLMExplanation:
    return LLMExplanation.model_validate(json.loads(_strip_fences(text)))


def call_gemini(evidence: dict[str, Any]) -> tuple[LLMExplanation, str]:
    s = get_settings()
    url = f"{s.gemini_url}/models/{s.gemini_model}:generateContent"
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": _user_prompt(evidence)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
        },
    }
    r = httpx.post(url, json=body, headers={"x-goog-api-key": s.gemini_api_key}, timeout=s.llm_timeout_s)
    r.raise_for_status()
    data = r.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _parse(text), f"gemini:{s.gemini_model}"


def call_ollama(evidence: dict[str, Any]) -> tuple[LLMExplanation, str]:
    s = get_settings()
    body = {
        "model": s.ollama_model,
        "stream": False,
        "format": "json",
        "options": {"num_predict": 600, "temperature": 0.2},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(evidence)},
        ],
    }
    r = httpx.post(f"{s.ollama_url}/api/chat", json=body, timeout=s.llm_timeout_s)
    r.raise_for_status()
    return _parse(r.json()["message"]["content"]), f"ollama:{s.ollama_model}"


def active_provider() -> str:
    s = get_settings()
    choice = s.llm_provider.lower()
    if choice == "auto":
        return "gemini" if s.gemini_api_key else "ollama"
    return choice


def generate_llm_explanation(evidence: dict[str, Any]) -> Explanation | None:
    """Return a validated model explanation, or None on any failure. Never raises."""
    provider = active_provider()
    try:
        if provider == "gemini":
            parsed, source = call_gemini(evidence)
        elif provider == "ollama":
            parsed, source = call_ollama(evidence)
        else:
            return None
    except Exception as exc:  # noqa: BLE001 - contract: never raise, always fall back
        log.warning("LLM explanation unavailable via %s: %s", provider, exc)
        return None
    return Explanation(**parsed.model_dump(), source=source)


# ---------------------------------------------------------------------------
# Cache + background job
# ---------------------------------------------------------------------------

_cache: dict[str, Explanation] = {}
_lock = threading.Lock()


def cache_key(kind: str, payment_id: str | None = None) -> str:
    return f"payment:{payment_id}" if kind == "payment" else "incident"


def get_cached(key: str) -> Explanation | None:
    with _lock:
        return _cache.get(key)


def put_cached(key: str, explanation: Explanation) -> None:
    with _lock:
        _cache[key] = explanation


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def generate_and_cache(key: str, evidence: dict[str, Any]) -> None:
    """Background task: enrich the cached rule-based answer with a model answer when possible."""
    result = generate_llm_explanation(evidence)
    if result is not None:
        put_cached(key, result)
