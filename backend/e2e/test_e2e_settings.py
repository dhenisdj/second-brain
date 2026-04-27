"""
E2E Scenario 2: Settings & LLM Switch — AC-6

Verifies LLM provider configuration switching.
"""

import pytest


class TestLLMConfigSwitch:
    """E2E: settings CRUD and provider switching"""

    async def test_default_then_switch_to_ollama_then_back(self, client):
        # Get defaults
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        defaults = resp.json()
        assert "llm_provider" in defaults

        # Switch to Ollama
        resp = await client.put("/api/settings", json={
            "llm_provider": "ollama",
            "ollama_base_url": "http://my-ollama:11434",
            "ollama_model": "llama3",
        })
        assert resp.status_code == 200
        assert resp.json()["llm_provider"] == "ollama"
        assert resp.json()["ollama_model"] == "llama3"

        # Verify persistence
        resp = await client.get("/api/settings")
        assert resp.json()["llm_provider"] == "ollama"
        assert resp.json()["ollama_base_url"] == "http://my-ollama:11434"

        # Switch back to OpenAI
        resp = await client.put("/api/settings", json={
            "llm_provider": "openai",
            "openai_api_key": "sk-new-key",
            "openai_model": "gpt-4o-mini",
        })
        assert resp.status_code == 200
        assert resp.json()["llm_provider"] == "openai"
        assert resp.json()["openai_model"] == "gpt-4o-mini"

        # Ollama settings should still be there
        assert resp.json()["ollama_model"] == "llama3"

    async def test_invalid_provider_rejected(self, client):
        resp = await client.put("/api/settings", json={"llm_provider": "anthropic"})
        assert resp.status_code == 422
