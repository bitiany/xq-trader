"""Tushare 数据采集服务 — 封装 tushare pro_api 数据采集接口。

核心模式：通过 tushare pro_api 获取数据，asyncio.to_thread 适配异步框架。
所有 tushare 接口调用均为同步 HTTP 请求，通过线程池桥接为异步。
内置令牌桶限流器，控制 API 调用频率（默认 500 次/分钟）。
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pandas as pd
import tushare as ts  # type: ignore[import-untyped]

from framework.commons.exceptions import DataCollectionError
from framework.commons.logger import get_logger
from framework.commons.utils.rate_limiter import SlidingWindowLimiter

logger = get_logger(__name__)

# tushare 限流：500 次/分钟（滑动窗口）
# 任意60秒内请求数不超过480（留20次余量避免边界误差）
_TUSHARE_MAX_REQUESTS = 480
_TUSHARE_WINDOW_SECONDS = 60.0


class TushareDataCollector:
    """Tushare 数据采集服务。

    封装 tushare pro_api，提供个股资金流向等数据采集能力。
    tushare 接口为同步 HTTP 调用，通过 asyncio.to_thread 适配异步框架。
    内置滑动窗口限流器，每次 API 调用前自动 acquire 许可。
    使用独立线程池（max_workers=3），避免默认线程池过大导致并发超限。
    """

    _THREAD_POOL: ThreadPoolExecutor | None = None

    def __init__(
        self,
        max_requests: int = _TUSHARE_MAX_REQUESTS,
        window_seconds: float = _TUSHARE_WINDOW_SECONDS,
    ) -> None:
        token = os.getenv("TUSHARE_TOKEN", "")
        if not token:
            logger.warning("TUSHARE_TOKEN 未配置，tushare 接口将不可用")
        ts.set_token(token)
        self._pro = ts.pro_api()
        self._limiter = SlidingWindowLimiter(max_requests=max_requests, window_seconds=window_seconds)
        logger.info(
            "TushareDataCollector 初始化: 滑动窗口限流 max=%d/%.0fs",
            max_requests, window_seconds,
        )

    @classmethod
    def _get_executor(cls) -> ThreadPoolExecutor:
        """获取共享线程池（懒初始化，max_workers=20）。"""
        if cls._THREAD_POOL is None:
            cls._THREAD_POOL = ThreadPoolExecutor(max_workers=20, thread_name_prefix="tushare")
        return cls._THREAD_POOL

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
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.moneyflow_dc,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
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

    async def fetch_moneyflow(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取 tushare 原生个股资金流向数据。

        接口：moneyflow
        限制：单次最大 6000 条
        字段：买卖量/金额（手/万元），无占比字段

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，包含 ts_code/trade_date/buy_sm_amount/sell_sm_amount 等字段
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.moneyflow,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "moneyflow 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "moneyflow 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"moneyflow 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e

    async def fetch_daily_basic(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取每日指标数据（估值/换手率/市值等）。

        接口：daily_basic
        限制：单次最大 6000 条，需 2000 积分

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，包含 ts_code/trade_date/close/turnover_rate/pe/pb/total_mv 等字段
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.daily_basic,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "daily_basic 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "daily_basic 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"daily_basic 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e

    async def fetch_stock_basic(
        self,
        ts_code: str = "",
        list_status: str = "L",
        exchange: str = "",
    ) -> pd.DataFrame:
        """获取股票基本信息。

        接口：stock_basic
        限制：无单次上限，无需积分

        Args:
            ts_code: 股票代码，如 "000001.SZ"
            list_status: 上市状态 L(上市) D(退市) P(暂停上市)
            exchange: 交易所 SSE/SZSE/BSE

        Returns:
            DataFrame，包含 ts_code/symbol/name/area/industry/list_date/list_status 等字段
        """
        # 必须显式指定 fields，否则 Tushare SDK 默认只返回部分字段
        # （缺少 list_status/exchange/fullname/enname/curr_type/delist_date/is_hs 等）
        _fields = (
            "ts_code,symbol,name,area,industry,fullname,enname,cnspell,"
            "market,exchange,curr_type,list_status,list_date,delist_date,"
            "is_hs,act_name,act_ent_type"
        )
        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.stock_basic,
                ts_code=ts_code,
                list_status=list_status,
                exchange=exchange,
                fields=_fields,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "stock_basic 无数据: ts_code=%s list_status=%s exchange=%s",
                    ts_code, list_status, exchange,
                )
                return pd.DataFrame()

            logger.debug(
                "stock_basic 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"stock_basic 采集失败 ts_code={ts_code} list_status={list_status}: {e}"
            ) from e

    async def fetch_sw_daily(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取申万行业日线行情数据。

        接口：sw_daily
        限制：单次最大 4000 条，需 5000 积分

        Args:
            ts_code: 行业代码，如 "801010.SI"
            trade_date: 交易日期 YYYYMMDD
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame，包含 ts_code/trade_date/open/close/high/low/change/pct_change/vol/amount/pe/pb 等字段
        """
        if not ts_code and not trade_date:
            raise DataCollectionError("ts_code 和 trade_date 至少输入一个")

        try:
            await self._limiter.acquire()
            loop = asyncio.get_running_loop()
            func = partial(
                self._pro.sw_daily,
                ts_code=ts_code,
                trade_date=trade_date,
                start_date=start_date,
                end_date=end_date,
            )
            result = await loop.run_in_executor(self._get_executor(), func)
            df = pd.DataFrame() if result is None else pd.DataFrame(result)
            if df.empty:
                logger.debug(
                    "sw_daily 无数据: ts_code=%s trade_date=%s range=%s~%s",
                    ts_code, trade_date, start_date, end_date,
                )
                return pd.DataFrame()

            logger.debug(
                "sw_daily 获取完成: ts_code=%s rows=%d",
                ts_code, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"sw_daily 采集失败 ts_code={ts_code} trade_date={trade_date}: {e}"
            ) from e
