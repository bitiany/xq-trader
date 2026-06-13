"""证券标的基本信息采集任务。

数据源：Tushare stock_basic + suspend_d 接口。
采集流程：
  1. 调用 Tushare stock_basic 一次获取全量标的列表
  2. 调用 Tushare suspend_d 获取当日停牌信息，合并到 DataFrame
  3. 清洗数据后一次 upsert 到 Security 表

Tushare stock_basic 接口不传 list_status 时返回全部上市状态（L/D/P）的数据。
Tushare suspend_d 接口按日期获取停牌标的，S-停牌，R-复牌/正常交易。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
from framework.scheduler.base_task import BaseTask
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.security.models import Security
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger(__name__)

_collector: TushareDataCollector | None = None

# Tushare stock_basic 字段 → Security 模型字段
# ts_code（如 301669.SZ）映射为 Security 表主键 symbol；
# Tushare 原始 symbol 列（如 301669，无后缀）需在清洗时删除，避免冲突
# act_ent_type → act_type（实控人企业性质 → 实控人类型）
# delist_date → del_date（退市日期字段名不同）
_COLUMN_MAPPING: dict[str, str] = {
    "ts_code": "symbol",
    "act_ent_type": "act_type",
    "delist_date": "del_date",
}

# 数值/字符串列无需特殊转换，直接映射
# 注意：仅包含 Tushare stock_basic 接口实际返回的字段，
# 不包含 board_type/introduction 等数据源不提供的字段，避免 upsert 时覆写为空串
_PERSIST_UPDATE_FIELDS = [
    "code", "name", "area", "industry", "fullname", "enname",
    "cnspell", "market", "exchange", "curr_type",
    "list_date", "list_status", "del_date", "is_hs",
    "act_name", "act_type", "suspend_status",
]


def _get_collector() -> TushareDataCollector:
    """延迟初始化 TushareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = TushareDataCollector()
    return _collector


def _clean_stock_basic_data(df: pd.DataFrame) -> pd.DataFrame:
    """清洗 stock_basic 数据。

    1. 删除 Tushare 原始 symbol 列（无后缀，如 301669），避免与映射后的 symbol 冲突
    2. 列名映射（ts_code → symbol）
    3. code 字段与 symbol 相同（均为 TS代码格式，如 301669.SZ）
    4. 删除 symbol 为空的行
    5. 去重（按 symbol）
    """
    # 1. 删除 Tushare 原始 symbol 列
    if "symbol" in df.columns:
        df = df.drop(columns=["symbol"])

    # 2. 列名映射
    df = df.rename(columns=_COLUMN_MAPPING)

    # 3. code 字段与 symbol 相同
    df["code"] = df["symbol"]

    # 4. 删除关键字段为空的行
    df = df.dropna(subset=["symbol"])
    if df.empty:
        return df

    # 5. 去重
    df = df.drop_duplicates(subset=["symbol"], keep="first")

    # 填充缺失的字段为空字符串（遍历模型所有非自增列，确保 upsert 时不出现 NaN）
    for col in Security.__table__.columns:
        if col.autoincrement is True:
            continue
        col_name = col.name
        if col_name in df.columns:
            df[col_name] = df[col_name].fillna("")
        else:
            df[col_name] = ""

    return df.reset_index(drop=True)


def _merge_suspend_status(
    df: pd.DataFrame,
    suspended_codes: set[str],
) -> pd.DataFrame:
    """将停牌状态合并到 DataFrame 的 suspend_status 列。

    - 停牌标的 → "S"
    - 其余标的 → "R"（正常交易）

    Args:
        df: 已清洗的 stock_basic DataFrame，必须包含 symbol 列
        suspended_codes: 当日停牌标的集合

    Returns:
        合并停牌状态后的 DataFrame
    """
    df["suspend_status"] = "R"  # 默认正常交易
    if suspended_codes:
        mask = df["symbol"].isin(suspended_codes)
        df.loc[mask, "suspend_status"] = "S"
    return df


async def _fetch_suspended_codes(trade_date: date) -> set[str]:
    """获取指定交易日的停牌标的集合。

    Args:
        trade_date: 查询停牌信息的交易日

    Returns:
        停牌标的集合
    """
    date_str = trade_date.strftime("%Y%m%d")

    suspend_df = await _get_collector().fetch_suspend_d(
        trade_date=date_str, suspend_type="S",
    )
    if suspend_df is not None and not suspend_df.empty:
        codes = set(suspend_df["ts_code"].unique().tolist())
        logger.info("[security_info] 当日停牌标的: %d 只", len(codes))
        return codes

    return set()


async def _persist_security_data(df: pd.DataFrame) -> int:
    """将证券基本信息 upsert 到 Security 表。"""
    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=Security,
    )
    if not instances:
        return 0
    return await Security.bulk_create_or_update(
        instances,  # type: ignore[arg-type]
        on_conflict=["symbol"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=500,
    )


class SecurityInfoCollectTask(BaseTask):
    """证券标的基本信息采集任务。

    入参：
      - list_status: 上市状态（L/D/P，为空则采集全部）
      - trade_date: 停复牌查询日期（YYYYMMDD，为空则取最新交易日）
    """

    task_name = "reference.security_info_collect"
    description = "采集全市场证券标的基本信息（Tushare stock_basic）并同步停复牌状态"
    time_limit = 600
    soft_time_limit = 570

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        list_status: str = kwargs.get("list_status", "")
        trade_date_str: str = kwargs.get("trade_date", "")

        # ── Step 1: 获取停复牌信息 ──
        td: date | None = None
        if trade_date_str:
            td = date(
                int(trade_date_str[:4]),
                int(trade_date_str[4:6]),
                int(trade_date_str[6:8]),
            )
        else:
            td = await TradeCalendar.get_latest_trade_date()

        suspended_codes: set[str] = set()
        if td is not None:
            logger.info("[security_info] 获取停牌信息: trade_date=%s", td)
            suspended_codes = await _fetch_suspended_codes(td)

        # ── Step 2: 采集 stock_basic 数据 ──
        logger.info("[security_info] 开始采集 stock_basic: list_status=%s", list_status or "全部")
        df = await _get_collector().fetch_stock_basic(list_status=list_status)
        if df is None or df.empty:
            logger.info("[security_info] stock_basic 无数据")
            return {"total_persisted": 0, "suspended": len(suspended_codes)}

        logger.info("[security_info] stock_basic 获取完成: rows=%d", len(df))

        # ── Step 3: 清洗 + 合并停复牌状态 ──
        df = _clean_stock_basic_data(df)
        if df.empty:
            return {"total_persisted": 0, "suspended": len(suspended_codes)}

        df = _merge_suspend_status(df, suspended_codes)

        # ── Step 4: 一次 upsert ──
        count = await _persist_security_data(df)
        logger.info(
            "[security_info] 全部完成: persisted=%d suspended=%d",
            count, len(suspended_codes),
        )
        return {
            "total_persisted": count,
            "suspended": len(suspended_codes),
        }
