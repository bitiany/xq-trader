"""证券标的基本信息采集任务。

数据源：Tushare stock_basic 接口，采集全市场证券标的基本信息写入 Security 表。
采集流程：
  1. 调用 Tushare stock_basic 获取标的列表
  2. 清洗数据（列映射、去重、格式统一）
  3. 批量 upsert 到 Security 表

Tushare stock_basic 接口按上市状态分批采集（L/D/P），每次返回全量数据。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
from framework.scheduler.base_task import BaseTask
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.security.models import Security

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
    "act_name", "act_type",
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

    # 填充缺失的可选字段为空字符串
    for col in _PERSIST_UPDATE_FIELDS:
        if col in df.columns:
            df[col] = df[col].fillna("")
        else:
            df[col] = ""

    return df.reset_index(drop=True)


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
    """

    task_name = "reference.security_info_collect"
    description = "采集全市场证券标的基本信息（Tushare stock_basic）"
    time_limit = 600
    soft_time_limit = 570

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        list_status: str = kwargs.get("list_status", "")

        # 按上市状态分批采集（为空时采集全部 L/D/P）
        statuses = [list_status] if list_status else ["L", "D", "P"]
        total_persisted = 0
        results: dict[str, int] = {}

        for status in statuses:
            logger.info("[security_info] 开始采集: list_status=%s", status)
            df = await _get_collector().fetch_stock_basic(list_status=status)
            if df is None or df.empty:
                logger.info("[security_info] 无数据: list_status=%s", status)
                results[status] = 0
                continue

            logger.info("[security_info] 获取完成: list_status=%s rows=%d", status, len(df))

            # 清洗
            df = _clean_stock_basic_data(df)
            if df.empty:
                results[status] = 0
                continue

            # 持久化
            count = await _persist_security_data(df)
            total_persisted += count
            results[status] = count
            logger.info("[security_info] 持久化完成: list_status=%s persisted=%d", status, count)

        logger.info("[security_info] 全部完成: total_persisted=%d details=%s", total_persisted, results)
        return {"total_persisted": total_persisted, "details": results}
