"""Config D: the scoring library's core, as the product runs it (Must-have Coverage with
semantic matching, Experience timeline, anchored rubric, grounding). Config C and D-luna are
the same core with Coverage off, or with the extraction model scoring too."""

from collections.abc import Callable

from smart_ats_eval.dataset import Job
from smart_ats_eval.harness import ScoreResult
from smart_ats_scoring import scoring
from smart_ats_scoring.embedding import Embedder
from smart_ats_scoring.llm import Llm
from smart_ats_scoring.parsing import Parsed, parse_cv, parse_job
from smart_ats_scoring.pricing import cost


class Parser:
    """Parses each JD and CV Document once per invocation, shared by every Config that reads
    the parsed criteria and profile, so they all score the same parse."""

    def __init__(self, extraction: Llm) -> None:
        self.extraction = extraction
        self.parsed: dict[str, Parsed] = {}

    def parse(self, parse: Callable[[str, Llm], Parsed], text: str) -> Parsed:
        if text not in self.parsed:
            self.parsed[text] = parse(text, self.extraction)
        return self.parsed[text]

    def application(self, job: Job, cv_text: str) -> tuple[Parsed, Parsed, float]:
        """The Job's criteria, the CV's profile, and what parsing costs the product per
        Application: its own parse and its share of the JD parse. The parse is counted in
        every run although the harness runs it once."""
        jd = self.parse(parse_job, job.jd_text)
        cv = self.parse(parse_cv, cv_text)
        return jd, cv, float(cost(cv.usage) + cost(jd.usage) / len(job.cvs))


class ConfigD:
    prompt_version: str | None = scoring.PROMPT_VERSION
    rubric_version: str | None = scoring.RUBRIC_VERSION

    def __init__(
        self,
        parser: Parser,
        reasoning: Llm,
        model: str,
        embedder: Embedder,
        name: str = "Config D",
        must_have_coverage: bool = True,
    ) -> None:
        """`reasoning`, named `model`, scores; Config C passes `must_have_coverage=False`."""
        self.parser = parser
        self.reasoning = reasoning
        self.model: str | None = model
        self.embedder = embedder
        self.name = name
        self.must_have_coverage = must_have_coverage

    def score(self, job: Job) -> list[ScoreResult]:
        results = []
        for cv in job.cvs:
            jd, parsed, usd = self.parser.application(job, cv.text)
            # "nay" runs to the day the CVs were collected, so the table does not drift by day.
            result = scoring.score(
                jd.data,
                parsed.data,
                cv.text,
                job.jd_text,
                self.reasoning,
                self.embedder,
                job.as_of,
                must_have_coverage=self.must_have_coverage,
            )
            usd += float(cost(result.usage))
            if result.embedding_usage:
                usd += float(cost(result.embedding_usage))
            results.append(ScoreResult(cv.id, result.total, tuple(result.grounded_quotes), usd))
        return results
