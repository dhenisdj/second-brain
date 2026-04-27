from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import analysis_service
from app.services.llm_service import LLMTimeoutError

router = APIRouter(prefix="/api", tags=["analysis"])


class AnalysisRequest(BaseModel):
    date: str


@router.post("/analysis/run")
async def run_analysis(req: AnalysisRequest, db: AsyncSession = Depends(get_db)):
    try:
        result = await analysis_service.run_analysis(db, req.date)
    except LLMTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="LLM 响应超时，请稍后重试，或减少当天数据量 / 切换更快模型后再分析。",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result
