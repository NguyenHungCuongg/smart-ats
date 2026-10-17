"""Experiment 1 metrics (docs/EVAL/experiment_plan.md §4). Pure functions, no I/O."""

import math
import statistics
from collections.abc import Sequence


def spearman(predicted: Sequence[float], truth: Sequence[float]) -> float:
    """Spearman rho with averaged ranks for ties; NaN when either side is constant."""
    try:
        return statistics.correlation(predicted, truth, method="ranked")
    except statistics.StatisticsError:
        return math.nan


def ndcg_at_k(ranking: Sequence[str], hr_top: Sequence[str], k: int = 5) -> float:
    """NDCG@k of a system ranking; relevance is k for the HR's first pick down to 1, else 0."""
    relevance = {cv_id: k - position for position, cv_id in enumerate(hr_top[:k])}

    def dcg(ids: Sequence[str]) -> float:
        return sum(relevance.get(cv_id, 0) / math.log2(i + 2) for i, cv_id in enumerate(ids[:k]))

    return dcg(ranking) / dcg(hr_top)


def precision_at_k(ranking: Sequence[str], hr_top: Sequence[str], k: int = 5) -> float:
    return len(set(ranking[:k]) & set(hr_top[:k])) / k


def stability(totals: Sequence[Sequence[float]]) -> float:
    """Mean over Applications of the sample standard deviation of Total across repeated runs."""
    return statistics.fmean(statistics.stdev(runs) for runs in totals)


def weighted_kappa(rater_a: Sequence[int], rater_b: Sequence[int]) -> float:
    """Cohen's Kappa with quadratic weights between two raters' labels of the same pairs.

    Quadratic weights make the expected disagreement the mean squared difference over all
    cross pairs of labels, so no confusion matrix is needed. NaN when it is zero.
    """
    observed = statistics.fmean((a - b) ** 2 for a, b in zip(rater_a, rater_b, strict=True))
    expected = statistics.fmean((a - b) ** 2 for a in rater_a for b in rater_b)
    return 1 - observed / expected if expected else math.nan
