"""Replays provider calls from disk (`--cache DIR`), so a run cut short by a free tier's daily
limit carries on another day without paying for the calls it already made.

A call is keyed by its model, its full request and how many times this invocation has made
that request before: run 2 of `--runs 2` asks again instead of replaying run 1, which would
fake a perfect Stability, and the next invocation replays both runs in order.
The directory holds CV text the provider returned, so keep it out of the repo.
"""

import hashlib
import json
import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from smart_ats_scoring.embedding import Embedder, EmbeddingResult
from smart_ats_scoring.llm import Llm, LlmResult, Usage


class _Store:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.seen: Counter[str] = Counter()

    def path(self, request: dict[str, Any]) -> Path:
        body = json.dumps(request, ensure_ascii=False, sort_keys=True)
        self.seen[body] += 1
        key = hashlib.sha256(f"{self.seen[body]}\n{body}".encode()).hexdigest()
        return self.directory / f"{key}.json"

    def write(self, path: Path, value: dict[str, Any]) -> None:
        # Whole or not at all: a run killed mid-write must not leave a file it cannot read.
        partial = path.with_suffix(".partial")
        partial.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(partial, path)


class CachedLlm:
    def __init__(self, llm: Llm, directory: Path, model: str) -> None:
        """`model` is the one `llm` calls: Config D and D-luna send the same prompt to two."""
        self.llm = llm
        self.store = _Store(directory)
        self.model = model

    def structured(
        self,
        system: str,
        user: str,
        name: str,
        schema: dict[str, Any],
        temperature: float | None = None,
    ) -> LlmResult:
        path = self.store.path(
            {
                "model": self.model,
                "system": system,
                "user": user,
                "name": name,
                "schema": schema,
                "temperature": temperature,
            }
        )
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            return LlmResult(saved["data"], Usage(**saved["usage"]))
        result = self.llm.structured(system, user, name, schema, temperature)
        self.store.write(path, {"data": result.data, "usage": asdict(result.usage)})
        return result


class CachedEmbedder:
    def __init__(self, embedder: Embedder, directory: Path) -> None:
        self.embedder = embedder
        self.store = _Store(directory)
        self.model = embedder.model

    def embed(self, texts: list[str]) -> EmbeddingResult:
        path = self.store.path({"model": self.model, "texts": texts})
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            return EmbeddingResult(saved["vectors"], Usage(**saved["usage"]))
        result = self.embedder.embed(texts)
        self.store.write(path, {"vectors": result.vectors, "usage": asdict(result.usage)})
        return result
