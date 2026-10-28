"""Shared test setup."""

import sys
import types

import pytest


class _Refuse:
    """Stands in for the real engines. Any attempt to load one fails the test at once."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("a test tried to load a real model; use tests/fakes.py")

    from_pretrained = classmethod(lambda cls, **kwargs: cls())


@pytest.fixture(autouse=True)
def _no_real_models(monkeypatch):
    """Tests never download or run the real LLM or OCR (tests can still swap in their own)."""
    monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(Llama=_Refuse))
    monkeypatch.setitem(
        sys.modules, "rapidocr_onnxruntime", types.SimpleNamespace(RapidOCR=_Refuse)
    )
