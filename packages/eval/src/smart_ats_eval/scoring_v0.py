"""Scoring v0: the scoring library's core (Must-have Coverage, anchored rubric, grounding)."""

from collections.abc import Callable

from smart_ats_eval.dataset import Job
from smart_ats_eval.harness import ScoreResult
from smart_ats_scoring import scoring
from smart_ats_scoring.llm import Llm
from smart_ats_scoring.parsing import Parsed, parse_cv, parse_job
from smart_ats_scoring.pricing import cost


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
        self.parsed: dict[str, Parsed] = {}

    def score(self, job: Job) -> list[ScoreResult]:
        jd = self._parse(parse_job, job.jd_text)
        results = []
        for cv in job.cvs:
            parsed = self._parse(parse_cv, cv.text)
            result = scoring.score(jd.data, parsed.data, cv.text, job.jd_text, self.reasoning)
            # What an Application costs the product: its own parse, its share of the JD parse
            # and the scoring; the parse is counted in every run although the harness runs it once.
            usd = cost(parsed.usage) + cost(jd.usage) / len(job.cvs) + cost(result.usage)
            results.append(
                ScoreResult(cv.id, result.total, tuple(result.grounded_quotes), float(usd))
            )
        return results

    def _parse(self, parse: Callable[[str, Llm], Parsed], text: str) -> Parsed:
        if text not in self.parsed:
            self.parsed[text] = parse(text, self.extraction)
        return self.parsed[text]
