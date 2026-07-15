"""A 股市场情绪采集器 — 涨跌停家数比 / 市场活跃度 / 微博财经舆情。

架构文档 §11.3.2 第二层扩展：A 股恐慌指标（补充 Yahoo Finance 海外指标）。

数据源：akshare（公开接口，无需认证）
  - stock_zt_pool_em          涨停池
  - stock_zt_pool_dtgc_em     跌停池
  - stock_market_activity_legu 乐咕乐股市场活跃度
  - stock_js_weibo_report     微博财经舆情

采集失败处理：单个指标失败返回 None，不降级、不 fallback；
全部失败时返回全 None 并记录 WARNING。

调用方式：复用 AkshareDataCollector 的线程池桥接模式
（run_in_executor + SlidingWindowLimiter）。
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from functools import partial
from typing import Any, cast

import akshare as ak  # type: ignore[import-untyped]
import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.rate_limiter import SlidingWindowLimiter

logger = get_logger("EVENT.CN_SENTIMENT")

# akshare 调用限流（30 次/分钟，与 AkshareDataCollector 默认限流一致）
_ZT_POOL_LIMIT = (30, 60.0)
_ACTIVITY_LIMIT = (30, 60.0)
_WEIBO_LIMIT = (30, 60.0)


def _call_zt_pool(dt: str) -> pd.DataFrame:
    """同步调用 akshare stock_zt_pool_em（涨停池）。"""
    return cast(pd.DataFrame, ak.stock_zt_pool_em(date=dt))


def _call_dtgc_pool(dt: str) -> pd.DataFrame:
    """同步调用 akshare stock_zt_pool_dtgc_em（跌停池）。"""
    return cast(pd.DataFrame, ak.stock_zt_pool_dtgc_em(date=dt))


def _call_market_activity() -> pd.DataFrame:
    """同步调用 akshare stock_market_activity_legu（乐咕乐股市场活跃度）。"""
    return cast(pd.DataFrame, ak.stock_market_activity_legu())


def _call_weibo_sentiment(time_period: str) -> pd.DataFrame:
    """同步调用 akshare stock_js_weibo_report（微博财经舆情）。"""
    if time_period:
        return cast(pd.DataFrame, ak.stock_js_weibo_report(time_period=time_period))
    return cast(pd.DataFrame, ak.stock_js_weibo_report())


class CNMarketSentimentService:
    """A 股市场情绪采集服务。

    设计原则：
      - 复用 AkshareDataCollector 的线程池桥接模式（run_in_executor + Limiter）
      - 独立线程池，与 AkshareDataCollector 隔离，避免影响新闻/研报采集
      - 每个接口独立限流器
      - 采集失败返回 None（不降级、不 fallback）
    """

    _THREAD_POOL: ThreadPoolExecutor | None = None

    def __init__(self) -> None:
        self._limiters: dict[str, SlidingWindowLimiter] = {
            "zt_pool": SlidingWindowLimiter(*_ZT_POOL_LIMIT),
            "dtgc_pool": SlidingWindowLimiter(*_ZT_POOL_LIMIT),
            "market_activity": SlidingWindowLimiter(*_ACTIVITY_LIMIT),
            "weibo_sentiment": SlidingWindowLimiter(*_WEIBO_LIMIT),
        }

    @classmethod
    def _get_executor(cls) -> ThreadPoolExecutor:
        """获取共享线程池（懒初始化，与 AkshareDataCollector 隔离）。"""
        if cls._THREAD_POOL is None:
            cls._THREAD_POOL = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="cn-sentiment",
            )
        return cls._THREAD_POOL

    def _get_limiter(self, name: str) -> SlidingWindowLimiter:
        return self._limiters.get(name) or SlidingWindowLimiter(30, 60.0)

    async def fetch_limit_up_count(self, as_of: date) -> int | None:
        """获取涨停股家数。

        Args:
            as_of: 基准日期（akshare 要求 YYYYMMDD 字符串）

        Returns:
            涨停家数，采集失败返回 None
        """
        dt_str = as_of.strftime("%Y%m%d")
        try:
            await self._get_limiter("zt_pool").acquire()
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                self._get_executor(), partial(_call_zt_pool, dt_str),
            )
            if df is None or df.empty:
                logger.debug("[cn_sentiment.zt_pool] 无数据: %s", dt_str)
                return None
            count = len(df)
            logger.debug("[cn_sentiment.zt_pool] %s 涨停家数=%d", dt_str, count)
            return count
        except Exception as exc:
            logger.warning(
                "涨停池采集失败 (as_of=%s): %s", dt_str, exc, exc_info=True,
            )
            return None

    async def fetch_limit_down_count(self, as_of: date) -> int | None:
        """获取跌停股家数。

        Args:
            as_of: 基准日期

        Returns:
            跌停家数，采集失败返回 None
        """
        dt_str = as_of.strftime("%Y%m%d")
        try:
            await self._get_limiter("dtgc_pool").acquire()
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                self._get_executor(), partial(_call_dtgc_pool, dt_str),
            )
            if df is None or df.empty:
                logger.debug("[cn_sentiment.dtgc_pool] 无数据: %s", dt_str)
                return None
            count = len(df)
            logger.debug("[cn_sentiment.dtgc_pool] %s 跌停家数=%d", dt_str, count)
            return count
        except Exception as exc:
            logger.warning(
                "跌停池采集失败 (as_of=%s): %s", dt_str, exc, exc_info=True,
            )
            return None

    async def fetch_market_activity(self) -> float | None:
        """获取乐咕乐股市场活跃度指数。

        Returns:
            活跃度指数（0-100），采集失败返回 None
        """
        try:
            await self._get_limiter("market_activity").acquire()
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                self._get_executor(), _call_market_activity,
            )
            if df is None or df.empty:
                logger.debug("[cn_sentiment.activity] 无数据")
                return None
            # 取第一行的活跃度数值（字段名不确定，按列名匹配）
            value = self._extract_activity_value(df)
            logger.debug("[cn_sentiment.activity] 活跃度=%s", value)
            return value
        except Exception as exc:
            logger.warning(
                "市场活跃度采集失败: %s", exc, exc_info=True,
            )
            return None

    async def fetch_weibo_sentiment_score(self) -> float | None:
        """获取微博财经舆情热度（最近 12 小时）。

        Returns:
            热度数值，采集失败返回 None
        """
        try:
            await self._get_limiter("weibo_sentiment").acquire()
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(
                self._get_executor(), partial(_call_weibo_sentiment, "CNHOUR12"),
            )
            if df is None or df.empty:
                logger.debug("[cn_sentiment.weibo] 无数据")
                return None
            score = self._extract_weibo_hot_score(df)
            logger.debug("[cn_sentiment.weibo] 热度=%s", score)
            return score
        except Exception as exc:
            logger.warning(
                "微博舆情采集失败: %s", exc, exc_info=True,
            )
            return None

    @staticmethod
    def _extract_activity_value(df: pd.DataFrame) -> float | None:
        """从 stock_market_activity_legu 返回中提取活跃度数值。

        常见字段名：市场活跃度 / 整数活跃度 / 活跃度
        """
        candidates = ["市场活跃度", "整数活跃度", "活跃度"]
        for col in candidates:
            if col in df.columns and len(df) > 0:
                value = df.iloc[0][col]
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        # 兜底：取最后一列第一行的数值
        if len(df) > 0:
            last_col = df.columns[-1]
            try:
                return float(df.iloc[0][last_col])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _extract_weibo_hot_score(df: pd.DataFrame) -> float | None:
        """从 stock_js_weibo_report 返回中提取热度均分。

        常见字段：热度 / hot
        """
        candidates = ["热度", "hot"]
        for col in candidates:
            if col in df.columns and len(df) > 0:
                values = pd.to_numeric(df[col], errors="coerce").dropna()
                if not values.empty:
                    return float(values.mean())
        return None

    async def fetch_all(
        self,
        *,
        as_of: date | None = None,
    ) -> dict[str, Any]:
        """并发采集所有 A 股市场情绪指标。

        Args:
            as_of: 基准日期（None 表示今天）

        Returns:
            含 limit_up / limit_down / advance_decline_ratio /
            market_activity / weibo_hot 五个字段的 dict
        """
        ref_date = as_of or date.today()
        results = await asyncio.gather(
            self.fetch_limit_up_count(ref_date),
            self.fetch_limit_down_count(ref_date),
            self.fetch_market_activity(),
            self.fetch_weibo_sentiment_score(),
            return_exceptions=False,
        )
        limit_up = cast(int | None, results[0])
        limit_down = cast(int | None, results[1])
        activity = cast(float | None, results[2])
        weibo = cast(float | None, results[3])

        advance_decline_ratio: float | None = None
        if limit_up is not None and limit_down is not None and limit_down > 0:
            advance_decline_ratio = limit_up / limit_down

        logger.info(
            "A 股市场情绪采集完成: as_of=%s 涨停=%s 跌停=%s 涨跌停比=%s "
            "活跃度=%s 微博热度=%s",
            ref_date, limit_up, limit_down, advance_decline_ratio,
            activity, weibo,
        )
        return {
            "as_of": ref_date,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "advance_decline_ratio": advance_decline_ratio,
            "market_activity": activity,
            "weibo_hot": weibo,
        }


# 模块级单例
cn_market_sentiment_service = CNMarketSentimentService()
