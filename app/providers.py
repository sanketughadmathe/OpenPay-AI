"""Simulated payment providers.

Every attempt outcome is drawn from the provider's configured rates using a
deterministic per-attempt RNG, so a given (seed, payment, attempt) always
reproduces the same result. No network calls, no sleeping.
"""

from dataclasses import dataclass
from decimal import Decimal
from random import Random

# Outcome classes that terminate a payment without any retry.
FINAL_FAILURES = {"DECLINED", "INSUFFICIENT_FUNDS"}
# Outcome classes that make the orchestrator try the next eligible provider.
RETRYABLE_FAILURES = {"PROVIDER_ERROR", "PROVIDER_DOWN"}


@dataclass(frozen=True)
class AttemptResult:
    status: str
    failure_code: str | None
    latency_ms: int
    simulated_cost: float


def attempt_rng(seed: str, payment_id: str, attempt_number: int) -> Random:
    """Deterministic RNG stream for one (payment, attempt) pair."""

    return Random(f"{seed}:{payment_id}:{attempt_number}")


def simulate_attempt(provider, payment, rng: Random) -> AttemptResult:
    """Draw one attempt outcome for `provider` handling `payment`.

    Outcome draw: `simulated_success_rate` -> SUCCEEDED, then `timeout_rate`
    -> TIMEOUT, the remaining mass splits 70/30 between PROVIDER_ERROR and
    DECLINED. An unhealthy provider always fails with PROVIDER_DOWN.
    Latency is `average_latency_ms` +/- 30%, cost is `amount * configured_cost`.
    """

    if not provider.is_healthy:
        return AttemptResult(
            status="PROVIDER_DOWN",
            failure_code="PROVIDER_DOWN",
            latency_ms=_draw_latency(rng, provider.average_latency_ms),
            simulated_cost=_draw_cost(rng, payment.amount, provider.configured_cost),
        )

    roll = rng.random()
    success_cut = provider.simulated_success_rate
    timeout_cut = success_cut + provider.timeout_rate
    remaining = max(0.0, 1.0 - timeout_cut)

    if roll < success_cut:
        status, failure_code = "SUCCEEDED", None
    elif roll < timeout_cut:
        status, failure_code = "TIMEOUT", "TIMEOUT"
    elif roll < timeout_cut + 0.7 * remaining:
        status, failure_code = "PROVIDER_ERROR", "PROVIDER_ERROR"
    else:
        status, failure_code = "DECLINED", "DECLINED"

    return AttemptResult(
        status=status,
        failure_code=failure_code,
        latency_ms=_draw_latency(rng, provider.average_latency_ms),
        simulated_cost=_draw_cost(rng, payment.amount, provider.configured_cost),
    )


def _draw_latency(rng: Random, average_latency_ms: int) -> int:
    return int(round(rng.uniform(0.7, 1.3) * average_latency_ms))


def _draw_cost(rng: Random, amount: Decimal, configured_cost: float) -> float:
    # Consume one roll so cost stays deterministic and decoupled from latency.
    _ = rng.random()
    return round(float(amount) * configured_cost, 6)