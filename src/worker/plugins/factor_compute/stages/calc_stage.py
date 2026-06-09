"""计算阶段 — 批量调用 FactorPlugin.compute()。

核心逻辑：
  1. 从上下文获取已加载的行情数据
  2. 解析因子列表（通过注册表）
  3. 对每个因子执行数据门控检查
  4. 批量计算因子值
  5. 对齐结果到完整日期范围
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

        # 解析因子列表
        factor_ids = ctx.get("factor_ids") or []
        if isinstance(factor_ids, str):
            factor_ids = [f.strip() for f in factor_ids.split(",") if f.strip()]

        factors = await resolve_factor_list(factor_ids if factor_ids else None)

        if not factors:
            logger.warning("[calc] %s no factors resolved", symbol)
            ctx.set("skip_persist", True)
            return StageResult.ok(data={"symbol": symbol, "factors": 0})

        # 数据门控
        valid_factors = []
        for factor in factors:
            passed, reason = _check_data_gate(df, factor)
            if passed:
                valid_factors.append(factor)
            else:
                logger.info("[calc] %s gated: %s - %s", symbol, factor.factor_id, reason)

        if not valid_factors:
            logger.warning("[calc] %s all factors gated out", symbol)
            ctx.set("skip_persist", True)
            return StageResult.ok(data={"symbol": symbol, "factors": 0})

        # 批量计算 — 全量计算所有加载的数据（已包含预热期）
        # 预热数据保证5年起点的因子值有效，持久化阶段截断5年内数据
        result_parts: dict[str, pd.Series] = {}
        for factor in valid_factors:
            try:
                result_df = factor.compute(df)
                if result_df.empty:
                    continue
                for col_name in result_df.columns:
                    series = result_df[col_name]
                    if series is None or series.empty:
                        continue
                    result_parts[col_name] = pd.Series(series.values, index=df.index, name=str(series.name))
            except Exception as e:
                logger.warning(
                    "[calc] %s failed: %s - %s", symbol, factor.factor_id, e, exc_info=True,
                )

        if not result_parts:
            ctx.set("skip_persist", True)
            return StageResult.ok(data={"symbol": symbol, "factors": 0})

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
            "[calc] %s factors=%d/%d rows=%d",
            symbol, factor_count, len(factors), len(result_df),
        )
        return StageResult.ok(data={"symbol": symbol, "factors": factor_count})
