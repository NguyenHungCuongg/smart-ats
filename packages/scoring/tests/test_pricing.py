"""Price of a model call (FR-C1.4)."""

from decimal import Decimal

import pytest

from smart_ats_scoring import pricing
from smart_ats_scoring.llm import Usage


@pytest.fixture
def prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        pricing.PRICES, "test-model", pricing.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )


@pytest.mark.usefixtures("prices")
def test_cost_bills_cached_input_at_its_own_price() -> None:
    # 600 uncached x $2 + 400 cached x $0.5 + 500 output x $8, per 1M tokens.
    assert pricing.cost(Usage("test-model", 1000, 500, 400)) == Decimal("0.005400")


@pytest.mark.usefixtures("prices")
def test_a_dated_snapshot_takes_its_models_price() -> None:
    assert pricing.cost(Usage("test-model-2026-08-01", 1_000_000, 0, 0)) == Decimal("2.000000")


@pytest.mark.parametrize("model", ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"])
def test_the_listed_free_tier_models_are_free(model: str) -> None:
    assert pricing.cost(Usage(model, 1000, 500, 0)) == 0


@pytest.mark.parametrize("model", ["gemini-4-pro", "gemini-3.5-flash-image"])
def test_a_gemini_model_that_is_not_listed_is_unpriced(model: str) -> None:
    with pytest.raises(LookupError, match=model):
        pricing.cost(Usage(model, 1000, 500, 0))


def test_a_model_without_a_price_is_an_error() -> None:
    with pytest.raises(LookupError, match="unpriced-model"):
        pricing.cost(Usage("unpriced-model", 1000, 500, 0))


def test_the_reasoning_model_is_priced() -> None:
    # $2 input + $10 output per 1M tokens (OpenAI Standard tier, short context).
    assert pricing.cost(Usage("gpt-6-sol-2026-09-01", 1_000_000, 1_000_000, 0)) == Decimal("12")


def test_the_openai_embedding_model_is_priced() -> None:
    # $0.13 per 1M input tokens (OpenAI Standard tier); an embedding has no output tokens.
    assert pricing.cost(Usage("text-embedding-3-large", 1_000_000, 0, 0)) == Decimal("0.13")


def test_the_gemini_embedding_model_is_free() -> None:
    assert pricing.cost(Usage("gemini-embedding-2", 1000, 0, 0)) == 0
