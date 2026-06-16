"""季度财务因子计算任务 — 计算B2-B5因子并写入fac_financial_factor_value。

管线流程（逐标的串行执行）：
  加载财务指标 + 利润表数据 → 计算缺失成长因子 → 逐因子计算 → 持久化

与日频因子计算的核心区别：
  - 数据粒度为季度（非日频），值仅在财报发布时变化
  - 存储到 fac_financial_factor_value（非 fac_factor_value）
  - 使用 PIT（Point-in-Time）机制，以 ann_date 为关键字段
  - 不做前向填充，保留原始季度记录（前向填充由 CrossSectionReader 完成）

数据来源与补充策略：
  - fina_indicator：提供大部分比率指标（roe/roa/grossprofit_margin 等，覆盖率 >95%）
  - income_statement：补充 ebit_to_interest（fina 仅 64%），计算 q_or_yoy/q_netprofitgrow_qoq 等
  - 跨期计算：单季度值 = 当期累计 - 上期累计，同比/环比基于单季度值
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.base import FactorPlugin
from xqtrader.domain.factor.models.financial_factor_value import FacFinancialFactorValue
from xqtrader.domain.factor.services.registry import (
    auto_discover_factors,
    register_factor_variants,
    resolve_factor_list,
    sync_to_registry,
)
from xqtrader.domain.market.models.financial_indicator import FinancialIndicator
from xqtrader.domain.market.models.income_statement import IncomeStatement
from xqtrader.domain.security.models import Security

logger = get_logger("factor.compute_quarterly")

_COMPUTE_MODE_INCREMENTAL = "incremental"
_COMPUTE_MODE_FULL = "full"

# 增量模式下跨期计算（同比/环比）需要历史数据回溯窗口（月数）
# 同比需去年同期（12个月）+ 余量 → 15个月确保覆盖
_LOOKBACK_MONTHS = 15

# B2-B5 财务因子所在的模块路径前缀
_FINANCIAL_FACTOR_MODULE_PREFIXES = frozenset({
    "worker.plugins.factor_compute.factors.fundamental_profitability",
    "worker.plugins.factor_compute.factors.fundamental_growth",
    "worker.plugins.factor_compute.factors.fundamental_quality",
    "worker.plugins.factor_compute.factors.fundamental_leverage",
})


def _is_financial_factor(plugin: FactorPlugin) -> bool:
    """判断因子插件是否为B2-B5财务因子。"""
    module = plugin.__class__.__module__
    return any(module.startswith(prefix) for prefix in _FINANCIAL_FACTOR_MODULE_PREFIXES)


class FactorQuarterlyTask(BaseTask):
    """季度财务因子计算任务 — 计算B2-B5因子并写入fac_financial_factor_value。

    入参：
      - symbols: 股票代码列表（为空时计算全市场）
      - factor_ids: 因子ID列表（为空时计算所有活跃财务因子）
      - mode: 计算模式 incremental/full

    增量水位策略：
      查询 fac_financial_factor_value 中该标的的最大 ann_date 作为水位，
      加载 ann_date > (水位 - 15个月) 的数据用于跨期计算，
      仅持久化 ann_date > 水位 的新记录。任务失败时已处理的标的数据
      已写入，未处理的标的下次运行时会重新计算（幂等 upsert）。
    """

    task_name = "factor.compute_quarterly"
    description = "计算B2-B5财务因子，写入fac_financial_factor_value（按ann_date季度存储）"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        symbols = parse_list_param(kwargs.get("symbols"))
        factor_ids = parse_list_param(kwargs.get("factor_ids"))
        mode = str(kwargs.get("mode", _COMPUTE_MODE_INCREMENTAL))

        if mode not in (_COMPUTE_MODE_INCREMENTAL, _COMPUTE_MODE_FULL):
            return {"status": "FAILED", "message": f"Invalid mode: {mode}"}

        # 初始化因子注册表
        auto_discover_factors()
        register_factor_variants()
        await sync_to_registry()

        # 解析因子列表并过滤B2-B5财务因子
        all_plugins = await resolve_factor_list(factor_ids)
        plugins = [p for p in all_plugins if _is_financial_factor(p)]

        if not plugins:
            logger.warning("无财务因子需要计算")
            return {"status": "skipped", "reason": "no_financial_factors"}

        # 获取标的列表
        if not symbols:
            symbols = await self._get_security_list()
            if not symbols:
                return {"status": "FAILED", "message": "No symbols to process"}

        logger.info(
            "季度因子计算开始: %d标的, %d因子, mode=%s",
            len(symbols), len(plugins), mode,
        )

        # 逐标的处理
        total_upserted = 0
        for symbol in symbols:
            try:
                upserted = await self._process_symbol(symbol, plugins, mode)
                total_upserted += upserted
            except Exception:
                logger.error("标的 %s 季度因子计算失败", symbol, exc_info=True)

        logger.info("季度因子计算完成: total_upserted=%d", total_upserted)
        return {"status": "success", "total_upserted": total_upserted}

    async def _process_symbol(
        self, symbol: str, plugins: list[FactorPlugin], mode: str,
    ) -> int:
        """处理单个标的的季度因子计算。"""
        # 增量模式下查询已有最大 ann_date（用于过滤持久化结果）
        persist_cutoff: date | None = None
        if mode == _COMPUTE_MODE_INCREMENTAL:
            cutoff_str = await self._get_max_ann_date(symbol)
            if cutoff_str:
                persist_cutoff = date.fromisoformat(cutoff_str)

        fina_df = await self._load_financial_data(symbol, mode)
        if fina_df is None or fina_df.empty:
            logger.debug("%s: 无财务指标数据，跳过", symbol)
            return 0

        rows: list[FacFinancialFactorValue] = []
        end_dates = fina_df["end_date"]
        ann_dates = fina_df["ann_date"]

        for plugin in plugins:
            try:
                result_df = plugin.compute(fina_df)
                if result_df is None or result_df.empty:
                    continue
                factor_col = plugin.factor_id
                if factor_col not in result_df.columns:
                    continue
                # 向量化筛选有效记录
                valid_mask = (
                    result_df[factor_col].notna()
                    & end_dates.notna()
                    & ann_dates.notna()
                )
                # 增量模式：仅持久化 ann_date > cutoff 的新记录
                if persist_cutoff is not None:
                    valid_mask = valid_mask & (ann_dates > persist_cutoff)
                if not valid_mask.any():
                    continue
                valid_end = end_dates[valid_mask]
                valid_ann = ann_dates[valid_mask]
                valid_val = result_df.loc[valid_mask, factor_col]
                for i in range(len(valid_val)):
                    rows.append(FacFinancialFactorValue(
                        symbol=symbol,
                        end_date=valid_end.iloc[i],
                        factor_id=factor_col,
                        ann_date=valid_ann.iloc[i],
                        factor_value=float(valid_val.iloc[i]),
                    ))
            except Exception:
                logger.error("%s: 因子 %s 计算失败", symbol, plugin.factor_id, exc_info=True)

        if not rows:
            return 0

        upserted = await FacFinancialFactorValue.bulk_create_or_update(
            rows,
            on_conflict=["symbol", "end_date", "factor_id", "ann_date"],
            update_fields=["factor_value"],
        )
        logger.info(
            "%s: upserted=%d factors=%d",
            symbol, upserted, len({r.factor_id for r in rows}),
        )
        return upserted

    async def _load_financial_data(
        self, symbol: str, mode: str,
    ) -> pd.DataFrame | None:
        """加载财务指标 + 利润表数据，计算缺失的成长因子。

        增量模式：加载 ann_date > (cutoff - lookback) 的数据用于跨期计算，
        但仅持久化 ann_date > cutoff 的新记录（过滤在 _process_symbol 中完成）。
        全量模式：加载全部数据。
        """
        # 计算数据加载的截止日期
        # 增量模式下需要 lookback 窗口确保同比/环比计算有历史数据
        load_cutoff: date | None = None
        if mode == _COMPUTE_MODE_INCREMENTAL:
            cutoff_str = await self._get_max_ann_date(symbol)
            if cutoff_str:
                cutoff_date = date.fromisoformat(cutoff_str)
                # 回溯 _LOOKBACK_MONTHS 个月，确保同比计算有去年同期数据
                load_cutoff = _subtract_months(cutoff_date, _LOOKBACK_MONTHS)

        # --- 1. 加载 fina_indicator ---
        fina_df = await self._load_fina_indicator(symbol, load_cutoff)
        if fina_df is None or fina_df.empty:
            return None

        # --- 2. 加载 income_statement 并补充缺失字段 ---
        income_df = await self._load_income_statement(symbol, load_cutoff)
        if income_df is not None and not income_df.empty:
            fina_df = self._enrich_with_income(fina_df, income_df)

        return fina_df

    @staticmethod
    async def _get_max_ann_date(symbol: str) -> str | None:
        """查询该标的在 fac_financial_factor_value 中的最大 ann_date。"""
        from sqlalchemy import func, select

        from framework.dal.session import get_session
        from xqtrader.domain.factor.models.financial_factor_value import FacFinancialFactorValue

        with get_session("stock") as session:
            stmt = select(func.max(FacFinancialFactorValue.ann_date)).where(
                FacFinancialFactorValue.symbol == symbol,
            )
            result = session.execute(stmt).scalar()
            if result is not None:
                return str(result)
        return None

    async def _load_fina_indicator(
        self, symbol: str, load_cutoff: date | None,
    ) -> pd.DataFrame | None:
        """加载财务指标原始数据。增量模式下加载 ann_date > load_cutoff 的记录。"""
        if load_cutoff:
            records = await FinancialIndicator.filter(
                symbol=symbol,
                update_flag="1",
                ann_date__gt=load_cutoff,
                order_by=[FinancialIndicator.end_date.asc(), FinancialIndicator.ann_date.asc()],
            )
        else:
            records = await FinancialIndicator.filter(
                symbol=symbol,
                update_flag="1",
                order_by=[FinancialIndicator.end_date.asc(), FinancialIndicator.ann_date.asc()],
            )

        if not records:
            return None

        data = []
        for rec in records:
            row = {
                "symbol": rec.symbol,
                "ann_date": rec.ann_date,
                "end_date": rec.end_date,
                # B2 盈利
                "roe": rec.roe,
                "roe_waa": rec.roe_waa,
                "roe_dt": rec.roe_dt,
                "roa": rec.roa,
                "roic": rec.roic,
                "grossprofit_margin": rec.grossprofit_margin,
                "netprofit_margin": rec.netprofit_margin,
                "assets_turn": rec.assets_turn,
                # B3 成长（单季度原始值，用于跨期计算）
                "q_roe": rec.q_roe,
                # B3 成长（增长率，直接取值）
                "q_or_yoy": rec.q_or_yoy,
                "q_netprofit_yoy": rec.q_netprofit_yoy,
                "q_dtprofit_yoy": rec.q_dtprofit_yoy,
                "q_op_yoy": rec.q_op_yoy,
                "q_ocf_yoy": rec.q_ocf_yoy,
                "q_roe_yoy": rec.q_roe_yoy,
                "q_netprofitgrow_qoq": rec.q_netprofitgrow_qoq,
                "q_orgrow_qoq": rec.q_orgrow_qoq,
                "q_opgrow_qoq": rec.q_opgrow_qoq,
                "q_roegrow_qoq": rec.q_roegrow_qoq,
                # B4 质量
                "ocf_to_profit": rec.ocf_to_profit,
                "ocf_to_or": rec.ocf_to_or,
                "salescash_to_or": rec.salescash_to_or,
                "dtprofit_to_profit": rec.dtprofit_to_profit,
                "inv_turn": rec.inv_turn,
                "ar_turn": rec.ar_turn,
                # B5 杠杆
                "debt_to_assets": rec.debt_to_assets,
                "current_ratio": rec.current_ratio,
                "eqt_to_talcapital": rec.eqt_to_talcapital,
                "ebit_to_interest": rec.ebit_to_interest,
                "ocf_to_debt": rec.ocf_to_debt,
                "assets_to_eqt": rec.assets_to_eqt,
            }
            data.append(row)

        df = pd.DataFrame(data)
        df = df.dropna(subset=["ann_date"])
        if df.empty:
            return None

        numeric_cols = [c for c in df.columns if c not in ("symbol", "ann_date", "end_date")]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    async def _load_income_statement(
        self, symbol: str, load_cutoff: date | None,
    ) -> pd.DataFrame | None:
        """加载利润表原始数据。增量模式下加载 ann_date > load_cutoff 的记录。"""
        if load_cutoff:
            records = await IncomeStatement.filter(
                symbol=symbol,
                update_flag="1",
                ann_date__gt=load_cutoff,
                order_by=[IncomeStatement.end_date.asc(), IncomeStatement.ann_date.asc()],
            )
        else:
            records = await IncomeStatement.filter(
                symbol=symbol,
                update_flag="1",
                order_by=[IncomeStatement.end_date.asc(), IncomeStatement.ann_date.asc()],
            )

        if not records:
            return None

        data = []
        for rec in records:
            row = {
                "end_date": rec.end_date,
                "ann_date": rec.ann_date,
                "revenue": rec.revenue,
                "oper_cost": rec.oper_cost,
                "operate_profit": rec.operate_profit,
                "n_income_attr_p": rec.n_income_attr_p,
                "ebit": rec.ebit,
                "fin_exp": rec.fin_exp,
                "total_profit": rec.total_profit,
            }
            data.append(row)

        df = pd.DataFrame(data)
        df = df.dropna(subset=["ann_date"])
        if df.empty:
            return None

        numeric_cols = [c for c in df.columns if c not in ("ann_date", "end_date")]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    @staticmethod
    def _enrich_with_income(
        fina_df: pd.DataFrame, income_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """用利润表数据补充 fina_indicator 缺失字段。

        补充策略：
          1. ebit_to_interest：fina_indicator 覆盖率仅 64%，用 ebit/fin_exp 补充
          2. q_or_yoy：fina_indicator 覆盖率 0%，从利润表跨期计算
          3. q_netprofitgrow_qoq/q_orgrow_qoq/q_opgrow_qoq：覆盖率 0%，从利润表跨期计算
          4. q_roe_yoy/q_roegrow_qoq：覆盖率 0%，从 fina_indicator q_roe 跨期计算
        """
        # 按 (end_date, ann_date) 合并利润表数据，避免笛卡尔积
        merge_cols = ["end_date", "ann_date"]
        merged = fina_df.merge(
            income_df[merge_cols + ["revenue", "oper_cost", "operate_profit",
                                     "n_income_attr_p", "ebit", "fin_exp", "total_profit"]],
            on=merge_cols,
            how="left",
            suffixes=("", "_inc"),
        )

        # --- 补充 ebit_to_interest（仅当 fin_exp > 0 时计算） ---
        _fill_ebit_to_interest(merged)

        # --- 计算单季度值（累计值 → 单季度值） ---
        merged = merged.sort_values("end_date").reset_index(drop=True)
        _derive_single_quarter(merged)

        # --- 计算同比增长率（基于 end_date 精确匹配，而非 shift） ---
        _calc_yoy_growth(merged)

        # --- 计算环比增长率（基于 end_date 精确匹配） ---
        _calc_qoq_growth(merged)

        # 清理临时列
        drop_cols = [c for c in merged.columns if c.startswith(("sq_", "prev_"))]
        drop_cols += [c for c in merged.columns if c.endswith(("_inc", "_comp"))]
        merged = merged.drop(columns=drop_cols, errors="ignore")

        return merged

    @staticmethod
    async def _get_security_list() -> list[str]:
        """获取全市场A股标的代码。"""
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        codes = [row.symbol for row in rows]
        logger.debug("全市场标的数: %d", len(codes))
        return codes


def _fill_ebit_to_interest(merged: pd.DataFrame) -> None:
    """补充 ebit_to_interest：仅当 fin_exp > 0（利息支出为正）时计算利息保障倍数。"""
    null_mask = merged["ebit_to_interest"].isna()
    if not null_mask.any():
        return
    ebit = pd.to_numeric(merged.loc[null_mask, "ebit"], errors="coerce")
    fin_exp = pd.to_numeric(merged.loc[null_mask, "fin_exp"], errors="coerce")
    # 仅当利息支出为正时才有意义（利息收入公司不需要利息保障）
    computed = np.where(
        np.isfinite(ebit) & np.isfinite(fin_exp) & (fin_exp > 0),
        ebit / fin_exp,
        np.nan,
    )
    merged.loc[null_mask, "ebit_to_interest"] = computed


def _derive_single_quarter(merged: pd.DataFrame) -> None:
    """推导单季度值：累计值 → 单季度值。

    单季度值 = 当期累计 - 上期累计。Q1（3月31日）直接取累计值。
    """
    for col in ("revenue", "operate_profit", "n_income_attr_p"):
        sq_col = f"sq_{col}"
        merged[sq_col] = merged[col].diff()
        # Q1（end_date 月份为 3）直接取累计值
        is_q1 = merged["end_date"].apply(
            lambda d: d.month == 3 if hasattr(d, "month") else False
        )
        merged.loc[is_q1, sq_col] = merged.loc[is_q1, col]
        # 数据首行若非 Q1 且 diff 为 NaN，取累计值作为近似
        if not merged.empty and pd.isna(merged.loc[0, sq_col]):
            merged.loc[0, sq_col] = merged.loc[0, col]


def _calc_yoy_growth(merged: pd.DataFrame) -> None:
    """计算同比增长率：基于 end_date 精确匹配（月份相同、年份差1）。

    同比 = (今年单季度 - 去年同期单季度) / |去年同期单季度|
    仅在 fina_indicator 原值为空时补充。
    """
    # 构建 (year, month) 辅助列
    merged["_year"] = merged["end_date"].apply(lambda d: d.year if hasattr(d, "year") else None)
    merged["_month"] = merged["end_date"].apply(lambda d: d.month if hasattr(d, "month") else None)

    for col, yoy_col in [
        ("sq_revenue", "q_or_yoy"),
        ("sq_operate_profit", "q_op_yoy_comp"),
        ("sq_n_income_attr_p", "q_netprofit_yoy_comp"),
    ]:
        # 构建 (year, month) → col 值 的索引 dict，O(1) 查找
        prev_col = f"{col}_prev_y"
        lookup = _build_ym_lookup(merged, col)
        merged[prev_col] = [
            lookup.get((yr - 1, mo), np.nan) if yr is not None and mo is not None else np.nan
            for yr, mo in zip(merged["_year"], merged["_month"])
        ]
        valid = np.isfinite(merged[col]) & np.isfinite(merged[prev_col]) & (merged[prev_col] != 0)
        computed = np.where(valid, (merged[col] - merged[prev_col]) / merged[prev_col].abs(), np.nan)
        if yoy_col in merged.columns:
            null_mask = merged[yoy_col].isna()
            merged.loc[null_mask & valid, yoy_col] = computed[null_mask & valid]

    # q_roe_yoy：从 fina_indicator q_roe（单季度 ROE）跨期计算
    prev_q_roe = "q_roe_prev_y"
    roe_lookup = _build_ym_lookup(merged, "q_roe")
    merged[prev_q_roe] = [
        roe_lookup.get((yr - 1, mo), np.nan) if yr is not None and mo is not None else np.nan
        for yr, mo in zip(merged["_year"], merged["_month"])
    ]
    valid_roe = np.isfinite(merged["q_roe"]) & np.isfinite(merged[prev_q_roe]) & (merged[prev_q_roe] != 0)
    roe_yoy = np.where(valid_roe, (merged["q_roe"] - merged[prev_q_roe]) / merged[prev_q_roe].abs(), np.nan)
    null_roe_yoy = merged["q_roe_yoy"].isna()
    merged.loc[null_roe_yoy & valid_roe, "q_roe_yoy"] = roe_yoy[null_roe_yoy & valid_roe]

    merged.drop(columns=["_year", "_month"], inplace=True, errors="ignore")


def _calc_qoq_growth(merged: pd.DataFrame) -> None:
    """计算环比增长率：基于 end_date 精确匹配（上一季度）。

    环比 = (本季度 - 上季度) / |上季度|
    仅在 fina_indicator 原值为空时补充。
    """
    merged["_year"] = merged["end_date"].apply(lambda d: d.year if hasattr(d, "year") else None)
    merged["_month"] = merged["end_date"].apply(lambda d: d.month if hasattr(d, "month") else None)

    for col, qoq_col in [
        ("sq_revenue", "q_orgrow_qoq"),
        ("sq_operate_profit", "q_opgrow_qoq"),
        ("sq_n_income_attr_p", "q_netprofitgrow_qoq"),
    ]:
        prev_col = f"{col}_prev_q"
        lookup = _build_ym_lookup(merged, col)
        merged[prev_col] = [
            lookup.get(key, np.nan) if (key := _prev_quarter_ym(yr, mo)) is not None else np.nan
            for yr, mo in zip(merged["_year"], merged["_month"])
        ]
        valid = np.isfinite(merged[col]) & np.isfinite(merged[prev_col]) & (merged[prev_col] != 0)
        computed = np.where(valid, (merged[col] - merged[prev_col]) / merged[prev_col].abs(), np.nan)
        null_mask = merged[qoq_col].isna()
        merged.loc[null_mask & valid, qoq_col] = computed[null_mask & valid]

    # q_roegrow_qoq：从 fina_indicator q_roe（单季度 ROE）环比
    prev_q_roe_q = "q_roe_prev_q"
    roe_lookup = _build_ym_lookup(merged, "q_roe")
    merged[prev_q_roe_q] = [
        roe_lookup.get(key, np.nan) if (key := _prev_quarter_ym(yr, mo)) is not None else np.nan
        for yr, mo in zip(merged["_year"], merged["_month"])
    ]
    valid_roe_q = np.isfinite(merged["q_roe"]) & np.isfinite(merged[prev_q_roe_q]) & (merged[prev_q_roe_q] != 0)
    roe_qoq = np.where(valid_roe_q, (merged["q_roe"] - merged[prev_q_roe_q]) / merged[prev_q_roe_q].abs(), np.nan)
    null_roe_qoq = merged["q_roegrow_qoq"].isna()
    merged.loc[null_roe_qoq & valid_roe_q, "q_roegrow_qoq"] = roe_qoq[null_roe_qoq & valid_roe_q]

    merged.drop(columns=["_year", "_month"], inplace=True, errors="ignore")


def _build_ym_lookup(df: pd.DataFrame, col: str) -> dict[tuple[int, int], float]:
    """构建 (year, month) → col 最后一个有效值 的索引 dict，O(1) 查找。

    同一 (year, month) 可能有多条记录（不同 ann_date），取最后一条有效值。
    """
    lookup: dict[tuple[int, int], float] = {}
    for yr, mo, val in zip(df["_year"], df["_month"], df[col]):
        if yr is not None and mo is not None and pd.notna(val):
            lookup[(int(yr), int(mo))] = float(val)
    return lookup


def _prev_quarter_ym(year: int | None, month: int | None) -> tuple[int, int] | None:
    """计算上一季度的 (year, month)。"""
    if year is None or month is None:
        return None
    prev_month = month - 3
    prev_year = year
    if prev_month <= 0:
        prev_month += 12
        prev_year -= 1
    return (prev_year, prev_month)


def _subtract_months(d: date, months: int) -> date:
    """将日期减去指定月数，保持日不变（溢出时取月末）。"""
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(d.day, max_day)
    return date(year, month, day)
