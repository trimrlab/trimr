"""
@Project: Trimr
@File: app/api/dashboard.py
@Description: Dashboard Data Interface
"""

import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.db.models import get_db, RequestLog, StrategyConfig

router = APIRouter()

@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    result = db.query(
        func.count(RequestLog.id).label("total_requests"),
        func.sum(RequestLog.input_tokens_original).label("total_input_tokens"),
        func.sum(RequestLog.output_tokens).label("total_output_tokens"),
        func.sum(RequestLog.saved_tokens).label("total_saved_tokens"),
        func.sum(RequestLog.cost_actual).label("total_cost_actual"),
        func.sum(RequestLog.cost_saved).label("total_cost_saved"),
    ).first()

    cache_hits = db.query(func.count(RequestLog.id)).filter(
        RequestLog.cache_hit == True
    ).scalar() or 0

    compression_count = db.query(func.count(RequestLog.id)).filter(
        RequestLog.compression_triggered == True
    ).scalar() or 0

    total_requests = result.total_requests or 0
    total_input_tokens = result.total_input_tokens or 0
    total_output_tokens = result.total_output_tokens or 0
    total_saved_tokens = result.total_saved_tokens or 0
    total_cost_actual = result.total_cost_actual or 0.0
    total_cost_saved = result.total_cost_saved or 0.0

    total_original_tokens = total_input_tokens + total_saved_tokens
    avg_saving_pct = 0.0
    if total_original_tokens > 0:
        avg_saving_pct = round(total_saved_tokens / total_original_tokens * 100, 2)

    return {
        "total_requests": total_requests,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_saved_tokens": total_saved_tokens,
        "total_cost_actual": round(total_cost_actual, 6),
        "total_cost_saved": round(total_cost_saved, 6),
        "avg_saving_pct": avg_saving_pct,
        "cache_hits": cache_hits,
        "compression_count": compression_count,
    }


@router.get("/requests/{request_id}")
async def get_request_by_id(
        request_id: str,
        db: Session = Depends(get_db),
):
    log = db.query(RequestLog).filter_by(id=request_id).first()
    if not log:
        return {"error": f"Record {request_id} not found"}
    return log.to_dict()


@router.get("/requests")
async def get_requests(
        page: int = Query(default=1, ge=1, description="Start 1 page"),
        pagesize: int = Query(default=10, ge=1, le=100, description="Page size"),
        model: Optional[str] = Query(default=None, description="Model name"),
        db: Session = Depends(get_db)
):
    query = db.query(RequestLog)

    if model:
        query = query.filter(RequestLog.model == model)

    total = query.count()

    logs = query.order_by(desc(RequestLog.timestamp)) \
                .offset((page - 1) * pagesize) \
                .limit(pagesize) \
                .all()

    return {
        "total": total,
        "page": page,
        "pagesize": pagesize,
        "logs": [log.to_dict() for log in logs]
    }

@router.get("/trends")
async def get_trends(
        days: int = Query(default=7, ge=1, le=30, description="Days to look back"),
        db: Session = Depends(get_db)
):
    start_date = datetime.utcnow() - timedelta(days=days)

    logs = db.query(RequestLog).filter(
        RequestLog.timestamp >= start_date
    ).all()

    daily_stats = {}
    for log in logs:
        day_key = log.timestamp.strftime("%Y-%m-%d")
        if day_key not in daily_stats:
            daily_stats[day_key] = {
                "date": day_key,
                "requests": 0,
                "input_tokens": 0,
                "saved_tokens": 0,
                "cost_saved": 0.0
            }
        daily_stats[day_key]["requests"] += 1
        daily_stats[day_key]["input_tokens"] += log.input_tokens_actual or 0
        daily_stats[day_key]["saved_tokens"] += log.saved_tokens or 0
        daily_stats[day_key]["cost_saved"] += log.cost_saved or 0.0

    result = []
    for i in range(days):
        day = (datetime.utcnow() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        if day in daily_stats:
            result.append(daily_stats[day])
        else:
            result.append({
                "date": day,
                "requests": 0,
                "input_tokens": 0,
                "saved_tokens": 0,
                "cost_saved": 0.0,
            })

    return {"days": days, "data": result}

@router.get("/strategies")
async def get_strategies(db: Session = Depends(get_db)):
    configs = db.query(StrategyConfig).all()
    return {"data": [c.to_dict() for c in configs]}

@router.post("/strategies/{name}")
async def update_strategy(
        name: str,
        body: dict,
        db: Session = Depends(get_db)
):
    config = db.query(StrategyConfig).filter_by(name=name).first()
    if not config:
        return {"error": "Strategy not found"}

    if "enabled" in body:
        config.enabled = body["enabled"]

    if "config" in body:
        config.config_json = json.dumps(body["config"])

    config.updated_at = datetime.utcnow()
    db.commit()

    return {
        "message": f"Strategy '{name}' updated successfully",
        "data": config.to_dict(),
    }
