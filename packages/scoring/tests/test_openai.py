"""Optional: the real OpenAI (or Gemini) API. Runs only with a key, for example
`uv run --env-file .env pytest packages/scoring/tests/test_openai.py`."""

import os

import pytest

from smart_ats_scoring.llm import Llm, has_llm_key, llm_from_env
from smart_ats_scoring.parsing import CV_SCHEMA, JOB_SCHEMA, parse_cv, parse_job

pytestmark = pytest.mark.skipif(
    not (has_llm_key() and os.environ.get("LLM_EXTRACTION_MODEL")),
    reason="needs OPENAI_API_KEY or GEMINI_API_KEY, and LLM_EXTRACTION_MODEL",
)


def _llm() -> Llm:
    return llm_from_env(os.environ["LLM_EXTRACTION_MODEL"])


def test_parse_job_with_openai() -> None:
    text = "Tuyển Backend Developer. Bắt buộc: Python, PostgreSQL. Ưu tiên: Docker. Remote."

    parsed = parse_job(text, _llm())

    assert set(parsed.data) == set(JOB_SCHEMA["properties"])
    assert {s["name"] for s in parsed.data["skills"] if s["must_have"]} == {"Python", "PostgreSQL"}
    assert parsed.verification["skills"] == "VERIFIED"
    assert parsed.usage.input_tokens > 0 and parsed.usage.output_tokens > 0


def test_parse_cv_with_openai() -> None:
    text = "Trần Thị B, b@example.com. Backend Developer tại Công ty ABC (2021 - nay). Python."

    parsed = parse_cv(text, _llm())

    assert set(parsed.data) == set(CV_SCHEMA["properties"])
    assert parsed.data["contact"]["email"] == "b@example.com"
