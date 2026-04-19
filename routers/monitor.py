from typing import Optional
from fastapi import APIRouter, Query
from llm.llm_monitor import monitor
from core.llm import llm

router = APIRouter(prefix="/monitor", tags=["monitor"])


@router.get("/summary")
def get_summary():
    """대시보드 요약 통계"""
    summary = monitor.get_summary()
    summary["model_name"] = getattr(llm, "model_name", getattr(llm, "model", "unknown"))
    return summary


@router.get("/logs")
def get_logs(
    generator_type: Optional[str] = Query(default=None, description="analysis | sql | answer"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """로그 목록 조회 (최신순)"""
    return monitor.get_logs(generator_type=generator_type, limit=limit, offset=offset)


@router.get("/stats")
def get_stats(hours: int = Query(default=24, ge=1, le=168)):
    """시간대별 통계"""
    return monitor.get_recent_stats(hours=hours)


@router.get("/logs/{index}")
def get_log_detail(index: int):
    """특정 로그 상세 조회"""
    logs = monitor.get_logs(limit=1, offset=index)
    if not logs:
        return {"error": "해당 로그를 찾을 수 없습니다."}
    return logs[0]
