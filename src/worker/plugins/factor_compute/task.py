"""日频因子计算任务 — 逐标的计算技术/量价/资金流因子。

管线流程（每个标的串行执行）：
  FactorLoadStage → FactorCalcStage → FactorPreprocessStage → FactorPersistStage

数据加载策略：
  - 有状态因子（MACD/KDJ等 requires_full_history=True）：加载全量历史数据
  - 无状态因子（MA/RSI等）：加载5年内数据 + 前向补充300条预热数据
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
    has_stateful_factors,
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
      - start_date: 开始日期
      - end_date: 结束日期
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
        end_date = str(kwargs.get("end_date", ""))
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

        # 解析因子列表，确定数据加载范围
        factors = await resolve_factor_list(factor_ids)
        if not factors:
            return {"status": "FAILED", "message": "No factors resolved"}

        has_stateful = has_stateful_factors(factors)

        # 计算加载起始日期
        if not start_date:
            start_date = self._calc_load_start_date(mode, has_stateful, warmup_bars)

        # 获取标的列表
        if not symbols:
            symbols = await self._get_security_list()
            if not symbols:
                return {"status": "FAILED", "message": "No symbols to process"}

        logger.info(
            "[factor.compute] starting | symbols=%d mode=%s factors=%d stateful=%s range=%s~%s",
            len(symbols), mode, len(factors), has_stateful, start_date, end_date or "latest",
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
            "end_date": end_date,
            "factor_ids": [f.factor_id for f in factors],
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
    def _calc_load_start_date(
        mode: str,
        has_stateful: bool,
        warmup_bars: int,
    ) -> str:
        """计算数据加载起始日期。"""
        if mode == _COMPUTE_MODE_FULL or has_stateful:
            # 全量模式或有状态因子：从第一根bar计算
            return ""

        # 增量模式无状态因子：5年内数据 + 前向补充
        # 300个交易日约1.2年，保守估计1.5年
        warmup_days = int(warmup_bars * 1.5)
        start = date.today() - timedelta(days=_RETENTION_YEARS * 365 + warmup_days)
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
