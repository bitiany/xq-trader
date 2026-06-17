"""多因子共振 SPI 插件 — 业界成熟的多维度共振确认策略

基于 AQR 多因子模型 + 华泰金工因子轮动框架:
- 趋势门槛: mom_20d 与 barra_momentum 必须为正，避免下跌中继
- 动量维度: mom_20d + barra_momentum + hist_vol_20 (动量强势 + 低波)
- 价值维度: ep (盈利率 > 4%)
- 资金流维度: cs_main_net_pct (主力净流入显著为正)
- 技术面维度: rsi_14 + boll_position (不过热且处于可持续区间)

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
        "mom_20d", "barra_momentum", "hist_vol_20",
        "ep",
        "cs_main_net_pct",
        "rsi_14", "boll_position",
    ]

    # 默认维度权重
    DIMENSION_WEIGHTS: dict[str, float] = {
        "momentum": 0.40,
        "value": 0.20,
        "fund_flow": 0.25,
        "technical": 0.15,
    }

    MOMENTUM_THRESHOLD = 0.05
    BARRA_MOMENTUM_THRESHOLD = 0.0
    LOW_VOL_THRESHOLD = 0.45
    MAX_VOL_THRESHOLD = 0.90
    FUND_FLOW_THRESHOLD = 0.5

    # 最低共振维度数
    MIN_RESONANCE_DIMS = 3

    async def evaluate(self, context: RuleContext) -> RuleResult:
        """执行多因子共振评估"""
        config = {
            "min_resonance_dims": self.MIN_RESONANCE_DIMS,
            "dimension_weights": self.DIMENSION_WEIGHTS,
            "momentum_threshold": self.MOMENTUM_THRESHOLD,
            "barra_momentum_threshold": self.BARRA_MOMENTUM_THRESHOLD,
            "low_vol_threshold": self.LOW_VOL_THRESHOLD,
            "max_vol_threshold": self.MAX_VOL_THRESHOLD,
            "fund_flow_threshold": self.FUND_FLOW_THRESHOLD,
            **context.config,
        }
        min_dims = int(config["min_resonance_dims"])
        dimension_weights = dict(config["dimension_weights"])
        momentum_threshold = float(config["momentum_threshold"])
        barra_momentum_threshold = float(config["barra_momentum_threshold"])
        low_vol_threshold = float(config["low_vol_threshold"])
        max_vol_threshold = float(config["max_vol_threshold"])
        fund_flow_threshold = float(config["fund_flow_threshold"])

        # 截面模式
        if context.cross_section_df is not None:
            return self._evaluate_cross_section(
                context,
                min_dims,
                dimension_weights,
                momentum_threshold,
                barra_momentum_threshold,
                low_vol_threshold,
                max_vol_threshold,
                fund_flow_threshold,
            )

        # 时序模式（单标的）
        return self._evaluate_single(
            context,
            min_dims,
            dimension_weights,
            momentum_threshold,
            barra_momentum_threshold,
            low_vol_threshold,
            max_vol_threshold,
            fund_flow_threshold,
        )

    def _evaluate_cross_section(
        self,
        context: RuleContext,
        min_dims: int,
        dimension_weights: dict[str, float],
        momentum_threshold: float,
        barra_momentum_threshold: float,
        low_vol_threshold: float,
        max_vol_threshold: float,
        fund_flow_threshold: float,
    ) -> RuleResult:
        """截面模式：对全市场 DataFrame 做维度打分"""
        df = context.cross_section_df
        if df is None or df.empty:
            return RuleResult(rule_id=self.rule_id, passed=False)

        dim_scores: dict[str, pd.Series] = {}

        trend_mask = self._trend_mask(
            df, momentum_threshold, barra_momentum_threshold, max_vol_threshold,
        )

        # 动量维度
        dim_scores["momentum"] = self._score_momentum(
            df, momentum_threshold, barra_momentum_threshold, low_vol_threshold,
        )

        # 价值维度
        dim_scores["value"] = self._score_value(df)

        # 资金流维度
        dim_scores["fund_flow"] = self._score_fund_flow(df, fund_flow_threshold)

        # 技术面维度
        dim_scores["technical"] = self._score_technical(df)

        # 加权共振得分
        resonance_score = pd.Series(0.0, index=df.index)
        for dim_name, weight in dimension_weights.items():
            if dim_name in dim_scores:
                resonance_score += weight * dim_scores[dim_name].fillna(0.0)

        # 共振维度计数
        dim_passed = pd.Series(0, index=df.index)
        for dim_name, scores in dim_scores.items():
            dim_passed += (scores > 0.3).astype(int)

        # 趋势门槛必须通过，避免低估值/低波动股票在下跌中继阶段入选
        passed_series = (dim_passed >= min_dims) & trend_mask
        confidence = resonance_score.where(trend_mask, 0.0).clip(0.0, 1.0)

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

    def _evaluate_single(
        self,
        context: RuleContext,
        min_dims: int,
        dimension_weights: dict[str, float],
        momentum_threshold: float,
        barra_momentum_threshold: float,
        low_vol_threshold: float,
        max_vol_threshold: float,
        fund_flow_threshold: float,
    ) -> RuleResult:
        """时序模式：单标的评估"""
        fv = context.factor_values
        dim_scores: dict[str, float] = {}
        dim_passed_count = 0

        # 动量维度
        mom = fv.get("mom_20d", 0.0)
        barra_mom = fv.get("barra_momentum", 0.0)
        vol = fv.get("hist_vol_20", 1.0)
        trend_passed = (
            mom > momentum_threshold
            and barra_mom > barra_momentum_threshold
            and vol <= max_vol_threshold
        )
        mom_score = 0.0
        if mom > momentum_threshold:
            mom_score += 0.5
        if barra_mom > barra_momentum_threshold:
            mom_score += 0.3
        if vol < low_vol_threshold:
            mom_score += 0.2
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
        ff_score = 1.0 if fund_flow > fund_flow_threshold else 0.0
        dim_scores["fund_flow"] = ff_score
        if ff_score > 0.3:
            dim_passed_count += 1

        # 技术面维度
        rsi = fv.get("rsi_14", 50.0)
        boll = fv.get("boll_position", 0.5)
        tech_score = 0.0
        if 45 <= rsi < 75:
            tech_score += 0.5
        if 0.2 <= boll < 1.0:
            tech_score += 0.5
        dim_scores["technical"] = tech_score
        if tech_score > 0.3:
            dim_passed_count += 1

        # 加权共振
        resonance_score = sum(
            dimension_weights.get(dim, 0) * score
            for dim, score in dim_scores.items()
        )
        passed = trend_passed and dim_passed_count >= min_dims

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

    def _trend_mask(
        self,
        df: pd.DataFrame,
        momentum_threshold: float,
        barra_momentum_threshold: float,
        max_vol_threshold: float,
    ) -> pd.Series:
        """多头趋势硬门槛。"""
        required_columns = {"mom_20d", "barra_momentum", "hist_vol_20"}
        if not required_columns.issubset(df.columns):
            return pd.Series(False, index=df.index)
        return (
            (df["mom_20d"] > momentum_threshold)
            & (df["barra_momentum"] > barra_momentum_threshold)
            & (df["hist_vol_20"] <= max_vol_threshold)
        )

    def _score_momentum(
        self,
        df: pd.DataFrame,
        momentum_threshold: float,
        barra_momentum_threshold: float,
        low_vol_threshold: float,
    ) -> pd.Series:
        """动量维度打分: 中短期动量达阈值 + 低波。"""
        score = pd.Series(0.0, index=df.index)
        if "mom_20d" in df.columns:
            score += (df["mom_20d"] > momentum_threshold).astype(float) * 0.5
        if "barra_momentum" in df.columns:
            score += (df["barra_momentum"] > barra_momentum_threshold).astype(float) * 0.3
        if "hist_vol_20" in df.columns:
            score += (df["hist_vol_20"] < low_vol_threshold).astype(float) * 0.2
        return score

    def _score_value(self, df: pd.DataFrame) -> pd.Series:
        """价值维度打分: ep > 0.04"""
        if "ep" not in df.columns:
            return pd.Series(0.0, index=df.index)
        return (df["ep"] > 0.04).astype(float)

    def _score_fund_flow(self, df: pd.DataFrame, fund_flow_threshold: float) -> pd.Series:
        """资金流维度打分: 主力净流入显著为正。"""
        if "cs_main_net_pct" not in df.columns:
            return pd.Series(0.0, index=df.index)
        return (df["cs_main_net_pct"] > fund_flow_threshold).astype(float)

    def _score_technical(self, df: pd.DataFrame) -> pd.Series:
        """技术面维度打分: 不追极弱，也不追过热。"""
        score = pd.Series(0.0, index=df.index)
        if "rsi_14" in df.columns:
            score += ((df["rsi_14"] >= 45) & (df["rsi_14"] < 75)).astype(float) * 0.5
        if "boll_position" in df.columns:
            score += ((df["boll_position"] >= 0.2) & (df["boll_position"] < 1.0)).astype(float) * 0.5
        return score
