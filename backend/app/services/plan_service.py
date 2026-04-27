import json
from datetime import date as date_type, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.summary import DailySummary
from app.models.plan import Plan
from app.services.llm_service import get_llm_service
from app.prompts.plan import build_plan_prompt


def _normalize_plan_item(item: dict) -> dict:
    priority = item.get("priority", "medium")
    if priority not in {"high", "medium", "low"}:
        priority = "medium"

    status = item.get("status", "todo")
    if status not in {"todo", "done", "carried_over"}:
        status = "todo"

    estimated_minutes = item.get("estimated_minutes")
    try:
        estimated_minutes = int(estimated_minutes) if estimated_minutes not in (None, "") else None
    except (TypeError, ValueError):
        estimated_minutes = None

    scheduled_slot = item.get("scheduled_slot")
    if scheduled_slot is not None:
        scheduled_slot = str(scheduled_slot).strip() or None

    return {
        "title": item.get("title", "").strip(),
        "priority": priority,
        "reason": item.get("reason", "").strip(),
        "status": status,
        "estimated_minutes": estimated_minutes,
        "scheduled_slot": scheduled_slot,
    }


def _normalize_plan_items(items: list[dict] | None) -> list[dict]:
    return [_normalize_plan_item(item) for item in (items or [])]


def _plan_to_dict(plan: Plan) -> dict:
    return {
        "id": plan.id,
        "date": plan.date.isoformat(),
        "items": _normalize_plan_items(json.loads(plan.items) if plan.items else []),
        "suggestions": json.loads(plan.suggestions) if plan.suggestions else [],
    }


async def generate_plan(db: AsyncSession, date_str: str) -> dict:
    target = date_type.fromisoformat(date_str)

    result = await db.execute(select(DailySummary).where(DailySummary.date == target))
    summary = result.scalar_one_or_none()
    if not summary:
        raise ValueError("No summary found for this date. Generate a summary first.")

    summary_data = {
        "date": target.isoformat(),
        "timeline_md": summary.timeline_md,
        "progress_md": summary.progress_md,
        "knowledge_md": summary.knowledge_md,
        "time_distribution": json.loads(summary.time_distribution) if summary.time_distribution else {},
    }

    llm = get_llm_service()
    prompt = build_plan_prompt(summary_data)
    llm_result = await llm.complete_json(prompt)
    normalized_items = _normalize_plan_items(llm_result.get("items", []))

    next_date = target + timedelta(days=1)
    existing = await db.execute(
        select(Plan).where(Plan.summary_id == summary.id).order_by(Plan.created_at.desc())
    )
    plan = existing.scalars().first()

    if plan:
        plan.date = next_date
        plan.items = json.dumps(normalized_items, ensure_ascii=False)
        plan.suggestions = json.dumps(llm_result.get("suggestions", []), ensure_ascii=False)
    else:
        plan = Plan(
            date=next_date,
            summary_id=summary.id,
            items=json.dumps(normalized_items, ensure_ascii=False),
            suggestions=json.dumps(llm_result.get("suggestions", []), ensure_ascii=False),
        )
        db.add(plan)

    await db.commit()
    await db.refresh(plan)

    return _plan_to_dict(plan)


async def get_plan_by_summary_date(db: AsyncSession, date_str: str) -> dict | None:
    target = date_type.fromisoformat(date_str)

    result = await db.execute(select(DailySummary).where(DailySummary.date == target))
    summary = result.scalar_one_or_none()
    if not summary:
        return None

    plan_result = await db.execute(
        select(Plan).where(Plan.summary_id == summary.id).order_by(Plan.created_at.desc())
    )
    plan = plan_result.scalars().first()
    if not plan:
        return None

    return _plan_to_dict(plan)


async def update_plan(db: AsyncSession, plan_id: str, items: list) -> dict | None:
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        return None

    normalized_items = _normalize_plan_items(items)
    plan.items = json.dumps(normalized_items, ensure_ascii=False)
    await db.commit()
    await db.refresh(plan)

    return _plan_to_dict(plan)
