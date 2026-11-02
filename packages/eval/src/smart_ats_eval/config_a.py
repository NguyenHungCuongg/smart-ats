"""Config A: the cosine of the JD Document's and each CV Document's embeddings, x 100.
A ranker by meaning with no LLM; it embeds the same texts the Baseline reads."""

import math

from smart_ats_eval.dataset import Job
from smart_ats_eval.harness import ScoreResult
from smart_ats_scoring.embedding import Embedder
from smart_ats_scoring.pricing import cost


class ConfigA:
    name = "Config A"
    prompt_version: str | None = None
    rubric_version: str | None = None

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.model: str | None = embedder.model

    def score(self, job: Job) -> list[ScoreResult]:
        # One call per Job, so each Application costs its share of it.
        embedded = self.embedder.embed([job.jd_text, *(cv.text for cv in job.cvs)])
        jd, *cvs = embedded.vectors
        usd = float(cost(embedded.usage)) / len(job.cvs)
        return [
            ScoreResult(
                cv.id, 100 * math.sumprod(jd, v) / (math.hypot(*jd) * math.hypot(*v)), (), usd
            )
            for cv, v in zip(job.cvs, cvs, strict=True)
        ]
