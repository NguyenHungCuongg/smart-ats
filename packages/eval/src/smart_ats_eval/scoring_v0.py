"""Scoring v0: the scoring library's core (Must-have Coverage, anchored rubric, grounding)."""

from typing import Any

from smart_ats_eval.dataset import Job
from smart_ats_eval.harness import ScoreResult
from smart_ats_scoring import scoring
from smart_ats_scoring.llm import Llm
from smart_ats_scoring.parsing import parse_cv, parse_job


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
        criteria = self._parse(job.jd_text, is_job=True)
        results = []
        for cv in job.cvs:
            result = scoring.score(
                criteria, self._parse(cv.text, is_job=False), cv.text, job.jd_text, self.reasoning
            )
            claims = [
                *result.rubric.values(),
                *(claim for claims in result.fit_gap_report.values() for claim in claims),
            ]
            # Every quote the LLM made, dropped ones included: the harness measures Grounding.
            evidence = tuple(q for claim in claims for q in (*claim["evidence"], *claim["dropped"]))
            # ponytail: no price table yet, so Cost/App stays "-".
            results.append(ScoreResult(cv.id, result.total, evidence))
        return results

    def _parse(self, text: str, *, is_job: bool) -> dict[str, Any]:
        if text not in self.parsed:
            parse = parse_job if is_job else parse_cv
            self.parsed[text] = parse(text, self.extraction).data
        return self.parsed[text]
