"""A/D 截面因子 — CrossSectionReader 按需加载的截面因子元数据声明。

这些因子不在 Task 1 逐标的计算，而是由 CrossSectionReader 在 Task 2/3 中
按需加载并截面标准化。Plugin 定义仅用于元数据注册，compute() 不参与逐标的计算。

因子清单（参照 docs/factor-catalog.md §4.2）：
  - A 截面风险因子：
    - nl_size: 非线性规模，log_mv 三次方对 Size 正交化取残差
    - stom: 月换手率，log(Σ(21日, V_t/S_t))
    - stoq: 季换手率，log(mean(3月, exp(STOM)))
    - beta_250: 250日 Beta，Cov(ret, mkt_ret)/Var(mkt_ret)，半衰期63日
    - beta_down: 下行 Beta，负收益日 Cov(ret, mkt_ret)/Var(mkt_ret)

数据血缘：
  - nl_size/stom/stoq: 从 daily_indicator 加载 total_mv/turnover_rate，截面计算
  - beta_250/beta_down: CandlestickDaily 个股收益 + IndexDaily 市场收益，滚动回归

设计说明：
  截面 Z-score 标准化是 CrossSectionReader 五步预处理管线的一环（对所有因子统一执行），
  不作为独立因子注册。原 z_main_net_pct / z_turnover 已废弃删除，
  标准化由 CrossSectionReader._zscore_standardize 统一负责。
"""

from __future__ import annotations

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class NlSizeFactor(FactorPlugin):
    """非线性规模因子 — log_mv 三次方对 Size 正交化取残差。

    Barra CNE6 非线性规模因子：先对 log_mv 做 Z-score 标准化得 Size，
    再用 Size³ 对 Size 回归取残差，捕捉规模因子的非线性部分。
    data_origin='cross_section_compute' 由 cross_section_factor_calculator 计算。
    """

    factor_id: str = "nl_size"
    display_name: str = "非线性规模"
    category: str = "risk"
    group_id: str = "nl_size"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["total_mv"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "cross_section_compute"
    update_freq: str = "daily"
    compute_engine: str = "cross_section"
    tags: str = "cross_section,barra"
    description: str = "log_mv 三次方对 Size 正交化取残差（Barra 非线性规模）"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("nl_size 由 CrossSectionReader 截面回归计算")


class StomFactor(FactorPlugin):
    """月换手率因子 — log(Σ(21日, V_t/S_t))。

    Barra CNE6 流动性因子 STOM：21 日累计换手率的 log 值。
    使用 turnover_rate（V_t/S_t × 100）作为输入，21 日求和后取 log。
    data_origin='cross_section_compute' 由 cross_section_factor_calculator 计算。
    """

    factor_id: str = "stom"
    display_name: str = "月换手率"
    category: str = "risk"
    group_id: str = "stom"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["turnover_rate"]
    min_periods: int = 21
    requires_full_history: bool = True
    data_origin: str = "cross_section_compute"
    update_freq: str = "daily"
    compute_engine: str = "cross_section"
    tags: str = "cross_section,barra,liquidity"
    description: str = "log(Σ(21日, V_t/S_t))，Barra 月换手率流动性因子"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("stom 由 CrossSectionReader 截面计算")


class StoqFactor(FactorPlugin):
    """季换手率因子 — log(mean(3月, exp(STOM)))。

    Barra CNE6 流动性因子 STOQ：3 个月（63 日）STOM 均值的 log 值。
    衍生自 STOM，需先计算 stom 再做 63 日滚动平均。
    data_origin='cross_section_compute' 由 cross_section_factor_calculator 计算：
    先计算 stom，再做 63 日滚动均值。
    """

    factor_id: str = "stoq"
    display_name: str = "季换手率"
    category: str = "risk"
    group_id: str = "stoq"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    base_factor: str = "stom"
    dependencies: list[str] = ["turnover_rate"]
    min_periods: int = 63
    requires_full_history: bool = True
    data_origin: str = "cross_section_compute"
    update_freq: str = "daily"
    compute_engine: str = "cross_section"
    tags: str = "cross_section,barra,liquidity"
    description: str = "log(mean(3月, exp(STOM)))，Barra 季换手率流动性因子"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("stoq 由 CrossSectionReader 从 stom 派生计算")


class Beta250Factor(FactorPlugin):
    """250日 Beta 因子 — Cov(ret, mkt_ret)/Var(mkt_ret)，半衰期63日。

    Barra CNE6 Beta 因子：个股收益率对市场收益率回归的 beta 系数，
    使用 250 日滚动窗口，半衰期 63 日的指数加权。
    数据源：CandlestickDaily 个股收益 + IndexDaily 市场收益（沪深300）。
    data_origin='cross_section_beta' 触发专门的 beta 计算逻辑。
    """

    factor_id: str = "beta_250"
    display_name: str = "250日Beta"
    category: str = "risk"
    group_id: str = "beta_250"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 250
    requires_full_history: bool = True
    data_origin: str = "cross_section_beta"
    update_freq: str = "daily"
    compute_engine: str = "cross_section"
    tags: str = "cross_section,barra,beta"
    description: str = "Cov(ret, mkt_ret)/Var(mkt_ret)，250日滚动Beta，半衰期63日"
    params: dict = {"window": 250, "halflife": 63, "index_code": "000300.SH"}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("beta_250 由 CrossSectionReader 滚动回归计算")


class BetaDownFactor(FactorPlugin):
    """下行 Beta 因子 — 负收益日 Cov(ret, mkt_ret)/Var(mkt_ret)。

    Barra CNE6 下行 Beta：仅在市场负收益日计算 beta，
    衡量个股在市场下跌时的敏感度。数据源同 beta_250。
    data_origin='cross_section_beta' 触发专门的 beta 计算逻辑。
    """

    factor_id: str = "beta_down"
    display_name: str = "下行Beta"
    category: str = "risk"
    group_id: str = "beta_down"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 250
    requires_full_history: bool = True
    data_origin: str = "cross_section_beta"
    update_freq: str = "daily"
    compute_engine: str = "cross_section"
    tags: str = "cross_section,barra,beta"
    description: str = "负收益日 Cov(ret, mkt_ret)/Var(mkt_ret)，下行Beta"
    params: dict = {"window": 250, "index_code": "000300.SH", "downside_only": True}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("beta_down 由 CrossSectionReader 滚动回归计算")
