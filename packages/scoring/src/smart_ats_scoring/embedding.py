"""The Embedder seam: one call that embeds a list of strings, plus the usage to bill."""

import os
from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI
from openai.types import CreateEmbeddingResponse

from smart_ats_scoring.llm import GEMINI_BASE_URL, GEMINI_MAX_RETRIES, Usage, llm_provider
from smart_ats_scoring.pricing import by_model, price

# ADR-0005: the vector(1536) columns, and an HNSW index caps at 2,000 dimensions.
DIMENSIONS = 1536

# Least cosine at which two skill names count as one skill, by model name matched like PRICES.
# Chosen from the labelled pairs in packages/scoring/tests/skill_pairs.json, which
# tests/test_embedding_live.py checks it against. When no value splits every pair, it sits
# above the highest different pair: a false match inflates Technical Fit, a missed one only
# falls back to v0. Changing a value bumps RUBRIC_VERSION (ADR-0006).
THRESHOLDS: dict[str, float] = {
    # 2026-11-01, with the similarity task prefix: just above the highest different pair, 0.9157
    # (Kiểm thử thủ công / Kiểm thử tự động); the five same pairs it misses are in MISSED of
    # test_embedding_live.py. Without the prefix the highest different pair is 0.8749 and 18 of
    # the 28 same pairs fall below it.
    "gemini-embedding-2": 0.92,
    # text-embedding-3-large: not calibrated yet (needs an OpenAI key, issue #107), so refused.
}


def threshold(model: str) -> float | None:
    return by_model(THRESHOLDS, model)


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    usage: Usage


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> EmbeddingResult: ...


def _vectors(response: CreateEmbeddingResponse, texts: list[str]) -> list[list[float]]:
    if len(response.data) != len(texts):
        raise RuntimeError(
            f"{response.model} returned {len(response.data)} vectors for {len(texts)} strings"
        )
    # In input order; Gemini's endpoint leaves index None, so it cannot be sorted on.
    return [d.embedding for d in response.data]


class OpenAiEmbedder:
    def __init__(self, model: str, *, max_retries: int | None = None) -> None:
        self.model = model
        self.client = OpenAI() if max_retries is None else OpenAI(max_retries=max_retries)

    def embed(self, texts: list[str]) -> EmbeddingResult:
        response = self.client.embeddings.create(
            model=self.model, input=texts, dimensions=DIMENSIONS
        )
        return EmbeddingResult(
            _vectors(response, texts), Usage(response.model, response.usage.prompt_tokens, 0, 0)
        )


class GeminiEmbedder:
    """Gemini's OpenAI-compatible embeddings, for free testing with synthetic data (FR-C1.5)."""

    def __init__(self, model: str, api_key: str, *, max_retries: int | None = None) -> None:
        self.model = model
        retries = GEMINI_MAX_RETRIES if max_retries is None else max_retries
        self.client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL, max_retries=retries)

    def embed(self, texts: list[str]) -> EmbeddingResult:
        # Gemini Embedding 2 has no task_type: the task goes in the text, and THRESHOLDS is
        # calibrated with it (without it the labelled pairs overlap far more).
        response = self.client.embeddings.create(
            model=self.model,
            input=[f"task: sentence similarity | query: {t}" for t in texts],
            dimensions=DIMENSIONS,
        )
        # ponytail: this endpoint returns usage=None, so the entry bills 0 tokens; exact while
        # the model is free, count tokens natively if a paid Gemini embedding model is added.
        return EmbeddingResult(_vectors(response, texts), Usage(response.model, 0, 0, 0))


def embedder_from_env(model: str, *, max_retries: int | None = None) -> Embedder:
    # Refused before any call: an unpriced model would spend tokens the ledger cannot record
    # (FR-C1.4), an uncalibrated one would match must-haves on a guessed threshold.
    if price(model) is None:
        raise LookupError(f"no price for model {model} in smart_ats_scoring.pricing.PRICES")
    if threshold(model) is None:
        raise LookupError(
            f"no similarity threshold for model {model} in smart_ats_scoring.embedding.THRESHOLDS"
        )
    if llm_provider() == "gemini":
        return GeminiEmbedder(model, os.environ["GEMINI_API_KEY"], max_retries=max_retries)
    return OpenAiEmbedder(model, max_retries=max_retries)
