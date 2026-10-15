"""Cost of an AI Usage Entry (FR-C1.4)."""

from decimal import Decimal

import pytest

from app import usage
from smart_ats_scoring.llm import Usage


@pytest.fixture
def prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        usage.PRICES, "test-model", usage.Price(Decimal("2"), Decimal("0.5"), Decimal("8"))
    )


@pytest.mark.usefixtures("prices")
def test_cost_bills_cached_input_at_its_own_price() -> None:
    # 600 uncached x $2 + 400 cached x $0.5 + 500 output x $8, per 1M tokens.
    assert usage.cost(Usage("test-model", 1000, 500, 400)) == Decimal("0.005400")


@pytest.mark.usefixtures("prices")
def test_a_dated_snapshot_takes_its_models_price() -> None:
    assert usage.cost(Usage("test-model-2026-08-01", 1_000_000, 0, 0)) == Decimal("2.000000")


def test_gemini_is_free() -> None:
    assert usage.cost(Usage("gemini-2.5-flash", 1000, 500, 0)) == 0


def test_a_model_without_a_price_is_an_error() -> None:
    with pytest.raises(LookupError, match="unpriced-model"):
        usage.cost(Usage("unpriced-model", 1000, 500, 0))
