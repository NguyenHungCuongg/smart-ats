"""Scoring v0: the scoring library's core (Must-have Coverage, anchored rubric, grounding)."""

from collections.abc import Callable
from typing import Any

from smart_ats_eval.dataset import Job
from smart_ats_eval.harness import ScoreResult
from smart_ats_scoring import scoring
from smart_ats_scoring.llm import Llm
from smart_ats_scoring.parsing import Parsed, parse_cv, parse_job


class ScoringV0:
    name = "Scoring v0"
    prompt_version: str | None = scoring.PROMPT_VERSION
    rubric_version: str | None = scoring.RUBRIC_VERSION

    def __init__(self, extraction: Llm, reasoning: Llm, model: str) -> None:
        """`extraction` parses the JD and CV Documents; `reasoning`, named `model`, scores."""
        self.extraction = extraction
        self.reasoning = reasoning
        self.model: str | None = model
        # Parsing happens once per document in the product, so repeated runs measure the
        # Stability of scoring alone.
        self.parsed: dict[str, dict[str, Any]] = {}

    def score(self, job: Job) -> list[ScoreResult]:
        criteria = self._parse(parse_job, job.jd_text)
        results = []
        for cv in job.cvs:
            result = scoring.score(
                criteria, self._parse(parse_cv, cv.text), cv.text, job.jd_text, self.reasoning
            )
            # The harness measures Grounding itself, so it gets the dropped quotes too.
            # ponytail: no price table yet, so Cost/App stays "-".
            results.append(ScoreResult(cv.id, result.total, tuple(result.quotes)))
        return results

    def _parse(self, parse: Callable[[str, Llm], Parsed], text: str) -> dict[str, Any]:
        if text not in self.parsed:
            self.parsed[text] = parse(text, self.extraction).data
        return self.parsed[text]
