"""日频因子计算任务 — 逐标的计算技术/量价/资金流因子。

管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → LoadStage → CalcStage → PreprocessStage → PersistStage → WatermarkAspect(后切)

水位管理（WatermarkAspect）：
  - 前切：查询水位日期，水位最新时标记 is_up_to_date 跳过管线
  - 后切：持久化成功后更新水位日期为数据最新日期

数据加载与计算策略：
  - LoadStage: 始终加载全量历史数据（无日期过滤）
  - CalcStage: 有状态因子（MACD/KDJ等）传入全量数据；无状态因子传入 5yr+warmup 切片
  - PersistStage: 根据 start_date 只持久化增量部分
  - 不加载估值指标和财务数据（截面因子在评估/合成时通过 CrossSectionReader 加载）
"""

from __future__ import annotations

import warnings
from typing import Any

from framework.commons.logger import get_logger
from framework.pipeline import Pipeline, PipelineEngine
from framework.scheduler.base_task import BaseTask
from worker.plugins.aspects import WatermarkAspect
from worker.plugins.factor_compute.stages import (
    FactorCalcStage,
    FactorLoadStage,
    FactorPersistStage,
    FactorPreprocessStage,
)
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.base import FactorPlugin
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
_DEFAULT_WARMUP_BARS = 300
_WATERMARK_DATA_TYPE = "factor_compute"

# B 类基本面因子所在的模块路径前缀 — 由 FactorQuarterlyTask / CrossSectionReader 负责
_FUNDAMENTAL_MODULE_PREFIXES = frozenset({
    "worker.plugins.factor_compute.factors.fundamental",
    "worker.plugins.factor_compute.factors.fundamental_profitability",
    "worker.plugins.factor_compute.factors.fundamental_growth",
    "worker.plugins.factor_compute.factors.fundamental_quality",
    "worker.plugins.factor_compute.factors.fundamental_leverage",
})


def _is_fundamental_factor(plugin: FactorPlugin) -> bool:
    """判断因子插件是否为 B 类基本面因子。"""
    module = plugin.__class__.__module__
    return any(module.startswith(prefix) for prefix in _FUNDAMENTAL_MODULE_PREFIXES)


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
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        symbols = parse_list_param(kwargs.get("symbols"))
        user_start_date = kwargs.get("start_date")
        start_date = str(user_start_date or "")
        factor_ids = parse_list_param(kwargs.get("factor_ids"))
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

        # 解析因子列表，过滤掉：
        # - B 类基本面因子（由 FactorQuarterlyTask / CrossSectionReader 负责）
        # - D 类合成因子（由 FactorSynthesizeTask 负责）
        # - A/D3 截面因子（compute_engine='cross_section'，由 CrossSectionReader 在评估/合成时按需计算）
        factors = await resolve_factor_list(factor_ids)
        factors = [
            f for f in factors
            if not _is_fundamental_factor(f)
            and f.compute_engine != "synthesize"
            and f.compute_engine != "cross_section"
        ]
        if not factors:
            return {"status": "FAILED", "message": "No factors resolved"}

        # 计算增量持久化起始日期（仅用于 PersistStage 截断）
        persist_start_date = self._calc_persist_start_date()
        if not start_date:
            start_date = persist_start_date

        # 获取标的列表
        if not symbols:
            symbols = await self._get_security_list()
            if not symbols:
                return {"status": "FAILED", "message": "No symbols to process"}

        logger.info(
            "[factor.compute] starting | symbols=%d mode=%s factors=%d persist_from=%s",
            len(symbols), mode, len(factors), start_date,
        )

        # 构建管线：WatermarkAspect 前切判断水位，后切更新水位
        pipeline = Pipeline(
            name=_WATERMARK_DATA_TYPE,
            stages=[
                FactorLoadStage(),
                FactorCalcStage(),
                FactorPreprocessStage(),
                FactorPersistStage(),
            ],
            aspects=[WatermarkAspect(data_type=_WATERMARK_DATA_TYPE)],
        )

        # 全局上下文
        # full 模式：强制从 persist_start_date 开始重新计算，绕过水位检查
        # incremental 模式：当用户显式指定 start_date 时绕过水位，否则按水位增量
        collect_date: str | None
        if mode == _COMPUTE_MODE_FULL:
            collect_date = persist_start_date
        else:
            collect_date = start_date if user_start_date else None
        global_ctx: dict[str, Any] = {
            "start_date": start_date,
            "persist_start_date": persist_start_date,
            "factor_ids": [f.factor_id for f in factors],
            "factor_plugins": factors,
            "collect_date": collect_date if collect_date else None,
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
    def _calc_persist_start_date() -> str:
        """计算增量持久化起始日期。

        保留5年数据，按自然年计算，即从2021-01-01开始持久化。
        预热期数据仅参与计算不持久化。
        """
        return "2021-01-01"

    @staticmethod
    async def _get_security_list() -> list[str]:
        """获取全市场A股标的代码。"""
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        codes = [row.symbol for row in rows]
        logger.debug("[factor.compute] 全市场标的数: %d", len(codes))
        return codes
