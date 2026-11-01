"""Optional: the real embedding model of EMBEDDING_MODEL. Runs only with a key, for example
`uv run --env-file .env pytest packages/scoring/tests/test_embedding_live.py`.

Gemini's free tier counts each string as a request (100 a minute): run it once a minute at most.
"""

import json
import math
import os
from pathlib import Path

import pytest

from smart_ats_scoring import pricing
from smart_ats_scoring.embedding import DIMENSIONS, embedder_from_env, threshold
from smart_ats_scoring.llm import has_llm_key

pytestmark = [
    pytest.mark.skipif(
        not (has_llm_key() and os.environ.get("EMBEDDING_MODEL")),
        reason="needs the API key of LLM_PROVIDER, and EMBEDDING_MODEL",
    ),
    pytest.mark.skipif(
        threshold(os.environ.get("EMBEDDING_MODEL", "")) is None,
        reason="EMBEDDING_MODEL has no THRESHOLDS entry yet: calibrate it on skill_pairs.json",
    ),
]

PAIRS = json.loads((Path(__file__).parent / "skill_pairs.json").read_text(encoding="utf-8"))

# Same pairs below the model's threshold. No threshold splits every pair, so it sits above the
# highest different pair (THRESHOLDS): the first four are abbreviations ALIASES already matches,
# so only Object-oriented programming / OOP is lost against v0.
MISSED: dict[str, list[list[str]]] = {
    "gemini-embedding-2": [
        ["TypeScript", "TS"],
        ["React", "ReactJS"],
        ["Golang", "Go"],
        ["Machine Learning", "ML"],
        ["Object-oriented programming", "OOP"],
    ],
}


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / math.sqrt(
        sum(x * x for x in a) * sum(y * y for y in b)
    )


def test_one_call_returns_a_vector_per_string_and_a_priced_usage() -> None:
    result = embedder_from_env(os.environ["EMBEDDING_MODEL"]).embed(["REST API", "Java"])

    assert [len(v) for v in result.vectors] == [DIMENSIONS, DIMENSIONS]
    assert pricing.cost(result.usage) >= 0  # cost() raises on an unpriced model


def test_the_threshold_separates_the_labelled_skill_pairs() -> None:
    model = os.environ["EMBEDDING_MODEL"]
    texts = sorted({s for kind in ("same", "different") for pair in PAIRS[kind] for s in pair})
    vector = dict(zip(texts, embedder_from_env(model).embed(texts).vectors, strict=True))
    cut = threshold(model)
    assert cut is not None

    def similar(a: str, b: str) -> bool:
        return _cosine(vector[a], vector[b]) >= cut

    assert [p for p in PAIRS["different"] if similar(*p)] == []
    assert [p for p in PAIRS["same"] if not similar(*p)] == MISSED.get(model, [])
