from datetime import date as date_type
from typing import Optional
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import ingest_service
from app.services.browser_collector import collect_browser_history
from app.services.chrome_collector import collect_chrome_history
from app.services.gcal_collector import collect_gcal_events, has_google_authorized_token, has_google_client_credentials
from app.services.git_collector import collect_git_activity, parse_git_repo_paths
from app.services.safari_collector import collect_safari_history

router = APIRouter(prefix="/api", tags=["ingest"])


class ManualEntry(BaseModel):
    timestamp: str
    title: str
    content: Optional[str] = None
    duration_minutes: Optional[int] = None


class ManualIngestRequest(BaseModel):
    entries: list[ManualEntry]


class BrowserLocalRequest(BaseModel):
    days: int = 2


class GCalRequest(BaseModel):
    days: int = 2
    user_email: Optional[str] = None


class GitRequest(BaseModel):
    days: int = 2


class ConfiguredSourcesRequest(BaseModel):
    days: int = 2


@router.post("/ingest/manual")
async def ingest_manual(req: ManualIngestRequest, db: AsyncSession = Depends(get_db)):
    count = await ingest_service.ingest_manual(db, [e.model_dump() for e in req.entries])
    return {"imported_count": count}


@router.post("/ingest/chrome")
async def ingest_chrome(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    content = await file.read()
    try:
        result = await ingest_service.ingest_chrome(db, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


async def _ingest_browser_local_impl(req: BrowserLocalRequest, db: AsyncSession) -> dict:
    try:
        collected = collect_browser_history(req.days)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read browser history: {e}")

    if not collected["events"]:
        return {
            "imported_count": 0,
            "date_range": [],
            "collected_sources": collected.get("collected_sources", []),
            "source_breakdown": collected.get("source_breakdown", {}),
            "warnings": collected.get("warnings", []),
        }

    result = await ingest_service.ingest_browser_events(db, collected["events"])
    return {
        **result,
        "collected_sources": collected.get("collected_sources", []),
        "source_breakdown": collected.get("source_breakdown", {}),
        "warnings": collected.get("warnings", []),
    }


async def _ingest_single_browser_source_impl(source: str, days: int, db: AsyncSession) -> dict:
    collectors = {
        "chrome": collect_chrome_history,
        "safari": collect_safari_history,
    }
    collector = collectors[source]

    try:
        collected = collector(days)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{source.capitalize()} 历史记录采集失败: {e}")

    if not collected["events"]:
        return {
            "imported_count": 0,
            "skipped_count": 0,
            "date_range": collected.get("date_range", []),
            "collected_sources": [source],
            "source_breakdown": {source: 0},
            "warnings": collected.get("warnings", []),
        }

    result = await ingest_service.ingest_browser_events(db, collected["events"])
    return {
        **result,
        "collected_sources": [source],
        "source_breakdown": {source: len(collected["events"])},
        "warnings": collected.get("warnings", []),
    }


@router.post("/ingest/browser-local")
async def ingest_browser_local(req: BrowserLocalRequest, db: AsyncSession = Depends(get_db)):
    return await _ingest_browser_local_impl(req, db)


@router.post("/ingest/chrome-local")
async def ingest_chrome_local(req: BrowserLocalRequest, db: AsyncSession = Depends(get_db)):
    return await _ingest_browser_local_impl(req, db)


async def _ingest_gcal_impl(req: GCalRequest, db: AsyncSession) -> dict:
    from app.routers.settings import _get_all_settings

    settings = await _get_all_settings(db)
    user_email = req.user_email or settings.get("google_user_email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="请先在设置页配置 Google 邮箱地址")

    try:
        collected = collect_gcal_events(user_email, req.days)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Calendar 采集失败: {e}")

    if not collected["events"]:
        return {"imported_count": 0, "date_range": []}

    count = await ingest_service.ingest_gcal(db, collected["events"])
    return {
        "imported_count": count,
        "date_range": collected["date_range"],
    }


def _merge_date_ranges(ranges: list[list[str]]) -> list[str]:
    dates = sorted({date for current_range in ranges for date in current_range})
    if not dates:
        return []
    return [dates[0], dates[-1]]


@router.post("/ingest/gcal")
async def ingest_gcal(req: GCalRequest, db: AsyncSession = Depends(get_db)):
    return await _ingest_gcal_impl(req, db)


async def _ingest_git_impl(req: GitRequest, db: AsyncSession, settings: dict | None = None) -> dict:
    if settings is None:
        from app.routers.settings import _get_all_settings

        settings = await _get_all_settings(db)

    repo_paths = parse_git_repo_paths(settings.get("git_repo_paths", ""))
    if not repo_paths:
        raise HTTPException(status_code=400, detail="请先在配置页填写 Git 仓库路径")

    try:
        collected = collect_git_activity(
            repo_paths,
            req.days,
            author_filter=settings.get("git_author_filter", ""),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Git 记录采集失败: {e}")

    repositories = collected.get("repositories", [])
    if not collected["events"] and repositories and all(item.get("status") != "success" for item in repositories):
        detail = "；".join(collected.get("warnings", [])) or "未读取到有效 Git 仓库"
        raise HTTPException(status_code=400, detail=detail)

    if not collected["events"]:
        return {
            "imported_count": 0,
            "skipped_count": 0,
            "date_range": collected.get("date_range", []),
            "warnings": collected.get("warnings", []),
            "repositories": repositories,
        }

    result = await ingest_service.ingest_git(db, collected["events"])
    return {
        **result,
        "date_range": result.get("date_range") or collected.get("date_range", []),
        "warnings": collected.get("warnings", []),
        "repositories": repositories,
    }


@router.post("/ingest/git")
async def ingest_git(req: GitRequest, db: AsyncSession = Depends(get_db)):
    return await _ingest_git_impl(req, db)


@router.post("/ingest/collect")
async def ingest_configured_sources(req: ConfiguredSourcesRequest, db: AsyncSession = Depends(get_db)):
    from app.routers.settings import _get_all_settings

    settings = await _get_all_settings(db)
    chrome_enabled = settings.get("chrome_history_enabled", settings.get("browser_history_enabled", True))
    safari_enabled = settings.get("safari_history_enabled", settings.get("browser_history_enabled", True))
    gcal_enabled = settings.get("google_calendar_enabled", False)
    git_enabled = settings.get("git_activity_enabled", False)

    if not chrome_enabled and not safari_enabled and not gcal_enabled and not git_enabled:
        raise HTTPException(status_code=400, detail="请先在配置页启用至少一个数据源")

    source_results = []
    imported_count = 0
    skipped_count = 0
    date_ranges: list[list[str]] = []
    warnings: list[str] = []

    for source, label, enabled in (
        ("chrome", "Chrome 历史", chrome_enabled),
        ("safari", "Safari 历史", safari_enabled),
    ):
        if enabled:
            try:
                browser_result = await _ingest_single_browser_source_impl(source, req.days, db)
                imported_count += browser_result.get("imported_count", 0)
                skipped_count += browser_result.get("skipped_count", 0)
                date_ranges.append(browser_result.get("date_range", []))
                warnings.extend(browser_result.get("warnings", []))
                source_results.append({
                    "source": source,
                    "label": label,
                    "status": "success",
                    "imported_count": browser_result.get("imported_count", 0),
                    "skipped_count": browser_result.get("skipped_count", 0),
                    "date_range": browser_result.get("date_range", []),
                    "message": f"最近 2 天无新的{label}" if browser_result.get("imported_count", 0) == 0 else None,
                    "warnings": browser_result.get("warnings", []),
                    "collected_sources": browser_result.get("collected_sources", []),
                    "source_breakdown": browser_result.get("source_breakdown", {}),
                })
            except HTTPException as exc:
                detail = str(exc.detail)
                warnings.append(f"{label}：{detail}")
                source_results.append({
                    "source": source,
                    "label": label,
                    "status": "failed",
                    "imported_count": 0,
                    "skipped_count": 0,
                    "date_range": [],
                    "message": detail,
                    "warnings": [detail],
                    "collected_sources": [],
                    "source_breakdown": {},
                })
        else:
            source_results.append({
                "source": source,
                "label": label,
                "status": "disabled",
                "imported_count": 0,
                "skipped_count": 0,
                "date_range": [],
                "message": "已在配置页关闭",
                "warnings": [],
                "collected_sources": [],
                "source_breakdown": {},
            })

    if git_enabled:
        git_repo_paths = parse_git_repo_paths(settings.get("git_repo_paths", ""))
        if not git_repo_paths:
            message = "请先在配置页填写 Git 仓库路径"
            warnings.append(f"Git 记录：{message}")
            source_results.append({
                "source": "git",
                "label": "Git 记录",
                "status": "misconfigured",
                "imported_count": 0,
                "skipped_count": 0,
                "date_range": [],
                "message": message,
                "warnings": [message],
                "collected_sources": [],
                "source_breakdown": {},
            })
        else:
            try:
                git_result = await _ingest_git_impl(GitRequest(days=req.days), db, settings=settings)
                imported_count += git_result.get("imported_count", 0)
                skipped_count += git_result.get("skipped_count", 0)
                date_ranges.append(git_result.get("date_range", []))
                warnings.extend(git_result.get("warnings", []))
                source_results.append({
                    "source": "git",
                    "label": "Git 记录",
                    "status": "success",
                    "imported_count": git_result.get("imported_count", 0),
                    "skipped_count": git_result.get("skipped_count", 0),
                    "date_range": git_result.get("date_range", []),
                    "message": f"最近 {req.days} 天无新的 Git 提交" if git_result.get("imported_count", 0) == 0 else None,
                    "warnings": git_result.get("warnings", []),
                    "collected_sources": ["git"],
                    "source_breakdown": {"git": git_result.get("imported_count", 0)},
                })
            except HTTPException as exc:
                detail = str(exc.detail)
                warnings.append(f"Git 记录：{detail}")
                source_results.append({
                    "source": "git",
                    "label": "Git 记录",
                    "status": "failed",
                    "imported_count": 0,
                    "skipped_count": 0,
                    "date_range": [],
                    "message": detail,
                    "warnings": [detail],
                    "collected_sources": [],
                    "source_breakdown": {},
                })
    else:
        source_results.append({
            "source": "git",
            "label": "Git 记录",
            "status": "disabled",
            "imported_count": 0,
            "skipped_count": 0,
            "date_range": [],
            "message": "已在配置页关闭",
            "warnings": [],
            "collected_sources": [],
            "source_breakdown": {},
        })

    if gcal_enabled:
        user_email = settings.get("google_user_email", "")
        if not user_email:
            message = "请先在配置页填写 Google 邮箱地址"
            warnings.append(f"Google 日历：{message}")
            source_results.append({
                "source": "gcal",
                "label": "Google 日历",
                "status": "misconfigured",
                "imported_count": 0,
                "skipped_count": 0,
                "date_range": [],
                "message": message,
                "warnings": [message],
                "collected_sources": [],
                "source_breakdown": {},
            })
        elif not has_google_client_credentials():
            message = "请先在配置页上传 Google OAuth JSON 凭据文件"
            warnings.append(f"Google 日历：{message}")
            source_results.append({
                "source": "gcal",
                "label": "Google 日历",
                "status": "misconfigured",
                "imported_count": 0,
                "skipped_count": 0,
                "date_range": [],
                "message": message,
                "warnings": [message],
                "collected_sources": [],
                "source_breakdown": {},
            })
        elif not has_google_authorized_token():
            message = "请先在配置页完成 Google 日历授权"
            warnings.append(f"Google 日历：{message}")
            source_results.append({
                "source": "gcal",
                "label": "Google 日历",
                "status": "misconfigured",
                "imported_count": 0,
                "skipped_count": 0,
                "date_range": [],
                "message": message,
                "warnings": [message],
                "collected_sources": [],
                "source_breakdown": {},
            })
        else:
            try:
                gcal_result = await _ingest_gcal_impl(GCalRequest(days=req.days, user_email=user_email), db)
                imported_count += gcal_result.get("imported_count", 0)
                date_ranges.append(gcal_result.get("date_range", []))
                source_results.append({
                    "source": "gcal",
                    "label": "Google 日历",
                    "status": "success",
                    "imported_count": gcal_result.get("imported_count", 0),
                    "skipped_count": 0,
                    "date_range": gcal_result.get("date_range", []),
                    "message": "最近 2 天无新的日历事件" if gcal_result.get("imported_count", 0) == 0 else None,
                    "warnings": [],
                    "collected_sources": [],
                    "source_breakdown": {},
                })
            except HTTPException as exc:
                detail = str(exc.detail)
                warnings.append(f"Google 日历：{detail}")
                source_results.append({
                    "source": "gcal",
                    "label": "Google 日历",
                    "status": "failed",
                    "imported_count": 0,
                    "skipped_count": 0,
                    "date_range": [],
                    "message": detail,
                    "warnings": [detail],
                    "collected_sources": [],
                    "source_breakdown": {},
                })
    else:
        source_results.append({
            "source": "gcal",
            "label": "Google 日历",
            "status": "disabled",
            "imported_count": 0,
            "skipped_count": 0,
            "date_range": [],
            "message": "已在配置页关闭",
            "warnings": [],
            "collected_sources": [],
            "source_breakdown": {},
        })

    return {
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "date_range": _merge_date_ranges(date_ranges),
        "source_results": source_results,
        "warnings": warnings,
    }


@router.get("/events")
async def get_events(
    date: str = Query(...),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    source: Optional[str] = Query(None),
    aggregate_browser: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    try:
        date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid date format. Use YYYY-MM-DD.")
    result = await ingest_service.get_events_by_date(
        db,
        date,
        page,
        size,
        source,
        aggregate_browser=aggregate_browser,
    )
    return result
