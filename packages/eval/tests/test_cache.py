from pathlib import Path
from typing import Any

from smart_ats_eval.cache import CachedEmbedder, CachedLlm
from smart_ats_scoring.embedding import EmbeddingResult
from smart_ats_scoring.llm import LlmResult, Usage


class CountingLlm:
    """Answers with how many calls it has had, so a cached answer shows which call made it."""

    def __init__(self) -> None:
        self.calls = 0

    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult:
        self.calls += 1
        return LlmResult({"call": self.calls}, Usage("fake-model", 10, 5, 2))


class CountingEmbedder:
    model = "fake-embedding"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls += 1
        return EmbeddingResult([[float(self.calls)] for _ in texts], Usage(self.model, 7, 0, 0))


def _ask(llm: CachedLlm, user: str = "cv") -> LlmResult:
    return llm.structured("system", user, "score_result", {"type": "object"}, temperature=0)


def test_a_later_invocation_replays_the_calls_an_earlier_one_made(tmp_path: Path) -> None:
    first = CountingLlm()
    answer = _ask(CachedLlm(first, tmp_path, "fake-model"))

    # A new invocation, as on the next day: same request, new process.
    second = CountingLlm()
    replayed = _ask(CachedLlm(second, tmp_path, "fake-model"))

    assert second.calls == 0
    assert replayed == answer == LlmResult({"call": 1}, Usage("fake-model", 10, 5, 2))


def test_a_repeated_request_within_an_invocation_is_a_new_call(tmp_path: Path) -> None:
    # Run 2 of --runs 2 asks again: replaying run 1 would fake a perfect Stability.
    inner = CountingLlm()
    llm = CachedLlm(inner, tmp_path, "fake-model")

    assert [_ask(llm).data, _ask(llm).data] == [{"call": 1}, {"call": 2}]
    # The next invocation replays both runs in order, without calling.
    again = CountingLlm()
    replay = CachedLlm(again, tmp_path, "fake-model")
    assert [_ask(replay).data, _ask(replay).data] == [{"call": 1}, {"call": 2}]
    assert again.calls == 0


def test_a_different_request_is_never_served_from_another_ones_answer(tmp_path: Path) -> None:
    inner = CountingLlm()
    llm = CachedLlm(inner, tmp_path, "fake-model")

    _ask(llm, "cv one")
    _ask(llm, "cv two")

    assert inner.calls == 2


def test_the_same_request_to_another_model_is_a_new_call(tmp_path: Path) -> None:
    # Config D and D-luna send the same prompt; only the model differs.
    _ask(CachedLlm(CountingLlm(), tmp_path, "gemini-3.6-flash"))
    luna = CountingLlm()

    _ask(CachedLlm(luna, tmp_path, "gemini-3.5-flash-lite"))

    assert luna.calls == 1


def test_embeddings_are_replayed_like_llm_calls(tmp_path: Path) -> None:
    first = CountingEmbedder()
    answer = CachedEmbedder(first, tmp_path).embed(["Python", "REST API"])

    second = CountingEmbedder()
    replay = CachedEmbedder(second, tmp_path)

    assert replay.model == "fake-embedding"
    assert replay.embed(["Python", "REST API"]) == answer
    assert second.calls == 0
