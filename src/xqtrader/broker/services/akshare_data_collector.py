"""Akshare 数据采集服务 — 封装 akshare 与东方财富研报中心数据采集接口。

核心模式：
  - 研报接口：东方财富研报中心 HTTP API（reportapi.eastmoney.com），httpx 异步
  - PDF 下载：东方财富 PDF（pdf.dfcfw.com），httpx 流式下载
  - 新闻/公告/舆情：akshare 同步接口，asyncio.to_thread 桥接为异步

限流策略：
  - 东财研报 API：60 次/分钟（避免被识别为爬虫）
  - akshare 接口：30 次/分钟（akshare 底层走东财/新浪等公开接口，需控制频率）
  - 每个接口对应独立的 SlidingWindowLimiter 实例

线程池：max_workers=20，与 TushareDataCollector 隔离（独立线程池避免相互影响）。
"""

from __future__ import annotations

import asyncio
import random
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any, cast

import akshare as ak  # type: ignore[import-untyped]
import httpx
import pandas as pd

from framework.commons.exceptions import DataCollectionError
from framework.commons.logger import get_logger
from framework.commons.utils.rate_limiter import SlidingWindowLimiter

logger = get_logger(__name__)

# 东财研报 API 限流：60 次/分钟
_REPORT_LIST_LIMIT: tuple[int, float] = (60, 60.0)
_REPORT_PDF_LIMIT: tuple[int, float] = (60, 60.0)

# akshare 限流：30 次/分钟
_AKSHARE_NEWS_LIMIT: tuple[int, float] = (30, 60.0)
_AKSHARE_ANNOUNCEMENT_LIMIT: tuple[int, float] = (30, 60.0)
_AKSHARE_WEIBO_LIMIT: tuple[int, float] = (30, 60.0)

# 东财研报 API 端点
_REPORT_LIST_URL = "https://reportapi.eastmoney.com/report/list"
_REPORT_PDF_URL_TEMPLATE = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

# 研报类型 qType 映射
_REPORT_QTYPE: dict[str, int] = {
    "stock": 0,        # 个股研报
    "industry": 1,     # 行业研报
    "strategy": 2,     # 策略报告
    "macro": 3,        # 宏观研究
    "morning": 4,      # 券商晨报
}


def _strip_symbol_suffix(symbol: str) -> str:
    """去掉股票代码后缀（如 600887.SH → 600887）。

    akshare 与东财接口均使用 6 位裸代码。
    """
    return symbol.split(".")[0]


def _call_akshare_news(code: str) -> pd.DataFrame:
    """同步调用 akshare stock_news_em（在线程池中执行）。"""
    return cast(pd.DataFrame, ak.stock_news_em(symbol=code))


def _call_akshare_announcement(code: str, date_str: str) -> pd.DataFrame:
    """同步调用 akshare stock_individual_notice_report（在线程池中执行）。"""
    if date_str:
        return cast(pd.DataFrame, ak.stock_individual_notice_report(symbol=code, date_str=date_str))
    return cast(pd.DataFrame, ak.stock_individual_notice_report(symbol=code))


def _call_akshare_weibo(date_str: str) -> pd.DataFrame:
    """同步调用 akshare stock_js_weibo_report（在线程池中执行）。"""
    if date_str:
        return cast(pd.DataFrame, ak.stock_js_weibo_report(date_str=date_str))
    return cast(pd.DataFrame, ak.stock_js_weibo_report())


def _normalize_report_columns(df: pd.DataFrame, symbol: str | None) -> pd.DataFrame:
    """标准化东财研报 API 返回字段名为 ORM 字段名。"""
    column_map = {
        "infoCode": "info_code",
        "stockCode": "symbol",
        "title": "title",
        "orgSName": "org_name",
        "researcher": "researcher",
        "emRatingName": "rating",
        "ratingChangeName": "rating_change",
        "publishDate": "publish_date_raw",
        "industryName": "industry",
    }
    rename_map = {k: v for k, v in column_map.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    if "publish_date_raw" in df.columns:
        df["publish_date"] = pd.to_datetime(df["publish_date_raw"], errors="coerce").dt.date
        df = df.drop(columns=["publish_date_raw"])

    # 行业研报 stockCode 可能为空，回退到入参 symbol
    if "symbol" in df.columns:
        df["symbol"] = df["symbol"].replace("", pd.NA)
        if symbol:
            df["symbol"] = df["symbol"].fillna(_strip_symbol_suffix(symbol))

    # 拼接 PDF URL
    if "info_code" in df.columns:
        df["pdf_url"] = df["info_code"].map(
            lambda ic: _REPORT_PDF_URL_TEMPLATE.format(info_code=ic) if ic else None
        )

    return df.reset_index(drop=True)


class AkshareDataCollector:
    """Akshare 与东财研报数据采集服务。

    封装四类数据源：
      1. 东方财富研报中心 HTTP API（研报元数据 + PDF 下载）
      2. akshare stock_news_em（个股新闻）
      3. akshare stock_individual_notice_report（个股公告）
      4. akshare stock_js_weibo_report（微博财经舆情）

    限流策略：
      - 研报 API：60 次/分钟
      - akshare 接口：30 次/分钟
      - 每个接口对应独立的 SlidingWindowLimiter 实例

    线程池：
      - 独立 ThreadPoolExecutor（max_workers=20），与 TushareDataCollector 隔离
    """

    _THREAD_POOL: ThreadPoolExecutor | None = None

    def __init__(self) -> None:
        self._limiters: dict[str, SlidingWindowLimiter] = {
            "research_report": SlidingWindowLimiter(*_REPORT_LIST_LIMIT),
            "research_report_pdf": SlidingWindowLimiter(*_REPORT_PDF_LIMIT),
            "stock_news_em": SlidingWindowLimiter(*_AKSHARE_NEWS_LIMIT),
            "stock_individual_notice_report": SlidingWindowLimiter(*_AKSHARE_ANNOUNCEMENT_LIMIT),
            "stock_js_weibo_report": SlidingWindowLimiter(*_AKSHARE_WEIBO_LIMIT),
        }
        self._default_limiter = SlidingWindowLimiter(30, 60.0)
        self._http_client: httpx.AsyncClient | None = None

        logger.info(
            "AkshareDataCollector 初始化: 研报=%d/%.0fs akshare=%d/%.0fs",
            _REPORT_LIST_LIMIT[0], _REPORT_LIST_LIMIT[1],
            _AKSHARE_NEWS_LIMIT[0], _AKSHARE_NEWS_LIMIT[1],
        )

    def _get_limiter(self, endpoint: str) -> SlidingWindowLimiter:
        """根据接口名获取对应限流器。"""
        return self._limiters.get(endpoint, self._default_limiter)

    @classmethod
    def _get_executor(cls) -> ThreadPoolExecutor:
        """获取共享线程池（懒初始化，max_workers=20）。"""
        if cls._THREAD_POOL is None:
            cls._THREAD_POOL = ThreadPoolExecutor(max_workers=20, thread_name_prefix="akshare")
        return cls._THREAD_POOL

    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取 httpx 异步客户端（懒初始化）。"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                },
                follow_redirects=True,
            )
        return self._http_client

    async def fetch_research_reports(
        self,
        symbol: str | None = None,
        begin_date: str = "",
        end_date: str = "",
        report_type: str = "stock",
        page_size: int = 50,
        max_pages: int = 0,
    ) -> pd.DataFrame:
        """获取东方财富研报列表。

        Args:
            symbol: 股票代码（如 600887.SH），行业/策略研报可空
            begin_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            report_type: 研报类型 stock/industry/strategy/macro/morning
            page_size: 每页数量（最大 50）
            max_pages: 最大页数（0=不限，自动翻页直到无数据）

        Returns:
            DataFrame，包含 info_code/title/org_name/researcher/publish_date 等字段
        """
        q_type = _REPORT_QTYPE.get(report_type, 0)
        code = _strip_symbol_suffix(symbol) if symbol else ""

        try:
            await self._get_limiter("research_report").acquire()
            client = await self._get_http_client()

            all_rows: list[dict[str, Any]] = []
            page_no = 1
            total_pages = 1

            while page_no <= total_pages:
                params = {
                    "industryCode": "*",
                    "pageSize": str(page_size),
                    "industry": "*",
                    "rating": "*",
                    "ratingChange": "*",
                    "beginTime": begin_date,
                    "endTime": end_date,
                    "pageNo": str(page_no),
                    "fields": "",
                    "qType": str(q_type),
                    "orgCode": "",
                    "code": code,
                    "rcode": "",
                    "_": str(int(time.time() * 1000)),
                }

                resp = await client.get(_REPORT_LIST_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

                if page_no == 1:
                    total_pages = int(data.get("pages", 1) or 1)
                    if max_pages > 0:
                        total_pages = min(total_pages, max_pages)
                    logger.info(
                        "[akshare.research_report] %s type=%s pages=%d",
                        symbol or "all", report_type, total_pages,
                    )

                rows = data.get("data") or []
                if not rows:
                    break

                all_rows.extend(rows)
                page_no += 1

                if page_no <= total_pages:
                    await asyncio.sleep(0.3 + random.random() * 0.3)

            if not all_rows:
                logger.debug(
                    "[akshare.research_report] 无数据: symbol=%s type=%s range=%s~%s",
                    symbol, report_type, begin_date, end_date,
                )
                return pd.DataFrame()

            df = _normalize_report_columns(pd.DataFrame(all_rows), symbol)

            logger.info(
                "[akshare.research_report] 获取完成: symbol=%s type=%s rows=%d",
                symbol or "all", report_type, len(df),
            )
            return df
        except Exception as e:
            raise DataCollectionError(
                f"research_report 采集失败 symbol={symbol} type={report_type}: {e}"
            ) from e

    async def download_research_report_pdf(
        self,
        info_code: str,
        save_path: str | Path,
    ) -> str | None:
        """下载研报 PDF 到本地。

        Args:
            info_code: 东财研报唯一标识
            save_path: 本地保存路径（含文件名）

        Returns:
            成功返回保存路径字符串，失败返回 None
        """
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        if save_path.exists():
            logger.debug("[akshare.pdf] 已存在，跳过: %s", save_path)
            return str(save_path)

        url = _REPORT_PDF_URL_TEMPLATE.format(info_code=info_code)

        try:
            await self._get_limiter("research_report_pdf").acquire()
            client = await self._get_http_client()

            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    logger.warning(
                        "[akshare.pdf] 下载失败 info_code=%s status=%d",
                        info_code, resp.status_code,
                    )
                    return None

                with open(save_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

            logger.debug("[akshare.pdf] 下载完成: %s -> %s", info_code, save_path)
            return str(save_path)
        except Exception as e:
            raise DataCollectionError(f"PDF 下载失败 info_code={info_code}: {e}") from e

    async def fetch_stock_news(self, symbol: str) -> pd.DataFrame:
        """获取个股新闻列表（akshare stock_news_em）。

        Args:
            symbol: 股票代码（如 600887.SH）

        Returns:
            DataFrame，包含 title/content/source/news_url/publish_time 等字段
        """
        code = _strip_symbol_suffix(symbol)

        try:
            await self._get_limiter("stock_news_em").acquire()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._get_executor(), partial(_call_akshare_news, code),
            )

            if result is None or result.empty:
                logger.debug("[akshare.news] 无数据: %s", symbol)
                return pd.DataFrame()

            result = result.rename(columns={
                "新闻标题": "title",
                "新闻内容": "content",
                "发布来源": "source",
                "发布时间": "publish_time",
                "新闻链接": "news_url",
                "文章ID": "article_id",
            })
            result["symbol"] = symbol
            result["news_type"] = "news"

            logger.debug("[akshare.news] 获取完成: %s rows=%d", symbol, len(result))
            return result
        except Exception as e:
            raise DataCollectionError(f"stock_news 采集失败 symbol={symbol}: {e}") from e

    async def fetch_stock_announcements(self, symbol: str, date_str: str = "") -> pd.DataFrame:
        """获取个股公告列表（akshare stock_individual_notice_report）。

        Args:
            symbol: 股票代码（如 600887.SH）
            date_str: 查询日期 YYYYMMDD（可选，为空时取近期）

        Returns:
            DataFrame，包含 title/content/source/news_url/publish_time 等字段
        """
        code = _strip_symbol_suffix(symbol)

        try:
            await self._get_limiter("stock_individual_notice_report").acquire()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._get_executor(), partial(_call_akshare_announcement, code, date_str),
            )

            if result is None or result.empty:
                logger.debug("[akshare.announcement] 无数据: %s date=%s", symbol, date_str)
                return pd.DataFrame()

            result = result.rename(columns={
                "公告标题": "title",
                "公告内容": "content",
                "公告来源": "source",
                "公告日期": "publish_time",
                "公告链接": "news_url",
                "文章ID": "article_id",
            })
            result["symbol"] = symbol
            result["news_type"] = "announcement"

            logger.debug(
                "[akshare.announcement] 获取完成: %s date=%s rows=%d",
                symbol, date_str, len(result),
            )
            return result
        except Exception as e:
            raise DataCollectionError(
                f"stock_announcement 采集失败 symbol={symbol} date={date_str}: {e}"
            ) from e

    async def fetch_weibo_sentiment(self, date_str: str = "") -> pd.DataFrame:
        """获取微博财经舆情报告（akshare stock_js_weibo_report）。

        Args:
            date_str: 查询日期 YYYYMMDD（可选，为空时取最新）

        Returns:
            DataFrame，包含日期/关键词/热度/正负面数据等字段
        """
        try:
            await self._get_limiter("stock_js_weibo_report").acquire()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._get_executor(), partial(_call_akshare_weibo, date_str),
            )

            if result is None or result.empty:
                logger.debug("[akshare.weibo] 无数据: date=%s", date_str)
                return pd.DataFrame()

            logger.debug(
                "[akshare.weibo] 获取完成: date=%s rows=%d",
                date_str, len(result),
            )
            return result
        except Exception as e:
            raise DataCollectionError(f"weibo_sentiment 采集失败 date={date_str}: {e}") from e
