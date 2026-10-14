from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from smart_ats_eval import dataset, harness
from smart_ats_eval.__main__ import configs
from smart_ats_eval.scoring_v0 import ScoringV0
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
# Each axis quotes the JD ("Python") once and invents one quote.
AXIS = {"evidence": ["Python", "không có trong tài liệu"], "reason": "r", "grade": 3}
ANSWER: dict[str, Any] = {
    "technical": AXIS,
    "soft_skills": AXIS,
    "experience": AXIS,
    "strengths": [],
    "gaps": [],
    "recommendations": [],
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
        return LlmResult(data, Usage("fake-model", 1, 1, 0))


def test_scoring_v0_row_reports_versions_and_raw_grounding() -> None:
    llm = FakeLlm()

    table = harness.compare(
        dataset.load(SCRATCH), [ScoringV0(llm, llm, "fake-model")], split="dev", runs=2
    )

    row = next(line for line in table.splitlines() if line.startswith("| Scoring v0 "))
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[1:4] == ["fake-model", "v0", "v0"]
    # The harness checks every quote the LLM made, dropped ones included: 1 of 2 is real.
    assert cells[7] == "0.500"
    # One Job and six CV Documents in dev: each parsed once, each Application scored per run.
    assert llm.calls == {"job_criteria": 1, "cv_profile": 6, "score_result": 12}


def test_scoring_v0_is_compared_only_with_an_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert [config.name for config in configs()] == ["Baseline (BM25)"]

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "luna")
    monkeypatch.setenv("LLM_REASONING_MODEL", "sol")
    found = configs()
    assert [(config.name, config.model) for config in found] == [
        ("Baseline (BM25)", None),
        ("Scoring v0", "sol"),
    ]
