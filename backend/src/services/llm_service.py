"""LLM adapter interface + Ollama implementation (Constitution IV — Modular Design)."""
import asyncio
from abc import ABC, abstractmethod

import httpx

from src.config import settings
from src.logging_config import get_logger
from src.services.health_service import CHECK_TIMEOUT, CheckStatus

logger = get_logger(__name__)


class LLMAdapter(ABC):
    """Abstract interface for LLM backend liveness checks."""

    @abstractmethod
    async def ping(self) -> CheckStatus:
        """Return ok if the LLM backend is reachable, unreachable otherwise."""


class OllamaAdapter(LLMAdapter):
    """Ollama implementation of LLMAdapter."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def ping(self) -> CheckStatus:
        if not self._base_url:
            return CheckStatus.UNCONFIGURED
        try:
            async with asyncio.timeout(CHECK_TIMEOUT):
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{self._base_url}/api/tags")
                    resp.raise_for_status()
            return CheckStatus.OK
        except Exception as exc:
            logger.warning("health_check_llm_failed", url=self._base_url, error=str(exc))
            return CheckStatus.UNREACHABLE


def get_default_llm_adapter() -> LLMAdapter:
    """Return the configured LLM adapter (switchable at config time)."""
    return OllamaAdapter(settings.ollama_base_url)
