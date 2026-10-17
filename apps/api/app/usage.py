"""AI Usage Ledger: one AI Usage Entry per model call (FR-C1.4, ERD §7)."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_ats_scoring.llm import Usage
from smart_ats_scoring.pricing import cost


def record(
    session: Session,
    user_id: UUID | None,
    feature: str,
    usage: Usage,
    ref_type: str,
    ref_id: UUID,
) -> None:
    session.execute(
        text(
            "INSERT INTO ai_usage_entries (tenant_id, user_id, feature, model, input_tokens,"
            "  output_tokens, cached_tokens, cost_usd, ref_type, ref_id)"
            " VALUES (:tenant_id, :user_id, :feature, :model, :input_tokens,"
            "  :output_tokens, :cached_tokens, :cost_usd, :ref_type, :ref_id)"
        ),
        {
            "tenant_id": session.info["tenant_id"],
            "user_id": user_id,
            "feature": feature,
            "model": usage.model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cached_tokens": usage.cached_tokens,
            "cost_usd": cost(usage),
            "ref_type": ref_type,
            "ref_id": ref_id,
        },
    )
