"""Alpha 合成因子定义 — 声明式注册，由 factor_synthesize 任务产出。

这些因子不参与 factor_compute 管线的逐标的计算，
而是由 factor_synthesize_weekly 任务按样本池截面合成后写入 fac_factor_value。

合成架构：两阶段分层合成
  第一层：组内等权合成（value/momentum/volatility/liquidity/technical/fund_flow）
          → 独立落库为 alpha_value / alpha_momentum / ... 因子
  第二层：跨组加权合成 → 最终 alpha 因子
"""

from __future__ import annotations

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin  # noqa: E402

# ── 第一层：组内合成因子 ──


class AlphaValueFactor(FactorPlugin):
    """价值因子组 — EP/BP/DP/SP 等权合成。"""

    factor_id: str = "alpha_value"
    display_name: str = "价值Alpha"
    category: str = "alpha_group"
    direction: str = "DESC"
    description: str = "价值因子组内等权合成（EP/BP/DP/SP等）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("alpha_value 由 factor_synthesize_weekly 任务合成")


class AlphaMomentumFactor(FactorPlugin):
    """动量因子组 — 动量/反转因子等权合成。"""

    factor_id: str = "alpha_momentum"
    display_name: str = "动量Alpha"
    category: str = "alpha_group"
    direction: str = "DESC"
    description: str = "动量/反转因子组内等权合成（mom_5d/mom_20d/mom_60d/barra_momentum/barra_strev等）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("alpha_momentum 由 factor_synthesize_weekly 任务合成")


class AlphaVolatilityFactor(FactorPlugin):
    """波动率因子组 — 波动率/风险因子等权合成。"""

    factor_id: str = "alpha_volatility"
    display_name: str = "波动率Alpha"
    category: str = "alpha_group"
    direction: str = "DESC"
    description: str = "波动率因子组内等权合成（hist_vol/atr_ratio/natr_14/dastd/cmra等）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("alpha_volatility 由 factor_synthesize_weekly 任务合成")


class AlphaLiquidityFactor(FactorPlugin):
    """流动性因子组 — 换手率/成交额因子等权合成。"""

    factor_id: str = "alpha_liquidity"
    display_name: str = "流动性Alpha"
    category: str = "alpha_group"
    direction: str = "DESC"
    description: str = "流动性因子组内等权合成（cs_turnover/turnover_f/cs_log_amount等）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("alpha_liquidity 由 factor_synthesize_weekly 任务合成")


class AlphaTechnicalFactor(FactorPlugin):
    """技术因子组 — 超买超卖/趋势/形态因子等权合成。"""

    factor_id: str = "alpha_technical"
    display_name: str = "技术Alpha"
    category: str = "alpha_group"
    direction: str = "DESC"
    description: str = "技术因子组内等权合成（RSI/KDJ/MACD/ADX/BOLL/Alpha158/Alpha101/缠论/K线形态等）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("alpha_technical 由 factor_synthesize_weekly 任务合成")


class AlphaFundFlowFactor(FactorPlugin):
    """资金流因子组 — 主力/大单/超大单资金流因子等权合成。"""

    factor_id: str = "alpha_fund_flow"
    display_name: str = "资金流Alpha"
    category: str = "alpha_group"
    direction: str = "DESC"
    description: str = "资金流因子组内等权合成（cs_main_net_pct/huge_net_pct/big_net_pct等）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("alpha_fund_flow 由 factor_synthesize_weekly 任务合成")


# ── 第二层：跨组合成因子 ──


class AlphaFactor(FactorPlugin):
    """最终 Alpha — 组内 Alpha 跨组加权合成。

    加权方式：滚动 IC/ICIR 加权，无足够 IC 历史时退化为等权。
    IC/ICIR 是内部加权手段，不体现在因子名称中。
    """

    factor_id: str = "alpha"
    display_name: str = "综合Alpha"
    category: str = "alpha_composite"
    direction: str = "DESC"
    description: str = "跨组加权合成最终Alpha（组内Alpha的滚动IC/ICIR加权，退化为等权）"
    update_freq: str = "weekly"
    compute_engine: str = "synthesize"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("alpha 由 factor_synthesize_weekly 任务合成")
