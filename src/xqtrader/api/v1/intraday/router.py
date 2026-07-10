"""盘内行情监控 API 路由。

提供盘内监控的控制入口（start/stop/status）和数据查询接口（分钟线、股票池）。
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from framework.commons.exceptions import BusinessException
from framework.dal.enginee import engines_manager
from xqtrader.domain.market.intraday.dynamic_pool import load_dynamic_stock_pool
from xqtrader.domain.market.intraday.intraday_monitor_task import IntradayMonitorTask
from xqtrader.domain.market.models.candlestick import CandlestickMinute

logger = logging.getLogger("API.INTRADAY")

router = APIRouter(prefix="/intraday", tags=["盘内监控"])


@router.post("/start", summary="启动盘内监控")
async def start_intraday_monitor() -> dict:
    """启动盘内监控：加载股票池 -> 启动 Collector/Scanner -> 订阅 QMT。"""
    task = IntradayMonitorTask.get_instance()
    if not task.is_running:
        raise BusinessException(code=5031, message="IntradayMonitorTask 未启动，请检查服务状态")
    if task.is_monitoring:
        return {"message": "盘内监控已在运行中"}
    try:
        await task.start_monitoring()
    except Exception as e:
        logger.error("启动盘内监控失败: %s", e, exc_info=True)
        raise BusinessException(code=5032, message=f"启动盘内监控失败: {e}") from e
    if not task.is_monitoring:
        # 诊断：检查股票池是否为空
        from xqtrader.domain.market.intraday.dynamic_pool import load_dynamic_stock_pool
        symbols = await load_dynamic_stock_pool()
        if not symbols:
            return {"message": "盘内监控启动失败：动态股票池为空（自选股+持仓+pre_order 均为空）"}
        return {"message": f"盘内监控启动失败：股票池 {len(symbols)} 只，但 QMT 订阅可能失败，请检查日志"}
    return {"message": "盘内监控已启动"}


@router.post("/stop", summary="停止盘内监控")
async def stop_intraday_monitor() -> dict:
    """停止盘内监控：取消 QMT 订阅 -> 停止 Collector/Scanner。"""
    task = IntradayMonitorTask.get_instance()
    if not task.is_monitoring:
        return {"message": "盘内监控未在运行"}
    await task.stop_monitoring()
    return {"message": "盘内监控已停止"}


@router.get("/status", summary="查询盘内监控状态")
async def get_intraday_status() -> dict:
    """查询当前监控状态。"""
    task = IntradayMonitorTask.get_instance()
    return {
        "running": task.is_running,
        "monitoring": task.is_monitoring,
    }


@router.get("/pool", summary="查询动态股票池")
async def get_dynamic_pool() -> dict:
    """查询当前动态股票池（自选+持仓+已审批 pre_order 去重）。"""
    symbols = await load_dynamic_stock_pool()
    return {"symbols": symbols, "count": len(symbols)}


@router.get("/minute-bars", summary="查询分钟线数据")
async def get_minute_bars(
    symbol: str = Query(..., description="证券代码，如 600000.SH"),
    trade_date: date | None = Query(None, description="交易日期，默认今天"),
    limit: int = Query(240, ge=1, le=2000, description="返回条数上限"),
) -> dict:
    """查询分钟级 K 线数据。"""
    if trade_date is None:
        trade_date = date.today()

    engine = engines_manager.get_engine("stock")
    async with engine.connect() as conn:
        stmt = (
            select(CandlestickMinute)
            .where(
                CandlestickMinute.symbol == symbol,
                CandlestickMinute.trade_date >= trade_date,
            )
            .order_by(CandlestickMinute.trade_time.desc())
            .limit(limit)
        )
        result = await conn.execute(stmt)
        rows = result.fetchall()

    bars = [
        {
            "symbol": r.symbol,
            "trade_time": r.trade_time.isoformat(),
            "open": r.open,
            "high": r.high,
            "low": r.low,
            "close": r.close,
            "volume": r.volume,
            "amount": r.amount,
            "trade_date": r.trade_date.isoformat(),
        }
        for r in rows
    ]
    # 按时间正序返回
    bars.reverse()
    return {"symbol": symbol, "bars": bars, "count": len(bars)}


@router.get("/anomalies", summary="查询异动事件")
async def get_anomalies(
    symbol: str | None = Query(None, description="证券代码过滤"),
    anomaly_type: str | None = Query(None, description="异动类型: surge/volume_spike"),
    limit: int = Query(50, ge=1, le=500, description="返回条数上限"),
) -> dict:
    """查询盘内异动事件记录。"""
    from xqtrader.domain.market.models.intraday_anomaly import IntradayAnomaly

    filters: dict[str, Any] = {}
    if symbol:
        filters["symbol"] = symbol
    if anomaly_type:
        filters["anomaly_type"] = anomaly_type

    records = await IntradayAnomaly.filter(
        limit=limit,
        order_by=IntradayAnomaly.detected_at.desc(),
        **filters,
    )

    anomalies = [
        {
            "id": r.id,
            "symbol": r.symbol,
            "anomaly_type": r.anomaly_type,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            "change_pct": r.change_pct,
            "price": r.price,
            "volume_ratio": r.volume_ratio,
            "detail": json.loads(r.detail_json) if r.detail_json else None,
        }
        for r in records
    ]
    return {"anomalies": anomalies, "count": len(anomalies)}
