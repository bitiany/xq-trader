"""多因子共振 SPI 插件 — 业界成熟的多维度共振确认策略

基于 AQR 多因子模型 + 华泰金工因子轮动框架:
- 动量维度: mom_20d + hist_vol_20 (动量为正 + 低波)
- 价值维度: ep (盈利率 > 4%)
- 资金流维度: cs_main_net_pct (主力净流入为正)
- 技术面维度: rsi_14 + boll_position (RSI未超买 + 布林中轨以下)

共振逻辑:
1. 各维度独立打分 [0, 1]
2. 维度间加权共振: resonance_score = Σ(w_dim × score_dim)
3. 共振强度: 参与共振的维度越多，confidence 越高
4. 至少 3 个维度共振才入选
"""

from __future__ import annotations

import pandas as pd

from framework.commons.logger import get_logger

from ..base import RuleContext, RulePlugin, RuleResult

logger = get_logger(__name__)


class MultiFactorResonancePlugin(RulePlugin):
    """多因子共振 SPI 插件"""

    rule_id = "cs_multi_factor_resonance"
    name = "多因子共振"
    category = "cross_section"
    factor_ids = [
        "mom_20d", "hist_vol_20",
        "ep",
        "cs_main_net_pct",
        "rsi_14", "boll_position",
    ]

    # 维度权重
    DIMENSION_WEIGHTS: dict[str, float] = {
        "momentum": 0.30,
        "value": 0.25,
        "fund_flow": 0.25,
        "technical": 0.20,
    }

    # 最低共振维度数
    MIN_RESONANCE_DIMS = 3

    async def evaluate(self, context: RuleContext) -> RuleResult:
        """执行多因子共振评估"""
        config = {**{"min_resonance_dims": self.MIN_RESONANCE_DIMS}, **context.config}
        min_dims = config["min_resonance_dims"]

        # 截面模式
        if context.cross_section_df is not None:
            return self._evaluate_cross_section(context, min_dims)

        # 时序模式（单标的）
        return self._evaluate_single(context, min_dims)

    def _evaluate_cross_section(self, context: RuleContext, min_dims: int) -> RuleResult:
        """截面模式：对全市场 DataFrame 做维度打分"""
        df = context.cross_section_df
        if df is None or df.empty:
            return RuleResult(rule_id=self.rule_id, passed=False)

        dim_scores: dict[str, pd.Series] = {}

        # 动量维度
        dim_scores["momentum"] = self._score_momentum(df)

        # 价值维度
        dim_scores["value"] = self._score_value(df)

        # 资金流维度
        dim_scores["fund_flow"] = self._score_fund_flow(df)

        # 技术面维度
        dim_scores["technical"] = self._score_technical(df)

        # 加权共振得分
        resonance_score = pd.Series(0.0, index=df.index)
        for dim_name, weight in self.DIMENSION_WEIGHTS.items():
            if dim_name in dim_scores:
                resonance_score += weight * dim_scores[dim_name].fillna(0.0)

        # 共振维度计数
        dim_passed = pd.Series(0, index=df.index)
        for dim_name, scores in dim_scores.items():
            dim_passed += (scores > 0.3).astype(int)

        # 至少 min_dims 个维度共振
        passed_series = dim_passed >= min_dims
        confidence = resonance_score.clip(0.0, 1.0)

        # 当前标的
        symbol = context.symbol
        if symbol in passed_series.index:
            p = bool(passed_series.loc[symbol])
            s = float(resonance_score.loc[symbol]) if symbol in resonance_score.index else 0.0
            c = float(confidence.loc[symbol]) if symbol in confidence.index else 0.0
            return RuleResult(
                rule_id=self.rule_id,
                passed=p,
                score=s,
                direction="long" if p else "neutral",
                confidence=c,
                detail={
                    "dim_scores": {
                        k: float(v.loc[symbol]) if symbol in v.index else 0.0
                        for k, v in dim_scores.items()
                    },
                    "dim_passed": int(dim_passed.loc[symbol]) if symbol in dim_passed.index else 0,
                },
            )

        return RuleResult(rule_id=self.rule_id, passed=False)

    def _evaluate_single(self, context: RuleContext, min_dims: int) -> RuleResult:
        """时序模式：单标的评估"""
        fv = context.factor_values
        dim_scores: dict[str, float] = {}
        dim_passed_count = 0

        # 动量维度
        mom = fv.get("mom_20d", 0.0)
        vol = fv.get("hist_vol_20", 1.0)
        mom_score = 0.0
        if mom > 0:
            mom_score += 0.5
        if vol < 0.35:
            mom_score += 0.5
        dim_scores["momentum"] = mom_score
        if mom_score > 0.3:
            dim_passed_count += 1

        # 价值维度
        ep = fv.get("ep", 0.0)
        val_score = 1.0 if ep > 0.04 else 0.0
        dim_scores["value"] = val_score
        if val_score > 0.3:
            dim_passed_count += 1

        # 资金流维度
        fund_flow = fv.get("cs_main_net_pct", 0.0)
        ff_score = 1.0 if fund_flow > 0 else 0.0
        dim_scores["fund_flow"] = ff_score
        if ff_score > 0.3:
            dim_passed_count += 1

        # 技术面维度
        rsi = fv.get("rsi_14", 50.0)
        boll = fv.get("boll_position", 0.5)
        tech_score = 0.0
        if rsi < 70:
            tech_score += 0.5
        if boll < 0.8:
            tech_score += 0.5
        dim_scores["technical"] = tech_score
        if tech_score > 0.3:
            dim_passed_count += 1

        # 加权共振
        resonance_score = sum(
            self.DIMENSION_WEIGHTS.get(dim, 0) * score
            for dim, score in dim_scores.items()
        )
        passed = dim_passed_count >= min_dims

        return RuleResult(
            rule_id=self.rule_id,
            passed=passed,
            score=resonance_score,
            direction="long" if passed else "neutral",
            confidence=resonance_score if passed else 0.0,
            detail={
                "dim_scores": dim_scores,
                "dim_passed": dim_passed_count,
                "min_dims": min_dims,
            },
        )

    # ==================== 截面维度打分 ====================

    def _score_momentum(self, df: pd.DataFrame) -> pd.Series:
        """动量维度打分: mom_20d > 0 + hist_vol_20 < 0.35"""
        score = pd.Series(0.0, index=df.index)
        if "mom_20d" in df.columns:
            score += (df["mom_20d"] > 0).astype(float) * 0.5
        if "hist_vol_20" in df.columns:
            score += (df["hist_vol_20"] < 0.35).astype(float) * 0.5
        return score

    def _score_value(self, df: pd.DataFrame) -> pd.Series:
        """价值维度打分: ep > 0.04"""
        if "ep" not in df.columns:
            return pd.Series(0.0, index=df.index)
        return (df["ep"] > 0.04).astype(float)

    def _score_fund_flow(self, df: pd.DataFrame) -> pd.Series:
        """资金流维度打分: cs_main_net_pct > 0"""
        if "cs_main_net_pct" not in df.columns:
            return pd.Series(0.0, index=df.index)
        return (df["cs_main_net_pct"] > 0).astype(float)

    def _score_technical(self, df: pd.DataFrame) -> pd.Series:
        """技术面维度打分: rsi_14 < 70 + boll_position < 0.8"""
        score = pd.Series(0.0, index=df.index)
        if "rsi_14" in df.columns:
            score += (df["rsi_14"] < 70).astype(float) * 0.5
        if "boll_position" in df.columns:
            score += (df["boll_position"] < 0.8).astype(float) * 0.5
        return score
