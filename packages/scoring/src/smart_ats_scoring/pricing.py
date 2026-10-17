"""Price of a model call, the one table the API's AI Usage Ledger and the eval harness share."""

from decimal import Decimal
from typing import NamedTuple

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
    # OpenAI Standard tier, short context (<= 272K input tokens), as of 2026-10-16.
    # ponytail: cache writes ($2.50 / $0.125) are billed here as plain input, since Usage does
    # not count them apart; split them out if the ledger drifts from the invoice.
    "gpt-6-sol": Price(Decimal("2.00"), Decimal("0.20"), Decimal("10.00")),
    "gpt-6-luna": Price(Decimal("0.10"), Decimal("0.01"), Decimal("0.50")),
}

_PER_TOKENS = 1_000_000


def price(model: str) -> Price | None:
    prefix = max((p for p in PRICES if model.startswith(p)), key=len, default=None)
    return None if prefix is None else PRICES[prefix]


def cost(usage: Usage) -> Decimal:
    rate = price(usage.model)
    if rate is None:
        raise LookupError(f"no price for model {usage.model} in smart_ats_scoring.pricing.PRICES")
    usd = (
        (usage.input_tokens - usage.cached_tokens) * rate.input
        + usage.cached_tokens * rate.cached_input
        + usage.output_tokens * rate.output
    ) / _PER_TOKENS
    return usd.quantize(Decimal("0.000001"))
