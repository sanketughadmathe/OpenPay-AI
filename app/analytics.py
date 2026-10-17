"""Analytics summary built from SQL aggregates (AC-7: numbers equal SQL counts)."""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Payment, PaymentAttempt
from app.schemas import AnalyticsSummary, ProviderSummary


def build_summary(db: Session) -> AnalyticsSummary:
    status_rows = db.execute(
        select(Payment.status, func.count()).group_by(Payment.status)
    ).all()
    by_status: dict[str, int] = {status: int(count) for status, count in status_rows}
    total_payments = sum(by_status.values())
    succeeded = by_status.get("SUCCEEDED", 0)
    failed = by_status.get("FAILED", 0)
    pending = by_status.get("PENDING", 0)
    processing = by_status.get("PROCESSING", 0)

    attempts_total = int(db.scalar(select(func.count()).select_from(PaymentAttempt)) or 0)

    value_rows = db.execute(
        select(Payment.currency, func.sum(Payment.amount)).group_by(Payment.currency)
    ).all()
    value_by_currency = {currency: round(float(total or 0), 2) for currency, total in value_rows}

    provider_rows = db.execute(
        select(
            PaymentAttempt.provider_id,
            func.count().label("attempts"),
            func.sum(case((PaymentAttempt.status == "SUCCEEDED", 1), else_=0)).label(
                "succeeded"
            ),
            func.avg(PaymentAttempt.latency_ms).label("avg_latency_ms"),
            func.coalesce(func.sum(PaymentAttempt.simulated_cost), 0.0).label("total_cost"),
        ).group_by(PaymentAttempt.provider_id)
    ).all()
    per_provider: dict[str, ProviderSummary] = {}
    for provider_id, attempts, prov_succeeded, avg_latency, total_cost in provider_rows:
        per_provider[provider_id] = ProviderSummary(
            success_rate=round(prov_succeeded / attempts, 4) if attempts else 0.0,
            avg_latency_ms=round(float(avg_latency), 1) if avg_latency is not None else None,
            total_cost=round(float(total_cost), 6),
            attempts=int(attempts),
        )

    failure_rows = db.execute(
        select(PaymentAttempt.failure_code, func.count())
        .where(PaymentAttempt.failure_code.is_not(None))
        .group_by(PaymentAttempt.failure_code)
    ).all()
    failure_codes: dict[str, int] = {code: int(count) for code, count in failure_rows}

    retry_count = int(
        db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "RETRY_INITIATED")
        )
        or 0
    )

    return AnalyticsSummary(
        totals={
            "payments": total_payments,
            "attempts": attempts_total,
            "succeeded": succeeded,
            "failed": failed,
            "pending": pending,
            "processing": processing,
        },
        success_rate=round(succeeded / total_payments, 4) if total_payments else 0.0,
        simulated_value=round(sum(value_by_currency.values()), 2),
        value_by_currency=value_by_currency,
        per_provider=per_provider,
        failure_codes=failure_codes,
        retry_count=retry_count,
    )