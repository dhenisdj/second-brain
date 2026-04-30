from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./second_brain.db"
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_MODEL: str = "deepseek-v4-flash"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5"
    GRAPHITI_MCP_ENABLED: bool = False
    GRAPHITI_MCP_URL: str = "http://127.0.0.1:8001/mcp/"
    GRAPHITI_MCP_GROUP_ID: str = "second-brain"
    GRAPHITI_MCP_ALLOW_REMOTE: bool = False
    GRAPHITI_MCP_TIMEOUT_SECONDS: int = 60
    DAILY_AUTOMATION_ENABLED: bool = True
    DAILY_AUTOMATION_HOUR: int = 3
    DAILY_AUTOMATION_MINUTE: int = 0
    DAILY_AUTOMATION_TIMEZONE: str = "Asia/Shanghai"
    DAILY_AUTOMATION_COLLECT_DAYS: int = 2
    CURRENT_DAY_REFRESH_ENABLED: bool = True
    CURRENT_DAY_REFRESH_INTERVAL_HOURS: int = 4
    CURRENT_DAY_REFRESH_COLLECT_DAYS: int = 1

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
