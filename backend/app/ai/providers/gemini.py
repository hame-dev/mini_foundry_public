from typing import Any
import asyncio

import google.generativeai as genai

from app.ai.providers.base import AIProvider


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, api_key: str):
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        genai.configure(api_key=api_key)

    async def generate(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: str | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        history: list[dict[str, Any]] = []
        for m in messages:
            role = m.get("role")
            if role in ("user", "assistant"):
                history.append({"role": "user" if role == "user" else "model", "parts": [m["content"]]})

        generation_config: dict[str, Any] = {"temperature": temperature}
        if response_format == "json":
            generation_config["response_mime_type"] = "application/json"

        gm = genai.GenerativeModel(model_name=model, system_instruction=system or None)

        def _call() -> Any:
            return gm.generate_content(history, generation_config=generation_config)

        resp = await asyncio.to_thread(_call)
        text = getattr(resp, "text", "") or ""
        return {"text": text, "raw": {"candidates": getattr(resp, "candidates", None)}}
