"""GeminiClient behavior with the SDK mocked out (no network, no real key)."""
import pytest

from llm_client import GeminiClient


def test_missing_key_raises_without_leaking_anything(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Missing GEMINI_API_KEY"):
        GeminiClient()


def test_api_error_returns_empty_string_and_applies_temperature(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-test-value")
    client = GeminiClient(temperature=0.7)
    seen = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            seen["temperature"] = config.temperature
            raise RuntimeError("quota exceeded")

    class FakeSdk:
        models = FakeModels()

    client.client = FakeSdk()
    assert client.complete("sys", "user") == ""
    assert seen["temperature"] == 0.7
