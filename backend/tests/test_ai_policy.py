import pytest
from app.ai.gateway import enforce_ai_policy, AIPolicyError


class FakeDataset:
    def __init__(self, name: str, policy: str):
        self.name = name
        self.ai_policy = policy


def test_local_only_with_ollama_ok():
    enforce_ai_policy(FakeDataset("d", "local_only"), "ollama")


def test_local_only_with_gemini_blocked():
    with pytest.raises(AIPolicyError):
        enforce_ai_policy(FakeDataset("d", "local_only"), "gemini")


def test_cloud_allowed_with_gemini_ok():
    enforce_ai_policy(FakeDataset("d", "cloud_allowed"), "gemini")


def test_no_external_with_openai_compat_blocked():
    with pytest.raises(AIPolicyError):
        enforce_ai_policy(FakeDataset("d", "no_external"), "openai_compatible")


def test_metadata_only_allows_any_provider():
    enforce_ai_policy(FakeDataset("d", "metadata_only"), "gemini")
    enforce_ai_policy(FakeDataset("d", "metadata_only"), "ollama")
