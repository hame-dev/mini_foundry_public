"""AI gateway: provider selection + data policy enforcement.

`generate()` looks up the requested provider, enforces the per-dataset
`ai_policy` against the chosen provider, then dispatches to the provider's
async `generate` method.
"""
from functools import lru_cache
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import AIProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.ollama import OllamaProvider
from app.ai.providers.openai_compatible import OpenAICompatibleProvider
from app.config import get_settings
from app.data.models import Dataset


LOCAL_PROVIDERS = {"ollama"}
EXTERNAL_PROVIDERS = {"gemini", "openai_compatible"}


class AIPolicyError(PermissionError):
    pass


def enforce_ai_policy(dataset: Dataset, provider: str) -> None:
    policy = (dataset.ai_policy or "local_only").lower()
    if policy == "local_only" and provider not in LOCAL_PROVIDERS:
        raise AIPolicyError(f"dataset '{dataset.name}' is local_only; cannot use provider '{provider}'")
    if policy == "no_external" and provider not in LOCAL_PROVIDERS:
        raise AIPolicyError(f"dataset '{dataset.name}' is no_external; cannot use provider '{provider}'")
    # cloud_allowed and metadata_only are permitted; row inclusion is decided by the caller.


@lru_cache(maxsize=4)
def _get_provider(name: str) -> AIProvider:
    s = get_settings()
    if name == "ollama":
        return OllamaProvider(s.ollama_base_url)
    if name == "gemini":
        return GeminiProvider(s.gemini_api_key)
    if name == "openai_compatible":
        return OpenAICompatibleProvider(s.custom_ai_base_url, s.custom_ai_key)
    raise ValueError(f"unknown provider: {name}")


def default_model_for(provider: str) -> str:
    s = get_settings()
    return {
        "ollama": s.ollama_default_model,
        "gemini": s.gemini_default_model,
        "openai_compatible": s.custom_ai_default_model,
    }[provider]


async def generate(
    *,
    session: AsyncSession,
    provider: str,
    model: str | None,
    messages: list[dict[str, str]],
    datasets: list[Dataset] | None = None,
    response_format: str | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    if datasets:
        for ds in datasets:
            enforce_ai_policy(ds, provider)
    p = _get_provider(provider)
    return await p.generate(
        model=model or default_model_for(provider),
        messages=messages,
        response_format=response_format,
        temperature=temperature,
    )
