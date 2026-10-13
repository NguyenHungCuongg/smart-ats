"""Baseline: Okapi BM25 of the JD Document against each CV Document of the Job."""

import math
import re
import statistics
from collections import Counter

from smart_ats_eval.dataset import Job
from smart_ats_eval.harness import Score

K1 = 1.5
B = 0.75


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class Bm25Baseline:
    name = "Baseline (BM25)"
    model: str | None = None
    prompt_version: str | None = None
    rubric_version: str | None = None

    def score(self, job: Job) -> list[Score]:
        # The corpus is the Job's own CV Documents, so IDF reflects this applicant pool.
        docs = [Counter(_tokens(cv.text)) for cv in job.cvs]
        avg_len = statistics.fmean(doc.total() for doc in docs)
        df = Counter(term for doc in docs for term in doc)
        n = len(docs)

        def bm25(doc: Counter[str]) -> float:
            norm = K1 * (1 - B + B * doc.total() / avg_len)
            return sum(
                math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1)
                * doc[t]
                * (K1 + 1)
                / (doc[t] + norm)
                for t in _tokens(job.jd_text)
                if t in doc
            )

        return [Score(cv.id, bm25(doc)) for cv, doc in zip(job.cvs, docs, strict=True)]
