"""资金流向增量采集 Stage — 逐日采集全市场个股资金流向数据。

执行流程：
  1. 确定日期范围 [start_date, end_date]
  2. 获取交易日列表
  3. 逐日执行：采集 → 清洗 → 持久化 → 更新标的水位

数据源：Tushare moneyflow_dc 接口（东方财富，基于 L2 主动买卖单统计）。
数据起始日期：2023-09-11。
逐日采集时传入 trade_date 获取全市场当日数据。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.market.models.fund_flow import FundFlowIndividual
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger(__name__)

_collector: TushareDataCollector | None = None

_DATA_TYPE = "fund_flow"

# 持久化配置
_PERSIST_UPDATE_FIELDS = [
    "huge_buy_amt", "huge_sell_amt", "huge_net_amt", "huge_net_pct",
    "big_buy_amt", "big_sell_amt", "big_net_amt", "big_net_pct",
    "mid_buy_amt", "mid_sell_amt", "mid_net_amt", "mid_net_pct",
    "small_buy_amt", "small_sell_amt", "small_net_amt", "small_net_pct",
    "main_net_amt", "main_net_pct",
    "net_mf_amt",
]

_PERSIST_CUSTOM_TRANSFORMS = {
    "trade_date": lambda v: date.fromisoformat(str(v)) if v and str(v) != "nan" else None,
}


def _get_collector() -> TushareDataCollector:
    """延迟初始化 TushareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = TushareDataCollector()
    return _collector


def clean_fund_flow_dc_data(df: pd.DataFrame) -> pd.DataFrame:
    """moneyflow_dc 数据清洗 — 东财数据源，各档 buy_* 字段实为净流入额/占比。

    moneyflow_dc 不返回买卖分拆金额，仅映射净流入相关字段到 FundFlowIndividual。
    """
    numeric_cols = [
        "close", "pct_change",
        "huge_net_amt", "huge_net_pct",
        "big_net_amt", "big_net_pct",
        "mid_net_amt", "mid_net_pct",
        "small_net_amt", "small_net_pct",
        "main_net_amt", "main_net_pct",
        "net_mf_amt",
    ]
    net_mapping = {
        "buy_elg_amount": "huge_net_amt",
        "buy_lg_amount": "big_net_amt",
        "buy_md_amount": "mid_net_amt",
        "buy_sm_amount": "small_net_amt",
    }
    pct_mapping = {
        "buy_elg_amount_rate": "huge_net_pct",
        "buy_lg_amount_rate": "big_net_pct",
        "buy_md_amount_rate": "mid_net_pct",
        "buy_sm_amount_rate": "small_net_pct",
    }

    df = df.rename(columns={"ts_code": "symbol"})

    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")

    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return df

    for src, dst in net_mapping.items():
        if src in df.columns:
            df[dst] = pd.to_numeric(df[src], errors="coerce")

    for src, dst in pct_mapping.items():
        if src in df.columns:
            df[dst] = pd.to_numeric(df[src], errors="coerce")

    if "net_amount" in df.columns:
        df["net_mf_amt"] = pd.to_numeric(df["net_amount"], errors="coerce")
    if "net_amount_rate" in df.columns:
        df["main_net_pct"] = pd.to_numeric(df["net_amount_rate"], errors="coerce")

    if "huge_net_amt" in df.columns and "big_net_amt" in df.columns:
        df["main_net_amt"] = df["huge_net_amt"] + df["big_net_amt"]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].round(4)

    df = df.dropna(subset=["symbol", "trade_date"])
    return df.reset_index(drop=True)


async def persist_fund_flow_data(df: pd.DataFrame) -> int:
    """将资金流向数据 upsert 到 FundFlowIndividual 表。"""
    df["source"] = "tushare"
    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=FundFlowIndividual,
        custom_transforms=_PERSIST_CUSTOM_TRANSFORMS,
    )
    if not instances:
        return 0
    return await FundFlowIndividual.bulk_create_or_update(
        instances,  # type: ignore[arg-type]
        on_conflict=["symbol", "trade_date", "source"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=100,
    )


class FundFlowIncrementalStage:
    """资金流向增量采集 Stage — 逐日采集全市场个股资金流向数据。"""

    DATA_TYPE = _DATA_TYPE

    async def execute(self, start_date: date, end_date: date) -> dict[str, Any]:
        """执行增量采集。

        Args:
            start_date: 增量起始日期（含）
            end_date: 增量结束日期（含）

        Returns:
            执行结果汇总
        """
        # 获取交易日列表
        trade_dates = await self._get_trade_dates(start_date, end_date)
        if not trade_dates:
            logger.info("[fund_flow.incremental] 无需采集的交易日")
            return {"total": 0, "succeeded": 0, "failed": 0, "persisted": 0}

        # 获取标的级水位
        watermark_map = await self._get_watermark_map()

        logger.info(
            "[fund_flow.incremental] 开始: range=%s~%s trade_days=%d",
            start_date, end_date, len(trade_dates),
        )

        total = len(trade_dates)
        succeeded = 0
        failed = 0
        total_persisted = 0

        for idx, td in enumerate(trade_dates, 1):
            try:
                persisted = await self._process_trade_date(td, watermark_map)
                succeeded += 1
                total_persisted += persisted
            except Exception as e:
                failed += 1
                logger.error(
                    "[fund_flow.incremental] 日期 %s 失败: %s",
                    td, e, exc_info=True,
                )

            if idx % 5 == 0 or idx == total:
                logger.info(
                    "[fund_flow.incremental] 进度: %d/%d days succeeded=%d failed=%d persisted=%d",
                    idx, total, succeeded, failed, total_persisted,
                )

        logger.info(
            "[fund_flow.incremental] 完成: range=%s~%s days=%d succeeded=%d failed=%d persisted=%d",
            start_date, end_date, total, succeeded, failed, total_persisted,
        )
        return {"total": total, "succeeded": succeeded, "failed": failed, "persisted": total_persisted}

    async def _process_trade_date(
        self,
        trade_date: date,
        watermark_map: dict[str, date],
    ) -> int:
        """处理单个交易日：采集→清洗→持久化→更新标的水位。"""
        ts_date = trade_date.strftime("%Y%m%d")

        # moneyflow_dc 按交易日全市场采集
        raw = await _get_collector().fetch_moneyflow_dc(trade_date=ts_date)
        if raw is None or raw.empty:
            logger.debug("[fund_flow.incremental] 无数据: %s", trade_date)
            return 0

        df = clean_fund_flow_dc_data(raw)
        if df.empty:
            return 0

        # 按标的水位过滤：单日采集，直接过滤水位 >= 当日的标的
        if watermark_map:
            skip_codes = {code for code, wm in watermark_map.items() if wm >= trade_date}
            if skip_codes:
                df = df[~df["symbol"].isin(skip_codes)]
                if df.empty:
                    return 0

        # 持久化
        count = await persist_fund_flow_data(df)

        # 更新标的级水位
        if count > 0:
            await self._update_item_watermarks(df, trade_date)

        return count

    @staticmethod
    async def _get_trade_dates(start_date: date, end_date: date) -> list[date]:
        """获取日期范围内的交易日列表。"""
        rows = await TradeCalendar.filter(
            exchange="SSE",
            is_open=True,
            cal_date__gte=start_date,
            cal_date__lte=end_date,
            order_by=TradeCalendar.cal_date.asc(),
        )
        return [row.cal_date for row in rows]

    @staticmethod
    async def _get_watermark_map() -> dict[str, date]:
        """获取标的级水位映射 {code: watermark_date}。"""
        rows = await CollectWatermark.filter(data_type=_DATA_TYPE, status="active")
        return {row.watermark_code: row.watermark_date for row in rows if row.watermark_date is not None}

    @staticmethod
    async def _update_item_watermarks(df: pd.DataFrame, trade_date: date) -> None:
        """批量更新有新数据的标的的水位日期（使用 bulk_create_or_update）。

        仅更新上市标的的水位，跳过退市标的（避免退市标的水位被反复更新）。
        """
        from xqtrader.domain.security.models import Security  # noqa: PLC0415

        listed = await Security.filter(list_status="L")
        listed_codes = {s.symbol for s in listed}

        codes = [c for c in df["symbol"].unique().tolist() if c in listed_codes]
        if not codes:
            return
        instances = [
            CollectWatermark(
                data_type=_DATA_TYPE,
                watermark_code=code,
                watermark_date=trade_date,
                record_count=0,
                status="active",
            )
            for code in codes
        ]
        await CollectWatermark.bulk_create_or_update(
            instances,
            on_conflict=["data_type", "watermark_code"],
            update_fields=["watermark_date"],
        )
