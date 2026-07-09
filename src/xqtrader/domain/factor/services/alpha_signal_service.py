"""L3 Alpha 信号层 — 日频截面得分 / TopN 排序 / 单标的时序。

定位（docs/factor-system-design.md §18.4）：
  - 在 L2 合成（composite_alpha 已入库）与 L4 战术层之间
  - 日频按需计算全市场相对强弱 → 排序 / 权重 / 合成阈值
  - 不持久化至 DB（§18.4.3）

三种信号输出模式（§18.4.2）：
  - A 截面排序: score_i = Σ w_k × z(f_k,i), TopN
  - B 合成阈值: composite_alpha 已 Z-score, score > θ_buy
  - C 目标权重: weight_i = max(0, score_i) / Σ max(0, score)

设计约束（§18.7）：
  - 仅允许 composite_alpha / composite_alpha_quarterly 等 composite_output
  - 不得叠加原始 A/B 因子组；合成得分已涵盖子因子信息
  - Alpha 因子不得直接作时序阈值，须经标准化与合成后再进入信号层
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader
from xqtrader.domain.factor.services.factor_panel_service import FactorPanelService

logger = get_logger(__name__)

# 默认合成因子 ID
_DEFAULT_COMPOSITE_ALPHA = "composite_alpha"

# ICIR 权重加权时，从 fac_factor_stats 取最新评估记录的 icir 字段
_STATS_WINDOW = 504


class AlphaSignalService:
    """L3 Alpha 信号服务 — 按需计算截面得分与排序。

    依赖：
      - FactorPanelService: 加载截面面板（含截面标准化）
      - FacFactorStats: 读取 ICIR 权重（icir_weighted 模式）
      - FacFactorRegistry: 读取因子等级（A/B 候选）
    """

    def __init__(self) -> None:
        self._panel_service = FactorPanelService()
        self._reader = CrossSectionReader()

    async def compute_cross_section_scores(
        self,
        signal_date: date,
        pool_id: str,
        method: str = "icir_weighted",
        factor_ids: list[str] | None = None,
    ) -> pd.DataFrame:
        """计算全市场截面 Alpha 得分。

        Args:
            signal_date: 截面日期
            pool_id: 样本池标识
            method: 评分方法
              - 'composite_alpha': 直接使用 composite_alpha 因子值作为得分
              - 'icir_weighted': 按 A/B 因子 ICIR 加权求和
            factor_ids: 指定因子列表（仅 icir_weighted 模式生效）；
                        None 时自动取 A/B 级 dense 因子

        Returns:
            DataFrame columns: symbol, score, rank, weight
            - score: 截面得分（Z-score 语义）
            - rank: 按 score 降序排名（1=最强）
            - weight: 目标权重 = max(0, score) / Σ max(0, score)
        """
        symbols = await self._reader.load_pool_symbols(pool_id)
        if not symbols:
            logger.warning("[alpha_signal] pool=%s 无标的", pool_id)
            return pd.DataFrame(columns=["symbol", "score", "rank", "weight"])

        if method == "composite_alpha":
            score_series = await self._score_by_composite_alpha(
                signal_date, pool_id, symbols,
            )
        elif method == "icir_weighted":
            score_series = await self._score_by_icir_weighted(
                signal_date, pool_id, symbols, factor_ids,
            )
        else:
            raise ValueError(
                f"不支持的评分方法: {method},仅支持 'composite_alpha' / 'icir_weighted'"
            )

        if score_series is None or score_series.empty:
            logger.info(
                "[alpha_signal] pool=%s signal_date=%s method=%s 得分为空",
                pool_id, signal_date, method,
            )
            return pd.DataFrame(columns=["symbol", "score", "rank", "weight"])

        # 构建结果 DataFrame
        result = pd.DataFrame({
            "symbol": score_series.index,
            "score": score_series.values,
        })
        result = result.sort_values("score", ascending=False).reset_index(drop=True)
        result["rank"] = range(1, len(result) + 1)

        # 目标权重: weight_i = max(0, score_i) / Σ max(0, score)
        positive_scores = result["score"].clip(lower=0)
        total_positive = positive_scores.sum()
        if total_positive > 0:
            result["weight"] = positive_scores / total_positive
        else:
            # 所有得分非正时，等权分配给得分最高的前 N 只
            result["weight"] = 0.0
            if len(result) > 0:
                result.loc[0, "weight"] = 1.0

        logger.info(
            "[alpha_signal] compute_cross_section_scores pool=%s signal_date=%s "
            "method=%s symbols=%d valid=%d",
            pool_id, signal_date, method, len(symbols), len(result),
        )
        return result

    async def rank_universe(
        self,
        signal_date: date,
        pool_id: str,
        top_n: int = 10,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """模式 A：截面选股 TopN。

        Args:
            signal_date: 截面日期
            pool_id: 样本池标识
            top_n: 取前 N 只
            **kwargs: 传递给 compute_cross_section_scores（method/factor_ids）

        Returns:
            list[dict], 每项含 symbol/score/rank/weight
        """
        scores = await self.compute_cross_section_scores(
            signal_date, pool_id, **kwargs,
        )
        if scores.empty:
            return []
        top = scores.head(top_n)
        # TopN 内权重重新归一化
        total_weight = top["weight"].sum()
        if total_weight > 0:
            top = top.copy()
            top["weight"] = top["weight"] / total_weight
        return [{str(k): v for k, v in row.items()} for row in top.to_dict(orient="records")]

    async def load_alpha_series(
        self,
        symbol: str,
        start: date,
        end: date,
        factor_id: str = _DEFAULT_COMPOSITE_ALPHA,
    ) -> pd.Series:
        """模式 B：单标的合成 Alpha 时序（供表达式规则 / 研究）。

        Args:
            symbol: 标的代码
            start: 起始日期
            end: 结束日期
            factor_id: 合成因子 ID，默认 composite_alpha

        Returns:
            pd.Series, index=trade_date, name=factor_id
        """
        panel = await self._panel_service.load_time_series_panel(
            [factor_id], symbol, start, end, pool_id="all",
        )
        if panel.empty or factor_id not in panel.columns:
            return pd.Series(dtype=float, name=factor_id)
        return panel[factor_id]

    async def _score_by_composite_alpha(
        self,
        signal_date: date,
        pool_id: str,
        symbols: list[str],
    ) -> pd.Series | None:
        """模式 composite_alpha：直接使用 composite_alpha 因子值作为得分。

        composite_alpha 已在 Task2 中完成 ICIR 加权合成 + Z-score，
        截面消费时仅需加载 + 标准化（FactorPanelService 处理）。
        """
        panel = await self._panel_service.load_cross_section_panel(
            [_DEFAULT_COMPOSITE_ALPHA], symbols, signal_date, pool_id,
        )
        if panel.empty or _DEFAULT_COMPOSITE_ALPHA not in panel.columns:
            return None
        # 取 signal_date 截面，按 symbol 展开
        return panel[_DEFAULT_COMPOSITE_ALPHA].droplevel("trade_date")

    async def _score_by_icir_weighted(
        self,
        signal_date: date,
        pool_id: str,
        symbols: list[str],
        factor_ids: list[str] | None,
    ) -> pd.Series | None:
        """模式 icir_weighted：按 A/B 因子 ICIR 加权求和。

        步骤（§18.4.2 模式 A）：
          1. FactorPanelService.load_cross_section_panel — 截面标准化 + 中性化
          2. 读取 fac_factor_stats 最新 ICIR 权重（或等权）
          3. 加权求和 → score
        """
        # 解析候选因子：显式指定 或 A/B 级 dense 因子
        candidates = factor_ids if factor_ids else await self._resolve_ab_factors(pool_id)
        if not candidates:
            logger.warning(
                "[alpha_signal] pool=%s 无 A/B 级 dense 因子候选", pool_id,
            )
            return None

        # 加载截面面板（FactorPanelService 按 preprocess_policy 自动标准化）
        panel = await self._panel_service.load_cross_section_panel(
            candidates, symbols, signal_date, pool_id,
        )
        if panel.empty:
            return None

        # 读取 ICIR 权重
        weights = await self._load_icir_weights(candidates, pool_id)
        if not weights:
            # 无 ICIR 历史时退化为等权
            logger.info(
                "[alpha_signal] pool=%s 无 ICIR 权重,退化为等权", pool_id,
            )
            weights = {fid: 1.0 for fid in candidates}

        # 加权求和: score_i = Σ w_k × z(f_k,i)
        available = [fid for fid in candidates if fid in panel.columns]
        if not available:
            return None
        weight_series = pd.Series([weights.get(fid, 0.0) for fid in available])
        weight_sum = weight_series.abs().sum()
        if weight_sum == 0:
            return None
        normalized_weights = weight_series / weight_sum
        score = panel[available].multiply(normalized_weights.values, axis=1).sum(axis=1)

        # 取 signal_date 截面
        return score.droplevel("trade_date")

    @staticmethod
    async def _resolve_ab_factors(pool_id: str) -> list[str]:
        """解析 A/B 级 dense 因子候选（§18.3.2 合成 eligibility）。"""
        rows = await FacFactorRegistry.filter(
            status="active",
            is_composite=0,
            factor_grade__in=["A", "B"],
        )
        # 过滤 density=dense（§18.3.2 _SYNTH_CANDIDATE 条件）
        return [r.factor_id for r in rows if r.density == "dense"]

    @staticmethod
    async def _load_icir_weights(
        factor_ids: list[str], pool_id: str,
    ) -> dict[str, float]:
        """从 fac_factor_stats 加载最新 ICIR 权重。

        取每个因子在 pool_id 下的最新评估记录的 icir 绝对值作为权重。
        """
        weights: dict[str, float] = {}
        for fid in factor_ids:
            stats_rows = await FacFactorStats.filter(
                factor_id=fid,
                pool_id=pool_id,
                order_by=FacFactorStats.calc_date.desc(),
                limit=1,
            )
            if stats_rows and stats_rows[0].icir is not None:
                icir = stats_rows[0].icir
                if np.isfinite(icir):
                    weights[fid] = abs(icir)
        return weights
