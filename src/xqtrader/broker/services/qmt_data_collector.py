"""QMT 数据采集服务 — 封装 xtdata 行情数据采集接口。"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any, cast

import pandas as pd
from xtquant import xtdata

from framework.commons.exceptions import DataCollectionError

logger = logging.getLogger(__name__)


class QmtDataCollector:
    """QMT 行情数据采集服务。

    封装 xtdata 模块，提供 K线、Tick、财务数据等采集能力。
    核心模式：先 download_history_data2 补缓存，再 get_market_data_ex 获取数据，
    """

    _LOCK_TIMEOUT = 300             # 锁等待超时（connect/get_full_tick/get_market_data_ex 等）
    _DOWNLOAD_TIMEOUT = 120         # download_history_data2 超时（秒），防止废弃代码导致永久挂起
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

    async def fetch_kline_daily(
        self,
        stock_list: list[str],
        start_time: str = "",
        end_time: str = "",
        dividend_type: str = "front",
    ) -> dict[str, pd.DataFrame]:
        """获取日线行情数据（先下载补缓存，再获取）。

        单支与批量统一入口，单支传 [code]，批量传 [code1, code2, ...]。
        QMT download 不指定 end_time，默认下载到最新交易日；end_time 参数仅用于
        API 层日志展示，底层实际不限制结束日期。

        Args:
            stock_list: 证券代码列表，如 ["600000.SH"] 或 ["600000.SH", "000001.SZ"]
            start_time: 起始日期 YYYYMMDD
            end_time: 结束日期 YYYYMMDD（仅日志展示，底层不限制）
            dividend_type: 复权方式 none/front/back/front_ratio/back_ratio

        Returns:
            {stock_code: pd.DataFrame}，DataFrame 包含
            trade_date/open/close/high/low/volume/amount/change/pre_close/pct_chg 列
        """
        if not stock_list:
            return {}

        sd = start_time.replace("-", "")
        ed = end_time.replace("-", "") if end_time else "latest"

        logger.debug(
            "获取日线: stocks=%d start=%s end=%s dividend=%s",
            len(stock_list), sd, ed, dividend_type,
        )

        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._download_and_get_kline, stock_list, sd, dividend_type),
                timeout=self._DOWNLOAD_TIMEOUT,
            )
        except TimeoutError as e:
            raise DataCollectionError(
                f"下载超时 stocks={stock_list} start={sd} timeout={self._DOWNLOAD_TIMEOUT}s"
            ) from e

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
            "获取日线完成: start=%s 请求=%d 有数据=%d 总行数=%d",
            sd, len(stock_list), nonempty, row_sum,
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
            df["pct_chg"] = df["close"].pct_change(fill_method=None).round(4) * 100
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
        dividend_type: str = "front",
    ) -> dict[str, Any]:
        """同步方法：先下载补缓存，再获取K线数据。

        download_history_data2 不指定 end_time，QMT 默认下载到最新交易日；
        get_market_data_ex 读取已下载缓存。底层同步，并发由上层业务控制。
        """
        # 阶段 1: 下载补缓存（不指定 end_time，QMT 默认下载到最新交易日）
        xtdata.download_history_data2(stock_list, "1d", start_time)

        # 阶段 2: 读取数据
        raw = xtdata.get_market_data_ex(
            field_list=[],
            stock_list=stock_list,
            period="1d",
            start_time=start_time,
            count=-1,
            dividend_type=dividend_type,
            fill_data=True,
        )

        if not isinstance(raw, dict):
            logger.warning("get_market_data_ex 非 dict start=%s", start_time)
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

    @classmethod
    def sync_get_full_tick(cls, code_list: list[str]) -> dict[str, Any]:
        """同步获取全推 Tick 数据，供 WebSocket SPI 在线程池中调用。"""
        if not code_list:
            return {}
        logger.info("同步获取全推Tick: codes=%s", code_list)
        return cast(dict[str, Any], cls._with_lock(xtdata.get_full_tick, code_list))

    # ── 分钟级行情 ────────────────────────────────────────

    async def fetch_kline_minute(
        self,
        stock_list: list[str],
        period: str = "1m",
        start_time: str = "",
        end_time: str = "",
    ) -> dict[str, pd.DataFrame]:
        """获取分钟级行情数据（先下载补缓存，再获取）。

        用于盘后全量补全或历史分钟线查询。

        Args:
            stock_list: 证券代码列表，如 ["600000.SH"]
            period: K线周期，如 "1m"/"5m"/"15m"/"30m"/"1h"
            start_time: 起始时间 YYYYMMDD 或 YYYYMMDDHHMMSS
            end_time: 结束时间（可选，空表示到最新）

        Returns:
            {stock_code: pd.DataFrame}，DataFrame 包含
            trade_time/open/high/low/close/volume/amount 列
        """
        if not stock_list:
            return {}

        sd = start_time.replace("-", "")
        ed = end_time.replace("-", "") if end_time else ""

        logger.debug(
            "获取分钟线: stocks=%d period=%s start=%s end=%s",
            len(stock_list), period, sd, ed,
        )

        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._download_and_get_kline_minute, stock_list, period, sd, ed),
                timeout=self._DOWNLOAD_TIMEOUT,
            )
        except TimeoutError as e:
            raise DataCollectionError(
                f"下载分钟线超时 stocks={stock_list} period={period} start={sd} "
                f"timeout={self._DOWNLOAD_TIMEOUT}s"
            ) from e

        out: dict[str, pd.DataFrame] = {}
        nonempty = 0
        row_sum = 0
        for sym in stock_list:
            df = raw.get(sym)
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                out[sym] = self._format_minute_kline(df)
                nonempty += 1
                row_sum += len(out[sym])
            else:
                out[sym] = pd.DataFrame()

        logger.debug(
            "获取分钟线完成: period=%s 请求=%d 有数据=%d 总行数=%d",
            period, len(stock_list), nonempty, row_sum,
        )
        return out

    def _download_and_get_kline_minute(
        self,
        stock_list: list[str],
        period: str,
        start_time: str,
        end_time: str = "",
    ) -> dict[str, Any]:
        """同步方法：下载并获取分钟级K线数据。

        与日线不同：download_history_data2 指定 end_time（分钟线需精确控制范围）。
        """
        # 阶段 1: 下载补缓存
        xtdata.download_history_data2(stock_list, period, start_time, end_time)

        # 阶段 2: 读取数据
        raw = xtdata.get_market_data_ex(
            field_list=[],
            stock_list=stock_list,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=-1,
        )

        if not isinstance(raw, dict):
            logger.warning("get_market_data_ex 非 dict period=%s start=%s", period, start_time)
            return {s: pd.DataFrame() for s in stock_list}

        return raw

    @staticmethod
    def _format_minute_kline(df: pd.DataFrame) -> pd.DataFrame:
        """将 xtdata 原始分钟K线 DataFrame 转换为标准格式。

        与日线 _format_kline 不同：
        - 时间戳为 datetime（带时间），非 date
        - amount 单位为元，不除以 1000
        - 不计算 pre_close/change/pct_chg（日级概念）
        """
        df = df.reset_index()
        df = df.rename(columns={df.columns[0]: "trade_time"})

        if "trade_time" in df.columns:
            df["trade_time"] = pd.to_datetime(df["trade_time"])

        if "volume" in df.columns:
            df["volume"] = df["volume"].astype(int)

        keep_cols = ["trade_time", "open", "high", "low", "close", "volume", "amount"]
        existing = [c for c in keep_cols if c in df.columns]
        return df[existing]

    def subscribe_minute_bar(
        self,
        stock_codes: list[str],
        callback: Callable[[str, dict[str, Any]], None],
        period: str = "1m",
    ) -> list[int]:
        """订阅实时分钟K线（盘中用）。

        xtdata.subscribe_quote 仅支持单个股票代码，本方法逐个订阅并返回全部 seq。

        回调在 QMT 内部线程中执行，如需访问 asyncio 资源（如 DB 写入），
        调用方需通过 asyncio.run_coroutine_threadsafe 桥接。

        Args:
            stock_codes: 证券代码列表（Tushare 格式，如 ["600000.SH"]）
            callback: 收到新分钟线时的回调，签名 callback(stock_code, bar_data)
                      bar_data 包含 keys: time, open, high, low, close, volume, amount
            period: K线周期，默认 "1m"

        Returns:
            订阅序号列表（用于 unsubscribe 取消订阅）
        """
        def _on_data(datas: dict[str, Any]) -> None:
            """xtdata 回调：{stock_code: [bar_dict, ...]}"""
            for stock_code, bars in datas.items():
                if not bars:
                    continue
                latest_bar = bars[-1]
                callback(stock_code, latest_bar)

        seqs: list[int] = []
        try:
            for code in stock_codes:
                seq = cast(int, self._with_lock(
                    xtdata.subscribe_quote,
                    code,
                    period=period,
                    count=1,
                    callback=_on_data,
                ))
                seqs.append(seq)
        except Exception:
            # 部分成功时回滚已订阅的
            for seq in seqs:
                try:
                    self._with_lock(xtdata.unsubscribe_quote, seq)
                except Exception:
                    pass
            raise
        logger.info("订阅分钟线: period=%s stocks=%d seqs=%s", period, len(stock_codes), seqs)
        return seqs

    def subscribe_whole_quote(
        self,
        stock_codes: list[str],
        callback: Callable[[dict[str, dict[str, Any]]], None],
    ) -> int:
        """订阅全推快照（盘中异动扫描用）。

        回调在 QMT 内部线程中执行，调用方需确保回调函数线程安全。

        Args:
            stock_codes: 证券代码列表
            callback: 收到全推快照时的回调，签名 callback(datas)
                      datas 格式: {qmt_symbol: {lastPrice, volume, amount, ...}}

        Returns:
            订阅序号（用于 unsubscribe_quote 取消订阅）
        """
        seq = cast(int, self._with_lock(
            xtdata.subscribe_whole_quote,
            stock_codes,
            callback=callback,
        ))
        logger.info("订阅全推快照: stocks=%d seq=%s", len(stock_codes), seq)
        return seq

    def unsubscribe(self, seq: int) -> None:
        """取消订阅"""
        self._with_lock(xtdata.unsubscribe_quote, seq)
        logger.info("取消订阅: seq=%s", seq)

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
