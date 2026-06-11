"""QMT 数据采集服务 — 封装 xtdata 行情数据采集接口。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import pandas as pd
from xtquant import xtdata

from framework.commons.exceptions import DataCollectionError

logger = logging.getLogger(__name__)


def convert_symbol_to_qmt(symbol: str) -> str:
    """将 Tushare 格式代码转为 QMT 格式。

    Tushare: 000001.SH / 399006.SZ
    QMT:     SH.000001 / SZ.399006
    """
    parts = symbol.split(".")
    if len(parts) == 2:
        return f"{parts[1]}.{parts[0]}"
    return symbol


def convert_symbol_from_qmt(qmt_code: str) -> str:
    """将 QMT 格式代码转为 Tushare 格式。

    QMT:     SH.000001 / SZ.399006
    Tushare: 000001.SH / 399006.SZ
    """
    parts = qmt_code.split(".")
    if len(parts) == 2:
        return f"{parts[1]}.{parts[0]}"
    return qmt_code


class QmtDataCollector:
    """QMT 行情数据采集服务。

    封装 xtdata 模块，提供 K线、Tick、财务数据等采集能力。
    xtdata 是同步 API，通过 asyncio.to_thread 适配异步框架。

    核心模式：先 download_history_data2 补缓存，再 get_market_data_ex 获取数据，
    确保返回完整的历史数据。全程加锁避免多线程并发 xtdata。
    """

    _LOCK_TIMEOUT = 60
    _DOWNLOAD_WAIT_SECONDS = 5
    _xtdata_lock = threading.Lock()

    @classmethod
    def _with_lock(cls, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """在 xtdata 全局锁保护下执行同步调用。"""
        acquired = cls._xtdata_lock.acquire(timeout=cls._LOCK_TIMEOUT)
        if not acquired:
            raise TimeoutError(f"QMT lock acquire timed out after {cls._LOCK_TIMEOUT}s")
        try:
            return fn(*args, **kwargs)
        finally:
            cls._xtdata_lock.release()

    async def connect(self) -> None:
        """连接 MiniQMT 行情服务。

        xtdata.connect() 成功时返回 IPythonApiClient 对象，失败时抛异常。
        """
        result = await asyncio.to_thread(self._with_lock, xtdata.connect)
        logger.info("QMT 行情连接完成: result=%s", result)
        if result is None:
            raise DataCollectionError("QMT 行情连接失败: 返回值为空")

    async def disconnect(self) -> None:
        """断开行情连接。"""
        await asyncio.to_thread(self._with_lock, xtdata.disconnect)
        logger.info("QMT 行情连接已断开")

    # ── 日线行情 ──────────────────────────────────────────

    async def fetch_index_kline_daily(
        self,
        index_list: list[str],
        start_time: str = "",
        end_time: str = "",
        dividend_type: str = "front",
    ) -> dict[str, pd.DataFrame]:
        """获取指数日线行情数据。

        接口与 fetch_kline_daily 相同，但输入/输出使用 Tushare 格式代码，
        内部自动转换为 QMT 格式调用 xtdata。

        Args:
            index_list: 指数代码列表（Tushare 格式），如 ["000001.SH", "399006.SZ"]
            start_time: 起始日期 YYYYMMDD
            end_time: 结束日期 YYYYMMDD
            dividend_type: 复权方式 none/front/back/front_ratio/back_ratio

        Returns:
            {index_code: pd.DataFrame}，key 为 Tushare 格式代码
        """
        if not index_list:
            return {}

        # Tushare 格式 → QMT 格式
        qmt_list = [convert_symbol_to_qmt(c) for c in index_list]
        qmt_to_tushare = {convert_symbol_to_qmt(c): c for c in index_list}

        raw = await self.fetch_kline_daily(
            stock_list=qmt_list,
            start_time=start_time,
            end_time=end_time,
            dividend_type=dividend_type,
        )

        # QMT 格式 key → Tushare 格式 key
        return {qmt_to_tushare.get(k, k): v for k, v in raw.items()}

    async def fetch_kline_daily(
        self,
        stock_list: list[str],
        start_time: str = "",
        end_time: str = "",
        dividend_type: str = "front",
    ) -> dict[str, pd.DataFrame]:
        """获取日线行情数据（先下载补缓存，再获取）。

        单支与批量统一入口，单支传 [code]，批量传 [code1, code2, ...]。

        Args:
            stock_list: 证券代码列表，如 ["600000.SH"] 或 ["600000.SH", "000001.SZ"]
            start_time: 起始日期 YYYYMMDD
            end_time: 结束日期 YYYYMMDD
            dividend_type: 复权方式 none/front/back/front_ratio/back_ratio

        Returns:
            {stock_code: pd.DataFrame}，DataFrame 包含
            trade_date/open/close/high/low/volume/amount/change/pre_close/pct_chg 列
        """
        if not stock_list:
            return {}

        sd = start_time.replace("-", "")
        ed = end_time.replace("-", "")
        if sd > ed:
            logger.warning("fetch_kline_daily 忽略倒置区间 start=%s end=%s", sd, ed)
            return {s: pd.DataFrame() for s in stock_list}

        logger.debug(
            "获取日线: stocks=%d range=%s~%s dividend=%s",
            len(stock_list), sd, ed, dividend_type,
        )

        raw = await asyncio.to_thread(self._download_and_get_kline, stock_list, sd, ed, dividend_type)

        out: dict[str, pd.DataFrame] = {}
        nonempty = 0
        row_sum = 0
        for sym in stock_list:
            df = raw.get(sym)
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                out[sym] = self._format_kline(df)
                nonempty += 1
                row_sum += len(out[sym])
            else:
                out[sym] = pd.DataFrame()

        logger.debug(
            "获取日线完成: range=%s~%s 请求=%d 有数据=%d 总行数=%d",
            sd, ed, len(stock_list), nonempty, row_sum,
        )
        return out

    @staticmethod
    def _format_kline(df: pd.DataFrame) -> pd.DataFrame:
        """将 xtdata 原始 K线 DataFrame 转换为标准格式。"""
        df = df.reset_index()
        df = df.rename(columns={df.columns[0]: "trade_date"})

        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")

        if "volume" in df.columns:
            df["volume"] = df["volume"].astype(int)

        if "amount" in df.columns:
            df["amount"] = (df["amount"] / 1000).round(2)

        if "close" in df.columns:
            df["pre_close"] = df["close"].shift(1)
            df.loc[df.index[0], "pre_close"] = df.iloc[0]["open"] if "open" in df.columns else df.iloc[0]["close"]

        if "close" in df.columns and "pre_close" in df.columns:
            df["change"] = (df["close"] - df["pre_close"]).round(4)

        if "close" in df.columns:
            df["pct_chg"] = df["close"].pct_change().round(4) * 100
            df.loc[df.index[0], "pct_chg"] = 0.0

        keep_cols = [
            "trade_date", "open", "close", "high", "low",
            "volume", "amount", "change", "pre_close", "pct_chg",
        ]
        existing = [c for c in keep_cols if c in df.columns]
        return df[existing]

    def _download_and_get_kline(
        self,
        stock_list: list[str],
        start_time: str,
        end_time: str,
        dividend_type: str = "front",
    ) -> dict[str, Any]:
        """同步方法：先下载补缓存，再获取K线数据。全程加锁。"""
        acquired = self._xtdata_lock.acquire(timeout=self._LOCK_TIMEOUT)
        if not acquired:
            raise TimeoutError(
                f"QMT lock acquire timed out after {self._LOCK_TIMEOUT}s for batch {start_time}~{end_time}"
            )
        try:
            try:
                xtdata.download_history_data2(stock_list, "1d", start_time, end_time)
            except Exception as e:
                raise DataCollectionError(
                    f"下载历史数据失败 range={start_time}~{end_time} count={len(stock_list)}: {e}"
                ) from e

            time.sleep(self._DOWNLOAD_WAIT_SECONDS)

            raw = xtdata.get_market_data_ex(
                field_list=[],
                stock_list=stock_list,
                period="1d",
                start_time=start_time,
                end_time=end_time,
                count=-1,
                dividend_type=dividend_type,
                fill_data=True,
            )
        finally:
            self._xtdata_lock.release()

        if not isinstance(raw, dict):
            logger.warning("get_market_data_ex 非 dict range=%s~%s", start_time, end_time)
            return {s: pd.DataFrame() for s in stock_list}

        return raw

    # ── Tick 数据 ────────────────────────────────────────

    async def get_full_tick(self, code_list: list[str]) -> dict[str, Any]:
        """获取全推 Tick 数据（最新分笔）。

        Args:
            code_list: 证券代码列表
        """
        logger.info("获取全推Tick: codes=%s", code_list)
        return await asyncio.to_thread(self._with_lock, xtdata.get_full_tick, code_list)

    # ── 财务数据 ──────────────────────────────────────────

    async def fetch_financial_data(
        self,
        stock_list: list[str],
        table_list: list[str] | None = None,
        start_time: str = "",
        end_time: str = "",
        report_type: str = "report_time",
    ) -> dict[str, dict[str, pd.DataFrame]]:
        """获取财务数据。

        Args:
            stock_list: 证券代码列表
            table_list: 报表名列表，如 ["Balance", "Income", "CashFlow"]
            start_time: 起始时间
            end_time: 结束时间
            report_type: 报告类型 report_time/announce_time

        Returns:
            {stock_code: {table_name: pd.DataFrame}}，如 {"600000.SH": {"Balance": DataFrame}}
        """
        if not stock_list:
            return {}

        logger.info(
            "获取财务数据: stocks=%s tables=%s start=%s end=%s",
            stock_list, table_list, start_time, end_time,
        )

        raw = await asyncio.to_thread(
            self._get_financial_data,
            stock_list, table_list or [], start_time, end_time, report_type,
        )

        out: dict[str, dict[str, pd.DataFrame]] = {}
        for sym in stock_list:
            inner = raw.get(sym)
            if inner is None or not isinstance(inner, dict):
                out[sym] = {}
                continue
            tables: dict[str, pd.DataFrame] = {}
            for tbl_name, df in inner.items():
                if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                    tables[tbl_name] = df.copy()
            out[sym] = tables

        return out

    def _get_financial_data(
        self,
        stock_list: list[str],
        table_list: list[str],
        start_time: str,
        end_time: str,
        report_type: str,
    ) -> dict[str, Any]:
        """同步方法：获取财务数据。全程加锁。"""
        acquired = self._xtdata_lock.acquire(timeout=self._LOCK_TIMEOUT)
        if not acquired:
            raise TimeoutError(
                f"QMT lock acquire timed out after {self._LOCK_TIMEOUT}s for financial data"
            )
        try:
            raw = xtdata.get_financial_data(
                stock_list, table_list, start_time, end_time, report_type,
            )
        finally:
            self._xtdata_lock.release()

        if not isinstance(raw, dict):
            logger.warning("get_financial_data 非 dict")
            return {}

        return raw

    # ── 合约信息 ──────────────────────────────────────────

    async def get_instrument_detail(self, stock_code: str) -> dict[str, Any] | None:
        """获取合约基础信息。"""
        logger.info("获取合约信息: stock=%s", stock_code)
        return await asyncio.to_thread(self._with_lock, xtdata.get_instrument_detail, stock_code)

    async def get_trading_dates(
        self,
        market: str,
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
    ) -> list[int]:
        """获取交易日列表。

        Args:
            market: 市场代码，如 "SH", "SZ"
            start_time: 起始时间
            end_time: 结束时间
            count: 数量
        """
        logger.info("获取交易日: market=%s start=%s end=%s", market, start_time, end_time)
        return await asyncio.to_thread(
            self._with_lock, xtdata.get_trading_dates, market, start_time, end_time, count,
        )

    # ── 板块与指数 ────────────────────────────────────────

    async def get_sector_list(self) -> list[str]:
        """获取板块列表。"""
        logger.info("获取板块列表")
        return await asyncio.to_thread(self._with_lock, xtdata.get_sector_list)

    async def get_stock_list_in_sector(self, sector_name: str) -> list[str]:
        """获取板块成分股。"""
        logger.info("获取板块成分股: sector=%s", sector_name)
        return await asyncio.to_thread(self._with_lock, xtdata.get_stock_list_in_sector, sector_name)

    async def get_index_weight(self, index_code: str) -> dict[str, Any]:
        """获取指数成分权重。"""
        logger.info("获取指数权重: index=%s", index_code)
        return await asyncio.to_thread(self._with_lock, xtdata.get_index_weight, index_code)
