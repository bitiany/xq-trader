"""日频因子计算任务 — 逐标的计算技术/量价/资金流因子。

管线流程（每个标的串行执行）：
  FactorLoadStage → FactorCalcStage → FactorPreprocessStage → FactorPersistStage

数据加载与计算策略：
  - LoadStage: 始终加载全量历史数据（无日期过滤）
  - CalcStage: 有状态因子（MACD/KDJ等）传入全量数据；无状态因子传入 5yr+warmup 切片
  - PersistStage: 根据 start_date 只持久化增量部分
  - 不加载估值指标和财务数据（截面因子在评估/合成时通过 CrossSectionReader 加载）
"""

from __future__ import annotations

import json
import warnings
from datetime import date, timedelta
from typing import Any

from framework.commons.logger import get_logger
from framework.pipeline import Pipeline, PipelineEngine
from framework.scheduler.base_task import BaseTask
from worker.plugins.factor_compute.stages import (
    FactorCalcStage,
    FactorLoadStage,
    FactorPersistStage,
    FactorPreprocessStage,
)
from xqtrader.domain.factor.services.registry import (
    auto_discover_factors,
    register_factor_variants,
    resolve_factor_list,
    sync_to_registry,
)
from xqtrader.domain.security.models import Security

logger = get_logger("factor.compute")

_COMPUTE_MODE_INCREMENTAL = "incremental"
_COMPUTE_MODE_FULL = "full"
_RETENTION_YEARS = 5
_DEFAULT_WARMUP_BARS = 300


def _parse_list_param(value: Any) -> list[str] | None:
    """解析可能为JSON字符串的列表参数。"""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            return [value]
        except (json.JSONDecodeError, TypeError):
            return [v.strip() for v in value.split(",") if v.strip()]
    return None


class FactorComputeTask(BaseTask):
    """日频因子计算任务。

    入参：
      - symbols: 股票代码列表（为空时计算全市场）
      - start_date: 增量持久化起始日期（为空时自动计算5年）
      - factor_ids: 因子ID列表（为空时计算所有活跃因子）
      - max_workers: 最大并发数（默认10）
      - mode: 计算模式 incremental/full
      - warmup_bars: 预热K线数（默认300）
    """

    task_name = "factor.compute_daily"
    description = "逐标的计算技术/量价/资金流因子"
    time_limit = 14400
    soft_time_limit = 14370
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        symbols = _parse_list_param(kwargs.get("symbols"))
        start_date = str(kwargs.get("start_date", ""))
        factor_ids = _parse_list_param(kwargs.get("factor_ids"))
        max_workers = int(kwargs.get("max_workers", 10))
        mode = str(kwargs.get("mode", _COMPUTE_MODE_INCREMENTAL))
        warmup_bars = int(kwargs.get("warmup_bars", _DEFAULT_WARMUP_BARS))

        if mode not in (_COMPUTE_MODE_INCREMENTAL, _COMPUTE_MODE_FULL):
            return {"status": "FAILED", "message": f"Invalid mode: {mode}"}

        # 抑制 numpy RuntimeWarning（全 NaN 切片求均值等），避免大量警告淹没业务日志
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy")

        # 初始化因子注册表
        auto_discover_factors()
        register_factor_variants()

        # 同步因子元数据到 DB
        await sync_to_registry()

        # 解析因子列表
        factors = await resolve_factor_list(factor_ids)
        if not factors:
            return {"status": "FAILED", "message": "No factors resolved"}

        # 计算增量持久化起始日期（仅用于 PersistStage 截断）
        if not start_date:
            start_date = self._calc_persist_start_date(mode)

        # 获取标的列表
        if not symbols:
            symbols = await self._get_security_list()
            if not symbols:
                return {"status": "FAILED", "message": "No symbols to process"}

        logger.info(
            "[factor.compute] starting | symbols=%d mode=%s factors=%d persist_from=%s",
            len(symbols), mode, len(factors), start_date,
        )

        # 构建管线
        pipeline = Pipeline(
            name="factor_compute",
            stages=[
                FactorLoadStage(),
                FactorCalcStage(),
                FactorPreprocessStage(),
                FactorPersistStage(),
            ],
        )

        # 全局上下文
        global_ctx: dict[str, Any] = {
            "start_date": start_date,
            "factor_ids": [f.factor_id for f in factors],
            "warmup_bars": warmup_bars,
        }

        # 执行管道引擎
        engine = PipelineEngine(
            pipelines=[pipeline],
            concurrency=max_workers,
            global_context=global_ctx,
        )
        result = await engine.execute(symbols)

        return result.to_dict()

    @staticmethod
    def _calc_persist_start_date(mode: str) -> str:
        """计算增量持久化起始日期。"""
        # 统一从5年前开始持久化（预热期数据仅参与计算不持久化）
        start = date.today() - timedelta(days=_RETENTION_YEARS * 365)
        return start.strftime("%Y-%m-%d")

    @staticmethod
    async def _get_security_list() -> list[str]:
        """获取全市场A股标的代码。"""
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        codes = [row.symbol for row in rows]
        logger.debug("全市场标的数: %d", len(codes))
        return codes
