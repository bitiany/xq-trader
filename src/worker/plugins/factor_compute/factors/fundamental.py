"""B1 价值因子 — 估值指标。

数据来源：
  - ep/bp/dp/sp/pe_ttm/ps_ttm: sdc_daily_indicator（pe_ttm/pb/dv_ttm/ps_ttm）
  - ev_ebitda: total_mv（sdc_daily_indicator）+ ebitda（sdc_financial_indicator
    季频原始值，前向填充由 CrossSectionReader 完成）
  - cfp: ocf_to_or（sdc_financial_indicator 季频原始值）
    + revenue（sdc_income_statement 季频原始值）+ total_mv（sdc_daily_indicator）

注意：B1 因子由 CrossSectionReader 从 sdc_daily_indicator 直接加载，
不通过 FactorComputeTask 逐标的计算。ev_ebitda 和 cfp 为混合频率因子，
需在 CrossSectionReader 中合并日频+季频数据计算。
当前 FactorPlugin 定义仅用于元数据注册，compute() 实现供 CrossSectionReader 调用。

参照 Barra 风格因子体系与业界成熟框架：
  - ep: 盈利收益率(EP) = 1/PE_TTM，截面可比，价值因子核心
  - bp: 账面市值比(BP) = 1/PB，截面可比，价值因子核心
  - dp: 股息率(DP) = dv_ttm/100，截面可比，价值因子辅助
  - ev_ebitda: 企业价值倍数倒数 = EBITDA/total_mv，截面可比，价值因子补充
  - sp: 市销率倒数(SP) = 1/PS_TTM，截面可比，成长-价值复合

因子ID：
  - ep: 盈利收益率
  - bp: 账面市值比
  - dp: 股息率
  - ev_ebitda: 企业价值倍数
  - sp: 市销率倒数
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class EarningsYieldFactor(FactorPlugin):
    """盈利收益率因子(EP) — 1/PE_TTM，截面可比。

    EP 是 Barra 价值因子的核心指标，PE_TTM 为正时取倒数，
    PE_TTM 为负（亏损）时设为 NaN，避免失真。
    """

    factor_id: str = "ep"
    display_name: str = "盈利收益率"
    category: str = "fundamental"
    group_id: str = "ep"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["pe_ttm"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "daily_indicator"
    update_freq: str = "daily_derived"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        pe_ttm = df["pe_ttm"].astype(float)
        # PE > 0 时 EP = 1/PE；PE <= 0（亏损）设为 NaN
        ep = np.where(pe_ttm > 0, 1.0 / pe_ttm, np.nan)
        return pd.DataFrame({self.factor_id: ep}, index=df.index)


class BookToPriceFactor(FactorPlugin):
    """账面市值比因子(BP) — 1/PB，截面可比。

    BP 是 Fama-French HML 因子的核心，PB > 0 时取倒数，
    PB <= 0 时设为 NaN。
    """

    factor_id: str = "bp"
    display_name: str = "账面市值比"
    category: str = "fundamental"
    group_id: str = "bp"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["pb"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "daily_indicator"
    update_freq: str = "daily_derived"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        pb = df["pb"].astype(float)
        bp = np.where(pb > 0, 1.0 / pb, np.nan)
        return pd.DataFrame({self.factor_id: bp}, index=df.index)


class DividendYieldFactor(FactorPlugin):
    """股息率因子(DP) — dv_ttm/100，截面可比。

    股息率是价值因子的辅助指标，高股息率通常伴随低估值。
    dv_ttm 单位为%，需除以 100 转为比率。
    """

    factor_id: str = "dp"
    display_name: str = "股息率"
    category: str = "fundamental"
    group_id: str = "dp"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["dv_ttm"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "daily_indicator"
    update_freq: str = "daily_derived"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        dv_ttm = df["dv_ttm"].astype(float)
        dp = dv_ttm / 100.0
        return pd.DataFrame({self.factor_id: dp}, index=df.index)


class EvEbitdaFactor(FactorPlugin):
    """企业价值倍数因子 — EBITDA/total_mv，截面可比。

    Tushare daily_basic 不返回 ev_ebitda 字段，因此自行计算：
    ev_ebitda = EBITDA(万元) / total_mv(万元)
    注：fina_indicator 的 ebitda 单位为元，需除以 10000 转为万元。
    方向 ASC：EBITDA/total_mv 越小越"贵"（高估值），排名越靠前。
    """

    factor_id: str = "ev_ebitda"
    display_name: str = "企业价值倍数"
    category: str = "fundamental"
    group_id: str = "ev_ebitda"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["total_mv", "ebitda"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "daily_indicator,fina_indicator"
    update_freq: str = "daily_derived"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        # ev_ebitda 是混合频率因子，需在 CrossSectionReader 中合并日频+季频数据计算
        # 此处需 total_mv（日频）和 ebitda（季频），缺少任一字段时返回空
        if "total_mv" not in df.columns or "ebitda" not in df.columns:
            return pd.DataFrame({self.factor_id: np.nan}, index=df.index)
        total_mv = df["total_mv"].astype(float)  # 万元
        ebitda = df["ebitda"].astype(float) / 10000.0  # 元 → 万元
        # EBITDA/total_mv：正值有效，排除零值和负值
        ratio = np.where(
            (ebitda > 0) & (total_mv > 0),
            ebitda / total_mv,
            np.nan,
        )
        return pd.DataFrame({self.factor_id: ratio}, index=df.index)


class SalesToPriceFactor(FactorPlugin):
    """市销率倒数因子(SP) — 1/PS_TTM，截面可比。

    SP 兼具价值和成长属性，PS_TTM > 0 时取倒数。
    适用于盈利不稳定但营收稳定的公司。
    """

    factor_id: str = "sp"
    display_name: str = "市销率倒数"
    category: str = "fundamental"
    group_id: str = "sp"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ps_ttm"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "daily_indicator"
    update_freq: str = "daily_derived"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        ps_ttm = df["ps_ttm"].astype(float)
        sp = np.where(ps_ttm > 0, 1.0 / ps_ttm, np.nan)
        return pd.DataFrame({self.factor_id: sp}, index=df.index)


class PeTtmFactor(FactorPlugin):
    """市盈率TTM因子 — 直接取 pe_ttm，截面可比。

    方向 ASC：PE 越低越"便宜"（低估值），排名越靠前。
    """

    factor_id: str = "pe_ttm"
    display_name: str = "市盈率TTM"
    category: str = "fundamental"
    group_id: str = "pe_ttm"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["pe_ttm"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "daily_indicator"
    update_freq: str = "daily_derived"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df["pe_ttm"].astype(float)}, index=df.index)


class PsTtmFactor(FactorPlugin):
    """市销率TTM因子 — 直接取 ps_ttm，截面可比。

    方向 ASC：PS 越低越"便宜"（低估值），排名越靠前。
    """

    factor_id: str = "ps_ttm"
    display_name: str = "市销率TTM"
    category: str = "fundamental"
    group_id: str = "ps_ttm"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ps_ttm"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "daily_indicator"
    update_freq: str = "daily_derived"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df["ps_ttm"].astype(float)}, index=df.index)


class CashFlowPriceFactor(FactorPlugin):
    """现金收益率因子(CFP) — 经营现金流/总市值，截面可比。

    CFP = ocf_to_or * revenue / total_mv。
    ocf_to_or（经营现金流/营收比率）* revenue = 经营现金流，
    再除以 total_mv 得到现金收益率。高 CFP 意味着低估值。

    混合频率因子：ocf_to_or/revenue 为季频，total_mv 为日频，
    需在 CrossSectionReader 中合并日频+季频数据计算。
    """

    factor_id: str = "cfp"
    display_name: str = "现金收益率"
    category: str = "fundamental"
    group_id: str = "cfp"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ocf_to_or", "revenue", "total_mv"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "daily_indicator,fina_indicator"
    update_freq: str = "daily_derived"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        # cfp 是混合频率因子，需在 CrossSectionReader 中合并日频+季频数据计算
        # 此处需 ocf_to_or/revenue（季频）和 total_mv（日频），缺少任一字段时返回空
        required = {"ocf_to_or", "revenue", "total_mv"}
        if not required.issubset(df.columns):
            return pd.DataFrame({self.factor_id: np.nan}, index=df.index)
        ocf_to_or = df["ocf_to_or"].astype(float)
        revenue = df["revenue"].astype(float)
        total_mv = df["total_mv"].astype(float)
        # CFP = 经营现金流/总市值 = (经营现金流/营收) * 营收 / 总市值
        ocf = ocf_to_or * revenue
        cfp = np.where(
            np.isfinite(ocf) & (total_mv > 0),
            ocf / total_mv,
            np.nan,
        )
        return pd.DataFrame({self.factor_id: cfp}, index=df.index)
