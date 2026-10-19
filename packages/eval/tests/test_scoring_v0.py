from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from smart_ats_eval import dataset, harness
from smart_ats_eval.__main__ import configs
from smart_ats_eval.scoring_v0 import ScoringV0
from smart_ats_scoring import pricing
from smart_ats_scoring.llm import LlmResult, Usage

SCRATCH = Path(__file__).parents[1] / "datasets" / "scratch-v1.json"

CRITERIA: dict[str, Any] = {
    "title": "Backend Developer (Junior)",
    "level": "JUNIOR",
    "skills": [{"name": "Python", "must_have": True}],
    "min_years_experience": 1,
    "education": None,
    "responsibilities": [],
    "work_mode": None,
    "salary_range": None,
    "department": None,
    "location": None,
}
PROFILE: dict[str, Any] = {
    "contact": {"full_name": None, "email": None, "phone": None, "links": []},
    "work_history": [],
    "skills": {"hard": ["Python"], "soft": [], "tools": [], "languages": []},
    "education": [],
    "certifications": [],
    "anomalies": [],
}
# Each axis quotes the CV once ("Python"), then a stopword the CV also contains and an invention.
AXIS = {"evidence": ["Python", "and", "không có trong tài liệu"], "reason": "r", "grade": 3}
# Report items quote nothing, so only the axes count toward Grounding.
CLAIM = {"text": "t", "evidence": []}
ANSWER: dict[str, Any] = {
    "technical": AXIS,
    "soft_skills": AXIS,
    "experience": AXIS,
    "strengths": [CLAIM],
    "gaps": [CLAIM],
    "recommendations": [CLAIM],
}


class FakeLlm:
    """Answers each structured call by its schema name and counts the calls."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult:
        self.calls[name] += 1
        data = {"job_criteria": CRITERIA, "cv_profile": PROFILE, "score_result": ANSWER}[name]
        return LlmResult(data, Usage("fake-model", 1000, 500, 0))


@pytest.fixture
def fake_model_price(monkeypatch: pytest.MonkeyPatch) -> None:
    # $2 per 1M input tokens, $10 per 1M output tokens.
    monkeypatch.setitem(
        pricing.PRICES, "fake-model", pricing.Price(Decimal(2), Decimal(0), Decimal(10))
    )


@pytest.mark.usefixtures("fake_model_price")
def test_scoring_v0_row_reports_versions_grounding_by_the_library_rule_and_cost() -> None:
    llm = FakeLlm()
    data = dataset.load(SCRATCH)
    cv_text = "Kỹ năng: Python and FastAPI"
    data = replace(
        data,
        jobs=tuple(
            replace(job, cvs=tuple(replace(cv, text=f"{cv_text} {cv.id}") for cv in job.cvs))
            for job in data.jobs
        ),
    )

    table = harness.compare(data, [ScoringV0(llm, llm, "fake-model")], split="dev", runs=2)

    row = next(line for line in table.splitlines() if line.startswith("| Scoring v0 "))
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[1:4] == ["fake-model", "v1", "v0"]
    # Every quote the LLM made counts, dropped ones included: only "Python" of the 3 per axis
    # is evidence; "and" is a stopword and the third is invented.
    assert cells[8] == "0.333"
    # Each call costs 1000 x $2 + 500 x $10 = $0.007 per 1M tokens. An Application costs its CV
    # parse, 1/6 of the JD parse and its scoring: 0.007 x (1 + 1/6 + 1) = 0.0152.
    assert cells[10] == "0.0152"
    # One Job and six CV Documents in dev: each parsed once, each Application scored per run.
    assert llm.calls == {"job_criteria": 1, "cv_profile": 6, "score_result": 12}


def test_scoring_v0_is_compared_only_with_an_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert [config.name for config in configs()] == ["Baseline (BM25)"]

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "gpt-6-luna")
    monkeypatch.setenv("LLM_REASONING_MODEL", "gpt-6-sol")
    found = configs()
    assert [(config.name, config.model) for config in found] == [
        ("Baseline (BM25)", None),
        ("Scoring v0", "gpt-6-sol"),
    ]


def test_a_model_without_a_price_stops_the_run_before_any_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "gpt-6-luna")
    monkeypatch.setenv("LLM_REASONING_MODEL", "unpriced-model")

    with pytest.raises(SystemExit, match="unpriced-model"):
        configs()
