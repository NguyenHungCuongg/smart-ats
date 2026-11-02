import json
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_harness import row

from smart_ats_eval import dataset, harness
from smart_ats_eval.__main__ import configs
from smart_ats_eval.cache import CachedEmbedder, CachedLlm
from smart_ats_eval.config_a import ConfigA
from smart_ats_eval.config_b import ConfigB
from smart_ats_eval.config_d import ConfigD, Parser
from smart_ats_scoring import embedding, pricing
from smart_ats_scoring.embedding import EmbeddingResult
from smart_ats_scoring.llm import LlmResult, Usage

SCRATCH = Path(__file__).parents[1] / "datasets" / "scratch-v1.json"

CRITERIA: dict[str, Any] = {
    "title": "Backend Developer (Junior)",
    "level": "JUNIOR",
    # REST API is not in the CV, so every Application calls the Embedder once.
    "skills": [{"name": "Python", "must_have": True}, {"name": "REST API", "must_have": True}],
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
    "work_history": [
        {
            "company": "Acme",
            "title": "Backend Developer",
            "start": "01/2026",
            "end": "nay",
            "responsibilities": [],
            "achievements": [],
        }
    ],
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
        self.scoring_prompts: list[str] = []

    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult:
        self.calls[name] += 1
        if name == "score_result":
            self.scoring_prompts.append(user)
        data = {"job_criteria": CRITERIA, "cv_profile": PROFILE, "score_result": ANSWER}[name]
        return LlmResult(data, Usage("fake-model", 1000, 500, 0))


class FakeEmbedder:
    """Embeds every string on an axis of its own, so nothing matches by meaning."""

    model = "fake-embedding"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls += 1
        vectors = [[float(i == j) for j in range(len(texts))] for i in range(len(texts))]
        return EmbeddingResult(vectors, Usage("fake-embedding", 1000, 0, 0))


@pytest.fixture
def fake_model_price(monkeypatch: pytest.MonkeyPatch) -> None:
    # $2 per 1M input tokens, $10 per 1M output tokens; the embedding $2 per 1M tokens.
    monkeypatch.setitem(
        pricing.PRICES, "fake-model", pricing.Price(Decimal(2), Decimal(0), Decimal(10))
    )
    monkeypatch.setitem(
        pricing.PRICES, "fake-embedding", pricing.Price(Decimal(2), Decimal(2), Decimal(0))
    )
    monkeypatch.setitem(embedding.THRESHOLDS, "fake-embedding", 0.9)


def _document(user: str) -> Any:
    return json.loads(
        user.removeprefix("<untrusted_document>\n").removesuffix("\n</untrusted_document>")
    )


@pytest.mark.usefixtures("fake_model_price")
def test_config_d_row_reports_versions_grounding_by_the_library_rule_and_cost() -> None:
    llm = FakeLlm()
    embedder = FakeEmbedder()
    data = dataset.load(SCRATCH)
    cv_text = "Kỹ năng: Python and FastAPI"
    data = replace(
        data,
        jobs=tuple(
            replace(job, cvs=tuple(replace(cv, text=f"{cv_text} {cv.id}") for cv in job.cvs))
            for job in data.jobs
        ),
    )

    config = ConfigD(Parser(llm), llm, "fake-model", embedder)
    table = harness.compare(data, [config], split="dev", runs=2)

    cells = row(table, "Config D")
    assert cells[1:4] == ["fake-model", "v2", "v1"]
    # Every quote the LLM made counts, dropped ones included: only "Python" of the 3 per axis
    # is evidence; "and" is a stopword and the third is invented.
    assert cells[8] == "0.333"
    # Each LLM call costs 1000 x $2 + 500 x $10 = $0.007 per 1M tokens, each embedding call
    # 1000 x $2 = $0.002. An Application costs its CV parse, 1/6 of the JD parse, its embedding
    # and its scoring: 0.007 x (1 + 1/6 + 1) + 0.002 = 0.0172.
    assert cells[10] == "0.0172"
    # One Job and six CV Documents in dev: each parsed once, each Application scored per run.
    assert llm.calls == {"job_criteria": 1, "cv_profile": 6, "score_result": 12}
    assert embedder.calls == 12
    # "nay" runs to the dataset's as_of, 2026-10-13, whatever day the table is run:
    # January to October 2026.
    assert {
        _document(prompt)["experience_timeline"]["total_months"] for prompt in llm.scoring_prompts
    } == {10}


@pytest.mark.usefixtures("fake_model_price")
def test_config_c_scores_without_must_have_coverage_so_it_never_embeds() -> None:
    llm = FakeLlm()
    embedder = FakeEmbedder()
    config = ConfigD(Parser(llm), llm, "fake-model", embedder, "Config C", must_have_coverage=False)

    table = harness.compare(dataset.load(SCRATCH), [config], split="dev", runs=1)

    cells = row(table, "Config C")
    assert cells[1:4] == ["fake-model", "v2", "v1"]
    assert embedder.calls == 0
    assert all("must_have_coverage" not in _document(p) for p in llm.scoring_prompts)
    # 0.007 x (1 + 1/6 + 1): the CV parse, its share of the JD parse and the scoring.
    assert cells[10] == "0.0152"


@pytest.fixture
def calibrated_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-large")
    monkeypatch.setitem(embedding.THRESHOLDS, "text-embedding-3-large", 0.9)


@pytest.mark.usefixtures("calibrated_embedding")
def test_the_ablation_configs_are_compared_only_with_an_llm_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert [config.name for config in configs()] == ["Baseline (BM25)"]

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "gpt-6-luna")
    monkeypatch.setenv("LLM_REASONING_MODEL", "gpt-6-sol")
    found = configs()
    assert [(config.name, config.model) for config in found] == [
        ("Baseline (BM25)", None),
        ("Config A", "text-embedding-3-large"),
        ("Config B", "gpt-6-sol"),
        ("Config C", "gpt-6-sol"),
        ("Config D", "gpt-6-sol"),
        ("Config D-luna", "gpt-6-luna"),
    ]
    # D-luna scores with the extraction model, not only names it.
    luna = found[-1]
    assert isinstance(luna, ConfigD)
    assert getattr(luna.reasoning, "model", None) == "gpt-6-luna"


@pytest.mark.usefixtures("calibrated_embedding")
def test_with_a_cache_every_provider_call_goes_through_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "gpt-6-luna")
    monkeypatch.setenv("LLM_REASONING_MODEL", "gpt-6-sol")

    _, config_a, config_b, _, config_d, luna = configs(tmp_path)

    assert isinstance(config_a, ConfigA) and isinstance(config_a.embedder, CachedEmbedder)
    assert isinstance(config_b, ConfigB) and isinstance(config_b.parser.extraction, CachedLlm)
    assert isinstance(config_d, ConfigD) and isinstance(config_d.reasoning, CachedLlm)
    assert isinstance(config_d.embedder, CachedEmbedder)
    assert isinstance(luna, ConfigD) and isinstance(luna.reasoning, CachedLlm)
    assert (config_d.reasoning.model, luna.reasoning.model) == ("gpt-6-sol", "gpt-6-luna")


@pytest.mark.usefixtures("calibrated_embedding")
@pytest.mark.parametrize(
    ("variable", "model"),
    [
        ("LLM_REASONING_MODEL", "unpriced-model"),
        ("EMBEDDING_MODEL", "unpriced-embedding"),
        # Priced, but with no similarity threshold.
        ("EMBEDDING_MODEL", "gpt-6-luna"),
    ],
)
def test_a_model_without_a_price_or_threshold_stops_the_run_before_any_call(
    monkeypatch: pytest.MonkeyPatch, variable: str, model: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_EXTRACTION_MODEL", "gpt-6-luna")
    monkeypatch.setenv("LLM_REASONING_MODEL", "gpt-6-sol")
    monkeypatch.setenv(variable, model)

    with pytest.raises(SystemExit, match=model):
        configs()
