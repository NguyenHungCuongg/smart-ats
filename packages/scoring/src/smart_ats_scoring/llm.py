"""The LLM seam: one Structured Outputs call that returns JSON plus the usage to bill."""

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from openai import APIConnectionError, APIStatusError, OpenAI, omit


@dataclass(frozen=True)
class Usage:
    """What the caller records as an AI Usage Entry (ERD `ai_usage_entries`)."""

    model: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int


@dataclass(frozen=True)
class LlmResult:
    data: dict[str, Any]
    usage: Usage


class UnusableResponse(Exception):
    """The provider billed a response that holds no usable JSON (cut off, refused, malformed).

    It carries the usage, so the caller still records the AI Usage Entry (FR-C1.4).
    """

    def __init__(self, message: str, usage: Usage) -> None:
        super().__init__(message)
        self.usage = usage


def _decode(output: str | None, usage: Usage, status: str) -> LlmResult:
    if not output:
        raise UnusableResponse(f"{usage.model} returned no structured output ({status})", usage)
    try:
        return LlmResult(json.loads(output), usage)
    except json.JSONDecodeError as e:
        raise UnusableResponse(f"{usage.model} returned malformed JSON ({status})", usage) from e


class Llm(Protocol):
    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult: ...


class OpenAiLlm:
    """OpenAI Responses API with a strict JSON Schema (FR-C2.1: Structured Outputs)."""

    def __init__(self, model: str, *, max_retries: int | None = None) -> None:
        self.model = model
        self.client = OpenAI() if max_retries is None else OpenAI(max_retries=max_retries)

    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult:
        response = self.client.responses.create(
            model=self.model,
            instructions=system,
            input=user,
            text={
                "format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}
            },
            # CV and JD text is personal data: keep it out of OpenAI's stored responses.
            store=False,
            temperature=omit if temperature is None else temperature,
        )
        if response.usage is None:
            raise RuntimeError(f"{self.model} returned no usage ({response.status})")
        usage = response.usage
        # A refusal completes with no output text; an incomplete response is cut off.
        return _decode(
            response.output_text if response.status == "completed" else None,
            Usage(
                response.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.input_tokens_details.cached_tokens,
            ),
            str(response.status),
        )


GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# The free tier allows a few requests a minute, so a 429 waits the minute out: the SDK backs
# off 0.5s doubling to 8s, about 70s over 12 retries.
# ponytail: covers a per-minute limit only; a spent daily limit still fails after the retries.
GEMINI_MAX_RETRIES = 12


class GeminiLlm:
    """Gemini's OpenAI-compatible Chat Completions (it has no Responses API), for free testing.

    The free tier uses prompts to improve Google products: send synthetic data only, so
    llm_from_env builds it only when LLM_PROVIDER=gemini (FR-C1.5).
    """

    def __init__(self, model: str, api_key: str, *, max_retries: int | None = None) -> None:
        self.model = model
        retries = GEMINI_MAX_RETRIES if max_retries is None else max_retries
        self.client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL, max_retries=retries)

    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": name, "schema": schema, "strict": True},
            },
            temperature=omit if temperature is None else temperature,
            # No seed: this endpoint rejects it with 400 "Unknown name seed" (ADR-0006: seed
            # only where the model supports it).
        )
        if response.usage is None:
            raise RuntimeError(f"{self.model} returned no usage")
        usage = response.usage
        details = usage.prompt_tokens_details
        choice = response.choices[0]
        # A reply cut off at the token limit (or filtered) can still parse as JSON, so only
        # a normal stop is usable.
        return _decode(
            choice.message.content if choice.finish_reason == "stop" else None,
            Usage(
                response.model,
                usage.prompt_tokens,
                usage.completion_tokens,
                (details.cached_tokens or 0) if details else 0,
            ),
            str(choice.finish_reason),
        )


def llm_provider() -> str:
    """OpenAI unless LLM_PROVIDER=gemini says otherwise: a Gemini key alone never selects it."""
    provider = os.environ.get("LLM_PROVIDER") or "openai"
    if provider not in ("openai", "gemini"):
        raise ValueError(f"LLM_PROVIDER must be openai or gemini, not {provider!r}")
    return provider


def has_llm_key() -> bool:
    key = "GEMINI_API_KEY" if llm_provider() == "gemini" else "OPENAI_API_KEY"
    return bool(os.environ.get(key))


def is_transient_error(exc: BaseException) -> bool:
    """Classify provider failures into transient (timeout, 429, 5xx) vs deterministic (FR-C2.3).

    Shared across OpenAiLlm, GeminiLlm, and both Embedders since all four use the OpenAI SDK.
    """
    if isinstance(exc, (APIConnectionError, TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code == 429 or status_code >= 500
    response = getattr(exc, "response", None)
    resp_code = getattr(response, "status_code", None)
    if isinstance(resp_code, int):
        return resp_code == 429 or resp_code >= 500
    return False


def llm_from_env(model: str, *, max_retries: int | None = None) -> Llm:
    if llm_provider() == "gemini":
        return GeminiLlm(model, os.environ["GEMINI_API_KEY"], max_retries=max_retries)
    return OpenAiLlm(model, max_retries=max_retries)
