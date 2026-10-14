"""The LLM seam: one Structured Outputs call that returns JSON plus the usage to bill."""

import json
from dataclasses import dataclass
from typing import Any, Protocol

from openai import OpenAI, omit


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

    def __init__(self, model: str) -> None:
        self.model = model
        self.client = OpenAI()

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
        # A refusal completes with no output text.
        if response.status != "completed" or response.usage is None or not response.output_text:
            raise RuntimeError(f"{self.model} returned no structured output ({response.status})")
        usage = response.usage
        return LlmResult(
            json.loads(response.output_text),
            Usage(
                response.model,
                usage.input_tokens,
                usage.output_tokens,
                usage.input_tokens_details.cached_tokens,
            ),
        )
