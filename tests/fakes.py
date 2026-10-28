"""Small fakes for the two outside engines (OCR and LLM), so tests are fast and repeatable."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audit_prep.documents import OcrLine


class FakeOcr:
    """Returns fixed lines for every image, like RapidOCR would."""

    def __init__(self, lines: list[OcrLine]) -> None:
        self.lines = lines

    def read(self, image: Path) -> list[OcrLine]:
        return self.lines


class FakeLLM:
    """Returns prepared answers in order and records every call."""

    model_id = "fake/llm"

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        self.calls.append({"system": system, "user": user, "schema": schema})
        return self.answers.pop(0)
