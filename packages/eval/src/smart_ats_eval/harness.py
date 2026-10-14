"""Runs scoring Configs over one dataset split and builds the Experiment 1 comparison table."""

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from smart_ats_eval import metrics
from smart_ats_eval.dataset import Dataset, Job


@dataclass(frozen=True)
class ScoreResult:
    """One Application's result from a Config: its Total and the Evidence quoted for it."""

    cv_id: str
    total: float
    evidence: tuple[str, ...] = ()
    cost_usd: float | None = None


class Config(Protocol):
    """A scoring configuration under test (Baseline, Config A-D); registered in __main__.CONFIGS."""

    name: str
    model: str | None
    prompt_version: str | None
    rubric_version: str | None

    def score(self, job: Job) -> list[ScoreResult]:
        """Score every CV Document of the Job."""
        ...


COLUMNS = (
    "Config",
    "Model",
    "Prompt",
    "Rubric",
    "Spearman rho",
    "NDCG@5",
    "P@5",
    "Grounding",
    "Stability",
    "Cost/App (USD)",
)


def compare(data: Dataset, configs: Sequence[Config], split: str, runs: int) -> str:
    jobs = [job for job in data.jobs if job.split == split]
    if not jobs:
        raise ValueError(f"dataset has no Job in split {split!r}")
    cvs = [cv for job in jobs for cv in job.cvs]
    rater_a, rater_b = data.raters
    kappa = metrics.weighted_kappa(
        [cv.labels[rater_a] for cv in cvs], [cv.labels[rater_b] for cv in cvs]
    )
    real = sum(cv.source == "real" for cv in cvs)
    lines = [
        f"Dataset {data.name} v{data.version}, split {split}, {runs} run(s): {len(jobs)} Jobs,"
        f" {len(cvs)} CV Documents ({real} real, {len(cvs) - real} synthetic)",
        f"Weighted Kappa (quadratic) {rater_a} vs {rater_b}: {kappa:.3f}",
    ]
    if not data.for_report:
        lines.append("NOT FOR REPORT: this dataset has for_report = false.")
    lines += ["", _row(COLUMNS), _row(["---"] * len(COLUMNS))]
    lines += [_row(_evaluate(config, jobs, runs)) for config in configs]
    return "\n".join(lines)


def _evaluate(config: Config, jobs: Sequence[Job], runs: int) -> list[str]:
    results = [{job.id: _score(config, job) for job in jobs} for _ in range(runs)]

    # Each metric is computed per run, per Job (and per rater for Top 5), then averaged.
    rho, ndcg, p5 = [], [], []
    for result in results:
        for job in jobs:
            scores = result[job.id]
            # Ties break by a hash of the id: dataset ids may follow quality (be-01 is best).
            ranked = sorted(
                scores.values(), key=lambda s: (-s.total, sha256(s.cv_id.encode()).digest())
            )
            ranking = [s.cv_id for s in ranked]
            rho.append(
                metrics.spearman(
                    [scores[cv.id].total for cv in job.cvs], [cv.hr_score for cv in job.cvs]
                )
            )
            ndcg += [metrics.ndcg_at_k(ranking, top) for top in job.top5.values()]
            p5 += [metrics.precision_at_k(ranking, top) for top in job.top5.values()]

    # Evidence may quote the CV Document or the JD Document.
    evidence = [
        (quote, f"{cv.text}\n{job.jd_text}")
        for result in results
        for job in jobs
        for cv in job.cvs
        for quote in result[job.id][cv.id].evidence
    ]
    stability = (
        metrics.stability(
            [[result[job.id][cv.id].total for result in results] for job in jobs for cv in job.cvs]
        )
        if runs > 1
        else None
    )
    costs = [
        s.cost_usd
        for result in results
        for scores in result.values()
        for s in scores.values()
        if s.cost_usd is not None
    ]
    return [
        config.name,
        config.model or "-",
        config.prompt_version or "-",
        config.rubric_version or "-",
        _fmt(statistics.fmean(rho), 3),
        _fmt(statistics.fmean(ndcg), 3),
        _fmt(statistics.fmean(p5), 3),
        _fmt(metrics.grounding_rate(evidence), 3),
        _fmt(stability, 3),
        _fmt(statistics.fmean(costs) if costs else None, 4),
    ]


def _score(config: Config, job: Job) -> dict[str, ScoreResult]:
    results = {result.cv_id: result for result in config.score(job)}
    if sorted(results) != sorted(cv.id for cv in job.cvs):
        raise ValueError(f"{config.name} must return one ScoreResult per CV Document of {job.id}")
    return results


def _fmt(value: float | None, digits: int) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"
