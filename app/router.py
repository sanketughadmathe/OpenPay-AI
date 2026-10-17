"""Intelligent routing (FR-03).

Pure scoring logic — no database access. The orchestrator loads providers and
recent success rates, then calls :func:`route`.

Score = 0.6 * recent_success - 0.3 * cost_norm - 0.1 * latency_norm
where cost and latency are min-max normalised across the surviving candidates.
Highest score wins; ties break on the lower provider id.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

WEIGHTS: dict[str, float] = {
    "recent_success": 0.6,
    "cost": 0.3,
    "latency": 0.1,
}

EXCLUDE_TRIED = "already attempted for this payment"
EXCLUDE_UNHEALTHY = "provider unhealthy"
EXCLUDE_CURRENCY = "currency not supported"
EXCLUDE_METHOD = "payment method not supported"


class ProviderLike(Protocol):
    id: str
    is_healthy: bool
    supported_currencies: list[str]
    supported_payment_methods: list[str]
    configured_cost: float
    simulated_success_rate: float
    timeout_rate: float
    average_latency_ms: int


class PaymentLike(Protocol):
    currency: str
    payment_method: str


@dataclass
class RoutingDecision:
    candidates: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)
    selected: str | None = None
    weights: dict[str, float] = field(default_factory=lambda: dict(WEIGHTS))
    # Health snapshot at routing time — the AI copilot explains decisions from this.
    providers_health: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidates": self.candidates,
            "excluded": self.excluded,
            "scores": self.scores,
            "selected": self.selected,
            "weights": self.weights,
            "providers_health": self.providers_health,
        }


def _normalise(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {key: 0.0 for key in values}
    return {key: (value - lo) / (hi - lo) for key, value in values.items()}


def route(
    payment: PaymentLike,
    providers: list[ProviderLike],
    recent_success: Mapping[str, float],
    exclude: set[str] = frozenset(),
) -> RoutingDecision:
    """Pick the best eligible provider for `payment`."""

    decision = RoutingDecision()
    candidates: list[ProviderLike] = []

    for provider in providers:
        decision.providers_health[provider.id] = {
            "is_healthy": provider.is_healthy,
            "success_rate": provider.simulated_success_rate,
            "timeout_rate": provider.timeout_rate,
        }
        if provider.id in exclude:
            decision.excluded[provider.id] = EXCLUDE_TRIED
        elif not provider.is_healthy:
            decision.excluded[provider.id] = EXCLUDE_UNHEALTHY
        elif payment.currency not in provider.supported_currencies:
            decision.excluded[provider.id] = EXCLUDE_CURRENCY
        elif payment.payment_method not in provider.supported_payment_methods:
            decision.excluded[provider.id] = EXCLUDE_METHOD
        else:
            candidates.append(provider)

    decision.candidates = [provider.id for provider in candidates]

    success = {
        provider.id: float(recent_success.get(provider.id, provider.simulated_success_rate))
        for provider in candidates
    }
    cost_norm = _normalise({provider.id: provider.configured_cost for provider in candidates})
    latency_norm = _normalise(
        {provider.id: provider.average_latency_ms for provider in candidates}
    )

    decision.scores = {
        provider.id: round(
            WEIGHTS["recent_success"] * success[provider.id]
            - WEIGHTS["cost"] * cost_norm[provider.id]
            - WEIGHTS["latency"] * latency_norm[provider.id],
            6,
        )
        for provider in candidates
    }

    if candidates:
        best = sorted(candidates, key=lambda provider: (-decision.scores[provider.id], provider.id))
        decision.selected = best[0].id

    return decision