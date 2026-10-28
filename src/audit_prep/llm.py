"""LLM interface and the local llama-cpp client.

Settings for repeatable output: temperature 0, fixed seed, and output constrained
to a JSON schema. The answer comes back as raw text on purpose: extract.py
validates it, so a malformed answer is rejected there instead of trusted here.

Tests never load the real model; they use a fake client (tests/fakes.py).

Try the real one: uv run python -m audit_prep.llm --model qwen2.5-1.5b
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any, Protocol

from audit_prep.config import DEFAULT_MODEL, LLM_CONTEXT, LLM_MAX_TOKENS, LLM_SEED, MODELS


class LLMUnavailable(RuntimeError):
    """The model can't be loaded for any reason (package missing, download failed). Fall back to rules only."""


class LLM(Protocol):
    model_id: str  # saved with each brief (provenance)

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        """Return the model's answer as a JSON string shaped by `schema`."""
        ...


class LlamaCppClient:
    """Runs a GGUF model in-process on CPU. The model loads (and downloads) on first call."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        seed: int = LLM_SEED,
        n_ctx: int = LLM_CONTEXT,
        max_tokens: int = LLM_MAX_TOKENS,
    ) -> None:
        if model not in MODELS:
            raise ValueError(f"unknown model {model!r}, choose from {sorted(MODELS)}")

        self.repo, self.filename = MODELS[model]
        self.model_id = f"{self.repo}/{self.filename}"
        self.seed = seed
        self.n_ctx = n_ctx
        self.max_tokens = max_tokens

        self._llm = None

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        """Return the model's answer as a JSON string shaped by `schema`."""
        out = self._load().create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object", "schema": schema},
            temperature=0.0,
            seed=self.seed,
            max_tokens=self.max_tokens,
        )
        return out["choices"][0]["message"]["content"]

    def _load(self):
        """Load the model on first use. Raises LLMUnavailable if it can't be loaded."""
        if self._llm is None:
            try:
                from llama_cpp import Llama

                self._llm = Llama.from_pretrained(
                    repo_id=self.repo,
                    filename=self.filename,
                    n_ctx=self.n_ctx,
                    seed=self.seed,
                    verbose=False,
                )
            except Exception as e:  # import error, no network, broken file, ...
                raise LLMUnavailable(f"could not load {self.model_id}: {e}") from e
        return self._llm


def _demo(argv: list[str] | None = None) -> None:
    """Ask the real model one small example question, to check it runs."""

    parser = argparse.ArgumentParser(prog="python -m audit_prep.llm")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS))
    args = parser.parse_args(argv)

    schema = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "status": {"type": "string"}},
        "required": ["id", "status"],
    }

    client = LlamaCppClient(args.model)

    # pass an example input to the model and print the answer (JSON string)
    start = time.perf_counter()
    answer = client.complete_json(
        system="Extract the corrective action id and its status. Answer in JSON.",
        user="CA-12 was closed on 14 March 2026 after all suppliers were re-evaluated.",
        schema=schema,
    )
    print(f"{client.model_id} ({time.perf_counter() - start:.1f}s, includes loading)")
    print(json.dumps(json.loads(answer), indent=2))


if __name__ == "__main__":
    _demo()
