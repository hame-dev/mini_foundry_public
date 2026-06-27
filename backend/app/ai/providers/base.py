from abc import ABC, abstractmethod
from typing import Any


class AIProvider(ABC):
    name: str

    @abstractmethod
    async def generate(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_format: str | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """Return {"text": str, "raw": provider-specific}."""
