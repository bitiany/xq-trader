"""因子合成任务 — 基于 Barra/AQR 框架的复合因子合成。

核心流程：
  1. 读取单因子值（fac_factor_value）— 原始值
  2. 截面预处理（MAD 去极值 + Z-score 标准化）
  3. 读取因子统计指标（fac_factor_stats），获取 IC 权重
  4. IC 加权合成 Barra/AQR 维度复合因子
  5. 计算交互因子（Z-score 后的因子乘积）
  6. 持久化到 fac_factor_value（pool_id=alpha）
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.factor_compute.preprocessor import FactorPreprocessor
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger(__name__)


class FactorComposeTask(BaseTask):
    """因子合成任务 — 截面预处理 + IC 加权合成复合 Alpha 因子。

    合成维度：
      - Barra CNE6 风格因子：Size/Momentum/Reversal/Volatility/Liquidity
      - AQR 因子溢价：Momentum/Quality/LowVol/Value

    入参：
      - trade_date: 合成日期（为空时取最新交易日）
      - pool_id: 样本池标识（默认 all）
    """

    task_name = "factor.compose_daily"
    description = "因子日频合成（截面预处理 + IC加权）"
    time_limit = 1800
    soft_time_limit = 1770

    # Barra CNE6 风格因子映射
    BARRA_STYLE_FACTORS: dict[str, list[str]] = {
        "alpha_barra_size": ["cs_log_mv", "nl_size"],
        "alpha_barra_momentum": ["barra_momentum", "barra_strev"],
        "alpha_barra_volatility": ["hist_vol_20", "hist_vol_60", "dastd", "cmra"],
        "alpha_barra_liquidity": ["adv_20", "stom", "stoq", "turnover_f"],
        "alpha_barra_value": ["ep_ttm", "bp", "sp_ttm"],
    }

    # AQR 因子溢价映射
    AQR_PREMIUM_FACTORS: dict[str, list[str]] = {
        "alpha_aqr_momentum": ["barra_momentum", "mom_60d", "roc_10"],
        "alpha_aqr_quality": ["roe", "netprofit_margin", "ocf_to_profit"],
        "alpha_aqr_lowvol": ["hist_vol_20", "downside_vol", "atr_ratio"],
        "alpha_aqr_value": ["ep_ttm", "bp", "sp_ttm"],
    }

    # D4 交互因子映射: alpha_id → (factor_a, factor_b)
    INTERACTION_FACTORS: dict[str, tuple[str, str]] = {
        "mom_vol_cross": ("mom_20d", "atr_ratio"),
        "adx_rsi_cross": ("adx_14", "rsi_14"),
        "vol_ratio_mom_cross": ("cs_volume_ratio", "mom_20d"),
        "rsi_bbands_cross": ("rsi_14", "boll_width"),
        "macd_adx_cross": ("macd_hist", "adx_14"),
        "vol_mom_accel_cross": ("hist_vol_20", "mom_20d"),
    }

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        trade_date_str: str | None = kwargs.get("trade_date")
        pool_id: str = kwargs.get("pool_id", "all")

        # 1. 确定合成日期
        trade_date = await self._resolve_trade_date(trade_date_str)
        if trade_date is None:
            logger.warning("未找到有效交易日")
            return {"total": 0, "composed": 0}

        logger.info("开始因子合成: date=%s pool=%s", trade_date, pool_id)

        # 2. 读取当日截面因子值（原始值）
        factor_df = await self._load_factor_values(trade_date, pool_id)
        if factor_df is None or factor_df.empty:
            logger.warning("无因子值数据: date=%s", trade_date)
            return {"total": 0, "composed": 0}

        logger.info("截面因子值: stocks=%d factors=%d", len(factor_df), len(factor_df.columns))

        # 3. 截面预处理（MAD + Z-score + 行业中性化）
        preprocessor = FactorPreprocessor()
        factor_df = preprocessor.preprocess(factor_df, industry_map=None, neutralize=False)
        logger.info("截面预处理完成: MAD + Z-score")

        # 4. 读取 IC 权重
        ic_weights = await self._load_ic_weights(trade_date)

        # 5. 合成复合因子
        composed_values: dict[str, dict[str, float]] = {}
        all_compose_maps = {**self.BARRA_STYLE_FACTORS, **self.AQR_PREMIUM_FACTORS}

        for alpha_id, sub_factors in all_compose_maps.items():
            values = self._compose_factor(factor_df, sub_factors, ic_weights, alpha_id)
            if values is not None:
                composed_values[alpha_id] = values

        # 6. 计算交互因子（截面 Z-score 后的乘积）
        for alpha_id, (fa, fb) in self.INTERACTION_FACTORS.items():
            values = self._compose_interaction(factor_df, fa, fb, alpha_id)
            if values is not None:
                composed_values[alpha_id] = values

        if not composed_values:
            logger.warning("无合成因子产出")
            return {"total": len(factor_df), "composed": 0}

        # 7. 持久化
        persisted = await self._persist_composed(trade_date, composed_values)

        logger.info(
            "因子合成完成: date=%s alpha_count=%d persisted=%d",
            trade_date, len(composed_values), persisted,
        )
        return {"total": len(factor_df), "composed": len(composed_values), "persisted": persisted}

    @staticmethod
    async def _resolve_trade_date(trade_date_str: str | None) -> date | None:
        """解析交易日期。"""
        if trade_date_str:
            try:
                return date.fromisoformat(trade_date_str)
            except ValueError:
                logger.warning("无效的交易日期格式: %s", trade_date_str)
                return None

        tz = ZoneInfo("Asia/Shanghai")
        now = datetime.now(tz)
        ref_date = now.date()
        if now.hour < 15:
            ref_date = ref_date - timedelta(days=1)
        return await TradeCalendar.get_latest_trade_date(
            exchange="SSE", on_or_before=ref_date,
        )

    @staticmethod
    async def _load_factor_values(trade_date: date, pool_id: str) -> pd.DataFrame | None:
        """读取当日截面因子值，转为宽表（index=stock_code, columns=factor_id）。"""
        rows = await FacFactorValue.filter(
            trade_date=trade_date,
            pool_id=pool_id,
        )
        if not rows:
            return None
        data = [{"symbol": r.symbol, "factor_id": r.factor_id, "factor_value": r.factor_value} for r in rows]
        df = pd.DataFrame(data)
        pivot = df.pivot_table(index="symbol", columns="factor_id", values="factor_value", aggfunc="first")
        return pivot

    @staticmethod
    async def _load_ic_weights(trade_date: date) -> dict[str, float]:
        """读取最近一期因子 IC 权重（按 factor_id 分组取最新 ICIR）。"""
        rows = await FacFactorStats.filter(
            calc_date__lte=trade_date,
            pool_id="all",
            icir__not_isnull=True,
            order_by=FacFactorStats.calc_date.desc(),
        )
        if not rows:
            return {}
        latest_stats: dict[str, float] = {}
        for r in rows:
            if r.factor_id not in latest_stats and r.icir is not None:
                latest_stats[r.factor_id] = abs(r.icir)
        return latest_stats

    @staticmethod
    def _compose_factor(
        factor_df: pd.DataFrame,
        sub_factors: list[str],
        ic_weights: dict[str, float],
        alpha_id: str,
    ) -> dict[str, float] | None:
        """IC 加权合成单个复合因子。"""
        available = [f for f in sub_factors if f in factor_df.columns]
        if not available:
            logger.debug("合成因子 %s: 无可用子因子", alpha_id)
            return None

        # IC 权重（无 IC 数据时等权）
        weights: dict[str, float] = {}
        total_w = 0.0
        for f in available:
            w = ic_weights.get(f, 1.0)
            weights[f] = w
            total_w += w

        if total_w <= 0:
            return None

        # 归一化权重
        for f in weights:
            weights[f] /= total_w

        # 加权合成
        composed = pd.Series(0.0, index=factor_df.index)
        valid_count = 0
        for f in available:
            col = factor_df[f].fillna(0)
            composed += col * weights[f]
            valid_count += 1

        if valid_count == 0:
            return None

        logger.debug(
            "合成因子 %s: sub_factors=%s weights=%s",
            alpha_id, available, {k: round(v, 4) for k, v in weights.items()},
        )
        return {str(k): v for k, v in composed.to_dict().items()}

    @staticmethod
    def _compose_interaction(
        factor_df: pd.DataFrame,
        factor_a: str,
        factor_b: str,
        alpha_id: str,
    ) -> dict[str, float] | None:
        """交互因子合成 — 两个因子截面 Z-score 的乘积。

        交互因子 = Z(factor_a) × Z(factor_b)，
        其中 Z() 已在截面预处理阶段完成。
        """
        if factor_a not in factor_df.columns or factor_b not in factor_df.columns:
            logger.debug("交互因子 %s: 缺少依赖 %s/%s", alpha_id, factor_a, factor_b)
            return None

        a_vals = factor_df[factor_a].fillna(0)
        b_vals = factor_df[factor_b].fillna(0)
        interaction = a_vals * b_vals

        logger.debug("交互因子 %s: %s × %s", alpha_id, factor_a, factor_b)
        return {str(k): v for k, v in interaction.to_dict().items()}

    @staticmethod
    async def _persist_composed(
        trade_date: date,
        composed_values: dict[str, dict[str, float]],
    ) -> int:
        """持久化合成因子值。"""
        instances: list[FacFactorValue] = []
        for alpha_id, symbol_values in composed_values.items():
            for symbol, value in symbol_values.items():
                if np.isnan(value) or np.isinf(value):
                    continue
                instances.append(FacFactorValue(
                    symbol=symbol,
                    trade_date=trade_date,
                    factor_id=alpha_id,
                    pool_id="alpha",
                    factor_value=value,
                ))

        if not instances:
            return 0

        count = await FacFactorValue.bulk_create_or_update(
            instances,  # type: ignore[arg-type]
            on_conflict=["symbol", "trade_date", "factor_id", "pool_id"],
            update_fields=["factor_value"],
            batch_size=500,
        )
        return count
