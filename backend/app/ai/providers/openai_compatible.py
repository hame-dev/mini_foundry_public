from typing import Any
from openai import AsyncOpenAI

from app.ai.providers.base import AIProvider


class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"

    def __init__(self, base_url: str, api_key: str):
        if not base_url:
            raise RuntimeError("CUSTOM_AI_BASE_URL is not set")
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key or "sk-none")

    async def generate(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: str | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self.client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        return {"text": text, "raw": resp.model_dump()}
