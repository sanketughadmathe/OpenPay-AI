"""Router unit tests — pure scoring logic, no database (S1.b ACs)."""

from types import SimpleNamespace

from app.router import (
    EXCLUDE_CURRENCY,
    EXCLUDE_METHOD,
    EXCLUDE_TRIED,
    EXCLUDE_UNHEALTHY,
    route,
)


def make_provider(
    id: str,
    *,
    healthy: bool = True,
    currencies: tuple[str, ...] = ("INR", "USD"),
    methods: tuple[str, ...] = ("UPI", "CARD"),
    cost: float = 0.018,
    success: float = 0.97,
    timeout: float = 0.02,
    latency: int = 180,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        is_healthy=healthy,
        supported_currencies=list(currencies),
        supported_payment_methods=list(methods),
        configured_cost=cost,
        simulated_success_rate=success,
        timeout_rate=timeout,
        average_latency_ms=latency,
    )


def make_payment(currency: str = "INR", method: str = "UPI") -> SimpleNamespace:
    return SimpleNamespace(currency=currency, payment_method=method)


def test_unhealthy_provider_is_excluded() -> None:
    a = make_provider("provider_a", healthy=False)
    b = make_provider("provider_b")
    decision = route(make_payment(), [a, b], {"provider_a": 0.9, "provider_b": 0.9})
    assert decision.selected == "provider_b"
    assert decision.excluded["provider_a"] == EXCLUDE_UNHEALTHY
    assert decision.candidates == ["provider_b"]


def test_unsupported_currency_is_excluded() -> None:
    a = make_provider("provider_a", currencies=("USD",))
    b = make_provider("provider_b")
    decision = route(make_payment(currency="INR"), [a, b], {})
    assert decision.selected == "provider_b"
    assert decision.excluded["provider_a"] == EXCLUDE_CURRENCY


def test_unsupported_method_is_excluded() -> None:
    a = make_provider("provider_a", methods=("CARD",))
    b = make_provider("provider_b")
    decision = route(make_payment(method="UPI"), [a, b], {})
    assert decision.selected == "provider_b"
    assert decision.excluded["provider_a"] == EXCLUDE_METHOD


def test_tried_providers_are_excluded() -> None:
    a = make_provider("provider_a")
    b = make_provider("provider_b")
    decision = route(make_payment(), [a, b], {}, exclude={"provider_a"})
    assert decision.selected == "provider_b"
    assert decision.excluded["provider_a"] == EXCLUDE_TRIED


def test_higher_score_wins_and_recent_success_outweighs_cost() -> None:
    # A is cheaper and faster, but its recent success collapses; B should win.
    a = make_provider("provider_a", cost=0.010, latency=100)
    b = make_provider("provider_b", cost=0.030, latency=400)
    decision = route(make_payment(), [a, b], {"provider_a": 0.10, "provider_b": 0.99})
    assert decision.selected == "provider_b"
    assert decision.scores["provider_b"] > decision.scores["provider_a"]


def test_default_routing_prefers_cheap_fast_high_success() -> None:
    a = make_provider("provider_a", cost=0.018, success=0.97, latency=180)
    b = make_provider("provider_b", cost=0.021, success=0.94, latency=240)
    # No history: configured rates are used via the recent_success fallback.
    decision = route(make_payment(), [a, b], {})
    assert decision.selected == "provider_a"


def test_ties_break_on_lower_provider_id() -> None:
    a = make_provider("provider_a")
    b = make_provider("provider_b")
    decision = route(make_payment(), [a, b], {"provider_a": 0.9, "provider_b": 0.9})
    assert decision.selected == "provider_a"


def test_no_eligible_provider() -> None:
    a = make_provider("provider_a", healthy=False)
    b = make_provider("provider_b", healthy=False)
    decision = route(make_payment(), [a, b], {})
    assert decision.selected is None
    assert decision.candidates == []
    assert set(decision.excluded) == {"provider_a", "provider_b"}
    # Health snapshot is captured for the AI evidence even when nothing is eligible.
    assert decision.providers_health["provider_a"]["is_healthy"] is False


def test_same_inputs_produce_same_decision() -> None:
    providers = [make_provider("provider_a"), make_provider("provider_b")]
    first = route(make_payment(), providers, {"provider_a": 0.9, "provider_b": 0.5})
    second = route(make_payment(), providers, {"provider_a": 0.9, "provider_b": 0.5})
    assert first.to_payload() == second.to_payload()