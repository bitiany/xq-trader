"""计算阶段 — 批量调用 FactorPlugin.compute()。

核心逻辑：
  1. 从上下文获取已加载的全量行情数据
  2. 优先使用上下文中的 factor_plugins（由任务层解析），避免重复 DB 查询
  3. 对每个因子执行数据门控检查
  4. 批量计算因子值（统一使用全量数据，确保 index 对齐）
  5. 对齐结果到完整日期范围

注：有状态因子（MACD/KDJ等 requires_full_history=True）必须使用全量数据。
    无状态因子（MA/RSI等）也使用全量数据计算，保证结果 index 与有状态因子对齐。
    预热期数据仅参与计算，由 PersistStage 根据 start_date 截断不持久化。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult
from xqtrader.domain.factor.base import FactorPlugin
from xqtrader.domain.factor.services.registry import resolve_factor_list

logger = get_logger("factor.calc")


def _check_data_gate(df: pd.DataFrame, factor: FactorPlugin) -> tuple[bool, str]:
    """数据门控检查 — 验证因子计算所需数据是否充足。"""
    for dep in factor.dependencies:
        if dep not in df.columns:
            return False, f"column '{dep}' not found"

    if len(df) < factor.min_periods:
        return False, f"rows {len(df)} < min_periods {factor.min_periods}"

    return True, ""


class FactorCalcStage(Stage):
    """计算阶段 — 批量调用 FactorPlugin.compute()。"""

    @property
    def name(self) -> str:
        return "factor_calc"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        symbol: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"symbol": symbol, "factors": 0})

        df: pd.DataFrame | None = ctx.get("kline_df")
        if df is None or df.empty:
            return StageResult.ok(data={"symbol": symbol, "factors": 0})

        # 解析因子列表：优先使用任务层传入的 factor_plugins，避免重复 DB 查询
        factor_plugins: list[FactorPlugin] | None = ctx.get("factor_plugins")
        if factor_plugins:
            factors = factor_plugins
        else:
            # 回退：从 factor_ids 重新解析（兼容独立调用场景）
            factor_ids = ctx.get("factor_ids") or []
            if isinstance(factor_ids, str):
                factor_ids = [f.strip() for f in factor_ids.split(",") if f.strip()]
            factors = await resolve_factor_list(factor_ids if factor_ids else None)

        if not factors:
            logger.warning("[factor.compute] %s no factors resolved", symbol)
            ctx.set("skip_persist", True)
            return StageResult.ok(data={"symbol": symbol, "factors": 0})

        # 数据门控
        valid_factors: list[FactorPlugin] = []
        for factor in factors:
            passed, reason = _check_data_gate(df, factor)
            if not passed:
                logger.info("[factor.compute] %s gated: %s - %s", symbol, factor.factor_id, reason)
                continue
            valid_factors.append(factor)

        if not valid_factors:
            logger.warning("[factor.compute] %s all factors gated out", symbol)
            ctx.set("skip_persist", True)
            return StageResult.ok(data={"symbol": symbol, "factors": 0})

        # 批量计算 — 统一使用全量数据，确保 index 对齐
        result_parts: dict[str, pd.Series] = {}
        stateful_count = 0

        for factor in valid_factors:
            if factor.requires_full_history:
                stateful_count += 1
            self._compute_factor(symbol, factor, df, result_parts)

        if not result_parts:
            ctx.set("skip_persist", True)
            return StageResult.ok(data={"symbol": symbol, "factors": 0})

        # 构建结果 DataFrame — 所有因子 index 对齐到全量 df
        result_df = pd.DataFrame(result_parts, index=df.index)
        if "trade_date" in df.columns:
            result_df.insert(0, "trade_date", df["trade_date"].values)  # type: ignore[arg-type]

        ctx.set("factor_df", result_df)
        # 记录跳过预处理的因子列名，供 PreprocessStage 使用
        skip_cols = [fid for f in valid_factors if getattr(f, "skip_preprocess", False)
                     for fid in (f.composite_factor_ids if f.is_composite else [f.factor_id])]
        ctx.set("skip_preprocess_cols", set(skip_cols))
        factor_count = len(result_parts)

        logger.info(
            "[factor.compute] %s factors=%d/%d rows=%d (stateful=%d stateless=%d)",
            symbol, factor_count, len(factors), len(result_df),
            stateful_count, factor_count - stateful_count,
        )
        return StageResult.ok(data={"symbol": symbol, "factors": factor_count})

    @staticmethod
    def _compute_factor(
        symbol: str,
        factor: FactorPlugin,
        df: pd.DataFrame,
        result_parts: dict[str, pd.Series],
    ) -> None:
        """计算单个因子并合并结果。"""
        try:
            result_df = factor.compute(df)
            if result_df.empty:
                return
            for col_name in result_df.columns:
                series = result_df[col_name]
                if series is None or series.empty:
                    continue
                # 对齐到全量 df 的 index：取前 N 行（N = 因子输出长度）
                n = min(len(series), len(df))
                aligned = pd.Series(series.values[:n], index=df.index[:n], name=str(series.name))
                result_parts[col_name] = aligned
        except Exception as e:
            logger.warning(
                "[factor.compute] %s failed: %s - %s", symbol, factor.factor_id, e, exc_info=True,
            )
