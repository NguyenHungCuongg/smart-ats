from pathlib import Path

import pytest

from smart_ats_eval import dataset, harness
from smart_ats_eval.__main__ import main

SCRATCH = Path(__file__).parents[1] / "datasets" / "scratch-v1.json"


class FakeConfig:
    """Scores each CV Document at 20x its HR score, jittered +1 / -1 on alternate runs."""

    name = "Fake"
    model: str | None = "fake-model"
    prompt_version: str | None = "p1"
    rubric_version: str | None = "r1"

    def __init__(self) -> None:
        self.calls = 0

    def score(self, job: dataset.Job) -> list[harness.ScoreResult]:
        self.calls += 1
        jitter = 1 if self.calls % 2 else -1
        return [
            harness.ScoreResult(
                cv_id=cv.id,
                total=cv.hr_score * 20 + jitter,
                evidence=(cv.text[:12], "not in the CV Document"),
                cost_usd=0.01,
            )
            for cv in job.cvs
        ]


def row(table: str, config_name: str) -> list[str]:
    line = next(line for line in table.splitlines() if line.startswith(f"| {config_name} "))
    return [cell.strip() for cell in line.strip("|").split("|")]


def test_compare_reports_every_metric_for_a_config() -> None:
    data = dataset.load(SCRATCH)

    table = harness.compare(data, [FakeConfig()], split="dev", runs=2)

    # Totals follow the HR score exactly, so rho is 1. One of two quotes per CV is real.
    # Totals differ by 2 across two runs: sample standard deviation sqrt(2).
    name, model, prompt, rubric, rho, _ndcg, _p5, grounding, stability, cost = row(table, "Fake")
    assert (name, model, prompt, rubric) == ("Fake", "fake-model", "p1", "r1")
    assert (rho, grounding, stability, cost) == ("1.000", "0.500", "1.414", "0.0100")


def test_compare_rejects_a_config_that_skips_a_cv_document() -> None:
    class SkipsOne(FakeConfig):
        def score(self, job: dataset.Job) -> list[harness.ScoreResult]:
            return super().score(job)[1:]

    with pytest.raises(ValueError, match="one ScoreResult per CV Document"):
        harness.compare(dataset.load(SCRATCH), [SkipsOne()], split="dev", runs=1)


def test_cli_prints_the_baseline_row_and_flags_scratch_data(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main([str(SCRATCH), "--split", "test"])

    out = capsys.readouterr().out
    assert "NOT FOR REPORT" in out
    assert "Weighted Kappa" in out
    cells = row(out, "Baseline (BM25)")
    assert cells[1:4] == ["-", "-", "-"]
    assert all(cell not in ("-", "nan") for cell in cells[4:7])
