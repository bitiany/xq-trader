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
    """价值因子组 — EP/BP/DP/SP 等权合成。"""

    factor_id: str = "composite_value"
    display_name: str = "价值合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = "价值因子组内等权合成（EP/BP/DP/EV_EBITDA/SP）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    composite_method: str = "equal_weight"

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
    composite_method: str = "equal_weight"

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
        "（hist_vol/atr_ratio/natr_14/dastd/cmra/vol_osc/downside_vol/amihud/adv_20）"
    )
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    composite_method: str = "equal_weight"

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
    composite_method: str = "equal_weight"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_liquidity 由 factor_synthesize_weekly 任务合成")


class CompositeTechnicalFactor(FactorPlugin):
    """技术因子组 — 超买超卖/趋势/形态因子等权合成。"""

    factor_id: str = "composite_technical"
    display_name: str = "技术合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = "技术因子组内等权合成（RSI/KDJ/MACD/ADX/BOLL/MA_BIAS/Alpha158/Alpha101/缠论/K线形态）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"
    composite_method: str = "equal_weight"

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
    composite_method: str = "equal_weight"

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
    composite_method: str = "icir_weight"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_alpha 由 factor_synthesize_weekly 任务合成")
