"""AI Usage Ledger: one AI Usage Entry per model call (FR-C1.4, ERD §7)."""

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_ats_scoring.llm import Usage
from smart_ats_scoring.pricing import cost, price

log = logging.getLogger(__name__)


def priced(model: str) -> bool:
    """Whether the ledger can price model. Checked before every call: tokens it cannot price
    must not be spent."""
    if price(model) is None:
        log.error("no price for model %s in smart_ats_scoring.pricing.PRICES", model)
        return False
    return True


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
