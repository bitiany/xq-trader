"""资金流向增量采集 Stage — 逐日采集全市场个股资金流向数据。

执行流程：
  1. 确定日期范围 [start_date, end_date]
  2. 获取交易日列表
  3. 逐日执行：采集 → 清洗 → 持久化 → 更新标的水位

数据源：Tushare moneyflow 接口（单次上限 6000 条）。
逐日采集时传入 trade_date 获取全市场当日数据，若返回达到上限则按标的补采。
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

# moneyflow 接口字段 → FundFlowIndividual 模型字段
_COLUMN_MAPPING: dict[str, str] = {
    "ts_code": "symbol",
    "buy_elg_amount": "huge_buy_amt",
    "sell_elg_amount": "huge_sell_amt",
    "buy_lg_amount": "big_buy_amt",
    "sell_lg_amount": "big_sell_amt",
    "buy_md_amount": "mid_buy_amt",
    "sell_md_amount": "mid_sell_amt",
    "buy_sm_amount": "small_buy_amt",
    "sell_sm_amount": "small_sell_amt",
    "net_mf_amount": "net_mf_amt",
}

# 买卖金额列（用于计算净流入额和占比）
_BUY_SELL_PAIRS: list[tuple[str, str, str]] = [
    ("huge_buy_amt", "huge_sell_amt", "huge_net_amt"),
    ("big_buy_amt", "big_sell_amt", "big_net_amt"),
    ("mid_buy_amt", "mid_sell_amt", "mid_net_amt"),
    ("small_buy_amt", "small_sell_amt", "small_net_amt"),
]

# 净流入额列名 → 占比列名映射
_NET_TO_PCT: dict[str, str] = {
    "huge_net_amt": "huge_net_pct",
    "big_net_amt": "big_net_pct",
    "mid_net_amt": "mid_net_pct",
    "small_net_amt": "small_net_pct",
}

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

# moneyflow 单次上限（Tushare 官方文档：单次最大提取6000行记录）
_MONEYFLOW_ROW_LIMIT = 6000


def _get_collector() -> TushareDataCollector:
    """延迟初始化 TushareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = TushareDataCollector()
    return _collector


def clean_fund_flow_data(df: pd.DataFrame) -> pd.DataFrame:
    """资金流向数据清洗 — 列映射 + 派生字段计算。

    1. 列名映射（moneyflow → FundFlowIndividual）
    2. trade_date 格式统一 YYYY-MM-DD
    3. 删除 trade_date 为空
    4. 买卖金额列强制转 numeric
    5. 计算各档净流入额
    6. 计算主力净流入额
    7. 计算各档占比
    8. 计算主力占比
    9. 数值列精度 4 位小数
    10. 删除 symbol/trade_date 仍有 NaN 的行
    """
    amount_cols = [
        "huge_buy_amt", "huge_sell_amt",
        "big_buy_amt", "big_sell_amt",
        "mid_buy_amt", "mid_sell_amt",
        "small_buy_amt", "small_sell_amt",
        "net_mf_amt",
    ]
    all_numeric_cols = [
        *amount_cols,
        "main_net_amt", "main_net_pct",
        "huge_net_amt", "huge_net_pct",
        "big_net_amt", "big_net_pct",
        "mid_net_amt", "mid_net_pct",
        "small_net_amt", "small_net_pct",
    ]

    # 1. 列名映射
    df = df.rename(columns=_COLUMN_MAPPING)

    # 2. trade_date 格式统一
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")

    # 3. 删除 trade_date 为空
    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return df

    # 4. 买卖金额列强制转 numeric
    for col in amount_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 5. 计算各档净流入额
    for buy_col, sell_col, net_col in _BUY_SELL_PAIRS:
        if buy_col in df.columns and sell_col in df.columns:
            df[net_col] = df[buy_col] - df[sell_col]

    # 6. 主力净流入额
    if "huge_net_amt" in df.columns and "big_net_amt" in df.columns:
        df["main_net_amt"] = df["huge_net_amt"] + df["big_net_amt"]

    # 7. 各档占比
    for buy_col, sell_col, net_col in _BUY_SELL_PAIRS:
        pct_col = _NET_TO_PCT.get(net_col)
        if pct_col and buy_col in df.columns and sell_col in df.columns and net_col in df.columns:
            total = df[buy_col] + df[sell_col]
            df[pct_col] = (df[net_col] / total * 100).where(total != 0, 0)

    # 8. 主力占比
    required = ("main_net_amt", "huge_buy_amt", "huge_sell_amt", "big_buy_amt", "big_sell_amt")
    if all(c in df.columns for c in required):
        main_total = df["huge_buy_amt"] + df["huge_sell_amt"] + df["big_buy_amt"] + df["big_sell_amt"]
        df["main_net_pct"] = (df["main_net_amt"] / main_total * 100).where(main_total != 0, 0)

    # 9. 数值列精度
    for col in all_numeric_cols:
        if col in df.columns:
            df[col] = df[col].round(4)

    # 10. 删除关键列 NaN
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

        # 采集全市场当日数据
        df = await _get_collector().fetch_moneyflow(trade_date=ts_date)
        if df is None or df.empty:
            logger.debug("[fund_flow.incremental] 无数据: %s", trade_date)
            return 0

        # 检查是否达到上限，需要补采
        if len(df) >= _MONEYFLOW_ROW_LIMIT:
            logger.warning(
                "[fund_flow.incremental] 返回 %d 条达到上限 %d，可能存在截断: %s",
                len(df), _MONEYFLOW_ROW_LIMIT, trade_date,
            )
            df = await self._supplement_missing(df, ts_date)

        # 清洗
        df = clean_fund_flow_data(df)
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

    async def _supplement_missing(self, existing_df: pd.DataFrame, ts_date: str) -> pd.DataFrame:
        """当返回达到上限时，按标的批次补采缺失数据。"""
        existing_codes = set()
        if "ts_code" in existing_df.columns:
            existing_codes = set(existing_df["ts_code"].tolist())

        # 获取全市场标的，找出缺失的
        from xqtrader.domain.security.models import Security  # noqa: PLC0415

        all_securities = await Security.filter(list_status="L")
        all_codes = {s.symbol for s in all_securities}
        missing_codes = all_codes - existing_codes

        if not missing_codes:
            return existing_df

        logger.info(
            "[fund_flow.incremental] 补采缺失标的: date=%s missing=%d",
            ts_date, len(missing_codes),
        )

        # 按批次补采（每批 50 支，减少 API 调用次数）
        missing_list = sorted(missing_codes)
        batch_size = 50
        for i in range(0, len(missing_list), batch_size):
            batch = missing_list[i:i + batch_size]
            batch_str = ",".join(batch)
            try:
                extra = await _get_collector().fetch_moneyflow(ts_code=batch_str, trade_date=ts_date)
                if extra is not None and not extra.empty:
                    existing_df = pd.concat([existing_df, extra], ignore_index=True)
            except Exception as e:
                logger.warning(
                    "[fund_flow.incremental] 批量补采失败 batch=%d/%d: %s",
                    i // batch_size + 1, (len(missing_list) + batch_size - 1) // batch_size, e,
                )

        return existing_df

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
        """批量更新有新数据的标的的水位日期（使用 bulk_create_or_update）。"""
        codes = df["symbol"].unique().tolist()
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
