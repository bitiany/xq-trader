"""QMT 数据采集服务 — 封装 xtdata 行情数据采集接口。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from xtquant import xtdata

logger = logging.getLogger(__name__)


class QmtDataCollector:
    """QMT 行情数据采集服务。

    封装 xtdata 模块，提供 K线、Tick、财务数据等采集能力。
    xtdata 是同步 API，通过 asyncio.to_thread 适配异步框架。
    """

    async def connect(self) -> None:
        """连接 MiniQMT 行情服务。"""
        result = await asyncio.to_thread(xtdata.connect)
        logger.info("QMT 行情连接完成: result=%s", result)

    async def disconnect(self) -> None:
        """断开行情连接。"""
        await asyncio.to_thread(xtdata.disconnect)
        logger.info("QMT 行情连接已断开")

    # ── K线数据 ──────────────────────────────────────────

    async def get_market_data(
        self,
        stock_list: list[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
        dividend_type: str = "none",
        fill_data: bool = True,
    ) -> dict[str, Any]:
        """获取行情数据（K线）。

        Args:
            stock_list: 证券代码列表，如 ["600000.SH", "000001.SZ"]
            period: 周期，如 tick/1m/5m/15m/30m/1h/1d/1w/1mon
            start_time: 起始时间，格式 YYYYMMDD 或 YYYYMMDDHHmmss
            end_time: 结束时间
            count: 数据条数，-1 表示全部
            dividend_type: 复权方式 none/front/back/front_ratio/back_ratio
            fill_data: 是否填充缺失数据
        """
        logger.info(
            "获取行情数据: stocks=%s period=%s start=%s end=%s count=%s",
            stock_list, period, start_time, end_time, count,
        )
        return await asyncio.to_thread(
            xtdata.get_market_data,
            field_list=[],
            stock_list=stock_list,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            fill_data=fill_data,
        )

    async def get_market_data_ex(
        self,
        stock_list: list[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
        dividend_type: str = "none",
        fill_data: bool = True,
    ) -> dict[str, Any]:
        """获取行情数据（增强版，返回按股票分组的 DataFrame）。

        参数同 get_market_data，返回格式为 {stock_code: pd.DataFrame}。
        """
        logger.info(
            "获取行情数据(ex): stocks=%s period=%s start=%s end=%s count=%s",
            stock_list, period, start_time, end_time, count,
        )
        return await asyncio.to_thread(
            xtdata.get_market_data_ex,
            field_list=[],
            stock_list=stock_list,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            fill_data=fill_data,
        )

    # ── Tick 数据 ────────────────────────────────────────

    async def get_full_tick(self, code_list: list[str]) -> dict[str, Any]:
        """获取全推 Tick 数据（最新分笔）。

        Args:
            code_list: 证券代码列表
        """
        logger.info("获取全推Tick: codes=%s", code_list)
        return await asyncio.to_thread(xtdata.get_full_tick, code_list)

    # ── 历史数据下载 ──────────────────────────────────────

    async def download_history_data(
        self,
        stock_code: str,
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
    ) -> None:
        """下载单只证券历史行情数据。

        Args:
            stock_code: 证券代码
            period: 周期
            start_time: 起始时间
            end_time: 结束时间
        """
        logger.info(
            "下载历史数据: stock=%s period=%s start=%s end=%s",
            stock_code, period, start_time, end_time,
        )
        await asyncio.to_thread(
            xtdata.download_history_data,
            stock_code, period, start_time, end_time,
        )

    async def download_history_data2(
        self,
        stock_list: list[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
    ) -> None:
        """批量下载历史行情数据。

        Args:
            stock_list: 证券代码列表
            period: 周期
            start_time: 起始时间
            end_time: 结束时间
        """
        logger.info(
            "批量下载历史数据: stocks=%s period=%s start=%s end=%s",
            stock_list, period, start_time, end_time,
        )
        await asyncio.to_thread(
            xtdata.download_history_data2,
            stock_list, period, start_time, end_time,
        )

    # ── 财务数据 ──────────────────────────────────────────

    async def get_financial_data(
        self,
        stock_list: list[str],
        table_list: list[str] | None = None,
        start_time: str = "",
        end_time: str = "",
        report_type: str = "report_time",
    ) -> dict[str, Any]:
        """获取财务数据。

        Args:
            stock_list: 证券代码列表
            table_list: 报表名列表，如 ["Balance", "Income", "CashFlow"]
            start_time: 起始时间
            end_time: 结束时间
            report_type: 报告类型 report_time/announce_time
        """
        logger.info(
            "获取财务数据: stocks=%s tables=%s start=%s end=%s",
            stock_list, table_list, start_time, end_time,
        )
        return await asyncio.to_thread(
            xtdata.get_financial_data,
            stock_list, table_list or [], start_time, end_time, report_type,
        )

    async def download_financial_data(
        self,
        stock_list: list[str],
        table_list: list[str] | None = None,
        start_time: str = "",
        end_time: str = "",
    ) -> None:
        """下载财务数据。"""
        logger.info(
            "下载财务数据: stocks=%s tables=%s start=%s end=%s",
            stock_list, table_list, start_time, end_time,
        )
        await asyncio.to_thread(
            xtdata.download_financial_data,
            stock_list, table_list or [], start_time, end_time,
        )

    # ── 合约信息 ──────────────────────────────────────────

    async def get_instrument_detail(self, stock_code: str) -> dict[str, Any] | None:
        """获取合约基础信息。"""
        logger.info("获取合约信息: stock=%s", stock_code)
        return await asyncio.to_thread(xtdata.get_instrument_detail, stock_code)

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
            xtdata.get_trading_dates, market, start_time, end_time, count,
        )

    # ── 板块与指数 ────────────────────────────────────────

    async def get_sector_list(self) -> list[str]:
        """获取板块列表。"""
        logger.info("获取板块列表")
        return await asyncio.to_thread(xtdata.get_sector_list)

    async def get_stock_list_in_sector(self, sector_name: str) -> list[str]:
        """获取板块成分股。"""
        logger.info("获取板块成分股: sector=%s", sector_name)
        return await asyncio.to_thread(xtdata.get_stock_list_in_sector, sector_name)

    async def get_index_weight(self, index_code: str) -> dict[str, Any]:
        """获取指数成分权重。"""
        logger.info("获取指数权重: index=%s", index_code)
        return await asyncio.to_thread(xtdata.get_index_weight, index_code)
