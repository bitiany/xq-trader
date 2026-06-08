"""PIT截面取值服务 — 财务因子 Point-in-Time 读取。

采用 ann_date 精确模式：WHERE ann_date <= trade_date
兜底链：ann_date → f_ann_date → report_lag_days → NULL
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from xqtrader.domain.market.models.balance_sheet import BalanceSheet
from xqtrader.domain.market.models.cash_flow import CashFlowStatement
from xqtrader.domain.market.models.financial_indicator import FinancialIndicator
from xqtrader.domain.market.models.income_statement import IncomeStatement

logger = get_logger(__name__)

# 财务模型联合类型
_FinancialModel = type[FinancialIndicator | IncomeStatement | BalanceSheet | CashFlowStatement]

# 模型注册表: table_name -> ORM 模型类
_MODEL_MAP: dict[str, _FinancialModel] = {
    "sdc_financial_indicator": FinancialIndicator,
    "sdc_income_statement": IncomeStatement,
    "sdc_balance_sheet": BalanceSheet,
    "sdc_cash_flow": CashFlowStatement,
}

# 表是否有 f_ann_date 列
_HAS_F_ANN_DATE: dict[str, bool] = {
    "sdc_financial_indicator": False,
    "sdc_income_statement": True,
    "sdc_balance_sheet": True,
    "sdc_cash_flow": True,
}


class PITReader:
    """PIT截面取值器 — 按截面日读取最新可用财务数据。"""

    @staticmethod
    async def read_as_of(
        table_name: str,
        symbol: str,
        trade_date: date,
        report_lag_days: int = 120,
    ) -> dict[str, Any] | None:
        """读取截至 trade_date 的最新财务记录。

        三级兜底: ann_date → f_ann_date → report_lag_days

        Args:
            table_name: 财务表名 (如 sdc_financial_indicator)
            symbol: 证券代码
            trade_date: 截面日期
            report_lag_days: 财报滞后天数 (默认120天)

        Returns:
            最新财务记录字典，无数据返回 None
        """
        model = _MODEL_MAP.get(table_name)
        if model is None:
            logger.warning("未知的财务表: %s", table_name)
            return None

        # 模式1: ann_date 精确模式
        rows = await model.filter(
            symbol=symbol,
            ann_date__lte=trade_date,
            limit=1,
            order_by=model.end_date.desc(),
        )
        if rows:
            return rows[0].to_dict()

        # 模式2: f_ann_date 兜底
        if _HAS_F_ANN_DATE.get(table_name, False):
            rows = await model.filter(
                symbol=symbol,
                f_ann_date__lte=trade_date,
                limit=1,
                order_by=model.end_date.desc(),
            )
            if rows:
                return rows[0].to_dict()

        # 模式3: report_lag_days 兜底
        cutoff = trade_date - timedelta(days=report_lag_days)
        rows = await model.filter(
            symbol=symbol,
            end_date__lte=cutoff,
            limit=1,
            order_by=model.end_date.desc(),
        )
        if rows:
            return rows[0].to_dict()

        return None

    @staticmethod
    async def read_batch_as_of(
        table_name: str,
        symbols: list[str],
        trade_date: date,
        report_lag_days: int = 120,
    ) -> pd.DataFrame:
        """批量读取截至 trade_date 的最新财务记录。

        Args:
            table_name: 财务表名
            symbols: 证券代码列表
            trade_date: 截面日期
            report_lag_days: 财报滞后天数

        Returns:
            DataFrame, index=symbol
        """
        if not symbols:
            return pd.DataFrame()

        model = _MODEL_MAP.get(table_name)
        if model is None:
            return pd.DataFrame()

        # 模式1: ann_date 精确模式
        rows = await model.filter(
            symbol__in=symbols,
            ann_date__lte=trade_date,
            order_by=model.end_date.desc(),
        )
        if rows:
            # 去重：每个 symbol 只保留最新记录
            seen: set[str] = set()
            unique_rows: list[dict[str, Any]] = []
            for r in rows:
                if r.symbol not in seen:
                    seen.add(r.symbol)
                    unique_rows.append(r.to_dict())
            return pd.DataFrame(unique_rows).set_index("symbol") if unique_rows else pd.DataFrame()

        # 模式2: f_ann_date 兜底
        if _HAS_F_ANN_DATE.get(table_name, False):
            rows = await model.filter(
                symbol__in=symbols,
                f_ann_date__lte=trade_date,
                order_by=model.end_date.desc(),
            )
            if rows:
                seen = set()
                unique_rows = []
                for r in rows:
                    if r.symbol not in seen:
                        seen.add(r.symbol)
                        unique_rows.append(r.to_dict())
                return pd.DataFrame(unique_rows).set_index("symbol") if unique_rows else pd.DataFrame()

        # 模式3: report_lag_days 兜底
        cutoff = trade_date - timedelta(days=report_lag_days)
        rows = await model.filter(
            symbol__in=symbols,
            end_date__lte=cutoff,
            order_by=model.end_date.desc(),
        )
        if rows:
            seen = set()
            unique_rows = []
            for r in rows:
                if r.symbol not in seen:
                    seen.add(r.symbol)
                    unique_rows.append(r.to_dict())
            return pd.DataFrame(unique_rows).set_index("symbol") if unique_rows else pd.DataFrame()

        return pd.DataFrame()
