"""The Embedder seam: provider choice and refusal from the environment, the client stubbed."""

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from smart_ats_scoring import embedding, pricing
from smart_ats_scoring.embedding import GeminiEmbedder, OpenAiEmbedder, embedder_from_env
from smart_ats_scoring.llm import Usage


def _stub(embedder: Any, response: SimpleNamespace, sent: dict[str, Any]) -> None:
    def create(**kwargs: Any) -> SimpleNamespace:
        sent.update(kwargs)
        return response

    embedder.client = SimpleNamespace(embeddings=SimpleNamespace(create=create))


def _data(*vectors: list[float]) -> list[SimpleNamespace]:
    # index=None as Gemini's endpoint sends it: input order alone ties a vector to its string.
    return [SimpleNamespace(index=None, embedding=v) for v in vectors]


@pytest.fixture
def calibrated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        pricing.PRICES, "test-embedding", pricing.Price(Decimal("1"), Decimal("1"), Decimal(0))
    )
    monkeypatch.setitem(embedding.THRESHOLDS, "test-embedding", 0.8)


@pytest.mark.usefixtures("calibrated")
def test_a_gemini_key_alone_does_not_select_the_gemini_embedder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    assert isinstance(embedder_from_env("test-embedding"), OpenAiEmbedder)


@pytest.mark.usefixtures("calibrated")
def test_the_gemini_embedder_runs_only_when_the_provider_flag_asks_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert isinstance(embedder_from_env("test-embedding"), GeminiEmbedder)


def test_openai_returns_a_vector_per_string_in_order_with_its_usage() -> None:
    embedder = OpenAiEmbedder.__new__(OpenAiEmbedder)
    embedder.model = "text-embedding-test"
    sent: dict[str, Any] = {}
    response = SimpleNamespace(
        model="text-embedding-test",
        data=_data([1.0, 0.0], [0.0, 1.0]),
        usage=SimpleNamespace(prompt_tokens=7),
    )
    _stub(embedder, response, sent)

    result = embedder.embed(["REST API", "RESTful services"])

    assert sent == {
        "model": "text-embedding-test",
        "input": ["REST API", "RESTful services"],
        "dimensions": 1536,
    }
    assert result.vectors == [[1.0, 0.0], [0.0, 1.0]]
    assert result.usage == Usage("text-embedding-test", 7, 0, 0)


def test_gemini_bills_zero_tokens_since_its_endpoint_reports_no_usage() -> None:
    embedder = GeminiEmbedder.__new__(GeminiEmbedder)
    embedder.model = "gemini-embedding-test"
    sent: dict[str, Any] = {}
    _stub(
        embedder,
        SimpleNamespace(model="gemini-embedding-test", data=_data([1.0], [0.5]), usage=None),
        sent,
    )

    result = embedder.embed(["Java", "JavaScript"])

    # Gemini Embedding 2 takes its task in the text; THRESHOLDS is calibrated with it.
    assert sent["input"] == [
        "task: sentence similarity | query: Java",
        "task: sentence similarity | query: JavaScript",
    ]
    assert sent["dimensions"] == 1536
    assert result.vectors == [[1.0], [0.5]]
    assert result.usage == Usage("gemini-embedding-test", 0, 0, 0)


def test_a_reply_with_fewer_vectors_than_strings_is_an_error() -> None:
    # The native Gemini Embedding 2 API aggregates a list into one vector.
    embedder = GeminiEmbedder.__new__(GeminiEmbedder)
    embedder.model = "gemini-embedding-test"
    _stub(
        embedder, SimpleNamespace(model="gemini-embedding-test", data=_data([1.0]), usage=None), {}
    )

    with pytest.raises(RuntimeError, match="1 vectors for 2 strings"):
        embedder.embed(["Java", "JavaScript"])


def test_a_model_without_a_threshold_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        pricing.PRICES, "uncalibrated", pricing.Price(Decimal(1), Decimal(1), Decimal(0))
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(LookupError, match="no similarity threshold for model uncalibrated"):
        embedder_from_env("uncalibrated")


def test_a_model_without_a_price_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(embedding.THRESHOLDS, "unpriced", 0.8)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with pytest.raises(LookupError, match="no price for model unpriced"):
        embedder_from_env("unpriced")


@pytest.mark.usefixtures("calibrated")
def test_a_dated_snapshot_takes_its_models_threshold() -> None:
    assert embedding.threshold("test-embedding-2026-08-01") == 0.8
    assert embedding.threshold("test-embedding-large") is None
