"""LLM client tests. llama_cpp is replaced by a stand-in, so no model is downloaded or run."""

import sys
import types

import pytest

from audit_prep.llm import LlamaCppClient, LLMUnavailable
from fakes import FakeLLM


class StandInLlama:
    """Records how the client loads and calls the model."""

    loads: list[dict] = []

    def __init__(self, **kwargs):
        self.calls: list[dict] = []

    @classmethod
    def from_pretrained(cls, **kwargs):
        cls.loads.append(kwargs)
        return cls()

    def create_chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": '{"id": "CA-12", "status": "closed"}'}}]}


@pytest.fixture
def stand_in(monkeypatch):
    StandInLlama.loads = []
    monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(Llama=StandInLlama))
    return StandInLlama


def test_building_the_client_downloads_nothing(stand_in):
    LlamaCppClient("qwen2.5-1.5b")
    assert stand_in.loads == []


def test_call_is_repeatable_and_schema_bound(stand_in):
    client = LlamaCppClient("qwen2.5-3b", seed=7)
    schema = {"type": "object"}

    answer = client.complete_json("system text", "user text", schema)

    assert answer == '{"id": "CA-12", "status": "closed"}'
    [load] = stand_in.loads
    assert load["repo_id"] == "Qwen/Qwen2.5-3B-Instruct-GGUF"
    [call] = client._llm.calls
    assert call["temperature"] == 0.0
    assert call["seed"] == 7
    assert call["response_format"] == {"type": "json_object", "schema": schema}
    assert call["messages"][0] == {"role": "system", "content": "system text"}


def test_model_loads_once(stand_in):
    client = LlamaCppClient()
    client.complete_json("s", "u", {})
    client.complete_json("s", "u", {})
    assert len(stand_in.loads) == 1


def test_load_failure_is_llm_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)  # import fails, like a missing package
    with pytest.raises(LLMUnavailable):
        LlamaCppClient().complete_json("s", "u", {})


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError):
        LlamaCppClient("gpt-17")


def test_fake_llm_replays_answers_and_records_calls():
    fake = FakeLLM(['{"a": 1}', "not json"])
    assert fake.complete_json("s", "u", {}) == '{"a": 1}'
    assert fake.complete_json("s", "u2", {}) == "not json"
    assert [c["user"] for c in fake.calls] == ["u", "u2"]
