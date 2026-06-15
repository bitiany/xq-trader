"""A股利润表采集任务（Tushare income 数据源）。

数据源：Tushare income 接口（doc_id=33），采集上市公司利润表数据写入 IncomeStatement 表。
管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → CleanStage → PersistStage → WatermarkAspect(后切)

字段映射（income → IncomeStatement）：
  ts_code → symbol
  ann_date → ann_date
  f_ann_date → f_ann_date
  end_date → end_date
  其余字段同名

水位管理（WatermarkAspect）：
  - 前切：若指定 collect_date 则以该日期为起始；否则查询水位日期作为增量起始时间
  - 后切：持久化成功后更新水位日期为数据实际最新公告日期（ann_date）

注意事项：
  - income 接口单次最多返回按标的，需按标的逐个采集
  - 显式指定 fields 参数，确保全部字段（含默认不显示字段）均被采集
  - 利润表为季度数据，水位基于 ann_date（公告日期），非交易日维度
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
from framework.pipeline import (
    Pipeline,
    PipelineContext,
    PipelineEngine,
    PipelineError,
    Stage,
    StageResult,
)
from framework.scheduler.base_task import BaseTask
from worker.plugins.aspects import WatermarkAspect
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.market.models.income_statement import IncomeStatement
from xqtrader.domain.security.models import Security

logger = get_logger(__name__)

_collector: TushareDataCollector | None = None

_DATA_TYPE = "income_statement"

# income → IncomeStatement 列映射
_COLUMN_MAPPING: dict[str, str] = {
    "ts_code": "symbol",
}

# ORM 模型中存在的全部列名（用于过滤 Tushare 返回的额外字段）
_ORM_COLUMNS: set[str] = {c.name for c in IncomeStatement.__table__.columns}

# 数值列（需要强制转 numeric + 精度处理）— 仅 ORM 中存在的列
_NUMERIC_COLS = [c for c in _ORM_COLUMNS if c not in {
    "symbol", "ann_date", "f_ann_date", "end_date",
    "report_type", "comp_type", "end_type", "update_flag",
}]

# 持久化更新字段
_PERSIST_UPDATE_FIELDS = _NUMERIC_COLS

# 日期字段转换
_PERSIST_CUSTOM_TRANSFORMS = {
    "ann_date": lambda v: date_type.fromisoformat(str(v)) if v and str(v) != "nan" else None,
    "f_ann_date": lambda v: date_type.fromisoformat(str(v)) if v and str(v) != "nan" else None,
    "end_date": lambda v: date_type.fromisoformat(str(v)) if v and str(v) != "nan" else None,
}


def _get_collector() -> TushareDataCollector:
    """延迟初始化 TushareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = TushareDataCollector()
    return _collector


def clean_income_statement_data(df: pd.DataFrame) -> pd.DataFrame:
    """利润表数据清洗 — 列映射 + 格式统一 + 数值处理。

    1. 列名映射（income → IncomeStatement）
    2. 过滤掉 ORM 模型中不存在的列（Tushare 返回的额外字段）
    3. ann_date/f_ann_date/end_date 格式统一 YYYY-MM-DD
    4. 删除 symbol/end_date 为空的行
    5. update_flag 缺失填充 "1"（最新）
    6. 数值列强制转 numeric
    7. 数值列精度 4 位小数
    """
    # 1. 列名映射
    df = df.rename(columns=_COLUMN_MAPPING)

    # 2. 过滤掉 ORM 中不存在的列，避免持久化时属性错误
    extra_cols = [c for c in df.columns if c not in _ORM_COLUMNS]
    if extra_cols:
        logger.debug("[income_statement.clean] 过滤 ORM 外字段: %s", extra_cols)
        df = df[[c for c in df.columns if c in _ORM_COLUMNS]]

    # 3. 日期格式统一
    for col in ("ann_date", "f_ann_date", "end_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], format="%Y%m%d", errors="coerce").dt.strftime("%Y-%m-%d")

    # 4. 删除关键字段为空的行
    df = df.dropna(subset=["symbol", "end_date"])
    if df.empty:
        return df

    # 5. update_flag 缺失填充 "1"
    if "update_flag" in df.columns:
        df["update_flag"] = df["update_flag"].fillna("1")
    else:
        df["update_flag"] = "1"

    # 6. 数值列强制转 numeric
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 7. 数值列精度
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].round(4)

    return df.reset_index(drop=True)


async def persist_income_statement_data(df: pd.DataFrame) -> int:
    """将利润表数据 upsert 到 IncomeStatement 表。"""
    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=IncomeStatement,
        custom_transforms=_PERSIST_CUSTOM_TRANSFORMS,
    )
    if not instances:
        return 0
    return await IncomeStatement.bulk_create_or_update(
        instances,  # type: ignore[arg-type]
        on_conflict=["symbol", "end_date", "update_flag"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=100,
    )


class IncomeStatementError(PipelineError):
    """利润表采集异常基类。"""


class DownloadError(IncomeStatementError):
    """下载阶段异常。"""


class PersistError(IncomeStatementError):
    """持久化阶段异常。"""


class DownloadStage(Stage):
    """下载阶段 — 调用 TushareDataCollector 获取利润表数据。"""

    @property
    def name(self) -> str:
        return "download"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item
        start_date = ctx.get("start_date", "")
        end_date = ctx.get("end_date", "")

        if ctx.get("is_up_to_date"):
            return StageResult.ok(data={"stock_code": stock_code, "rows": 0, "skipped": True})

        if not start_date:
            return StageResult.fail(f"缺少 start_date，跳过 {stock_code}")

        try:
            ts_start = start_date.replace("-", "")
            ts_end = end_date.replace("-", "") if end_date else ""

            df = await _get_collector().fetch_income(
                ts_code=stock_code,
                start_date=ts_start,
                end_date=ts_end,
            )

            if df is None or df.empty:
                logger.debug(
                    "[income_statement.collect] 无数据: %s range=%s~%s",
                    stock_code, start_date, end_date,
                )
                ctx.set("download_data", None)
                ctx.set("row_count", 0)
                ctx.set("skip_persist", True)
            else:
                ctx.set("download_data", df)
                ctx.set("row_count", len(df))
                ctx.set("skip_persist", False)

            return StageResult.ok(data={"stock_code": stock_code, "rows": ctx.get("row_count", 0)})
        except Exception as e:
            raise DownloadError(f"下载失败 {stock_code}: {e}") from e


class CleanStage(Stage):
    """清洗阶段 — 对利润表数据进行列映射和数值处理。"""

    @property
    def name(self) -> str:
        return "clean"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        initial_len = len(df)
        df = clean_income_statement_data(df)

        ctx.set("download_data", df)
        ctx.set("row_count", len(df))

        cleaned = initial_len - len(df)
        if cleaned > 0:
            logger.debug(
                "[income_statement.collect] 清洗: %s removed %d invalid rows",
                stock_code, cleaned,
            )

        return StageResult.ok(data={"stock_code": stock_code, "cleaned": len(df)})


class PersistStage(Stage):
    """持久化阶段 — 将利润表数据写入 IncomeStatement 表。"""

    @property
    def name(self) -> str:
        return "persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        try:
            count = await persist_income_statement_data(df)

            ctx.set("persisted_count", count)
            # 水位基于 ann_date（公告日期），非报告期 end_date
            if count > 0 and "ann_date" in df.columns:
                valid_dates = df["ann_date"].dropna()
                if not valid_dates.empty:
                    max_td = valid_dates.map(
                        lambda v: date_type.fromisoformat(str(v))
                    ).max()
                    ctx.set("max_trade_date", max_td)

            logger.debug("[income_statement.collect] 持久化完成: %s rows=%d", stock_code, count)
            return StageResult.ok(data={"stock_code": stock_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {stock_code}: {e}") from e


class IncomeStatementCollectTask(BaseTask):
    """A股利润表采集任务（Tushare income 数据源）。

    入参：
      - data_type: 数据类型（默认 income_statement）
      - concurrency: 并发数（默认 3，income 接口限流较严）
      - stock_codes: 股票代码列表（为空时采集全市场）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 采集起始日期（格式 YYYY-MM-DD，为空时按水位日期增量采集）
    """

    task_name = "market.income_statement_collect"
    description = "A股利润表采集-Tushare income数据源（管道引擎并发）"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        data_type = kwargs.get("data_type", _DATA_TYPE)
        concurrency = kwargs.get("concurrency", 3)
        stock_codes: list[str] | None = kwargs.get("stock_codes")
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")

        # 获取标的列表
        if not stock_codes:
            stock_codes = await self._get_all_stock_codes()
            if not stock_codes:
                logger.warning("[income_statement.collect] 未找到任何标的代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        # 限制标的数量（用于测试）
        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.debug("[income_statement.collect] 限制标的数量: max_count=%d", max_count)

        # 构建全局上下文
        global_ctx: dict[str, Any] = {}
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "[income_statement.collect] 开始采集: pipeline=%s concurrency=%d stocks=%d collect_date=%s",
            data_type, concurrency, len(stock_codes), collect_date or "按水位",
        )

        # 组装管线: download → clean → persist
        pipeline = Pipeline(
            name=data_type,
            stages=[DownloadStage(), CleanStage(), PersistStage()],
            aspects=[WatermarkAspect(data_type=data_type)],
        )

        # 执行管道引擎
        engine = PipelineEngine(
            pipelines=[pipeline],
            concurrency=concurrency,
            global_context=global_ctx,
        )
        result = await engine.execute(stock_codes)

        return result.to_dict()

    @staticmethod
    async def _get_all_stock_codes() -> list[str]:
        """获取全市场 A 股标的代码。"""
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        codes = [row.symbol for row in rows]
        logger.debug("[income_statement.collect] 全市场标的数: %d", len(codes))
        return codes
