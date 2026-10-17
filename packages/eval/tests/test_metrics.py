import math

import pytest

from smart_ats_eval import metrics


def test_spearman_without_ties() -> None:
    # Rank differences 0, 1, 1, 0: rho = 1 - 6 * 2 / (4 * (16 - 1)) = 0.8.
    assert metrics.spearman([10, 30, 20, 40], [1, 2, 3, 4]) == pytest.approx(0.8)


def test_spearman_averages_tied_ranks() -> None:
    # Predicted ranks 1, 2, 3.5, 5, 3.5 against 1..5: rho = 8 / sqrt(10 * 9.5).
    assert metrics.spearman([5, 6, 7, 8, 7], [1, 2, 3, 4, 5]) == pytest.approx(8 / math.sqrt(95))


def test_spearman_is_nan_when_one_side_is_constant() -> None:
    assert math.isnan(metrics.spearman([3, 3, 3], [1, 2, 3]))


HR_TOP5 = ["a", "b", "c", "d", "e"]
SYSTEM_RANKING = ["b", "a", "x", "c", "y", "d", "e"]


def test_ndcg_at_5_grades_relevance_by_position_in_hr_top5() -> None:
    # Relevance a=5 .. e=1. DCG = 4/1 + 5/log2(3) + 0 + 3/log2(5) + 0 = 8.4467;
    # IDCG = 5 + 4/log2(3) + 3/2 + 2/log2(5) + 1/log2(6) = 10.2719.
    assert metrics.ndcg_at_k(SYSTEM_RANKING, HR_TOP5) == pytest.approx(0.82231, abs=1e-5)


def test_ndcg_at_5_is_one_for_the_hr_order() -> None:
    assert metrics.ndcg_at_k(HR_TOP5 + ["x"], HR_TOP5) == pytest.approx(1.0)


def test_precision_at_5_counts_hr_top5_hits() -> None:
    # b, a, c of the first five are in the HR Top 5.
    assert metrics.precision_at_k(SYSTEM_RANKING, HR_TOP5) == pytest.approx(0.6)


def test_stability_is_the_mean_per_application_standard_deviation() -> None:
    # Sample standard deviations 2 and 0.
    assert metrics.stability([[70, 72, 74], [50, 50, 50]]) == pytest.approx(1.0)


def test_weighted_kappa_quadratic() -> None:
    # Observed weighted disagreement 0.5/16, expected 1/16 from the marginals: kappa = 0.5.
    assert metrics.weighted_kappa([1, 1, 2, 2], [1, 2, 2, 3]) == pytest.approx(0.5)


def test_weighted_kappa_is_one_on_full_agreement() -> None:
    assert metrics.weighted_kappa([1, 3, 5, 4], [1, 3, 5, 4]) == pytest.approx(1.0)
