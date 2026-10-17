"""The LLM seam on billed responses it cannot use: the provider client is stubbed."""

from types import SimpleNamespace

import pytest

from smart_ats_scoring.llm import GeminiLlm, OpenAiLlm, UnusableResponse, Usage


def _openai(status: str, output_text: str) -> OpenAiLlm:
    llm = OpenAiLlm.__new__(OpenAiLlm)
    llm.model = "gpt-test"
    response = SimpleNamespace(
        model="gpt-test-2026-01-01",
        status=status,
        output_text=output_text,
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            input_tokens_details=SimpleNamespace(cached_tokens=10),
        ),
    )
    llm.client = SimpleNamespace(responses=SimpleNamespace(create=lambda **_: response))  # type: ignore[assignment]
    return llm


def _gemini(content: str) -> GeminiLlm:
    llm = GeminiLlm.__new__(GeminiLlm)
    llm.model = "gemini-test"
    response = SimpleNamespace(
        model="gemini-test",
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, prompt_tokens_details=None),
    )
    completions = SimpleNamespace(create=lambda **_: response)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]
    return llm


@pytest.mark.parametrize(
    ("status", "output_text"),
    [("incomplete", '{"title": "Back'), ("completed", "")],
    ids=["hit the token limit", "refused"],
)
def test_openai_response_it_cannot_use_raises_with_its_usage(status: str, output_text: str) -> None:
    with pytest.raises(UnusableResponse) as exc:
        _openai(status, output_text).structured("system", "user", "name", {})

    assert exc.value.usage == Usage("gpt-test-2026-01-01", 100, 50, 10)


def test_gemini_truncated_json_raises_with_its_usage() -> None:
    with pytest.raises(UnusableResponse) as exc:
        _gemini('{"title": "Back').structured("system", "user", "name", {})

    assert exc.value.usage == Usage("gemini-test", 100, 50, 0)
