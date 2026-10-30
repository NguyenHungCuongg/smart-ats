"""The LLM seam on billed responses it cannot use: the provider client is stubbed."""

from types import SimpleNamespace
from typing import Any

import pytest

from smart_ats_scoring.llm import (
    GeminiLlm,
    OpenAiLlm,
    UnusableResponse,
    Usage,
    has_llm_key,
    llm_from_env,
)


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


def _gemini(content: str, finish_reason: str, sent: dict[str, Any] | None = None) -> GeminiLlm:
    llm = GeminiLlm.__new__(GeminiLlm)
    llm.model = "gemini-test"
    response = SimpleNamespace(
        model="gemini-test",
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)
        ],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, prompt_tokens_details=None),
    )

    def create(**kwargs: Any) -> SimpleNamespace:
        if sent is not None:
            sent.update(kwargs)
        return response

    completions = SimpleNamespace(create=create)
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


def test_gemini_reply_cut_off_at_the_token_limit_raises_with_its_usage() -> None:
    # Cut exactly after a closing brace, the JSON parses: only finish_reason tells it is partial.
    with pytest.raises(UnusableResponse, match="length") as exc:
        _gemini('{"title": "Back"}', "length").structured("system", "user", "name", {})

    assert exc.value.usage == Usage("gemini-test", 100, 50, 0)


def test_gemini_call_sends_no_seed_which_its_endpoint_rejects() -> None:
    sent: dict[str, Any] = {}

    result = _gemini('{"title": "Back"}', "stop", sent).structured("system", "user", "name", {})

    assert "seed" not in sent
    assert result.data == {"title": "Back"}


def test_a_gemini_key_alone_does_not_select_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    assert isinstance(llm_from_env("gpt-6-luna"), OpenAiLlm)


def test_gemini_runs_only_when_the_provider_flag_asks_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert isinstance(llm_from_env("gemini-3.5-flash"), GeminiLlm)
    assert has_llm_key()


def test_has_llm_key_looks_only_at_the_chosen_providers_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert not has_llm_key()


def test_an_unknown_provider_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemni")

    with pytest.raises(ValueError, match="gemni"):
        llm_from_env("gemini-3.5-flash")
