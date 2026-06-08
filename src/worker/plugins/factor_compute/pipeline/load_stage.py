"""因子数据加载阶段 — 加载K线、日指标、财务PIT、资金流、指数K线数据。

为每只股票加载计算所需的全部输入数据，通过 PipelineContext 传递给后续阶段。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult
from worker.plugins.factor_compute.plugins.base import FactorPluginRegistry
from xqtrader.domain.factor.exceptions import FactorLoadError
from xqtrader.domain.index.index_daily import IndexDaily
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.market.models.daily_indicator import DailyIndicator
from xqtrader.domain.market.models.financial_indicator import FinancialIndicator
from xqtrader.domain.market.models.fund_flow_individual import FundFlowIndividual

logger = get_logger(__name__)


class FactorLoadStage(Stage):
    """因子数据加载阶段 — 为每只股票加载计算所需的全部输入数据。

    加载策略：
      - 有状态因子（is_stateful=True）：加载全部历史K线，确保 EWM/递推精度
      - 无状态因子：加载近5年+400天K线，满足最长窗口需求

    加载内容：
      1. K线数据（有状态→全部历史；无状态→5年+400天）
      2. 日指标数据（估值/换手率/市值等）
      3. 财务PIT数据（基本面因子）
      4. 资金流数据（量价因子）
    """

    def __init__(
        self,
        registry: FactorPluginRegistry,
        trade_dates: list[date],
    ) -> None:
        self._registry = registry
        self._trade_dates = trade_dates
        self._has_stateful = any(p.is_stateful for p in registry.all_plugins())

    @property
    def name(self) -> str:
        return "factor_load"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item
        end_date = self._trade_dates[-1]
        start_date = self._trade_dates[0]

        try:
            # 1. 加载K线数据
            kline_df = await self._load_kline(stock_code, start_date, end_date)
            if kline_df is None or kline_df.empty:
                logger.debug("无K线数据: %s", stock_code)
                ctx.set("skip_calc", True)
                return StageResult.ok(data={"stock_code": stock_code, "loaded": False})

            # 数据门禁校验
            if "close" not in kline_df.columns or kline_df["close"].isna().all():
                logger.warning("数据门禁不通过: %s close无效", stock_code)
                ctx.set("skip_calc", True)
                return StageResult.ok(data={"stock_code": stock_code, "loaded": False})

            ctx.set("kline_df", kline_df)

            # 2. 加载日指标数据
            indicator_df = await self._load_indicator(stock_code, start_date, end_date)
            ctx.set("indicator_df", indicator_df)

            # 3. 加载财务PIT数据（全部记录，供按日PIT取值）
            fina_df = await self._load_financial(stock_code, end_date)
            ctx.set("fina_df", fina_df)

            # 4. 加载资金流数据
            fund_flow_df = await self._load_fund_flow(stock_code, start_date, end_date)
            ctx.set("fund_flow_df", fund_flow_df)

            # 5. 指数K线（从全局上下文获取，避免重复加载）
            if not ctx.contains("index_kline_df"):
                index_kline_df = await self._load_index_kline(end_date)
                ctx.set("index_kline_df", index_kline_df)

            ctx.set("skip_calc", False)
            logger.debug(
                "数据加载完成: %s kline=%d indicator=%s fina=%s fund_flow=%s",
                stock_code, len(kline_df),
                len(indicator_df) if indicator_df is not None else 0,
                len(fina_df) if fina_df is not None else 0,
                len(fund_flow_df) if fund_flow_df is not None else 0,
            )
            return StageResult.ok(data={"stock_code": stock_code, "loaded": True, "kline_rows": len(kline_df)})

        except FactorLoadError as e:
            logger.error("数据加载失败: %s error=%s", stock_code, e)
            return StageResult.fail(f"数据加载失败 {stock_code}: {e}")

    async def _load_kline(self, stock_code: str, start_date: date, end_date: date) -> pd.DataFrame | None:
        """加载K线数据。有状态因子加载全部历史；无状态因子5年+400天。"""
        if self._has_stateful:
            rows = await CandlestickDaily.filter(
                symbol=stock_code,
                trade_date__lte=end_date,
                order_by=CandlestickDaily.trade_date.asc(),
            )
        else:
            lookback_start = start_date - timedelta(days=400)
            rows = await CandlestickDaily.filter(
                symbol=stock_code,
                trade_date__gte=lookback_start,
                trade_date__lte=end_date,
                order_by=CandlestickDaily.trade_date.asc(),
            )
        if not rows:
            return None
        data = [
            {
                "trade_date": r.trade_date,
                "open": r.open,
                "close": r.close,
                "high": r.high,
                "low": r.low,
                "volume": r.volume,
                "amount": r.amount,
            }
            for r in rows
        ]
        return pd.DataFrame(data)

    @staticmethod
    async def _load_indicator(stock_code: str, start_date: date, end_date: date) -> pd.DataFrame | None:
        """加载日指标数据。"""
        rows = await DailyIndicator.filter(
            symbol=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
            order_by=DailyIndicator.trade_date.asc(),
        )
        if not rows:
            return None
        return pd.DataFrame([r.to_dict() for r in rows])

    @staticmethod
    async def _load_financial(stock_code: str, end_date: date) -> pd.DataFrame | None:
        """加载全部财务记录（供按日PIT取值）。

        加载该股票截至 end_date 的所有财务指标记录，
        按 ann_date 排序，供后续 merge_asof 按交易日做 PIT 对齐。
        """
        rows = await FinancialIndicator.filter(
            symbol=stock_code,
            ann_date__lte=end_date,
            order_by=FinancialIndicator.ann_date.asc(),
        )
        if not rows:
            return None
        return pd.DataFrame([r.to_dict() for r in rows])

    @staticmethod
    async def _load_fund_flow(stock_code: str, start_date: date, end_date: date) -> pd.DataFrame | None:
        """加载资金流数据。"""
        rows = await FundFlowIndividual.filter(
            symbol=stock_code,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
            order_by=FundFlowIndividual.trade_date.asc(),
        )
        if not rows:
            return None
        data = [
            {
                "trade_date": r.trade_date,
                "net_mf_amt": r.net_mf_amt,
                "main_net_amt": r.main_net_amt,
                "main_net_pct": r.main_net_pct,
                "huge_net_amt": r.huge_net_amt,
                "huge_net_pct": r.huge_net_pct,
                "huge_buy_amt": r.huge_buy_amt,
                "huge_sell_amt": r.huge_sell_amt,
                "big_net_amt": r.big_net_amt,
                "big_net_pct": r.big_net_pct,
                "big_buy_amt": r.big_buy_amt,
                "big_sell_amt": r.big_sell_amt,
            }
            for r in rows
        ]
        return pd.DataFrame(data)

    @staticmethod
    async def _load_index_kline(end_date: date) -> pd.DataFrame | None:
        """加载沪深300指数K线数据。"""
        rows = await IndexDaily.filter(
            symbol="000300.SH",
            trade_date__lte=end_date,
            order_by=IndexDaily.trade_date.asc(),
        )
        if not rows:
            return None
        data = [{"trade_date": r.trade_date, "close": r.close} for r in rows]
        return pd.DataFrame(data)
