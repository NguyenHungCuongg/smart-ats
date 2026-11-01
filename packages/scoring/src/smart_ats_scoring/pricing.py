"""Price of a model call, the one table the API's AI Usage Ledger and the eval harness share."""

import re
from decimal import Decimal
from typing import NamedTuple

from smart_ats_scoring.llm import Usage


class Price(NamedTuple):
    """USD per 1M tokens."""

    input: Decimal
    cached_input: Decimal
    output: Decimal


# By model name, so a dated snapshot (gpt-6-luna-2026-08-01) takes its model's price; any other
# suffix (gemini-3.5-flash-image) is another model and stays unpriced.
# Add each model set in LLM_*_MODEL from the provider's price page; a task checks its model
# with price() before calling it, so an unpriced model fails rather than spend unrecorded.
PRICES: dict[str, Price] = {
    # Free tier, synthetic data only (LLM_PROVIDER=gemini, .env.example). Listed one by one: any
    # other Gemini model, whose free tier may not exist, stays unpriced and is refused.
    "gemini-3.5-flash": Price(Decimal(0), Decimal(0), Decimal(0)),
    "gemini-3.5-flash-lite": Price(Decimal(0), Decimal(0), Decimal(0)),
    "gemini-embedding-2": Price(Decimal(0), Decimal(0), Decimal(0)),
    # OpenAI Standard tier, as of 2026-11-01; an embedding bills input tokens only.
    "text-embedding-3-large": Price(Decimal("0.13"), Decimal("0.13"), Decimal(0)),
    # OpenAI Standard tier, short context (<= 272K input tokens), as of 2026-10-16.
    # ponytail: cache writes ($2.50 / $0.125) are billed here as plain input, since Usage does
    # not count them apart; split them out if the ledger drifts from the invoice.
    "gpt-6-sol": Price(Decimal("2.00"), Decimal("0.20"), Decimal("10.00")),
    "gpt-6-luna": Price(Decimal("0.10"), Decimal("0.01"), Decimal("0.50")),
}

_PER_TOKENS = 1_000_000


def by_model[T](table: dict[str, T], model: str) -> T | None:
    """The entry for model's name, matched like PRICES: a dated snapshot takes its model's."""
    name = next((p for p in table if re.fullmatch(rf"{re.escape(p)}(-\d.*)?", model)), None)
    return None if name is None else table[name]


def price(model: str) -> Price | None:
    return by_model(PRICES, model)


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
