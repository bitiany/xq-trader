"""个股详情服务。"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from framework.commons.exceptions import NotFoundException
from framework.commons.logger import get_logger
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.domain.market.models.balance_sheet import BalanceSheet
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.market.models.cash_flow import CashFlowStatement
from xqtrader.domain.market.models.daily_indicator import DailyIndicator
from xqtrader.domain.market.models.financial_indicator import FinancialIndicator
from xqtrader.domain.market.models.fund_flow import FundFlowIndividual
from xqtrader.domain.market.models.income_statement import IncomeStatement
from xqtrader.domain.research.models.stock_news import StockNews
from xqtrader.domain.security.models import Security
from xqtrader.domain.security.stock_tag import StockTag

logger = get_logger("STOCK_DETAIL_SERVICE")

_TAG_DEFINITIONS: dict[str, dict[str, str]] = {
    "growth": {"tag_name": "成长", "dimension": "fundamental", "description": "成长性标签"},
    "value": {"tag_name": "价值", "dimension": "valuation", "description": "估值吸引力标签"},
    "quality": {"tag_name": "质量", "dimension": "fundamental", "description": "盈利质量标签"},
    "momentum": {"tag_name": "动量", "dimension": "technical", "description": "趋势动量标签"},
}


class SecurityMixin:
    """证券存在性校验混入类。"""

    async def _ensure_security(self, symbol: str) -> Security:
        row = await Security.get_one_or_none(symbol=symbol)
        if row is None:
            raise NotFoundException(message=f"证券 {symbol} 不存在")
        return row


class StockApiFormatter:
    """个股接口格式化工具。"""

    @staticmethod
    def value(value: Any) -> float | int | str | None:
        if value is None:
            return None
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            return None
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, int | float | str):
            return value
        return None

    @classmethod
    def series(cls, values: np.ndarray) -> list[float | None]:
        result: list[float | None] = []
        for value in values:
            formatted = cls.value(value)
            result.append(formatted if isinstance(formatted, (int, float)) else None)
        return result

    @classmethod
    def date_value(cls, value: Any) -> str | None:
        formatted = cls.value(value)
        return formatted if isinstance(formatted, str) else None

    @classmethod
    def model_highlights(cls, row: Any, fields: list[str]) -> dict[str, float | int | str | None]:
        return {field: cls.value(getattr(row, field, None)) for field in fields}

    @classmethod
    def report_summary(cls, row: Any, fields: list[str]) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "end_date": cls.date_value(getattr(row, "end_date", None)),
            "ann_date": cls.date_value(getattr(row, "ann_date", None)),
            "highlights": cls.model_highlights(row, fields),
        }

    @staticmethod
    def bar_item(row: CandlestickDaily) -> dict[str, Any]:
        return {
            "trade_date": row.trade_date.isoformat(),
            "open": row.open,
            "close": row.close,
            "high": row.high,
            "low": row.low,
            "volume": row.volume,
            "amount": row.amount,
            "pct_chg": StockApiFormatter.value(row.pct_chg),
        }


@contextmanager
def chanlun_cache(df: pd.DataFrame) -> Generator[str, None, None]:
    """封装第三方库缓存操作，隔离 _DF_CACHE 实现细节。"""
    from DataAPI.DfApi import _DF_CACHE  # type: ignore[import-not-found]

    cache_key = f"_stock_detail_chan_{uuid4().hex}"
    _DF_CACHE[cache_key] = df
    try:
        yield cache_key
    finally:
        _DF_CACHE.pop(cache_key, None)


class StockDirectoryService(SecurityMixin):
    """个股列表、搜索与轻量信息服务。"""

    async def list_stocks(
        self,
        page: int,
        page_size: int,
        market: str | None,
        industry: str | None,
        list_status: str | None,
        q: str | None,
    ) -> dict:
        skip, limit = paginate(page, page_size)
        filters: dict[str, Any] = {"market": market, "industry": industry, "list_status": list_status}
        rows = await self._query_securities(q=q, filters=filters, skip=skip, limit=limit)
        total = await self._count_securities(q=q, filters=filters)
        latest_map = await self._latest_indicator_map([row.symbol for row in rows])
        items = [self._stock_list_item(row, latest_map.get(row.symbol)) for row in rows]
        return build_paginated_response(items, total, page, page_size)

    async def search_stocks(self, q: str, limit: int) -> list[dict[str, Any]]:
        rows = await self._query_securities(q=q, filters={"list_status": "L"}, skip=0, limit=limit)
        return [
            {
                "symbol": row.symbol,
                "code": row.code,
                "name": row.name,
                "industry": row.industry,
                "market": row.market,
            }
            for row in rows
        ]

    async def get_tag_definitions(self) -> list[dict[str, str]]:
        return [
            {
                "tag_key": key,
                "tag_name": item["tag_name"],
                "dimension": item["dimension"],
                "description": item["description"],
                "rule_engine": "system",
                "rebalance_freq": "daily",
                "status": "active",
            }
            for key, item in _TAG_DEFINITIONS.items()
        ]

    async def get_stock_tags(self, symbol: str) -> list[dict[str, Any]]:
        rows = await StockTag.filter(symbol=symbol, order_by=StockTag.effective_date.desc(), limit=20)
        return [self._tag_item(row) for row in rows]

    def _build_search_conditions(self, q: str) -> tuple[str, list]:
        """构建搜索条件，返回 (keyword, or_conditions)。"""
        keyword = f"%{q.strip()}%"
        or_conditions = [
            Security.symbol.ilike(keyword),
            Security.code.ilike(keyword),
            Security.name.ilike(keyword),
            Security.cnspell.ilike(keyword),
        ]
        return keyword, or_conditions

    async def _query_securities(
        self,
        q: str | None,
        filters: dict[str, Any],
        skip: int,
        limit: int,
    ) -> list[Security]:
        if not q:
            return await Security.filter(skip=skip, limit=limit, order_by=Security.symbol.asc(), **filters)
        _, or_conditions = self._build_search_conditions(q)
        return await Security.filter_with_or(
            or_conditions=or_conditions,
            and_filters=filters,
            skip=skip,
            limit=limit,
            order_by=Security.symbol.asc(),
        )

    async def _count_securities(self, q: str | None, filters: dict[str, Any]) -> int:
        if not q:
            return await Security.count(**filters)
        _, or_conditions = self._build_search_conditions(q)
        return await Security.count_with_or(
            or_conditions=or_conditions,
            and_filters=filters,
        )

    async def _latest_indicator_map(self, symbols: list[str]) -> dict[str, DailyIndicator]:
        indicators: dict[str, DailyIndicator] = {}
        if not symbols:
            return indicators
        all_rows = await DailyIndicator.filter(
            symbol__in=symbols,
            order_by=DailyIndicator.trade_date.desc(),
            limit=len(symbols) * 2,
        )
        seen: set[str] = set()
        for row in all_rows:
            if row.symbol not in seen:
                seen.add(row.symbol)
                indicators[row.symbol] = row
        return indicators

    def _stock_list_item(self, row: Security, indicator: DailyIndicator | None) -> dict[str, Any]:
        return {
            "symbol": row.symbol,
            "code": row.code,
            "name": row.name,
            "industry": row.industry,
            "market": row.market,
            "cnspell": row.cnspell,
            "close": StockApiFormatter.value(getattr(indicator, "close", None)),
            "change_pct": None,
            "pe_ttm": StockApiFormatter.value(getattr(indicator, "pe_ttm", None)),
            "pb": StockApiFormatter.value(getattr(indicator, "pb", None)),
            "total_mv": StockApiFormatter.value(getattr(indicator, "total_mv", None)),
            "turnover_rate": StockApiFormatter.value(getattr(indicator, "turnover_rate", None)),
            "roe": None,
            "grossprofit_margin": None,
            "dv_ratio": StockApiFormatter.value(getattr(indicator, "dv_ratio", None)),
            "tags": [],
        }

    def _tag_item(self, row: StockTag) -> dict[str, Any]:
        definition = _TAG_DEFINITIONS.get(row.tag_key, {})
        return {
            "tag_key": row.tag_key,
            "tag_name": definition.get("tag_name", row.tag_key),
            "dimension": definition.get("dimension", "custom"),
            "score": StockApiFormatter.value(row.score),
            "confidence": row.confidence,
        }


class StockDetailService(SecurityMixin):
    """个股详情聚合服务。"""

    async def get_overview(self, symbol: str) -> dict[str, Any]:
        security = await self._ensure_security(symbol)
        candles = await CandlestickDaily.filter(symbol=symbol, order_by=CandlestickDaily.trade_date.desc(), limit=1)
        indicators = await DailyIndicator.filter(symbol=symbol, order_by=DailyIndicator.trade_date.desc(), limit=1)
        latest_candle = candles[0] if candles else None
        latest_indicator = indicators[0] if indicators else None
        return {
            "symbol": security.symbol,
            "code": security.code,
            "name": security.name,
            "industry": security.industry,
            "market": security.market,
            "exchange": security.exchange,
            "list_date": security.list_date,
            "introduction": security.introduction,
            "quote": self._quote_snapshot(symbol, latest_candle),
            "valuation": self._valuation_panel(latest_indicator),
            "tags": [],
        }

    async def get_financials(self, symbol: str) -> dict[str, Any]:
        await self._ensure_security(symbol)
        income = await IncomeStatement.filter(
            symbol=symbol, update_flag="1", order_by=IncomeStatement.end_date.desc(), limit=1,
        )
        balance = await BalanceSheet.filter(
            symbol=symbol, update_flag="1", order_by=BalanceSheet.end_date.desc(), limit=1,
        )
        cash_flow = await CashFlowStatement.filter(
            symbol=symbol, update_flag="1", order_by=CashFlowStatement.end_date.desc(), limit=1,
        )
        indicator = await FinancialIndicator.filter(
            symbol=symbol, update_flag="1", order_by=FinancialIndicator.end_date.desc(), limit=1,
        )
        return {
            "symbol": symbol,
            "income_statement": StockApiFormatter.report_summary(
                income[0] if income else None,
                ["total_revenue", "revenue", "operate_profit", "n_income", "basic_eps"],
            ),
            "balance_sheet": StockApiFormatter.report_summary(
                balance[0] if balance else None,
                ["total_assets", "total_liab", "total_hldr_eqy_exc_min_int", "money_cap"],
            ),
            "cash_flow": StockApiFormatter.report_summary(
                cash_flow[0] if cash_flow else None,
                ["n_cashflow_act", "n_cashflow_inv_act", "n_cash_flows_fnc_act", "free_cashflow"],
            ),
            "financial_indicator": StockApiFormatter.report_summary(
                indicator[0] if indicator else None,
                ["eps", "roe", "roa", "grossprofit_margin", "netprofit_margin", "debt_to_assets", "current_ratio"],
            ),
        }

    async def get_diagnosis(self, symbol: str) -> dict[str, Any]:
        overview = await self.get_overview(symbol)
        return {
            "symbol": symbol,
            "available": True,
            "message": self._diagnosis_message(overview["valuation"]),
        }

    async def get_news(self, symbol: str) -> dict[str, Any]:
        await self._ensure_security(symbol)
        rows = await StockNews.filter(
            symbol=symbol, news_type="news",
            order_by=StockNews.publish_time.desc(), limit=20,
        )
        return {"symbol": symbol, "items": [self._news_item(r) for r in rows]}

    async def get_announcements(self, symbol: str) -> dict[str, Any]:
        await self._ensure_security(symbol)
        rows = await StockNews.filter(
            symbol=symbol, news_type="announcement",
            order_by=StockNews.publish_time.desc(), limit=20,
        )
        return {"symbol": symbol, "items": [self._news_item(r) for r in rows]}

    @staticmethod
    def _news_item(row: StockNews) -> dict[str, Any]:
        return {
            "title": row.title,
            "source": row.source,
            "url": row.news_url,
            "publish_time": StockApiFormatter.value(row.publish_time),
            "keywords": row.keywords or [],
            "content": row.content,
        }

    def _quote_snapshot(self, symbol: str, candle: CandlestickDaily | None) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "last": StockApiFormatter.value(getattr(candle, "close", None)),
            "prev_close": StockApiFormatter.value(getattr(candle, "pre_close", None)),
            "change": StockApiFormatter.value(getattr(candle, "change", None)),
            "change_pct": StockApiFormatter.value(getattr(candle, "pct_chg", None)),
            "open": StockApiFormatter.value(getattr(candle, "open", None)),
            "high": StockApiFormatter.value(getattr(candle, "high", None)),
            "low": StockApiFormatter.value(getattr(candle, "low", None)),
            "volume": StockApiFormatter.value(getattr(candle, "volume", None)),
            "amount": StockApiFormatter.value(getattr(candle, "amount", None)),
            "timestamp": StockApiFormatter.date_value(getattr(candle, "trade_date", None)),
            "status": "closed",
            "source": "daily",
        }

    def _valuation_panel(self, indicator: DailyIndicator | None) -> dict[str, Any]:
        fields = [
            "trade_date",
            "close",
            "pe",
            "pe_ttm",
            "pb",
            "ps",
            "ps_ttm",
            "dv_ratio",
            "total_mv",
            "circ_mv",
            "turnover_rate",
        ]
        return StockApiFormatter.model_highlights(indicator, fields)

    def _diagnosis_message(self, valuation: dict[str, Any]) -> str:
        pe_ttm = valuation.get("pe_ttm")
        pb = valuation.get("pb")
        return f"当前估值 PE(TTM)={pe_ttm or '--'}，PB={pb or '--'}，可结合趋势、资金与财务标签进一步分析。"


class StockKlineService(SecurityMixin):
    """个股K线及技术指标服务。"""

    async def get_kline(self, symbol: str, limit: int = 1200) -> dict[str, Any]:
        await self._ensure_security(symbol)
        rows = await CandlestickDaily.filter(symbol=symbol, order_by=CandlestickDaily.trade_date.desc(), limit=limit)
        rows = list(reversed(rows))
        bars = [StockApiFormatter.bar_item(row) for row in rows]
        overlays = self._technical_overlays(rows)
        return {
            "symbol": symbol,
            "bars": bars,
            "overlays": overlays,
            "ma_overlays": overlays["ma"],
        }

    async def get_kline_bars(self, symbol: str, limit: int = 1200) -> list[dict[str, Any]]:
        """仅查询K线数据，不计算技术指标。"""
        await self._ensure_security(symbol)
        rows = await CandlestickDaily.filter(symbol=symbol, order_by=CandlestickDaily.trade_date.desc(), limit=limit)
        rows = list(reversed(rows))
        return [StockApiFormatter.bar_item(row) for row in rows]

    def _technical_overlays(self, rows: list[CandlestickDaily]) -> dict[str, dict[str, list[float | None]]]:
        if not rows:
            return {key: {} for key in ["ma", "macd", "rsi", "kdj", "bias", "adx", "boll", "td9"]}
        close = np.array([row.close for row in rows], dtype=float)
        high = np.array([row.high for row in rows], dtype=float)
        low = np.array([row.low for row in rows], dtype=float)
        ma_periods = [5, 10, 20, 30, 60, 120]
        ma = {f"ma{p}": StockApiFormatter.series(talib.MA(close, timeperiod=p)) for p in ma_periods}
        dif, dea, macd = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
        k, d = talib.STOCH(high, low, close, fastk_period=9, slowk_period=3, slowd_period=3)
        j = 3 * k - 2 * d
        return {
            "ma": ma,
            "macd": {
                "dif": StockApiFormatter.series(dif),
                "dea": StockApiFormatter.series(dea),
                "macd": StockApiFormatter.series(macd * 2),
            },
            "rsi": {"rsi14": StockApiFormatter.series(talib.RSI(close, timeperiod=14))},
            "kdj": {
                "k": StockApiFormatter.series(k),
                "d": StockApiFormatter.series(d),
                "j": StockApiFormatter.series(j),
            },
            "bias": self._bias(close),
            "adx": {
                "adx": StockApiFormatter.series(talib.ADX(high, low, close, timeperiod=14)),
                "plus_di": StockApiFormatter.series(talib.PLUS_DI(high, low, close, timeperiod=14)),
                "minus_di": StockApiFormatter.series(talib.MINUS_DI(high, low, close, timeperiod=14)),
            },
            "boll": {
                "upper": StockApiFormatter.series(upper),
                "middle": StockApiFormatter.series(middle),
                "lower": StockApiFormatter.series(lower),
            },
            "td9": self._td9(close),
        }

    def _bias(self, close: np.ndarray) -> dict[str, list[float | None]]:
        result: dict[str, list[float | None]] = {}
        for period in [6, 12, 24]:
            ma = talib.MA(close, timeperiod=period)
            bias = np.where((ma == 0) | np.isnan(ma), np.nan, (close - ma) / ma * 100)
            result[f"bias{period}"] = StockApiFormatter.series(bias)
        return result

    def _td9(self, close: np.ndarray) -> dict[str, list[float | None]]:
        buy_setup: list[float | None] = [None] * len(close)
        sell_setup: list[float | None] = [None] * len(close)
        buy_count = 0
        sell_count = 0
        for index in range(len(close)):
            if index < 4:
                continue
            if close[index] > close[index - 4]:
                sell_count = sell_count + 1 if sell_count < 9 else 1
                buy_count = 0
                sell_setup[index] = float(sell_count)
            elif close[index] < close[index - 4]:
                buy_count = buy_count + 1 if buy_count < 9 else 1
                sell_count = 0
                buy_setup[index] = float(buy_count)
            else:
                buy_count = 0
                sell_count = 0
        return {"buy_setup": buy_setup, "sell_setup": sell_setup}


class StockFundFlowService(SecurityMixin):
    """个股资金流服务。"""

    async def get_fund_flow(self, symbol: str, limit: int = 120) -> dict[str, Any]:
        await self._ensure_security(symbol)
        # EMA 为有状态计算，需从第一条数据开始遍历，因此全量查询
        all_flow = await FundFlowIndividual.filter(
            symbol=symbol, source="tushare",
            order_by=FundFlowIndividual.trade_date.asc(),
        )
        if not all_flow:
            return {"symbol": symbol, "items": []}
        # 仅查询与资金流数据相同日期范围的 circ_mv，避免加载多余数据
        first_date = all_flow[0].trade_date
        indicators = await DailyIndicator.filter(
            symbol=symbol, trade_date__gte=first_date,
            order_by=DailyIndicator.trade_date.asc(),
        )
        circ_map: dict[str, float] = {}
        for ind in indicators:
            if ind.circ_mv and ind.trade_date:
                circ_map[str(ind.trade_date)] = float(ind.circ_mv)
        items = self._build_fund_flow_items(all_flow, circ_map)
        return {"symbol": symbol, "items": items[-limit:] if limit < len(items) else items}

    def _build_fund_flow_items(
        self,
        rows: list[FundFlowIndividual],
        circ_map: dict[str, float],
    ) -> list[dict[str, Any]]:
        """按东财资金博弈算法计算：net_amt/circ_mv*10000 万分比 + EMA5 平滑。"""
        ema_period = 5
        alpha = 2.0 / (ema_period + 1)
        ema_huge = ema_big = ema_mid = ema_small = 0.0
        initialized = False
        items: list[dict[str, Any]] = []
        for row in rows:
            base = StockApiFormatter.model_highlights(
                row,
                [
                    "trade_date", "close",
                    "main_net_amt", "main_net_pct",
                    "huge_net_amt", "huge_net_pct",
                    "big_net_amt", "big_net_pct",
                    "mid_net_amt", "mid_net_pct",
                    "small_net_amt", "small_net_pct",
                ],
            )
            base["pct_chg"] = StockApiFormatter.value(getattr(row, "pct_change", None))
            circ_mv = circ_map.get(str(row.trade_date)) if row.trade_date else None
            if circ_mv and circ_mv > 0:
                w_huge = (row.huge_net_amt or 0) / circ_mv * 10000
                w_big = (row.big_net_amt or 0) / circ_mv * 10000
                w_mid = (row.mid_net_amt or 0) / circ_mv * 10000
                w_small = (row.small_net_amt or 0) / circ_mv * 10000
                # EMA 平滑
                if not initialized:
                    ema_huge, ema_big, ema_mid, ema_small = w_huge, w_big, w_mid, w_small
                    initialized = True
                else:
                    ema_huge = alpha * w_huge + (1 - alpha) * ema_huge
                    ema_big = alpha * w_big + (1 - alpha) * ema_big
                    ema_mid = alpha * w_mid + (1 - alpha) * ema_mid
                    ema_small = alpha * w_small + (1 - alpha) * ema_small
            # circ_mv 缺失时跳过 EMA 更新，保持前值
            base["huge_net_inflow_pct"] = round(ema_huge, 4) if initialized else None
            base["big_net_inflow_pct"] = round(ema_big, 4) if initialized else None
            base["mid_net_inflow_pct"] = round(ema_mid, 4) if initialized else None
            base["small_net_inflow_pct"] = round(ema_small, 4) if initialized else None
            items.append(base)
        return items


class StockChanlunService(SecurityMixin):
    """个股缠论图形元素服务。"""

    async def get_chanlun(self, symbol: str) -> dict[str, Any]:
        await self._ensure_security(symbol)
        rows = await CandlestickDaily.filter(symbol=symbol, order_by=CandlestickDaily.trade_date.asc(), limit=12000)
        if len(rows) < 5:
            return {"fractals": [], "strokes": [], "pivots": []}
        return self._chanlun_visuals(rows)

    def _chanlun_visuals(self, rows: list[CandlestickDaily]) -> dict[str, list[dict[str, Any]]]:
        import chanpy  # noqa: F401, I001 — 顶级模块导入，触发 __init__.py 将包目录加入 sys.path
        from Chan import CChan  # type: ignore[import-not-found]  # noqa: I001
        from ChanConfig import CChanConfig  # type: ignore[import-not-found]  # noqa: I001
        from Common.CEnum import AUTYPE, KL_TYPE  # type: ignore[import-not-found]  # noqa: I001

        bars = [StockApiFormatter.bar_item(row) for row in rows]
        df = pd.DataFrame(bars)
        open_arr = df["open"].to_numpy(dtype=float)
        high_arr = df["high"].to_numpy(dtype=float)
        low_arr = df["low"].to_numpy(dtype=float)
        close_arr = df["close"].to_numpy(dtype=float)
        ohlc_max = np.maximum.reduce([open_arr, high_arr, low_arr, close_arr])
        ohlc_min = np.minimum.reduce([open_arr, high_arr, low_arr, close_arr])
        chan_df = pd.DataFrame(
            {
                "open": open_arr,
                "high": np.maximum(high_arr, ohlc_max),
                "low": np.minimum(low_arr, ohlc_min),
                "close": close_arr,
                "volume": df["volume"].to_numpy(dtype=float),
            },
            index=pd.DatetimeIndex(pd.to_datetime(df["trade_date"])),
        )
        try:
            with chanlun_cache(chan_df) as cache_key:
                config = CChanConfig(
                    {
                        "bi_strict": True,
                        "bi_fx_check": "strict",
                        "zs_combine": False,
                        "zs_algo": "auto",
                        "seg_algo": "chan",
                        "trigger_step": False,
                        "kl_data_check": False,
                    }
                )
                chan = CChan(
                    code=cache_key,
                    data_src="custom:DfApi.DfApi",
                    lv_list=[KL_TYPE.K_DAY],
                    autype=AUTYPE.NONE,
                    config=config,
                )
                kl_list = chan[0]
                return {
                    "fractals": self._chanlun_fractals(kl_list, bars),
                    "strokes": self._chanlun_strokes(kl_list, bars),
                    "pivots": self._chanlun_pivots(kl_list, bars),
                }
        except Exception as exc:
            logger.error("缠论图形元素计算失败: %s", exc, exc_info=True)
            raise

    def _chanlun_fractals(self, kl_list: Any, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from Common.CEnum import FX_TYPE  # type: ignore[import-not-found]  # noqa: I001

        fractals: list[dict[str, Any]] = []
        for klc in kl_list.lst:
            if klc.fx == FX_TYPE.UNKNOWN:
                continue
            klu = klc.get_peak_klu(is_high=klc.fx == FX_TYPE.TOP)
            if klu.idx < 0 or klu.idx >= len(bars):
                continue
            fractals.append(
                {
                    "index": klu.idx,
                    "trade_date": bars[klu.idx]["trade_date"],
                    "price": klu.high if klc.fx == FX_TYPE.TOP else klu.low,
                    "direction": "top" if klc.fx == FX_TYPE.TOP else "bottom",
                }
            )
        return fractals

    def _chanlun_strokes(self, kl_list: Any, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        strokes: list[dict[str, Any]] = []
        for bi in kl_list.bi_list:
            begin = bi.get_begin_klu()
            end = bi.get_end_klu()
            if begin.idx < 0 or end.idx < 0 or begin.idx >= len(bars) or end.idx >= len(bars):
                continue
            strokes.append(
                {
                    "start_index": begin.idx,
                    "start_date": bars[begin.idx]["trade_date"],
                    "start_price": bi.get_begin_val(),
                    "end_index": end.idx,
                    "end_date": bars[end.idx]["trade_date"],
                    "end_price": bi.get_end_val(),
                    "direction": "up" if bi.is_up() else "down",
                    "is_sure": bi.is_sure,
                }
            )
        return strokes

    def _chanlun_pivots(self, kl_list: Any, bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        pivots: list[dict[str, Any]] = []
        for zs in kl_list.zs_list:
            begin = zs.begin_bi.get_begin_klu()
            end = zs.end_bi.get_end_klu()
            if begin.idx < 0 or end.idx < 0 or begin.idx >= len(bars) or end.idx >= len(bars):
                continue
            pivots.append(
                {
                    "start_index": begin.idx,
                    "start_date": bars[begin.idx]["trade_date"],
                    "end_index": end.idx,
                    "end_date": bars[end.idx]["trade_date"],
                    "zg": zs.high,
                    "zd": zs.low,
                    "zz": zs.mid,
                    "is_sure": zs.is_sure,
                }
            )
        return pivots
