"""加载阶段 — 加载全量K线行情、资金流和风险因子所需指标数据。

数据加载策略：
  - 始终加载全量历史数据（无日期过滤），确保有状态因子（MACD/KDJ等）可从首根K线累计状态
  - CalcStage 根据因子是否有状态，决定传入全量数据还是 5yr+warmup 切片
  - PersistStage 根据 start_date 只持久化增量部分

根据架构设计，估值指标和财务因子属于截面因子，不在因子计算任务中加载。
但风险因子所需的 total_mv/turnover_rate 属于逐标的计算依赖，在此加载。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.market.models.daily_indicator import DailyIndicator
from xqtrader.domain.market.models.fund_flow import FundFlowIndividual

logger = get_logger("factor.load")


class FactorLoadStage(Stage):
    """加载阶段 — 加载全量K线行情和资金流数据。

    增量跳过由 WatermarkAspect 前切控制（is_up_to_date 标记）。
    """

    @property
    def name(self) -> str:
        return "factor_load"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        symbol: str = item

        # 水位最新时由 WatermarkAspect 标记跳过
        if ctx.get("is_up_to_date"):
            return StageResult.ok(data={"symbol": symbol, "rows": 0, "skipped": True})

        # 加载全量K线行情（无日期过滤，保证有状态因子可从首根K线累计）
        df_kline = await self._load_kline(symbol)
        if df_kline.empty:
            logger.info("[factor.compute] %s no kline data", symbol)
            ctx.set("skip_persist", True)
            ctx.set("kline_df", df_kline)
            return StageResult.ok(data={"symbol": symbol, "rows": 0})

        # 加载全量资金流数据
        df_flow = await self._load_fund_flow(symbol)

        # 加载风险因子所需指标（total_mv, turnover_rate 等）
        df_indicator = await self._load_daily_indicator(symbol)

        # 合并K线和资金流
        if not df_flow.empty:
            df_merged = self._merge_kline_flow(df_kline, df_flow)
        else:
            df_merged = df_kline

        # 合并指标数据
        if not df_indicator.empty:
            df_merged = self._merge_indicator(df_merged, df_indicator)

        ctx.set("kline_df", df_merged)
        ctx.set("skip_persist", False)

        date_range = ""
        if "trade_date" in df_merged.columns:
            dates = df_merged["trade_date"]
            date_range = f"{dates.iloc[0]}~{dates.iloc[-1]}"

        logger.info(
            "[factor.compute] %s rows=%d date=%s | flow=%s",
            symbol, len(df_merged), date_range,
            "yes" if not df_flow.empty else "no",
        )
        return StageResult.ok(data={"symbol": symbol, "rows": len(df_merged)})

    async def _load_kline(self, symbol: str) -> pd.DataFrame:
        """加载全量K线行情数据。"""
        filters: dict[str, Any] = {"symbol": symbol}

        rows = await CandlestickDaily.filter(
            **filters,
            order_by=CandlestickDaily.trade_date.asc(),
        )
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([r.to_dict() for r in rows])
        for col in ["open", "close", "high", "low", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    async def _load_fund_flow(self, symbol: str) -> pd.DataFrame:
        """加载全量资金流数据。"""
        filters: dict[str, Any] = {"symbol": symbol}

        rows = await FundFlowIndividual.filter(
            **filters,
            order_by=FundFlowIndividual.trade_date.asc(),
        )
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([r.to_dict() for r in rows])
        numeric_cols = [
            "main_net_amt", "main_net_pct", "huge_net_amt", "huge_net_pct",
            "big_net_amt", "big_net_pct", "mid_net_amt", "mid_net_pct",
            "small_net_amt", "small_net_pct", "net_mf_amt",
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 统一 tushare 数据源，按 source 优先级排序后去重（tushare 优先于 dc 等旧数据源）
        if "trade_date" in df.columns and "source" in df.columns:
            source_priority = {"tushare": 0, "dc": 1}
            df["_src_rank"] = df["source"].map(source_priority).fillna(99)
            df = df.sort_values("_src_rank").drop_duplicates(subset=["trade_date"], keep="first")
            df = df.drop(columns=["_src_rank"])
        elif "trade_date" in df.columns:
            df = df.drop_duplicates(subset=["trade_date"], keep="first")
        return df

    @staticmethod
    def _merge_kline_flow(df_kline: pd.DataFrame, df_flow: pd.DataFrame) -> pd.DataFrame:
        """合并K线和资金流数据 — 精确日期匹配，不前向填充。"""
        # 排除 close/pct_change：K线已有 close，资金流的 close/pct_change 为 dc 遗留字段
        flow_cols = [
            c for c in df_flow.columns
            if c not in ("symbol", "trade_date", "source", "close", "pct_change")
        ]
        if not flow_cols:
            return df_kline

        df_merge = df_flow[["trade_date"] + flow_cols].copy()
        df_kline_sorted = df_kline.sort_values("trade_date")

        # 统一 trade_date 类型为 date，确保精确匹配
        df_kline_sorted["trade_date"] = pd.to_datetime(df_kline_sorted["trade_date"]).dt.date
        df_merge["trade_date"] = pd.to_datetime(df_merge["trade_date"]).dt.date

        df_merged = df_kline_sorted.merge(df_merge, on="trade_date", how="left")
        return df_merged

    async def _load_daily_indicator(self, symbol: str) -> pd.DataFrame:
        """加载风险因子所需的每日指标数据（total_mv, turnover_rate 等）。"""
        rows = await DailyIndicator.filter(
            symbol=symbol,
            order_by=DailyIndicator.trade_date.asc(),
        )
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame([r.to_dict() for r in rows])
        indicator_cols = ["total_mv", "turnover_rate", "turnover_rate_f"]
        for col in indicator_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "trade_date" in df.columns:
            df = df.drop_duplicates(subset=["trade_date"], keep="last")
        return df

    @staticmethod
    def _merge_indicator(df_merged: pd.DataFrame, df_indicator: pd.DataFrame) -> pd.DataFrame:
        """合并指标数据到主 DataFrame。"""
        indicator_cols = [
            c for c in df_indicator.columns
            if c not in ("symbol", "trade_date", "source")
            and c not in df_merged.columns
        ]
        if not indicator_cols:
            return df_merged

        df_ind = df_indicator[["trade_date"] + indicator_cols].copy()
        df_merged["trade_date"] = pd.to_datetime(df_merged["trade_date"]).dt.date
        df_ind["trade_date"] = pd.to_datetime(df_ind["trade_date"]).dt.date

        df_merged = df_merged.merge(df_ind, on="trade_date", how="left")
        return df_merged
