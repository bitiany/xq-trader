"""券商研报采集任务（东财研报中心数据源）。

数据源：东方财富研报中心 HTTP API（reportapi.eastmoney.com/report/list）
管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → PersistStage → WatermarkAspect(后切)

字段映射（东财 API → ResearchReport）：
  infoCode → info_code
  stockCode → symbol
  title → title
  orgSName → org_name
  researcher → researcher
  emRatingName → rating
  ratingChangeName → rating_change
  publishDate → publish_date
  industryName → industry

PDF 下载：
  - 路径：{WORKSPACE_ROOT}/report/{symbol}/{info_code}.pdf
  - pdf_path 字段记录相对路径：report/{symbol}/{info_code}.pdf
  - 下载失败不阻塞主流程，仅记录 warning

水位管理（WatermarkAspect）：
  - 前切：若指定 collect_date 则以该日期为起始；否则按水位日期增量采集
  - 后切：持久化成功后更新水位日期为最新 publish_date（通过 max_ann_date 传递）

注意：WatermarkAspect 设置的 start_date/end_date 为 YYYYMMDD 格式（无连字符）；
      东财研报 API 需要 YYYY-MM-DD 格式，DownloadStage 中做转换。
"""

from __future__ import annotations

import os
from datetime import date as date_type
from pathlib import Path
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
from xqtrader.broker.services.akshare_data_collector import AkshareDataCollector
from xqtrader.domain.research.models.research_report import ResearchReport
from xqtrader.domain.security.models import Security

logger = get_logger(__name__)

_collector: AkshareDataCollector | None = None

_DATA_TYPE = "research_report"

# PDF 存储相对路径前缀
_PDF_RELATIVE_PREFIX = "report"

# ORM 模型中可被 upsert 更新的字段（不含 info_code 主键、id/created_at 审计字段）
_PERSIST_UPDATE_FIELDS = [
    "symbol", "title", "org_name", "researcher", "rating", "rating_change",
    "publish_date", "industry", "pdf_url", "pdf_path", "updated_at",
]


def _get_workspace_root() -> Path:
    """获取 workspace 根目录（环境变量 WORKSPACE_ROOT，默认 D:\\app\\volumes\\workspace）。"""
    return Path(os.getenv("WORKSPACE_ROOT", r"D:\app\volumes\workspace"))


def _get_collector() -> AkshareDataCollector:
    """延迟初始化 AkshareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = AkshareDataCollector()
    return _collector


def _normalize_date_param(date_str: str) -> str:
    """将 YYYYMMDD 格式转为东财 API 需要的 YYYY-MM-DD 格式。

    WatermarkAspect 设置的 start_date/end_date 为 YYYYMMDD 格式；
    东财研报 API beginTime/endTime 参数需要 YYYY-MM-DD 格式。
    """
    if not date_str:
        return ""
    if "-" in date_str:
        return date_str
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def clean_research_report_data(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """研报数据清洗 — 过滤无效行 + 字段对齐。"""
    if df.empty:
        return df

    # 过滤缺少 info_code 或 title 的行
    df = df.dropna(subset=["info_code", "title"])
    if df.empty:
        return df

    # 确保 symbol 列存在且非空
    if "symbol" not in df.columns:
        df["symbol"] = symbol
    else:
        df["symbol"] = df["symbol"].fillna(symbol)

    return df.reset_index(drop=True)


async def persist_research_report_data(
    df: pd.DataFrame,
    download_pdf: bool,
    collector: AkshareDataCollector,
) -> tuple[int, date_type | None]:
    """将研报数据 upsert 到 ResearchReport 表，并下载 PDF。

    Returns:
        (持久化行数, 最新 publish_date)
    """
    workspace_root = _get_workspace_root()

    pdf_paths: list[str | None] = []
    for _, row in df.iterrows():
        if not download_pdf:
            pdf_paths.append(None)
            continue

        info_code = row.get("info_code")
        row_symbol = row.get("symbol")
        if not info_code or not row_symbol or pd.isna(info_code) or pd.isna(row_symbol):
            pdf_paths.append(None)
            continue

        # 相对路径：report/{symbol}/{info_code}.pdf
        relative_path = f"{_PDF_RELATIVE_PREFIX}/{row_symbol}/{info_code}.pdf"
        absolute_path = workspace_root / relative_path

        try:
            saved = await collector.download_research_report_pdf(
                info_code=str(info_code),
                save_path=absolute_path,
            )
            pdf_paths.append(relative_path if saved else None)
        except Exception as e:
            logger.warning(
                "[research_report.pdf] 下载失败 info_code=%s: %s",
                info_code, e, exc_info=True,
            )
            pdf_paths.append(None)

    df = df.copy()
    df["pdf_path"] = pdf_paths

    custom_transforms = {
        "publish_date": lambda v: v if isinstance(v, date_type) else (
            date_type.fromisoformat(str(v))
            if v and str(v) not in {"nan", "None", "NaT"}
            else None
        ),
    }
    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=ResearchReport,
        custom_transforms=custom_transforms,
    )
    if not instances:
        return 0, None

    count = await ResearchReport.bulk_create_or_update(
        instances,  # type: ignore[arg-type]
        on_conflict=["info_code"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=100,
    )

    # 计算最新 publish_date 用于水位更新
    max_publish_date: date_type | None = None
    if "publish_date" in df.columns:
        valid_dates = [d for d in df["publish_date"].dropna() if isinstance(d, date_type)]
        if valid_dates:
            max_publish_date = max(valid_dates)

    return count, max_publish_date


class ResearchReportError(PipelineError):
    """研报采集异常基类。"""


class DownloadError(ResearchReportError):
    """下载阶段异常。"""


class PersistError(ResearchReportError):
    """持久化阶段异常。"""


class DownloadStage(Stage):
    """下载阶段 — 调用 AkshareDataCollector 获取研报列表。"""

    @property
    def name(self) -> str:
        return "download"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item
        start_date = ctx.get("start_date", "")
        end_date = ctx.get("end_date", "")
        report_type = ctx.get("report_type", "stock")
        max_pages = ctx.get("max_pages", 0)

        if ctx.get("is_up_to_date"):
            return StageResult.ok(data={"stock_code": stock_code, "rows": 0, "skipped": True})

        if not start_date:
            return StageResult.fail(f"缺少 start_date，跳过 {stock_code}")

        try:
            # WatermarkAspect 设置的日期为 YYYYMMDD，东财 API 需要 YYYY-MM-DD
            begin_date = _normalize_date_param(start_date)
            end_date_str = _normalize_date_param(end_date)

            df = await _get_collector().fetch_research_reports(
                symbol=stock_code,
                begin_date=begin_date,
                end_date=end_date_str,
                report_type=report_type,
                max_pages=max_pages,
            )

            if df is None or df.empty:
                logger.debug(
                    "[research_report.collect] 无数据: %s range=%s~%s",
                    stock_code, begin_date, end_date_str,
                )
                ctx.set("download_data", None)
                ctx.set("row_count", 0)
                ctx.set("skip_persist", True)
            else:
                df = clean_research_report_data(df, stock_code)
                ctx.set("download_data", df)
                ctx.set("row_count", len(df))
                ctx.set("skip_persist", df.empty)

            return StageResult.ok(data={"stock_code": stock_code, "rows": ctx.get("row_count", 0)})
        except Exception as e:
            raise DownloadError(f"下载失败 {stock_code}: {e}") from e


class PersistStage(Stage):
    """持久化阶段 — 写入 ResearchReport 表并下载 PDF。"""

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
            download_pdf = ctx.get("download_pdf", True)
            count, max_publish_date = await persist_research_report_data(
                df=df,
                download_pdf=download_pdf,
                collector=_get_collector(),
            )

            ctx.set("persisted_count", count)
            # WatermarkAspect 后切读取 max_ann_date 更新水位
            if count > 0 and max_publish_date is not None:
                ctx.set("max_ann_date", max_publish_date)

            logger.debug(
                "[research_report.collect] 持久化完成: %s rows=%d max_pub=%s",
                stock_code, count, max_publish_date,
            )
            return StageResult.ok(data={"stock_code": stock_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {stock_code}: {e}") from e


class ResearchReportCollectTask(BaseTask):
    """券商研报采集任务（东财研报中心数据源）。

    入参：
      - concurrency: 并发数（默认 3）
      - stock_codes: 股票代码列表（为空时采集全市场）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 采集起始日期（格式 YYYY-MM-DD，为空时按水位日期增量采集）
      - report_type: 研报类型（stock/industry/strategy/macro/morning）
      - download_pdf: 是否下载 PDF（默认 true）
      - max_pages: 单标的最大翻页数（0=不限）
    """

    task_name = "market.research_report_collect"
    description = "券商研报采集-东财研报中心（管道引擎并发 + PDF 下载）"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        concurrency = kwargs.get("concurrency", 3)
        stock_codes: list[str] | None = kwargs.get("stock_codes")
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")
        report_type: str = kwargs.get("report_type", "stock")
        download_pdf: bool = kwargs.get("download_pdf", True)
        max_pages: int = kwargs.get("max_pages", 0)

        # 获取标的列表
        if not stock_codes:
            stock_codes = await self._get_all_stock_codes()
            if not stock_codes:
                logger.warning("[research_report.collect] 未找到任何标的代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        # 限制标的数量（用于测试）
        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.debug("[research_report.collect] 限制标的数量: max_count=%d", max_count)

        # 构建全局上下文
        global_ctx: dict[str, Any] = {
            "report_type": report_type,
            "download_pdf": download_pdf,
            "max_pages": max_pages,
        }
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "[research_report.collect] 开始采集: concurrency=%d stocks=%d type=%s pdf=%s collect_date=%s",
            concurrency, len(stock_codes), report_type, download_pdf, collect_date or "按水位",
        )

        # 组装管线: download → persist
        pipeline = Pipeline(
            name=_DATA_TYPE,
            stages=[DownloadStage(), PersistStage()],
            aspects=[WatermarkAspect(data_type=_DATA_TYPE)],
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
        logger.debug("[research_report.collect] 全市场标的数: %d", len(codes))
        return codes
