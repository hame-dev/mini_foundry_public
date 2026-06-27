from typing import Any
import httpx

from app.ai.providers.base import AIProvider


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def generate(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: str | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if response_format == "json":
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        text = (data.get("message") or {}).get("content", "")
        return {"text": text, "raw": data}
