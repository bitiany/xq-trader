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

import ast
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
_AKSHARE_FUND_HOLDER_LIMIT: tuple[int, float] = (30, 60.0)

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


def _add_symbol_suffix(code: str) -> str:
    """为 6 位数字股票代码添加交易所后缀（回退逻辑，仅处理沪深主板/创业板/科创板）。

    北交所（8/4/9 开头）代码段存在 920xxx 等多段情况，
    不能按首位数字硬编码推断，必须从证券表查询真实 symbol；
    本函数仅作为 symbol_map 未命中时的回退，处理沪深主板/创业板/科创板，
    8/4/9 开头代码保持原样（不带后缀），由调用方通过 symbol_map 兜底。

    规则：
      - 6xxxxx → .SH（上海证券交易所，含主板/科创板 688）
      - 0xxxxx / 3xxxxx → .SZ（深圳证券交易所，含主板/创业板）
      - 8/4/9 开头：保持原样（北交所需从证券表查询真实 symbol）
      - 其他：保持原样
    """
    if not (len(code) == 6 and code.isdigit()):
        return code
    first = code[0]
    if first == "6":
        return f"{code}.SH"
    if first in ("0", "3"):
        return f"{code}.SZ"
    # 北交所（8/4/9 开头）不在此处硬编码，由调用方通过 symbol_map 兜底
    return code


def normalize_news_keywords(
    value: Any,
    symbol_map: dict[str, str] | None = None,
) -> list[str] | None:
    """将 akshare 新闻/公告关键词字段规范化为 list[str] 或 None。

    akshare "关键词" 列实际返回值形态：
      - "[600887"（带方括号前缀的字符串）
      - "600887,600888"（逗号分隔）
      - "[600887],[600888]"（多方括号）
      - 已是 list（如 ["600887"] 或 ["[600887"]）

    规范化步骤：
      1. 拆分逗号
      2. 清理方括号、空白、'nan'/'None' 哨兵
      3. 为 6 位数字代码添加交易所后缀：
         - 优先使用 symbol_map（从证券表加载的真实 symbol，覆盖沪深+北交所）
         - symbol_map 未命中时回退到 _add_symbol_suffix（仅处理沪深，北交所保持原样）
      4. 去重，保持顺序

    Args:
        value: akshare 原始关键词字段值
        symbol_map: 裸代码 → 带后缀 symbol 的映射（从 sdc_security 表加载）
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (ValueError, TypeError):
        pass

    items_raw: list[str] = []
    if isinstance(value, list):
        items_raw = [str(v) for v in value if v is not None]
    elif isinstance(value, str):
        text = value.strip()
        if text in {"", "nan", "None"}:
            return None
        # 处理字符串编码的列表，如 "['600887']" 或 "[600887]"
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list):
                    items_raw = [str(v) for v in parsed if v is not None]
                else:
                    items_raw = [text]
            except (ValueError, SyntaxError):
                items_raw = [text]
        else:
            items_raw = [text]
    else:
        return None

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items_raw:
        # 拆分逗号（akshare 偶尔返回逗号拼接的多关键词）
        for part in str(item).split(","):
            # 清理方括号与空白
            cleaned_part = part.strip().strip("[]").strip()
            if not cleaned_part or cleaned_part in {"nan", "None"}:
                continue
            # 为 6 位数字代码添加交易所后缀
            if len(cleaned_part) == 6 and cleaned_part.isdigit():
                if symbol_map and cleaned_part in symbol_map:
                    cleaned_part = symbol_map[cleaned_part]
                else:
                    cleaned_part = _add_symbol_suffix(cleaned_part)
            if cleaned_part and cleaned_part not in seen:
                seen.add(cleaned_part)
                cleaned.append(cleaned_part)

    return cleaned or None


def _call_akshare_news(code: str) -> pd.DataFrame:
    """同步调用 akshare stock_news_em（在线程池中执行）。"""
    return cast(pd.DataFrame, ak.stock_news_em(symbol=code))


def _call_akshare_announcement(code: str, begin_date: str, end_date: str) -> pd.DataFrame:
    """同步调用 akshare stock_individual_notice_report（在线程池中执行）。

    实际签名：stock_individual_notice_report(security, symbol='全部', begin_date, end_date)
    日期格式：YYYYMMDD

    注意：akshare 在日期范围无结果时会抛 KeyError（内部 bug），
    此处捕获并返回空 DataFrame。
    """
    try:
        if begin_date and end_date:
            return cast(pd.DataFrame, ak.stock_individual_notice_report(
                security=code, begin_date=begin_date, end_date=end_date,
            ))
        return cast(pd.DataFrame, ak.stock_individual_notice_report(security=code))
    except KeyError:
        # akshare 内部 bug：日期范围无数据时 big_df 为空，访问 "代码" 列报 KeyError
        logger.debug(
            "[akshare.announcement] 日期范围无数据（akshare KeyError）: code=%s range=%s~%s",
            code, begin_date, end_date,
        )
        return pd.DataFrame()


def _call_akshare_weibo(time_period: str) -> pd.DataFrame:
    """同步调用 akshare stock_js_weibo_report（在线程池中执行）。

    实际签名：stock_js_weibo_report(time_period='CNHOUR12')
    time_period: {'CNHOUR2','CNHOUR6','CNHOUR12','CNHOUR24','CNDAY7','CNDAY30'}
    """
    if time_period:
        return cast(pd.DataFrame, ak.stock_js_weibo_report(time_period=time_period))
    return cast(pd.DataFrame, ak.stock_js_weibo_report())


def _call_akshare_fund_stock_holder(code: str) -> pd.DataFrame:
    """同步调用 akshare stock_fund_stock_holder（新浪基金持股）。"""
    return cast(pd.DataFrame, ak.stock_fund_stock_holder(symbol=code))


def _normalize_report_columns(df: pd.DataFrame, symbol: str | None) -> pd.DataFrame:
    """标准化东财研报 API 返回字段名为 ORM 字段名。

    东财 API 实际返回字段（部分）：
      infoCode, stockCode, title, orgSName, researcher,
      emRatingName (评级名), lastEmRatingName (上次评级名),
      ratingChange (评级变化 int: 1=上调 2=下调 3=维持),
      publishDate (YYYY-MM-DD HH:mm:ss.SSS), industryName,
      predictThisYearEps/Pe, predictNextYearEps/Pe, predictNextTwoYearEps/Pe,
      predictLastYearEps/Pe, actualLastTwoYearEps, actualLastYearEps
    """
    column_map = {
        "infoCode": "info_code",
        "stockCode": "symbol_raw",
        "title": "title",
        "orgSName": "org_name",
        "researcher": "researcher",
        "emRatingName": "rating",
        "ratingChange": "rating_change",
        "publishDate": "publish_date_raw",
        "industryName": "industry",
        "indvInduName": "industry_fallback",
    }
    rename_map = {k: v for k, v in column_map.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    # industryName 在个股研报中常为空，回退到 indvInduName（个股所属行业）
    if "industry" in df.columns and "industry_fallback" in df.columns:
        df["industry"] = df["industry"].where(
            df["industry"].astype(str).str.strip() != "",
            df["industry_fallback"],
        )
        df = df.drop(columns=["industry_fallback"])
    elif "industry_fallback" in df.columns:
        df = df.rename(columns={"industry_fallback": "industry"})

    if "publish_date_raw" in df.columns:
        df["publish_date"] = pd.to_datetime(df["publish_date_raw"], errors="coerce").dt.date
        df = df.drop(columns=["publish_date_raw"])

    # symbol 统一使用带后缀格式（如 600519.SH）
    # 入参 symbol 来自 Security.symbol（带后缀），API 返回的 stockCode 为裸代码
    if symbol:
        df["symbol"] = symbol
    elif "symbol_raw" in df.columns:
        # 空字符串视为缺失
        raw = df["symbol_raw"].astype(str).str.strip()
        df["symbol"] = df["symbol_raw"].where(raw != "")
    if "symbol_raw" in df.columns:
        df = df.drop(columns=["symbol_raw"])

    # 聚合盈利预测字段为 eps_forecast（list[dict]）
    df = _build_eps_forecast(df)

    # 拼接 PDF URL
    if "info_code" in df.columns:
        df["pdf_url"] = df["info_code"].map(
            lambda ic: _REPORT_PDF_URL_TEMPLATE.format(info_code=ic) if ic else None
        )

    return df.reset_index(drop=True)


def _build_eps_forecast(df: pd.DataFrame) -> pd.DataFrame:
    """将东财研报 API 的盈利预测字段聚合为 eps_forecast（list[dict]）。

    API 字段：predictThisYearEps/Pe, predictNextYearEps/Pe, predictNextTwoYearEps/Pe,
              predictLastYearEps/Pe, actualLastTwoYearEps, actualLastYearEps

    聚合为：[{"year": 2025, "eps": 66.68, "pe": 19.8, "type": "predict"}, ...]
    年份基于 publish_date 推断。
    """
    eps_field_map = [
        ("predictThisYearEps", "predictThisYearPe", "predict_this"),
        ("predictNextYearEps", "predictNextYearPe", "predict_next"),
        ("predictNextTwoYearEps", "predictNextTwoYearPe", "predict_next_two"),
        ("predictLastYearEps", "predictLastYearPe", "predict_last"),
        ("actualLastTwoYearEps", None, "actual_last_two"),
        ("actualLastYearEps", None, "actual_last"),
    ]

    has_any_field = any(eps_field in df.columns for eps_field, _, _ in eps_field_map)
    if not has_any_field:
        return df

    forecasts: list[list[dict[str, Any]] | None] = []
    for _, row in df.iterrows():
        pub_date = row.get("publish_date")
        base_year: int | None = None
        if pub_date is not None and hasattr(pub_date, "year"):
            base_year = pub_date.year  # type: ignore[union-attr]

        items: list[dict[str, Any]] = []
        year_offset_map = {
            "predict_this": 0, "predict_next": 1, "predict_next_two": 2,
            "predict_last": -1, "actual_last_two": -2, "actual_last": -1,
        }
        for eps_field, pe_field, ftype in eps_field_map:
            eps_val = row.get(eps_field)
            if eps_val is None or str(eps_val).strip() in {"", "nan", "None"}:
                continue
            try:
                eps_float = float(eps_val)
            except (ValueError, TypeError):
                continue

            item: dict[str, Any] = {
                "type": ftype,
                "eps": eps_float,
            }
            if base_year is not None:
                item["year"] = base_year + year_offset_map[ftype]
            if pe_field and pe_field in df.columns:
                pe_val = row.get(pe_field)
                if pe_val is not None and str(pe_val).strip() not in {"", "nan", "None"}:
                    try:
                        item["pe"] = float(pe_val)
                    except (ValueError, TypeError):
                        pass
            items.append(item)

        forecasts.append(items if items else None)

    # 使用 object dtype 容纳 list[dict] | None
    df["eps_forecast"] = pd.Series(forecasts, index=df.index, dtype=object)
    return df


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
            "stock_fund_stock_holder": SlidingWindowLimiter(*_AKSHARE_FUND_HOLDER_LIMIT),
        }
        self._default_limiter = SlidingWindowLimiter(30, 60.0)
        self._http_client: httpx.AsyncClient | None = None
        # 裸代码 → 带后缀 symbol 映射（从 sdc_security 表加载，懒初始化缓存）
        self._symbol_map: dict[str, str] | None = None
        # 保护 _symbol_map 懒初始化的并发锁（避免多协程重复查表）
        self._symbol_map_lock = asyncio.Lock()

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

    async def _ensure_symbol_map(self) -> dict[str, str]:
        """从 sdc_security 表加载 裸代码→带后缀 symbol 映射（懒初始化缓存）。

        用于规范化新闻/公告关键词中的股票代码后缀，避免硬编码北交所代码段
        （北交所存在 8/4/920 等多段代码，无法按首位数字推断）。

        使用 asyncio.Lock 保护懒初始化，避免多协程并发时重复查表。
        """
        if self._symbol_map is None:
            async with self._symbol_map_lock:
                # 双重检查：获取锁后再次确认，避免其他协程已初始化
                if self._symbol_map is None:
                    # 延迟导入避免循环依赖
                    from xqtrader.domain.security.models import Security
                    rows = await Security.filter(list_status="L")
                    self._symbol_map = {
                        row.symbol.split(".")[0]: row.symbol for row in rows
                    }
                    logger.info(
                        "[akshare.symbol_map] 加载证券映射: count=%d", len(self._symbol_map),
                    )
        return self._symbol_map

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
                    # 东财 API 返回字段为 TotalPage（非 pages）
                    total_pages = int(data.get("TotalPage", 1) or 1)
                    if max_pages > 0:
                        total_pages = min(total_pages, max_pages)
                    logger.info(
                        "[akshare.research_report] %s type=%s pages=%d hits=%s",
                        symbol or "all", report_type, total_pages, data.get("hits"),
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

            # akshare stock_news_em 实际列名：
            #   ['关键词', '新闻标题', '新闻内容', '发布时间', '文章来源', '新闻链接']
            result = result.rename(columns={
                "新闻标题": "title",
                "新闻内容": "content",
                "文章来源": "source",
                "发布时间": "publish_time",
                "新闻链接": "news_url",
            })
            result["symbol"] = symbol
            result["news_type"] = "news"
            # 关键词列规范化为 list[str]（StockNews.keywords 为 JSONB 数组）
            # 使用 sdc_security 表加载的真实 symbol 映射，避免硬编码北交所代码段
            if "关键词" in result.columns:
                symbol_map = await self._ensure_symbol_map()
                result["keywords"] = result["关键词"].apply(
                    lambda v: normalize_news_keywords(v, symbol_map=symbol_map)
                )
                result = result.drop(columns=["关键词"])

            logger.debug("[akshare.news] 获取完成: %s rows=%d", symbol, len(result))
            return result
        except Exception as e:
            raise DataCollectionError(f"stock_news 采集失败 symbol={symbol}: {e}") from e

    async def fetch_stock_announcements(
        self,
        symbol: str,
        begin_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """获取个股公告列表（akshare stock_individual_notice_report）。

        Args:
            symbol: 股票代码（如 600887.SH）
            begin_date: 起始日期 YYYYMMDD（可选，为空时取近期）
            end_date: 结束日期 YYYYMMDD（可选，为空时取近期）

        Returns:
            DataFrame，包含 title/content/source/news_url/publish_time 等字段
        """
        code = _strip_symbol_suffix(symbol)

        try:
            await self._get_limiter("stock_individual_notice_report").acquire()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._get_executor(),
                partial(_call_akshare_announcement, code, begin_date, end_date),
            )

            if result is None or result.empty:
                logger.debug(
                    "[akshare.announcement] 无数据: %s range=%s~%s",
                    symbol, begin_date, end_date,
                )
                return pd.DataFrame()

            # akshare stock_individual_notice_report 实际列名：
            #   ['代码', '名称', '公告标题', '公告类型', '公告日期', '网址']
            result = result.rename(columns={
                "公告标题": "title",
                "公告日期": "publish_time",
                "网址": "news_url",
            })
            result["symbol"] = symbol
            result["news_type"] = "announcement"
            result["content"] = None
            result["source"] = None
            # 公告类型转为 list[str]（StockNews.keywords 为 JSONB 数组）
            # 公告类型为中文分类标签（如"重大事项"），不含股票代码，无需 symbol_map
            if "公告类型" in result.columns:
                result["keywords"] = result["公告类型"].apply(normalize_news_keywords)
                result = result.drop(columns=["公告类型"])

            logger.debug(
                "[akshare.announcement] 获取完成: %s range=%s~%s rows=%d",
                symbol, begin_date, end_date, len(result),
            )
            return result
        except Exception as e:
            raise DataCollectionError(
                f"stock_announcement 采集失败 symbol={symbol} "
                f"range={begin_date}~{end_date}: {e}"
            ) from e

    async def fetch_fund_hold_pct(self, symbol: str) -> float | None:
        """获取基金持股占流通股比例合计（akshare stock_fund_stock_holder，新浪数据源）。

        广义机构持股（akshare stock_institute_hold）对多数 A 股返回空表，
        暂以基金累计持股作为 key_metrics.institutional_hold_pct，并通过
        institutional_hold_source=fund 标注数据来源。

        返回值为百分比，如 27.70 表示 27.70%。无数据时返回 None。
        """
        code = _strip_symbol_suffix(symbol)
        try:
            await self._get_limiter("stock_fund_stock_holder").acquire()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._get_executor(),
                partial(_call_akshare_fund_stock_holder, code),
            )
            if result is None or result.empty:
                logger.debug("[akshare.fund_holder] 无数据: %s", symbol)
                return None

            ratio_col = next(
                (col for col in result.columns if "流通" in str(col)),
                None,
            )
            if ratio_col is None:
                raise DataCollectionError(
                    f"stock_fund_stock_holder 缺少占流通股比例列: symbol={symbol} cols={list(result.columns)}",
                )

            ratios = pd.to_numeric(result[ratio_col], errors="coerce").dropna()
            if ratios.empty:
                return None

            total = float(ratios.sum())
            return round(total, 2)
        except DataCollectionError:
            raise
        except Exception as e:
            raise DataCollectionError(f"stock_fund_stock_holder 采集失败 symbol={symbol}: {e}") from e

    async def fetch_weibo_sentiment(self, time_period: str = "") -> pd.DataFrame:
        """获取微博财经舆情报告（akshare stock_js_weibo_report）。

        Args:
            time_period: 时间周期，可选值：
                {'CNHOUR2':'2小时', 'CNHOUR6':'6小时', 'CNHOUR12':'12小时',
                 'CNHOUR24':'1天', 'CNDAY7':'1周', 'CNDAY30':'1月'}
                为空时取默认值 CNHOUR12

        Returns:
            DataFrame，包含日期/关键词/热度/正负面数据等字段
        """
        try:
            await self._get_limiter("stock_js_weibo_report").acquire()
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._get_executor(), partial(_call_akshare_weibo, time_period),
            )

            if result is None or result.empty:
                logger.debug("[akshare.weibo] 无数据: time_period=%s", time_period)
                return pd.DataFrame()

            logger.debug(
                "[akshare.weibo] 获取完成: time_period=%s rows=%d",
                time_period, len(result),
            )
            return result
        except Exception as e:
            raise DataCollectionError(f"weibo_sentiment 采集失败 time_period={time_period}: {e}") from e
