"""AC-6: LLM 配置切换"""

import json

import pytest

from app.models.setting import Setting
from app.services import gcal_collector


class TestSettings:
    """AC-6: 设置管理和 LLM 切换"""

    async def test_get_settings_default(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "llm_provider" in data
        assert data["chrome_history_enabled"] is True
        assert data["safari_history_enabled"] is True
        assert data["google_calendar_enabled"] is False
        assert data["gmail_enabled"] is False
        assert data["git_activity_enabled"] is False
        assert data["git_repo_paths"] == ""
        assert data["git_author_filter"] == ""
        assert data["openai_api_key"] == ""
        assert data["deepseek_api_key"] == ""
        assert data["nvidia_api_key"] == ""
        assert data["openai_api_key_configured"] is False
        assert data["deepseek_api_key_configured"] is False
        assert data["nvidia_api_key_configured"] is False
        assert data["deepseek_model"] == "deepseek-v4-flash"
        assert "google_credentials_configured" in data
        assert "google_calendar_authorized" in data
        assert "google_gmail_authorized" in data

    async def test_update_llm_provider_to_ollama(self, client):
        resp = await client.put("/api/settings", json={
            "llm_provider": "ollama",
            "ollama_base_url": "http://localhost:11434",
            "ollama_model": "qwen2.5",
        })
        assert resp.status_code == 200
        assert resp.json()["llm_provider"] == "ollama"

    async def test_update_llm_provider_to_openai(self, client):
        resp = await client.put("/api/settings", json={
            "llm_provider": "openai",
            "openai_api_key": "sk-test-key",
            "openai_model": "gpt-4o",
        })
        assert resp.status_code == 200
        assert resp.json()["llm_provider"] == "openai"
        assert resp.json()["openai_api_key"] == ""
        assert resp.json()["openai_api_key_configured"] is True

    async def test_update_llm_provider_to_deepseek(self, client):
        resp = await client.put("/api/settings", json={
            "llm_provider": "deepseek",
            "deepseek_api_key": "sk-deepseek-test-key",
            "deepseek_model": "deepseek-v4-flash",
            "deepseek_base_url": "https://api.deepseek.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["llm_provider"] == "deepseek"
        assert data["deepseek_model"] == "deepseek-v4-flash"

    async def test_deprecated_deepseek_model_is_normalized_to_flash(self, client, db_session):
        db_session.add(Setting(key="deepseek_model", value="deepseek-chat"))
        await db_session.commit()

        resp = await client.get("/api/settings")

        assert resp.status_code == 200
        assert resp.json()["deepseek_model"] == "deepseek-v4-flash"

    async def test_update_invalid_provider(self, client):
        resp = await client.put("/api/settings", json={
            "llm_provider": "invalid_provider",
        })
        assert resp.status_code == 422

    async def test_settings_persist_after_update(self, client):
        await client.put("/api/settings", json={
            "llm_provider": "ollama",
            "ollama_base_url": "http://localhost:11434",
            "ollama_model": "qwen2.5",
        })
        resp = await client.get("/api/settings")
        assert resp.json()["llm_provider"] == "ollama"
        assert resp.json()["ollama_model"] == "qwen2.5"

    async def test_partial_update_preserves_other_fields(self, client):
        await client.put("/api/settings", json={
            "llm_provider": "openai",
            "openai_api_key": "sk-key-1",
            "openai_model": "gpt-4o",
        })
        await client.put("/api/settings", json={
            "openai_model": "gpt-4o-mini",
        })
        resp = await client.get("/api/settings")
        data = resp.json()
        assert data["openai_model"] == "gpt-4o-mini"
        assert data["openai_api_key"] == ""
        assert data["openai_api_key_configured"] is True

    async def test_update_source_switches(self, client):
        resp = await client.put("/api/settings", json={
            "chrome_history_enabled": False,
            "safari_history_enabled": True,
            "google_calendar_enabled": True,
            "gmail_enabled": True,
            "git_activity_enabled": True,
            "git_repo_paths": "/Users/test/project",
            "git_author_filter": "tester@example.com",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["chrome_history_enabled"] is False
        assert data["safari_history_enabled"] is True
        assert data["google_calendar_enabled"] is True
        assert data["gmail_enabled"] is True
        assert data["git_activity_enabled"] is True
        assert data["git_repo_paths"] == "/Users/test/project"
        assert data["git_author_filter"] == "tester@example.com"

    async def test_legacy_browser_switch_updates_both_browser_sources(self, client):
        resp = await client.put("/api/settings", json={
            "browser_history_enabled": False,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["chrome_history_enabled"] is False
        assert data["safari_history_enabled"] is False

    async def test_legacy_browser_switch_from_db_is_coerced_to_booleans(self, client, db_session):
        db_session.add(Setting(key="browser_history_enabled", value="true"))
        await db_session.commit()

        resp = await client.get("/api/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["chrome_history_enabled"] is True
        assert data["safari_history_enabled"] is True

    async def test_get_settings_does_not_expose_stored_api_keys(self, client, db_session):
        db_session.add_all(
            [
                Setting(key="openai_api_key", value="sk-openai-secret"),
                Setting(key="deepseek_api_key", value="sk-deepseek-secret"),
                Setting(key="nvidia_api_key", value="nvapi-secret"),
            ]
        )
        await db_session.commit()

        resp = await client.get("/api/settings")

        assert resp.status_code == 200
        data = resp.json()
        assert data["openai_api_key"] == ""
        assert data["deepseek_api_key"] == ""
        assert data["nvidia_api_key"] == ""
        assert data["openai_api_key_configured"] is True
        assert data["deepseek_api_key_configured"] is True
        assert data["nvidia_api_key_configured"] is True

    async def test_clear_saved_openai_key(self, client, db_session):
        db_session.add(Setting(key="openai_api_key", value="sk-openai-secret"))
        await db_session.commit()

        resp = await client.put("/api/settings", json={"clear_openai_api_key": True})

        assert resp.status_code == 200
        assert resp.json()["openai_api_key_configured"] is False

        db_session.expire_all()
        stored = await db_session.get(Setting, "openai_api_key")
        assert stored is not None
        assert stored.value == ""

    async def test_upload_google_credentials_saves_client_secret(self, client, tmp_path, monkeypatch):
        cred_dir = tmp_path / "credentials"
        token_path = cred_dir / "gcal_token.json"
        client_secret_path = cred_dir / "google_credentials.json"
        cred_dir.mkdir()
        token_path.write_text("old-token", encoding="utf-8")
        monkeypatch.setattr(gcal_collector, "CRED_DIR", cred_dir)
        monkeypatch.setattr(gcal_collector, "CLIENT_SECRET_PATH", client_secret_path)
        monkeypatch.setattr(gcal_collector, "TOKEN_PATH", token_path)

        payload = {
            "installed": {
                "client_id": "client-id.apps.googleusercontent.com",
                "client_secret": "client-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        resp = await client.post(
            "/api/settings/google-credentials",
            files={"file": ("google_credentials.json", json.dumps(payload).encode(), "application/json")},
        )

        assert resp.status_code == 200
        assert resp.json()["google_credentials_configured"] is True
        assert resp.json()["google_calendar_authorized"] is False
        assert resp.json()["google_gmail_authorized"] is False
        assert client_secret_path.exists()
        assert json.loads(client_secret_path.read_text(encoding="utf-8"))["installed"]["client_id"] == payload["installed"]["client_id"]
        assert not token_path.exists()

        settings_resp = await client.get("/api/settings")
        assert settings_resp.json()["google_credentials_configured"] is True
        assert settings_resp.json()["google_calendar_authorized"] is False

    async def test_upload_google_credentials_rejects_invalid_json(self, client):
        resp = await client.post(
            "/api/settings/google-credentials",
            files={"file": ("google_credentials.json", b"{}", "application/json")},
        )

        assert resp.status_code == 400
        assert "installed" in resp.json()["detail"]

    async def test_start_google_calendar_authorization_returns_url(self, client, tmp_path, monkeypatch):
        cred_dir = tmp_path / "credentials"
        client_secret_path = cred_dir / "google_credentials.json"
        cred_dir.mkdir()
        client_secret_path.write_text(
            json.dumps({
                "installed": {
                    "client_id": "client-id.apps.googleusercontent.com",
                    "client_secret": "client-secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }),
            encoding="utf-8",
        )
        monkeypatch.setattr(gcal_collector, "CLIENT_SECRET_PATH", client_secret_path)

        resp = await client.post("/api/settings/google-calendar/authorize")

        assert resp.status_code == 200
        data = resp.json()
        assert data["authorization_url"].startswith("https://accounts.google.com/o/oauth2/auth")
        assert "gmail.readonly" in data["authorization_url"]
        assert data["state"]
        assert data["redirect_uri"] == "http://test/"
