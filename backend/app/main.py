from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import ingest, analysis, summary, knowledge, plan, settings, data_manage, jobs
from app.services.job_executor import resume_incomplete_jobs, shutdown_job_executor


def _serve_frontend_enabled() -> bool:
    return os.getenv("SECOND_BRAIN_SERVE_FRONTEND", "").lower() in {"1", "true", "yes", "on"}


def _frontend_dist_dir() -> Path:
    configured = os.getenv("SECOND_BRAIN_FRONTEND_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _frontend_index() -> Path:
    return _frontend_dist_dir() / "index.html"


async def _load_llm_from_db():
    """Load LLM config from database on startup."""
    from app.database import async_session_factory as async_session
    from app.routers.settings import _get_all_settings
    from app.services.llm_service import rebuild_llm_service
    try:
        async with async_session() as db:
            s = await _get_all_settings(db)
            provider = s.get("llm_provider", "nvidia")
            if provider == "nvidia":
                rebuild_llm_service(
                    provider="openai",
                    api_key=s.get("nvidia_api_key", ""),
                    base_url="https://integrate.api.nvidia.com/v1",
                    model=s.get("nvidia_model", "deepseek-ai/deepseek-v3.2"),
                )
            elif provider == "deepseek":
                rebuild_llm_service(
                    provider="openai",
                    api_key=s.get("deepseek_api_key", ""),
                    base_url=s.get("deepseek_base_url", "https://api.deepseek.com"),
                    model=s.get("deepseek_model", "deepseek-v4-flash"),
                )
            elif provider == "openai":
                rebuild_llm_service(
                    provider="openai",
                    api_key=s.get("openai_api_key", ""),
                    base_url=s.get("openai_base_url", ""),
                    model=s.get("openai_model", "gpt-4o"),
                )
            else:
                rebuild_llm_service(
                    provider="ollama",
                    base_url=s.get("ollama_base_url", "http://localhost:11434"),
                    model=s.get("ollama_model", "qwen2.5"),
                )
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _load_llm_from_db()
    await resume_incomplete_jobs()
    yield
    await shutdown_job_executor()


app = FastAPI(title="AI Second Brain", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router)
app.include_router(analysis.router)
app.include_router(summary.router)
app.include_router(knowledge.router)
app.include_router(plan.router)
app.include_router(settings.router)
app.include_router(data_manage.router)
app.include_router(jobs.router)

if _serve_frontend_enabled():
    assets_dir = _frontend_dist_dir() / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")


def _is_google_oauth_callback(request: Request) -> bool:
    params = request.query_params
    return bool(params.get("state") and (params.get("code") or params.get("error")))


def _render_google_oauth_callback(request: Request) -> HTMLResponse:
    if request.query_params.get("error"):
        return HTMLResponse(
            "<html><body><h2>Google 数据源授权失败</h2><p>请回到 Second Brain 配置页重新授权。</p></body></html>",
            status_code=400,
        )

    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    if not code:
        return HTMLResponse(
            "<html><body><h2>Google 数据源授权失败</h2><p>回调缺少授权码。</p></body></html>",
            status_code=400,
        )

    try:
        from app.services.gcal_collector import complete_google_authorization

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


@app.get("/")
async def root(request: Request):
    if _is_google_oauth_callback(request):
        return _render_google_oauth_callback(request)

    if _serve_frontend_enabled() and _frontend_index().exists():
        return FileResponse(_frontend_index())
    return {"name": "AI Second Brain", "version": "0.1.0"}


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    if not _serve_frontend_enabled():
        raise HTTPException(status_code=404, detail="Not found")

    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    frontend_dir = _frontend_dist_dir()
    candidate = (frontend_dir / full_path).resolve()
    try:
        candidate.relative_to(frontend_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")

    if candidate.is_file():
        return FileResponse(candidate)

    index = _frontend_index()
    if index.exists():
        return FileResponse(index)

    raise HTTPException(status_code=404, detail="Frontend build not found")
