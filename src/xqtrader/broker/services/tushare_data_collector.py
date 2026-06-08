"""Tushare 数据采集服务 — 封装 tushare pro_api 数据采集接口。

核心模式：通过 tushare pro_api 获取数据，asyncio.to_thread 适配异步框架。
所有 tushare 接口调用均为同步 HTTP 请求，通过线程池桥接为异步。
内置令牌桶限流器，控制 API 调用频率（默认 500 次/分钟）。
"""

from __future__ import annotations

import asyncio
import os

import pandas as pd
import tushare as ts  # type: ignore[import-untyped]

from framework.commons.exceptions import DataCollectionError
from framework.commons.logger import get_logger
from framework.commons.utils.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

# tushare 限流：500 次/分钟
_TUSHARE_CAPACITY = 500
_TUSHARE_REFILL_RATE = 500 / 60  # ≈8.33 tokens/s


class TushareDataCollector:
    """Tushare 数据采集服务。

    封装 tushare pro_api，提供个股资金流向等数据采集能力。
    tushare 接口为同步 HTTP 调用，通过 asyncio.to_thread 适配异步框架。
    内置令牌桶限流器，每次 API 调用前自动 acquire 令牌。
    """

    def __init__(
        self,
        rate_capacity: int = _TUSHARE_CAPACITY,
        rate_refill: float = _TUSHARE_REFILL_RATE,
    ) -> None:
        token = os.getenv("TUSHARE_TOKEN", "")
        if not token:
            logger.warning("TUSHARE_TOKEN 未配置，tushare 接口将不可用")
        ts.set_token(token)
        self._pro = ts.pro_api()
        self._limiter = TokenBucketLimiter(capacity=rate_capacity, refill_rate=rate_refill)
        logger.info(
            "TushareDataCollector 初始化: 限流 capacity=%d refill_rate=%.2f/s",
            rate_capacity, rate_refill,
        )

    async def fetch_moneyflow_dc(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取东方财富个股资金流向数据。

        接口：moneyflow_dc
        限制：单次最大 6000 条，需 5000 积分

        Args:
            ts_code: 股票代码，如 "002149.SZ"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，包含 ts_code/trade_date/close/pct_change/net_amount 等字段
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        try:
            await self._limiter.acquire()
            result = await asyncio.to_thread(
                self._pro.moneyflow_dc,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "moneyflow_dc 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "moneyflow_dc 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"moneyflow_dc 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e
