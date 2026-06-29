"""合成因子定义 — 声明式注册，由 factor_synthesize 任务产出。

这些因子不参与 factor_compute 管线的逐标的计算，
而是由 factor_synthesize_weekly 任务按样本池截面合成后写入 fac_factor_value。

合成架构：两阶段分层合成
  第一层：组内等权合成（value/momentum/volatility/liquidity/technical/fund_flow）
          → 独立落库为 composite_value / composite_momentum / ... 因子
  第二层：跨组 ICIR 加权合成 → 最终 composite_alpha 因子
"""

from __future__ import annotations

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin  # noqa: E402

# ── 第一层：组内合成因子 ──


class CompositeValueFactor(FactorPlugin):
    """价值因子组 — EP/BP/DP/EV_EBITDA/SP 等权合成。"""

    factor_id: str = "composite_value"
    display_name: str = "价值合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = "价值因子组内等权合成（EP/BP/DP/EV_EBITDA/SP）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = ["ep", "bp", "dp", "ev_ebitda", "sp"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_value 由 factor_synthesize_weekly 任务合成")


class CompositeMomentumFactor(FactorPlugin):
    """动量因子组 — 动量/反转因子等权合成。"""

    factor_id: str = "composite_momentum"
    display_name: str = "动量合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = (
        "动量/反转因子组内等权合成"
        "（mom_5d/mom_20d/mom_60d/barra_momentum/barra_strev/roc_10/cs_pct_chg）"
    )
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        "mom_5d", "mom_20d", "mom_60d",
        "barra_momentum", "barra_strev",
        "roc_10", "cs_pct_chg",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_momentum 由 factor_synthesize_weekly 任务合成")


class CompositeVolatilityFactor(FactorPlugin):
    """波动率因子组 — 波动率/风险因子等权合成。"""

    factor_id: str = "composite_volatility"
    display_name: str = "波动率合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = (
        "波动率因子组内等权合成"
        "（hist_vol_10/20/60, atr_ratio, natr_14, dastd, cmra, vol_osc, downside_vol, amihud, adv_20）"
    )
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        "hist_vol_10", "hist_vol_20", "hist_vol_60",
        "atr_ratio", "natr_14",
        "dastd", "cmra",
        "vol_osc", "downside_vol", "amihud", "adv_20",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_volatility 由 factor_synthesize_weekly 任务合成")


class CompositeLiquidityFactor(FactorPlugin):
    """流动性因子组 — 换手率/成交额因子等权合成。"""

    factor_id: str = "composite_liquidity"
    display_name: str = "流动性合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = "流动性因子组内等权合成（cs_turnover/turnover_f/cs_log_amount/cs_volume_ratio/cs_log_mv）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        "cs_turnover", "turnover_f",
        "cs_log_amount", "cs_volume_ratio", "cs_log_mv",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_liquidity 由 factor_synthesize_weekly 任务合成")


class CompositeTechnicalFactor(FactorPlugin):
    """技术因子组 — 超买超卖/趋势/形态因子等权合成。"""

    factor_id: str = "composite_technical"
    display_name: str = "技术合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = "技术因子组内等权合成（RSI/KDJ/MACD/ADX/BOLL/MA_BIAS/Alpha158/Alpha101/K线形态）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        # C3 超买超卖
        "rsi_6", "rsi_14", "rsi_24", "rsi_delta_14",
        "kdj_k", "kdj_d", "kdj_j",
        "bias_6", "bias_12", "bias_24",
        "cci_14", "wr_14",
        # C2 趋势
        "macd_hist_ratio", "macd_hist_delta",
        "adx_14", "adx_plus_di", "adx_minus_di", "adx_delta",
        "boll_position", "boll_position_delta", "boll_width",
        "sar_deviation",
        # C4 均线偏离
        "ma_bias_5", "ma_bias_10", "ma_bias_20", "ma_bias_60", "ma_bias_delta_20",
        # D1 Alpha101
        "alpha_1", "alpha_12", "alpha_33", "alpha_41", "alpha_55", "alpha_101",
        # D2 Alpha158
        "kmid_5", "klen_5", "kup2_5", "klow2_5",
        "rsv_9", "cntp_20", "imax_20",
        "roc5_close", "std20_close", "corr_pv_10",
        # E2 K线形态聚合（E1 缠论非截面连续值，不参与合成）
        "cdl_bull_freq_20", "cdl_bear_freq_20", "cdl_net_score_20",
        "cdl_upper_shadow_ratio", "cdl_lower_shadow_ratio", "cdl_body_ratio",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_technical 由 factor_synthesize_weekly 任务合成")


class CompositeFundFlowFactor(FactorPlugin):
    """资金流因子组 — 主力/大单/超大单资金流因子等权合成。"""

    factor_id: str = "composite_fund_flow"
    display_name: str = "资金流合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = "资金流因子组内等权合成（cs_main_net_pct/cs_net_mf_pct/huge_net_pct/big_net_pct）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        "cs_main_net_pct", "cs_net_mf_pct", "huge_net_pct", "big_net_pct",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_fund_flow 由 factor_synthesize_weekly 任务合成")


# ── 第二层：跨组合成因子 ──


class CompositeAlphaFactor(FactorPlugin):
    """最终合成因子 — 组内合成因子跨组 ICIR 加权合成。

    加权方式：滚动 IC/ICIR 加权，无足够 IC 历史时退化为等权。
    IC/ICIR 是内部加权手段，不体现在因子名称中。
    """

    factor_id: str = "composite_alpha"
    display_name: str = "综合合成因子"
    category: str = "composite_cross"
    direction: str = "DESC"
    description: str = "跨组ICIR加权合成最终因子（组内合成因子的滚动ICIR加权，退化为等权）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "icir_weight"
    composite_factor_ids: list[str] = [
        "composite_value", "composite_momentum", "composite_volatility",
        "composite_liquidity", "composite_technical", "composite_fund_flow",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_alpha 由 factor_synthesize_weekly 任务合成")


# ── D4 交互因子 — 截面 Z-score 后两两相乘 ──


class MomVolCrossFactor(FactorPlugin):
    """动量×波动交互因子 — mom_20d × atr_ratio。

    捕捉动量与波动的非线性交互：高动量+高波动 vs 高动量+低波动的差异。
    两个输入因子均由 CrossSectionReader 截面 Z-score 标准化后相乘。
    """

    factor_id: str = "mom_vol_cross"
    display_name: str = "动量×波动交互"
    category: str = "interaction"
    direction: str = "DESC"
    description: str = "mom_20d × atr_ratio（截面Z-score后相乘）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "interaction"
    composite_factor_ids: list[str] = ["mom_20d", "atr_ratio"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("mom_vol_cross 由 factor_synthesize_weekly 任务交互合成")


class AdxRsiCrossFactor(FactorPlugin):
    """ADX×RSI偏离交互因子 — adx_14 × rsi_14。

    趋势强度（ADX）与超买超卖（RSI）的交互：强趋势+超买 vs 强趋势+超卖。
    两个输入因子均由 CrossSectionReader 截面 Z-score 标准化后相乘。
    """

    factor_id: str = "adx_rsi_cross"
    display_name: str = "ADX×RSI交互"
    category: str = "interaction"
    direction: str = "DESC"
    description: str = "adx_14 × rsi_14（截面Z-score后相乘）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "interaction"
    composite_factor_ids: list[str] = ["adx_14", "rsi_14"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("adx_rsi_cross 由 factor_synthesize_weekly 任务交互合成")


class VolRatioMomCrossFactor(FactorPlugin):
    """量比×动量交互因子 — cs_volume_ratio × mom_20d。

    量价异动交互：高量比+高动量（放量上涨）vs 低量比+高动量（缩量上涨）。
    两个输入因子均由 CrossSectionReader 截面 Z-score 标准化后相乘。
    """

    factor_id: str = "vol_ratio_mom_cross"
    display_name: str = "量比×动量交互"
    category: str = "interaction"
    direction: str = "DESC"
    description: str = "cs_volume_ratio × mom_20d（截面Z-score后相乘）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "interaction"
    composite_factor_ids: list[str] = ["cs_volume_ratio", "mom_20d"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("vol_ratio_mom_cross 由 factor_synthesize_weekly 任务交互合成")


class RsiBbandsCrossFactor(FactorPlugin):
    """RSI×布林位置交互因子 — rsi_14 × boll_position。

    超买超卖与趋势位置的交互：RSI 超买+布林上轨 vs RSI 超买+布林下轨。
    两个输入因子均由 CrossSectionReader 截面 Z-score 标准化后相乘。
    """

    factor_id: str = "rsi_bbands_cross"
    display_name: str = "RSI×布林位置交互"
    category: str = "interaction"
    direction: str = "DESC"
    description: str = "rsi_14 × boll_position（截面Z-score后相乘）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "interaction"
    composite_factor_ids: list[str] = ["rsi_14", "boll_position"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("rsi_bbands_cross 由 factor_synthesize_weekly 任务交互合成")


class MacdAdxCrossFactor(FactorPlugin):
    """MACD×ADX 交互因子 — macd_hist_ratio × adx_14。

    动能（MACD柱）与趋势强度（ADX）的交互：强趋势+正MACD vs 强趋势+负MACD。
    两个输入因子均由 CrossSectionReader 截面 Z-score 标准化后相乘。
    """

    factor_id: str = "macd_adx_cross"
    display_name: str = "MACD×ADX交互"
    category: str = "interaction"
    direction: str = "DESC"
    description: str = "macd_hist_ratio × adx_14（截面Z-score后相乘）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "interaction"
    composite_factor_ids: list[str] = ["macd_hist_ratio", "adx_14"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("macd_adx_cross 由 factor_synthesize_weekly 任务交互合成")


class VolMomAccelCrossFactor(FactorPlugin):
    """波动×动量加速度交互因子 — atr_ratio × macd_hist_delta。

    波动与动量变化的交互：高波动+动量加速 vs 高波动+动量减速。
    两个输入因子均由 CrossSectionReader 截面 Z-score 标准化后相乘。
    """

    factor_id: str = "vol_mom_accel_cross"
    display_name: str = "波动×动量加速度交互"
    category: str = "interaction"
    direction: str = "DESC"
    description: str = "atr_ratio × macd_hist_delta（截面Z-score后相乘）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "interaction"
    composite_factor_ids: list[str] = ["atr_ratio", "macd_hist_delta"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("vol_mom_accel_cross 由 factor_synthesize_weekly 任务交互合成")
