"""截面因子数据加载服务 — 截面预处理 + 面板加载。

截面预处理流程（参考 Barra CNE6 / 华泰金工 / 示例 CASE-C preprocessor.py）：
  原始因子值 → 缺失值填充(行业均值) → 去极值(MAD) → Z-score → 行业+市值中性化 → 再Z-score

设计原则：
  - 按因子滚动：每次只加载1个因子的截面数据，评估完释放
  - 收益率面板全量加载一次，所有因子共用
  - 所有数据加载均按样本池标的过滤
  - 支持按月滚动加载，降低单次查询数据量
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.index.models.index import IndexWeight
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.security.models import Security

logger = get_logger(__name__)

_POOL_INDEX_MAP: dict[str, str] = {
    "all": "all",
    "idx_50": "000016.SH",
    "idx_300": "000300.SH",
    "idx_500": "000905.SH",
    "idx_1000": "000852.SH",
    "idx_kcb50": "000688.SH",
    "idx_cybz": "399006.SZ",
}

# 查询分片大小，避免单次 IN 列表过长
_QUERY_BATCH_SIZE = 500

# MAD 去极值倍数（Barra CNE6 标准为 5，华泰金工推荐 3~5）
_WINSORIZE_MAD_N = 5.0

# 高斯分布 MAD → std 换算系数
_MAD_TO_STD_FACTOR = 1.4826

# 风险警示股名称前缀（ST/*ST/PT），这些标的需要从样本池中排除
# 参考: 沪深交易所《股票上市规则》风险警示板相关规定
RISK_WARNING_PREFIXES: tuple[str, ...] = ("ST", "*ST", "PT")


def is_risk_warning_name(name: str) -> bool:
    """判断证券名称是否为风险警示股（ST/*ST/PT）。

    Args:
        name: 证券名称，如 "ST三木"、"*ST海航"

    Returns:
        True 表示为风险警示股，应从样本池中排除
    """
    if not name:
        return False
    return name.startswith(RISK_WARNING_PREFIXES)


class CrossSectionReader:
    """截面因子数据加载服务。

    支持两种加载模式：
    1. load_single_factor_panel: 加载单因子截面面板（按因子滚动评估时使用）
    2. load_returns_panel: 加载收益率面板（所有因子共用，一次加载）
    """

    async def load_single_factor_panel(
        self,
        start_date: date,
        end_date: date,
        pool_id: str,
        symbols: list[str],
        factor_id: str,
        industry_map: dict[str, str],
        market_cap_map: dict[str, float] | None = None,
    ) -> pd.DataFrame:
        """加载单因子截面面板并完成截面预处理。

        截面预处理流程：
          原始值 → 缺失值填充(行业均值) → MAD去极值 → Z-score → 行业+市值中性化 → 再Z-score

        按月滚动加载，降低单次查询数据量。每月内先做 MAD 去极值和 Z-score，
        合并后再做行业+市值中性化和再 Z-score（中性化需要跨月截面数据）。

        Args:
            start_date: 起始日期
            end_date: 结束日期
            pool_id: 样本池标识（仅用于日志）
            symbols: 样本池标的列表
            factor_id: 单个因子 ID
            industry_map: 行业映射 {symbol: industry_name}
            market_cap_map: 市值映射 {symbol: total_mv}，用于市值中性化

        Returns:
            MultiIndex(trade_date, symbol), columns=[factor_id]
        """
        factor_parts: list[pd.DataFrame] = []

        month_start = date(start_date.year, start_date.month, 1)
        while month_start <= end_date:
            if month_start.month == 12:
                month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)

            chunk_start = max(month_start, start_date)
            chunk_end = min(month_end, end_date)

            if chunk_start > chunk_end:
                month_start = date(month_start.year + (month_start.month // 12), (month_start.month % 12) + 1, 1)
                continue

            factor_df = await self._load_per_security_factors(chunk_start, chunk_end, [factor_id], symbols)

            if not factor_df.empty:
                # 月内：缺失值填充 → MAD去极值 → Z-score
                filled = self._fill_missing_industry_mean(factor_df, industry_map)
                winsorized = self._winsorize_mad(filled)
                month_panel = self._zscore_standardize(winsorized)
                factor_parts.append(month_panel)

            if month_start.month == 12:
                month_start = date(month_start.year + 1, 1, 1)
            else:
                month_start = date(month_start.year, month_start.month + 1, 1)

        if not factor_parts:
            return pd.DataFrame()

        # 跨月合并：行业+市值中性化 → 再Z-score
        factor_panel = pd.concat(factor_parts)
        factor_panel = self._industry_market_cap_neutralize(factor_panel, industry_map, market_cap_map)
        factor_panel = self._zscore_standardize(factor_panel)

        logger.debug(
            "单因子面板加载完成: pool=%s factor=%s rows=%d",
            pool_id, factor_id, len(factor_panel),
        )
        return factor_panel

    async def load_returns_panel(
        self,
        start_date: date,
        end_date: date,
        symbols: list[str],
    ) -> pd.DataFrame:
        """加载收益率面板（所有因子共用，按月滚动加载）。

        Args:
            start_date: 起始日期
            end_date: 结束日期
            symbols: 样本池标的列表

        Returns:
            MultiIndex(trade_date, symbol), column='fwd_ret_1d'
        """
        returns_parts: list[pd.DataFrame] = []

        month_start = date(start_date.year, start_date.month, 1)
        while month_start <= end_date:
            if month_start.month == 12:
                month_end = date(month_start.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(month_start.year, month_start.month + 1, 1) - timedelta(days=1)

            chunk_start = max(month_start, start_date)
            chunk_end = min(month_end, end_date)

            if chunk_start > chunk_end:
                month_start = date(month_start.year + (month_start.month // 12), (month_start.month % 12) + 1, 1)
                continue

            ret_df = await self._load_returns(chunk_start, chunk_end, symbols)
            if not ret_df.empty:
                returns_parts.append(ret_df)

            if month_start.month == 12:
                month_start = date(month_start.year + 1, 1, 1)
            else:
                month_start = date(month_start.year, month_start.month + 1, 1)

        if not returns_parts:
            return pd.DataFrame()

        returns_panel = pd.concat(returns_parts)
        logger.info("收益率面板加载完成: rows=%d", len(returns_panel))
        return returns_panel

    async def load_pool_symbols(self, pool_id: str) -> list[str]:
        """获取样本池标的列表。

        全市场样本池(pool_id='all')仅保留 list_status='L' 的上市标的，
        并排除 ST/*ST/PT 风险警示股。指数成分股池无需过滤（指数本身不含 ST）。
        """
        if pool_id == "all":
            securities = await Security.filter(list_status="L")
            # 过滤 ST/*ST 风险警示股（流动性差、退市风险高，会扭曲因子统计）
            symbols = [s.symbol for s in securities if not is_risk_warning_name(s.name)]
            logger.debug(
                "全 A 样本池: %d 只标的（过滤 ST/*ST 后，原始 %d 只）",
                len(symbols), len(securities),
            )
            return symbols

        index_code = _POOL_INDEX_MAP.get(pool_id, pool_id)
        weights = await IndexWeight.filter(index_code=index_code)
        symbols = list({w.stock_code for w in weights})
        logger.debug("样本池 %s (index=%s): %d 只标的", pool_id, index_code, len(symbols))
        return symbols

    async def load_industry_map(self, symbols: list[str]) -> dict[str, str]:
        """获取标的行业分类映射。"""
        securities = await Security.filter(symbol__in=symbols)
        return {s.symbol: s.industry for s in securities if s.industry}

    async def load_market_cap_map(self, symbols: list[str]) -> dict[str, float]:
        """获取标的最新总市值映射，用于市值中性化。

        批量查询后按 symbol 分组取最新日期记录，避免逐标的串行查询。
        """
        from xqtrader.domain.market.models.daily_indicator import DailyIndicator

        if not symbols:
            return {}

        market_cap: dict[str, float] = {}
        for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
            batch = symbols[i:i + _QUERY_BATCH_SIZE]
            records = await DailyIndicator.filter(
                symbol__in=batch,
                order_by=DailyIndicator.trade_date.desc(),
            )
            # 按 symbol 分组取最新记录（records 已按 trade_date 降序）
            seen: set[str] = set()
            for r in records:
                if r.symbol not in seen and r.total_mv is not None:
                    market_cap[r.symbol] = r.total_mv
                    seen.add(r.symbol)

        logger.debug("市值映射加载完成: %d/%d 只标的有市值数据", len(market_cap), len(symbols))
        return market_cap

    # ==================== 数据加载 ====================

    async def _load_per_security_factors(
        self,
        start_date: date,
        end_date: date,
        factor_ids: list[str],
        symbols: list[str],
    ) -> pd.DataFrame:
        """加载逐标的因子值（窄表转宽表），按样本池标的过滤。"""
        if not factor_ids or not symbols:
            return pd.DataFrame()

        all_rows: list[dict] = []
        for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
            batch = symbols[i:i + _QUERY_BATCH_SIZE]
            records = await FacFactorValue.filter(
                trade_date__gte=start_date,
                trade_date__lte=end_date,
                pool_id="all",
                factor_id__in=factor_ids,
                symbol__in=batch,
            )
            all_rows.extend(
                {"trade_date": r.trade_date, "symbol": r.symbol, r.factor_id: r.factor_value}
                for r in records
            )

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)
        df = df.groupby(["trade_date", "symbol"]).agg("first").reset_index()
        df = df.set_index(["trade_date", "symbol"])
        return df

    async def _load_returns(
        self,
        start_date: date,
        end_date: date,
        symbols: list[str],
    ) -> pd.DataFrame:
        """加载日行情并计算 fwd_ret_1d，按样本池标的过滤。"""
        all_rows: list[dict] = []
        for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
            batch = symbols[i:i + _QUERY_BATCH_SIZE]
            records = await CandlestickDaily.filter(
                trade_date__gte=start_date,
                trade_date__lte=end_date,
                symbol__in=batch,
            )
            all_rows.extend(
                {"trade_date": r.trade_date, "symbol": r.symbol, "close": r.close}
                for r in records
            )

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows).sort_values(["symbol", "trade_date"])
        df["fwd_ret_1d"] = df.groupby("symbol")["close"].shift(-1) / df["close"] - 1
        df = df.dropna(subset=["fwd_ret_1d"])
        df = df.set_index(["trade_date", "symbol"])[["fwd_ret_1d"]]
        return df

    # ==================== 截面预处理 ====================

    @staticmethod
    def _fill_missing_industry_mean(
        df: pd.DataFrame,
        industry_map: dict[str, str],
    ) -> pd.DataFrame:
        """缺失值填充：用同截面同行业均值填充 NaN。

        保证截面完整性，避免因缺失值导致后续 Z-score 和中性化偏差。
        """
        if df.empty or not industry_map:
            return df

        result = df.copy()
        for col in result.columns:
            missing = result[col].isna()
            if not missing.any():
                continue

            # 构造行业 Series
            symbols_in_index = result.index.get_level_values("symbol")
            industry_series = pd.Series(
                [industry_map.get(s, "unknown") for s in symbols_in_index],
                index=result.index,
            )

            # 按截面日+行业分组计算均值，填充缺失值
            industry_means = result[col].groupby([
                result.index.get_level_values("trade_date"),
                industry_series,
            ]).transform("mean")

            result[col] = result[col].fillna(industry_means)

        return result

    @staticmethod
    def _winsorize_mad(
        df: pd.DataFrame,
        n: float = _WINSORIZE_MAD_N,
    ) -> pd.DataFrame:
        """截面 MAD 去极值：按 trade_date 分组，把超出 n×MAD 边界的值截断。

        公式（参考 Barra CNE6 / 华泰金工 / CASE-C preprocessor.py）：
            median = 截面中位数
            mad = |x - median| 的中位数
            upper = median + n × 1.4826 × mad
            lower = median - n × 1.4826 × mad
            超出 [lower, upper] 的值截断到边界

        1.4826 是高斯分布 MAD → std 的换算系数。
        先去极值再标准化，否则极端值会扭曲均值和方差。
        """
        if df.empty:
            return df

        result = df.copy()

        def _winsorize_group(group: pd.DataFrame) -> pd.DataFrame:
            median = group.median(skipna=True)
            mad = (group - median).abs().median(skipna=True)

            # 处理零值和 NaN
            if isinstance(mad, pd.Series):
                mad = mad.replace(0, np.nan)
            elif mad == 0 or np.isnan(mad):
                mad = np.nan

            if isinstance(mad, pd.Series) and mad.isna().all():
                return group
            elif not isinstance(mad, pd.Series) and (np.isnan(mad) if isinstance(mad, float) else False):
                return group

            upper = median + n * _MAD_TO_STD_FACTOR * mad
            lower = median - n * _MAD_TO_STD_FACTOR * mad
            return group.clip(lower=lower, upper=upper, axis=0)

        return result.groupby(level="trade_date").transform(_winsorize_group)

    @staticmethod
    def _zscore_standardize(df: pd.DataFrame) -> pd.DataFrame:
        """截面 Z-score 标准化：按 trade_date 分组，(x - mean) / std。"""
        if df.empty:
            return df

        def _zscore(group: pd.DataFrame) -> pd.DataFrame:
            mean = group.mean(skipna=True)
            std = group.std(skipna=True)
            if isinstance(std, pd.Series):
                std = std.replace(0, np.nan)
            elif std == 0:
                std = np.nan
            return (group - mean) / std

        return df.groupby(level="trade_date").transform(_zscore)

    @staticmethod
    def _industry_market_cap_neutralize(
        df: pd.DataFrame,
        industry_map: dict[str, str],
        market_cap_map: dict[str, float] | None = None,
    ) -> pd.DataFrame:
        """行业+市值中性化：对每个因子回归行业虚拟变量 + log(市值)，取残差。

        Barra CNE6 标准做法：同时剥离行业暴露和规模暴露。
        小盘股偏高的因子值（如换手率、波动率）含规模因子残差，需通过市值中性化剥离。

        无市值数据时退化为纯行业中性化。
        """
        if df.empty or not industry_map:
            return df

        symbols_in_index = df.index.get_level_values("symbol")
        industry_series = pd.Series(
            [industry_map.get(s, "unknown") for s in symbols_in_index],
            index=df.index,
        )
        dummies = pd.get_dummies(industry_series, drop_first=True)

        # 构造 log(市值) 列
        if market_cap_map:
            log_mv_series = pd.Series(
                [np.log1p(market_cap_map.get(s, 0.0)) for s in symbols_in_index],
                index=df.index,
            )
            # 合并行业虚拟变量和 log(市值)
            x_all = pd.concat([dummies, log_mv_series.rename("log_mv")], axis=1)
        else:
            x_all = dummies

        result = df.copy()
        for col in df.columns:
            valid = df[col].notna()
            if valid.sum() < 2:
                continue
            y = df.loc[valid, col].values.astype(float)
            x_mat = x_all.loc[valid].values.astype(float)

            # 移除全零列（某行业在该截面无标的）
            nonzero_cols = ~np.all(x_mat == 0, axis=0)
            if nonzero_cols.sum() == 0:
                continue
            x_mat = x_mat[:, nonzero_cols]

            residuals = y - x_mat @ np.linalg.lstsq(x_mat, y, rcond=None)[0]  # type: ignore[arg-type]
            result.loc[valid, col] = residuals

        return result
