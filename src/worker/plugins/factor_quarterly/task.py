"""季度财务因子计算任务 — 计算B2-B5因子并写入fac_financial_factor_value。

管线流程（逐标的串行执行）：
  加载财务指标原始数据 → 逐因子计算 → 持久化到 fac_financial_factor_value

与日频因子计算的核心区别：
  - 数据粒度为季度（非日频），值仅在财报发布时变化
  - 存储到 fac_financial_factor_value（非 fac_factor_value）
  - 使用 PIT（Point-in-Time）机制，以 ann_date 为关键字段
  - 不做前向填充，保留原始季度记录
"""

from __future__ import annotations

from typing import Any

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
from xqtrader.domain.security.models import Security

logger = get_logger("factor.compute_quarterly")

_COMPUTE_MODE_INCREMENTAL = "incremental"
_COMPUTE_MODE_FULL = "full"

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
        """加载财务指标原始数据（不做前向填充）。"""
        records = await FinancialIndicator.filter(
            symbol=symbol,
            update_flag="1",
            order_by=[FinancialIndicator.end_date.asc(), FinancialIndicator.ann_date.asc()],
        )
        if not records:
            return None

        # 转换为 DataFrame
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
                # B3 成长
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
                # 额外依赖
                "ebitda": rec.ebitda,
            }
            data.append(row)

        df = pd.DataFrame(data)

        # 过滤 ann_date 为空的记录
        df = df.dropna(subset=["ann_date"])
        if df.empty:
            return None

        # 转换数值列
        numeric_cols = [c for c in df.columns if c not in ("symbol", "ann_date", "end_date")]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

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
