"""因子预处理服务 — 去极值/标准化/行业中性化。

三步流水线:
    1. MAD 去极值 — 截断超出 N 倍 MAD 的值
    2. Z-score 标准化 — (x - mean) / std
    3. 行业中性化 — 每个行业内单独 Z-score

参考: CASE-C preprocessor.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger

logger = get_logger(__name__)

# MAD → std 换算系数（高斯分布）
_MAD_TO_STD_FACTOR = 1.4826


class FactorPreprocessor:
    """因子预处理器 — 三步流水线。

    状态通过实例属性配置（winsorize_n），方法操作实例数据。
    """

    def __init__(self, winsorize_n: float = 3.0) -> None:
        self._winsorize_n = winsorize_n

    @property
    def winsorize_n(self) -> float:
        return self._winsorize_n

    def winsorize_mad(self, series: pd.Series, n: float | None = None) -> pd.Series:
        """MAD 去极值。

        公式:
            median = series.median()
            mad = (series - median).abs().median()
            upper = median + n × 1.4826 × mad
            lower = median - n × 1.4826 × mad
            截断到 [lower, upper]
        """
        n_val = n if n is not None else self._winsorize_n
        s = series.dropna().copy()
        if len(s) == 0:
            return series
        median = s.median()
        mad = (s - median).abs().median()
        if mad == 0 or np.isnan(mad):
            return series
        upper = median + n_val * _MAD_TO_STD_FACTOR * mad
        lower = median - n_val * _MAD_TO_STD_FACTOR * mad
        return series.clip(lower=lower, upper=upper)

    def zscore(self, series: pd.Series) -> pd.Series:
        """Z-score 标准化。"""
        s = series.dropna()
        if len(s) == 0:
            return series
        mean = s.mean()
        std = s.std(ddof=1)
        if std == 0 or np.isnan(std):
            return series * 0.0
        result = (series - mean) / std
        result.name = series.name
        return result

    def industry_neutralize(
        self,
        factor_series: pd.Series,
        industry_map: dict[str, str],
    ) -> pd.Series:
        """行业中性化 — 每个行业内单独 Z-score。

        Args:
            factor_series: index=股票代码, value=因子值
            industry_map: {stock_code: industry_name}

        Returns:
            行业中性化后的 Series，保留原始 name
        """
        if not industry_map:
            return factor_series

        original_name = factor_series.name
        ind_series = pd.Series(industry_map, name="industry")
        df = pd.DataFrame({"factor": factor_series, "industry": ind_series})
        df = df.dropna(subset=["industry"])

        # 每个行业组单独 Z-score
        result = df.groupby("industry")["factor"].transform(self._group_zscore)
        # 中性化后再做一次全市场 Z-score
        neutralized = self.zscore(result)
        neutralized.name = original_name
        return neutralized

    def preprocess(
        self,
        factor_df: pd.DataFrame,
        industry_map: dict[str, str] | None = None,
        neutralize: bool = True,
    ) -> pd.DataFrame:
        """完整预处理流水线。

        Args:
            factor_df: DataFrame, index=股票代码, columns=因子名
            industry_map: {stock_code: industry_name}, neutralize=True 时必须
            neutralize: 是否做行业中性化

        Returns:
            预处理后的 DataFrame, 同样 shape
        """
        processed_cols: list[pd.Series] = []
        for col in factor_df.columns:
            s = factor_df[col].dropna()
            if len(s) == 0:
                processed_cols.append(factor_df[col])
                continue
            # 1) 去极值
            s_w = self.winsorize_mad(s)
            # 2) 标准化
            s_z = self.zscore(s_w)
            # 3) 行业中性化 (可选)
            if neutralize and industry_map:
                s_z = self.industry_neutralize(s_z, industry_map)
            processed_cols.append(s_z)
        return pd.concat(processed_cols, axis=1)

    @staticmethod
    def _group_zscore(group: pd.Series) -> pd.Series:
        """组内 Z-score（供 groupby.transform 使用）。"""
        mean = group.mean()
        std = group.std(ddof=1)
        if std == 0 or np.isnan(std):
            return group * 0.0
        return (group - mean) / std
