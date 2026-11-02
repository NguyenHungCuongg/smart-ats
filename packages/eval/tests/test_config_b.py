from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_config_d import CRITERIA, PROFILE, _document
from test_harness import row

from smart_ats_eval import dataset, harness
from smart_ats_eval.config_b import ConfigB
from smart_ats_eval.config_d import Parser
from smart_ats_scoring import pricing
from smart_ats_scoring.llm import LlmResult, Usage

SCRATCH = Path(__file__).parents[1] / "datasets" / "scratch-v1.json"


class FreeLlm:
    """Parses to the canned criteria and profile, then scores 70; records the scoring calls."""

    def __init__(self, profile: dict[str, Any] = PROFILE) -> None:
        self.profile = profile
        self.scoring: list[dict[str, Any]] = []

    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult:
        if name == "fit_score":
            self.scoring.append({"user": user, "temperature": temperature})
        data = {
            "job_criteria": CRITERIA,
            "cv_profile": self.profile,
            "fit_score": {"score": 70},
        }[name]
        return LlmResult(data, Usage("fake-model", 1000, 500, 0))


@pytest.fixture
def fake_model_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        pricing.PRICES, "fake-model", pricing.Price(Decimal(2), Decimal(0), Decimal(10))
    )


@pytest.mark.usefixtures("fake_model_price")
def test_config_b_scores_freely_on_config_ds_input_with_no_evidence() -> None:
    llm = FreeLlm(PROFILE | {"contact": PROFILE["contact"] | {"full_name": "Nguyễn Văn An"}})

    table = harness.compare(
        dataset.load(SCRATCH), [ConfigB(Parser(llm), llm, "fake-model")], split="dev", runs=1
    )

    cells = row(table, "Config B")
    assert cells[1:4] == ["fake-model", "b-v1", "-"]
    # No Evidence, so no Grounding.
    assert cells[8] == "-"
    # 0.007 x (1 + 1/6 + 1): the CV parse, its share of the JD parse and the scoring.
    assert cells[10] == "0.0152"
    # Config D's input: the criteria and the Blind Profile, in the untrusted block, at
    # temperature 0, once per CV Document.
    assert len(llm.scoring) == 6
    assert {call["temperature"] for call in llm.scoring} == {0}
    document = _document(llm.scoring[0]["user"])
    assert document["job"] == CRITERIA
    assert document["candidate"]["work_history"] == PROFILE["work_history"]
    assert "Nguyễn Văn An" not in llm.scoring[0]["user"]


@pytest.mark.usefixtures("fake_model_price")
def test_config_b_takes_the_llms_score_as_the_total() -> None:
    llm = FreeLlm()
    job = next(job for job in dataset.load(SCRATCH).jobs if job.split == "dev")

    results = ConfigB(Parser(llm), llm, "fake-model").score(job)

    assert {r.total for r in results} == {70}
