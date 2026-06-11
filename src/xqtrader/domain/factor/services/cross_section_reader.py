"""截面因子数据加载服务，用于因子评估时加载截面因子面板与收益率面板。

架构设计（参考业界主流因子评估平台）：
  - 按因子滚动：每次只加载1个因子的截面数据，评估完释放
  - 收益率面板全量加载一次，所有因子共用
  - 所有数据加载均按样本池标的过滤，避免加载无关数据
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
    ) -> pd.DataFrame:
        """加载单因子截面面板（含估值/财务指标 + Z-score + 行业中性化）。

        按月滚动加载，降低单次查询数据量。

        Args:
            start_date: 起始日期
            end_date: 结束日期
            pool_id: 样本池标识（仅用于日志）
            symbols: 样本池标的列表
            factor_id: 单个因子 ID
            industry_map: 行业映射（预加载，所有因子共用）

        Returns:
            MultiIndex(trade_date, symbol), columns=[factor_id] + 估值/财务指标
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

            # 加载单因子值
            factor_df = await self._load_per_security_factors(chunk_start, chunk_end, [factor_id], symbols)

            if not factor_df.empty:
                month_panel = self._zscore_standardize(factor_df)
                factor_parts.append(month_panel)

            # 下一个月
            if month_start.month == 12:
                month_start = date(month_start.year + 1, 1, 1)
            else:
                month_start = date(month_start.year, month_start.month + 1, 1)

        if not factor_parts:
            return pd.DataFrame()

        factor_panel = pd.concat(factor_parts)
        factor_panel = self._industry_neutralize(factor_panel, industry_map)

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
        """获取样本池标的列表。"""
        if pool_id == "all":
            securities = await Security.filter(list_status="L")
            symbols = [s.symbol for s in securities]
            logger.debug("全 A 样本池: %d 只标的", len(symbols))
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

    # ==================== 截面处理 ====================

    @staticmethod
    def _zscore_standardize(df: pd.DataFrame) -> pd.DataFrame:
        """截面 Z-score 标准化：按 trade_date 分组，(x - mean) / std。"""
        if df.empty:
            return df

        def _zscore(group: pd.DataFrame) -> pd.DataFrame:
            mean = group.mean(skipna=True)
            std = group.std(skipna=True)
            # std 可能是标量（单列）或 Series（多列），统一处理零值
            if isinstance(std, pd.Series):
                std = std.replace(0, np.nan)
            elif std == 0:
                std = np.nan
            return (group - mean) / std

        return df.groupby(level="trade_date").transform(_zscore)

    @staticmethod
    def _industry_neutralize(df: pd.DataFrame, industry_map: dict[str, str]) -> pd.DataFrame:
        """行业中性化：对每个因子回归行业虚拟变量，取残差。"""
        if df.empty or not industry_map:
            return df

        symbols_in_index = df.index.get_level_values("symbol")
        industry_series = pd.Series(
            [industry_map.get(s, "unknown") for s in symbols_in_index],
            index=df.index,
        )
        dummies = pd.get_dummies(industry_series, drop_first=True)

        result = df.copy()
        for col in df.columns:
            valid = df[col].notna()
            if valid.sum() < 2:
                continue
            y = df.loc[valid, col].values
            x_mat = dummies.loc[valid].values.astype(float)
            if x_mat.shape[1] == 0:
                continue
            residuals = y - x_mat @ np.linalg.lstsq(x_mat, y, rcond=None)[0]
            result.loc[valid, col] = residuals

        return result
