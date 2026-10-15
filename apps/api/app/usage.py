"""AI Usage Ledger: one AI Usage Entry per model call (FR-C1.4, ERD §7)."""

from decimal import Decimal
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from smart_ats_scoring.llm import Usage


class Price(NamedTuple):
    """USD per 1M tokens."""

    input: Decimal
    cached_input: Decimal
    output: Decimal


# By model name prefix, so a dated snapshot (gpt-6-luna-2026-08-01) takes its model's price.
# Add each model set in LLM_*_MODEL from the provider's price page; a task checks its model
# with price() before calling it, so an unpriced model fails rather than spend unrecorded.
PRICES: dict[str, Price] = {
    # Free tier, used for testing only (.env.example).
    "gemini-": Price(Decimal(0), Decimal(0), Decimal(0)),
}

_PER_TOKENS = 1_000_000


def price(model: str) -> Price | None:
    prefix = max((p for p in PRICES if model.startswith(p)), key=len, default=None)
    return None if prefix is None else PRICES[prefix]


def cost(usage: Usage) -> Decimal:
    rate = price(usage.model)
    if rate is None:
        raise LookupError(f"no price for model {usage.model} in app.usage.PRICES")
    usd = (
        (usage.input_tokens - usage.cached_tokens) * rate.input
        + usage.cached_tokens * rate.cached_input
        + usage.output_tokens * rate.output
    ) / _PER_TOKENS
    return usd.quantize(Decimal("0.000001"))


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
