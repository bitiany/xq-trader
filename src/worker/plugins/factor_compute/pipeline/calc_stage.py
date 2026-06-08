"""因子计算阶段 — 遍历 FactorPlugin 执行 compute_batch 批量计算。

每个插件对单只股票的全部交易日一次性计算，利用 talib/pandas 向量化操作。
计算结果为 DataFrame（columns=[trade_date, factor_id_1, ...]），过滤到目标交易日后持久化。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult
from worker.plugins.factor_compute.plugins.base import FactorPluginRegistry
from xqtrader.domain.factor.exceptions import FactorComputeError

logger = get_logger(__name__)


class FactorCalcStage(Stage):
    """因子计算阶段 — 遍历注册的 FactorPlugin 执行批量因子计算。

    流程：
      1. 从 PipelineContext 读取加载的数据
      2. 构建计算上下文 ctx
      3. 逐插件调用 compute_batch()，返回全量日期的 DataFrame
      4. 合并所有插件结果，过滤到目标交易日
      5. 将合并后的 DataFrame 写入 PipelineContext
    """

    def __init__(
        self,
        registry: FactorPluginRegistry,
        trade_dates: list[Any],
        factor_ids: list[str] | None = None,
    ) -> None:
        self._registry = registry
        self._trade_dates = trade_dates
        self._factor_ids = factor_ids

    @property
    def name(self) -> str:
        return "factor_calc"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_calc", False):
            return StageResult.ok(data={"stock_code": stock_code, "computed": 0})

        kline_df: pd.DataFrame | None = ctx.get("kline_df")
        if kline_df is None or kline_df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "computed": 0})

        # 构建计算上下文（中间计算不过滤，避免行数不一致）
        compute_ctx: dict[str, Any] = {
            "indicator_df": ctx.get("indicator_df"),
            "fina_df": ctx.get("fina_df"),
            "fund_flow_df": ctx.get("fund_flow_df"),
            "index_kline_df": ctx.get("index_kline_df"),
            "trade_dates": [],  # 中间不过滤，最终统一过滤
            "factor_values": None,
        }

        # 解析需要计算的插件
        plugins = self._registry.resolve(self._factor_ids)
        all_factor_dfs: list[pd.DataFrame] = []
        computed_count = 0
        failed_plugins: list[str] = []

        for plugin in plugins:
            if len(kline_df) < plugin.min_periods:
                logger.debug(
                    "K线不足: %s plugin=%s need=%d has=%d",
                    stock_code, plugin.category, plugin.min_periods, len(kline_df),
                )
                continue

            try:
                factor_df = plugin.compute_batch(kline_df, compute_ctx)
                if factor_df is not None and not factor_df.empty:
                    all_factor_dfs.append(factor_df)
                    computed_count += len(factor_df)
                    # 更新已计算因子值供依赖因子使用
                    if compute_ctx["factor_values"] is None:
                        compute_ctx["factor_values"] = factor_df
                    else:
                        compute_ctx["factor_values"] = compute_ctx["factor_values"].merge(
                            factor_df, on="trade_date", how="outer",
                        )
            except FactorComputeError as e:
                failed_plugins.append(plugin.category)
                logger.warning("因子计算异常: %s plugin=%s error=%s", stock_code, plugin.category, e)

        if not all_factor_dfs:
            ctx.set("factor_df", None)
            return StageResult.ok(data={"stock_code": stock_code, "computed": 0})

        # 合并所有插件的计算结果
        merged = all_factor_dfs[0]
        for df in all_factor_dfs[1:]:
            merged = merged.merge(df, on="trade_date", how="outer")

        # 过滤到目标交易日
        if self._trade_dates:
            td_set = set(self._trade_dates)
            merged = merged[merged["trade_date"].isin(td_set)].copy()

        ctx.set("factor_df", merged)

        if failed_plugins:
            logger.warning(
                "因子计算部分失败: %s computed=%d failed_plugins=%s",
                stock_code, computed_count, failed_plugins,
            )
        return StageResult.ok(data={"stock_code": stock_code, "computed": computed_count})
