from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting
from app.services.gcal_collector import (
    build_google_authorization_url,
    complete_google_authorization,
    has_google_calendar_authorized_token,
    has_google_gmail_authorized_token,
    has_google_client_credentials,
    save_google_client_credentials,
)
from app.services.llm_service import rebuild_llm_service

router = APIRouter(prefix="/api", tags=["settings"])

VALID_PROVIDERS = {"openai", "nvidia", "deepseek", "ollama"}
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash"
DEPRECATED_DEEPSEEK_MODELS = {"deepseek-chat", "deepseek-reasoner"}
SETTING_KEYS = [
    "llm_provider",
    "openai_api_key",
    "openai_model",
    "openai_base_url",
    "deepseek_api_key",
    "deepseek_model",
    "deepseek_base_url",
    "nvidia_api_key",
    "nvidia_model",
    "ollama_base_url",
    "ollama_model",
    "google_user_email",
    "chrome_history_enabled",
    "safari_history_enabled",
    "google_calendar_enabled",
    "gmail_enabled",
    "git_activity_enabled",
    "git_repo_paths",
    "git_author_filter",
]

DEFAULT_SETTINGS = {
    "llm_provider": "nvidia",
    "openai_api_key": "",
    "openai_model": "gpt-4o",
    "openai_base_url": "",
    "deepseek_api_key": "",
    "deepseek_model": DEEPSEEK_DEFAULT_MODEL,
    "deepseek_base_url": "https://api.deepseek.com",
    "nvidia_api_key": "",
    "nvidia_model": "deepseek-ai/deepseek-v3.2",
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "qwen2.5",
    "google_user_email": "",
    "chrome_history_enabled": True,
    "safari_history_enabled": True,
    "google_calendar_enabled": False,
    "gmail_enabled": False,
    "git_activity_enabled": False,
    "git_repo_paths": "",
    "git_author_filter": "",
}

SECRET_SETTING_KEYS = (
    "openai_api_key",
    "deepseek_api_key",
    "nvidia_api_key",
)


class SettingsUpdate(BaseModel):
    llm_provider: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    openai_base_url: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_model: Optional[str] = None
    deepseek_base_url: Optional[str] = None
    nvidia_api_key: Optional[str] = None
    nvidia_model: Optional[str] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None
    google_user_email: Optional[str] = None
    chrome_history_enabled: Optional[bool] = None
    safari_history_enabled: Optional[bool] = None
    google_calendar_enabled: Optional[bool] = None
    gmail_enabled: Optional[bool] = None
    git_activity_enabled: Optional[bool] = None
    git_repo_paths: Optional[str] = None
    git_author_filter: Optional[str] = None
    browser_history_enabled: Optional[bool] = None
    clear_openai_api_key: Optional[bool] = None
    clear_deepseek_api_key: Optional[bool] = None
    clear_nvidia_api_key: Optional[bool] = None

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, v):
        if v is not None and v not in VALID_PROVIDERS:
            raise ValueError(f"Provider must be one of: {VALID_PROVIDERS}")
        return v


def _coerce_setting_value(key: str, value):
    default = DEFAULT_SETTINGS.get(key)
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return value


def _serialize_setting_value(key: str, value) -> str:
    if isinstance(DEFAULT_SETTINGS.get(key), bool):
        return "true" if bool(value) else "false"
    return str(value)


async def _get_all_settings(db: AsyncSession) -> dict:
    result = await db.execute(select(Setting))
    rows = result.scalars().all()
    stored = {r.key: _coerce_setting_value(r.key, r.value) for r in rows}
    merged = {**DEFAULT_SETTINGS, **stored}

    legacy_browser_enabled = stored.get("browser_history_enabled")
    if legacy_browser_enabled is not None and not isinstance(legacy_browser_enabled, bool):
        legacy_browser_enabled = str(legacy_browser_enabled).strip().lower() in {"1", "true", "yes", "on"}
    if "chrome_history_enabled" not in stored and legacy_browser_enabled is not None:
        merged["chrome_history_enabled"] = legacy_browser_enabled
    if "safari_history_enabled" not in stored and legacy_browser_enabled is not None:
        merged["safari_history_enabled"] = legacy_browser_enabled
    if merged.get("deepseek_model") in DEPRECATED_DEEPSEEK_MODELS:
        merged["deepseek_model"] = DEEPSEEK_DEFAULT_MODEL
    merged.pop("browser_history_enabled", None)
    return merged


def _build_public_settings(all_settings: dict) -> dict:
    public_settings = dict(all_settings)
    for key in SECRET_SETTING_KEYS:
        public_settings[f"{key}_configured"] = bool(all_settings.get(key))
        public_settings[key] = ""
    public_settings["google_credentials_configured"] = has_google_client_credentials()
    public_settings["google_calendar_authorized"] = has_google_calendar_authorized_token()
    public_settings["google_gmail_authorized"] = has_google_gmail_authorized_token()
    return public_settings


def _build_google_redirect_uri(request: Request) -> str:
    redirect_uri = str(request.base_url)
    if redirect_uri.startswith("http://127.0.0.1:"):
        redirect_uri = redirect_uri.replace("http://127.0.0.1:", "http://localhost:", 1)
    return redirect_uri


@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db)):
    return _build_public_settings(await _get_all_settings(db))


@router.post("/settings/google-credentials")
async def upload_google_credentials(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="请上传 Google OAuth JSON 凭据文件")

    content = await file.read()
    if len(content) > 512 * 1024:
        raise HTTPException(status_code=400, detail="凭据文件过大")

    try:
        return save_google_client_credentials(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/settings/google-calendar/authorize")
async def start_google_calendar_authorization(request: Request):
    try:
        return build_google_authorization_url(_build_google_redirect_uri(request))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/settings/google-calendar/oauth-callback", response_class=HTMLResponse)
async def complete_google_calendar_authorization(
    state: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
):
    if error:
        return HTMLResponse(
            "<html><body><h2>Google 数据源授权失败</h2><p>请回到 Second Brain 配置页重新授权。</p></body></html>",
            status_code=400,
        )
    if not code:
        return HTMLResponse(
            "<html><body><h2>Google 数据源授权失败</h2><p>回调缺少授权码。</p></body></html>",
            status_code=400,
        )

    try:
        complete_google_authorization(state, code)
    except ValueError as exc:
        return HTMLResponse(
            f"<html><body><h2>Google 数据源授权失败</h2><p>{exc}</p></body></html>",
            status_code=400,
        )
    except Exception:
        return HTMLResponse(
            "<html><body><h2>Google 数据源授权失败</h2><p>保存授权 token 时出现错误，请回到配置页重试。</p></body></html>",
            status_code=500,
        )

    return HTMLResponse(
        "<html><body><h2>Google 数据源授权完成</h2><p>可以回到 Second Brain 继续采集。</p></body></html>"
    )


@router.put("/settings")
async def update_settings(req: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    legacy_browser_enabled = updates.pop("browser_history_enabled", None)
    clear_openai_api_key = updates.pop("clear_openai_api_key", False)
    clear_deepseek_api_key = updates.pop("clear_deepseek_api_key", False)
    clear_nvidia_api_key = updates.pop("clear_nvidia_api_key", False)
    if legacy_browser_enabled is not None:
        updates.setdefault("chrome_history_enabled", legacy_browser_enabled)
        updates.setdefault("safari_history_enabled", legacy_browser_enabled)

    for secret_key, clear_requested in (
        ("openai_api_key", clear_openai_api_key),
        ("deepseek_api_key", clear_deepseek_api_key),
        ("nvidia_api_key", clear_nvidia_api_key),
    ):
        if clear_requested:
            updates[secret_key] = ""

    for key, value in updates.items():
        result = await db.execute(select(Setting).where(Setting.key == key))
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = _serialize_setting_value(key, value)
        else:
            db.add(Setting(key=key, value=_serialize_setting_value(key, value)))

    await db.commit()

    all_settings = await _get_all_settings(db)

    provider = all_settings["llm_provider"]
    if provider == "nvidia":
        rebuild_llm_service(
            provider="openai",
            api_key=all_settings.get("nvidia_api_key", ""),
            base_url="https://integrate.api.nvidia.com/v1",
            model=all_settings.get("nvidia_model", "deepseek-ai/deepseek-v3.2"),
        )
    elif provider == "deepseek":
        rebuild_llm_service(
            provider="openai",
            api_key=all_settings.get("deepseek_api_key", ""),
            base_url=all_settings.get("deepseek_base_url", "https://api.deepseek.com"),
            model=all_settings.get("deepseek_model", DEEPSEEK_DEFAULT_MODEL),
        )
    elif provider == "openai":
        rebuild_llm_service(
            provider="openai",
            api_key=all_settings.get("openai_api_key", ""),
            base_url=all_settings.get("openai_base_url") or None,
            model=all_settings.get("openai_model", "gpt-4o"),
        )
    else:
        rebuild_llm_service(
            provider="ollama",
            base_url=all_settings.get("ollama_base_url", "http://localhost:11434"),
            model=all_settings.get("ollama_model", "qwen2.5"),
        )

    return _build_public_settings(all_settings)
