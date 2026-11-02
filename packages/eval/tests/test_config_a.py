from decimal import Decimal
from pathlib import Path

import pytest
from test_harness import row

from smart_ats_eval import dataset, harness
from smart_ats_eval.config_a import ConfigA
from smart_ats_scoring import pricing
from smart_ats_scoring.embedding import EmbeddingResult
from smart_ats_scoring.llm import Usage

SCRATCH = Path(__file__).parents[1] / "datasets" / "scratch-v1.json"


class TableEmbedder:
    """Embeds each text by a fixed table and records what it was sent."""

    model = "fake-embedding"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> EmbeddingResult:
        self.calls.append(texts)
        return EmbeddingResult(
            [self.vectors[t] for t in texts], Usage("fake-embedding", 6000, 0, 0)
        )


@pytest.fixture
def fake_embedding_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        pricing.PRICES, "fake-embedding", pricing.Price(Decimal(2), Decimal(2), Decimal(0))
    )


@pytest.mark.usefixtures("fake_embedding_price")
def test_config_a_ranks_by_the_cosine_of_the_jd_and_cv_documents() -> None:
    data = dataset.load(SCRATCH)
    job = next(job for job in data.jobs if job.split == "dev")
    best, second, *rest = job.cvs
    # The JD on the first axis; the best CV on it, the second at 60 degrees, the rest across.
    vectors = {job.jd_text: [1.0, 0.0], best.text: [2.0, 0.0], second.text: [1.0, 3**0.5]}
    vectors |= {cv.text: [0.0, 1.0] for cv in rest}
    embedder = TableEmbedder(vectors)

    results = {r.cv_id: r for r in ConfigA(embedder).score(job)}

    # One call per Job: the JD Document and every CV Document, as written.
    assert embedder.calls == [[job.jd_text, *(cv.text for cv in job.cvs)]]
    assert results[best.id].total == pytest.approx(100)
    assert results[second.id].total == pytest.approx(50)
    assert {results[cv.id].total for cv in rest} == {0}
    # Each Application's share of the call: 6000 tokens x $2 per 1M, over the Job's six CVs.
    assert results[best.id].cost_usd == pytest.approx(0.002)


@pytest.mark.usefixtures("fake_embedding_price")
def test_config_a_row_names_the_embedding_model_and_no_prompt_or_rubric() -> None:
    data = dataset.load(SCRATCH)
    # Every document on one axis, so every Total is 100.
    texts = [text for job in data.jobs for text in (job.jd_text, *(cv.text for cv in job.cvs))]

    table = harness.compare(data, [ConfigA(TableEmbedder(dict.fromkeys(texts, [1.0])))], "dev", 1)

    assert row(table, "Config A")[1:4] == ["fake-embedding", "-", "-"]
