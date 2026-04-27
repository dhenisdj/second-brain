import json
import logging
import httpx
from openai import AsyncOpenAI, APITimeoutError

logger = logging.getLogger(__name__)


class LLMTimeoutError(Exception):
    pass


class LLMService:
    def __init__(self, provider: str = "openai", **kwargs):
        self.provider = provider
        if provider == "openai":
            self._openai = AsyncOpenAI(
                api_key=kwargs.get("api_key", ""),
                base_url=kwargs.get("base_url"),
                timeout=120.0,
            )
            self._model = kwargs.get("model", "gpt-4o")
        elif provider == "ollama":
            self._ollama_base = kwargs.get("base_url", "http://localhost:11434")
            self._model = kwargs.get("model", "qwen2.5")
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def complete(self, prompt: str, system: str | None = None) -> str:
        try:
            if self.provider == "openai":
                return await self._openai_complete(prompt, system)
            return await self._ollama_complete(prompt, system)
        except (APITimeoutError, httpx.TimeoutException) as exc:
            raise LLMTimeoutError("LLM request timed out") from exc

    async def complete_json(self, prompt: str, system: str | None = None) -> dict:
        raw = await self.complete(prompt, system)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # remove ```json
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        return json.loads(cleaned)

    async def _openai_complete(self, prompt: str, system: str | None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = await self._openai.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.3,
        )
        return resp.choices[0].message.content or ""

    async def _ollama_complete(self, prompt: str, system: str | None) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self._ollama_base}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")


_llm_instance: LLMService | None = None


def get_llm_service() -> LLMService:
    global _llm_instance
    if _llm_instance is None:
        from app.config import settings
        _llm_instance = _build_from_settings(settings)
    return _llm_instance


def rebuild_llm_service(provider: str, **kwargs):
    global _llm_instance
    _llm_instance = LLMService(provider=provider, **kwargs)


def _build_from_settings(settings) -> LLMService:
    if settings.LLM_PROVIDER == "nvidia":
        return LLMService(
            provider="openai",
            api_key=getattr(settings, "NVIDIA_API_KEY", "") or "",
            base_url="https://integrate.api.nvidia.com/v1",
            model=getattr(settings, "NVIDIA_MODEL", "deepseek-ai/deepseek-v3.2"),
        )
    if settings.LLM_PROVIDER == "deepseek":
        return LLMService(
            provider="openai",
            api_key=getattr(settings, "DEEPSEEK_API_KEY", "") or "",
            base_url=getattr(settings, "DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=getattr(settings, "DEEPSEEK_MODEL", "deepseek-v4-flash"),
        )
    if settings.LLM_PROVIDER == "openai":
        return LLMService(
            provider="openai",
            api_key=settings.OPENAI_API_KEY or "",
            base_url=settings.OPENAI_BASE_URL,
            model=settings.OPENAI_MODEL,
        )
    return LLMService(
        provider="ollama",
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.OLLAMA_MODEL,
    )
