"""因子评估任务 — 计算 IC/ICIR/换手率/因子等级等统计指标。

核心流程：
  1. 读取截面因子值（fac_factor_value）
  2. 截面预处理（MAD去极值 + Z-score标准化 + 行业中性化）
  3. 计算滚动 IC（Spearman 秩相关）
  4. 计算 ICIR / IC 胜率 / 换手率 / 覆盖率
  5. 评定因子等级（A/B/C/D）
  6. 持久化到 fac_factor_stats
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import spearmanr  # type: ignore[import-untyped]

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.factor_compute.preprocessor import FactorPreprocessor
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger(__name__)


class FactorEvaluateTask(BaseTask):
    """因子评估任务 — IC/ICIR/换手率/因子等级。

    评估指标：
      - IC均值（Spearman rank IC）
      - IC标准差
      - ICIR = IC均值 / IC标准差
      - IC胜率（IC>0的比例）
      - 因子换手率
      - 覆盖率
      - 因子等级（A/B/C/D）

    入参：
      - trade_date: 评估日期（为空时取最新交易日）
      - window: IC 滚动窗口（默认252）
      - pool_id: 样本池标识（默认 all）
    """

    task_name = "factor.evaluate_daily"
    description = "因子日频评估（IC/ICIR/等级）"
    time_limit = 1800
    soft_time_limit = 1770

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        trade_date_str: str | None = kwargs.get("trade_date")
        window: int = kwargs.get("window", 252)
        pool_id: str = kwargs.get("pool_id", "all")

        # 1. 确定评估日期
        trade_date = await self._resolve_trade_date(trade_date_str)
        if trade_date is None:
            logger.warning("未找到有效交易日")
            return {"total": 0, "evaluated": 0}

        logger.info("开始因子评估: date=%s window=%d pool=%s", trade_date, window, pool_id)

        # 2. 读取截面因子值（原始值）
        raw_factor_df = await self._load_factor_values(trade_date, pool_id)
        if raw_factor_df is None or raw_factor_df.empty:
            logger.warning("无因子值数据: date=%s", trade_date)
            return {"total": 0, "evaluated": 0}

        factor_ids = [c for c in raw_factor_df.columns]

        # 3. 计算滚动 IC（Spearman 秩相关）— 内部对每个截面日做预处理
        ic_series = await self._compute_rolling_ic(trade_date, factor_ids, window, pool_id)
        logger.info("IC计算完成: factors=%d", len(factor_ids))

        # 5. 计算统计指标并持久化
        # 覆盖率基于原始值，IC 基于预处理后的截面 IC 序列
        evaluated = 0
        for fid in factor_ids:
            stat = self._compute_stats(
                raw_coverage=self._calc_coverage(raw_factor_df[fid]),
                ic_list=ic_series.get(fid),
                factor_id=fid,
                trade_date=trade_date,
                window=window,
                pool_id=pool_id,
            )
            if stat is not None:
                await self._persist_stat(stat)
                evaluated += 1

        logger.info("因子评估完成: date=%s evaluated=%d/%d", trade_date, evaluated, len(factor_ids))
        return {"total": len(factor_ids), "evaluated": evaluated}

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
        """读取当日截面因子值，转为宽表（index=symbol, columns=factor_id）。"""
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
    async def _compute_rolling_ic(
        trade_date: date,
        factor_ids: list[str],
        window: int,
        pool_id: str,
    ) -> dict[str, list[float]]:
        """计算滚动 IC — 截面预处理后 Spearman 秩相关（因子值 vs 次日收益率）。

        对每个截面日，先做 MAD+Z-score 预处理，再计算因子值与次日收益的
        Spearman 秩相关系数，得到 IC 序列。
        """
        # 获取交易日历（多取一些以确保覆盖 window）
        start_date = trade_date - timedelta(days=window * 2)
        trade_dates = await TradeCalendar.get_trade_dates(start=start_date, end=trade_date)
        if not trade_dates:
            return {}

        # 只取最近 window 个交易日
        if len(trade_dates) > window:
            trade_dates = trade_dates[-window:]

        # 构建交易日 → 次交易日映射
        td_to_next: dict[date, date] = {}
        for i in range(len(trade_dates) - 1):
            td_to_next[trade_dates[i]] = trade_dates[i + 1]

        # 批量读取所有因子在窗口内的截面值（一次查询，避免逐因子查询）
        rows = await FacFactorValue.filter(
            factor_id__in=factor_ids,
            pool_id=pool_id,
            trade_date__in=trade_dates,
        )
        if not rows:
            return {}

        factor_all = pd.DataFrame([
            {"trade_date": r.trade_date, "symbol": r.symbol, "factor_id": r.factor_id, "value": r.factor_value}
            for r in rows
        ])

        # 批量读取次日收益率（cs_pct_chg）
        next_dates = [td_to_next[td] for td in trade_dates if td in td_to_next]
        ret_rows = await FacFactorValue.filter(
            factor_id="cs_pct_chg",
            pool_id="all",
            trade_date__in=next_dates,
        )
        if not ret_rows:
            return {}

        ret_all = pd.DataFrame([
            {"trade_date": r.trade_date, "symbol": r.symbol, "return": r.factor_value}
            for r in ret_rows
        ])

        preprocessor = FactorPreprocessor()
        ic_data: dict[str, list[float]] = {}

        for fid in factor_ids:
            fid_data = factor_all[factor_all["factor_id"] == fid]
            if fid_data.empty:
                continue

            factor_pivot = fid_data.pivot_table(index="symbol", columns="trade_date", values="value")
            ret_pivot = ret_all.pivot_table(index="symbol", columns="trade_date", values="return")

            # 逐日计算截面 Spearman IC
            daily_ics: list[float] = []
            for td in trade_dates:
                next_td = td_to_next.get(td)
                if next_td is None:
                    continue
                if td not in factor_pivot.columns or next_td not in ret_pivot.columns:
                    continue

                fvals = factor_pivot[td].dropna()
                rvals = ret_pivot[next_td].dropna()

                # 对齐 symbol
                common = fvals.index.intersection(rvals.index)
                if len(common) < 30:
                    continue

                # 截面预处理：MAD + Z-score
                fv_raw = fvals.loc[common]
                fv_processed = preprocessor.zscore(preprocessor.winsorize_mad(fv_raw))
                rv = np.asarray(rvals.loc[common].values, dtype=float)
                fv = np.asarray(fv_processed.values, dtype=float)

                # 跳过全相同值（Spearman无定义）
                if np.std(fv) == 0 or np.std(rv) == 0:
                    continue

                corr, _ = spearmanr(fv, rv)
                if np.isfinite(corr):
                    daily_ics.append(float(corr))

            if daily_ics:
                ic_data[fid] = daily_ics

        return ic_data

    @staticmethod
    def _calc_coverage(factor_series: pd.Series) -> float:
        """基于原始因子值计算覆盖率。"""
        if len(factor_series) == 0:
            return 0.0
        return len(factor_series.dropna()) / len(factor_series)

    @staticmethod
    def _compute_stats(
        raw_coverage: float,
        ic_list: list[float] | None,
        factor_id: str,
        trade_date: date,
        window: int,
        pool_id: str,
    ) -> FacFactorStats | None:
        """计算单个因子的统计指标。"""

        # IC 统计
        ic_mean = None
        ic_std = None
        icir = None
        ic_win_rate = None

        if ic_list and len(ic_list) >= 10:
            ic_arr = np.array(ic_list)
            ic_mean = float(np.mean(ic_arr))
            ic_std = float(np.std(ic_arr))
            if ic_std > 0:
                icir = ic_mean / ic_std
            ic_win_rate = float(np.mean(ic_arr > 0))

        # 因子等级评定
        factor_grade = "D"
        if icir is not None:
            if icir > 1.0:
                factor_grade = "A"
            elif icir > 0.5:
                factor_grade = "B"
            elif icir > 0.3:
                factor_grade = "C"

        return FacFactorStats(
            factor_id=factor_id,
            pool_id=pool_id,
            calc_date=trade_date,
            window=window,
            ic_mean=ic_mean,
            ic_std=ic_std,
            icir=icir,
            ic_win_rate=ic_win_rate,
            coverage=raw_coverage,
            factor_grade=factor_grade,
        )

    @staticmethod
    async def _persist_stat(stat: FacFactorStats) -> None:
        """持久化因子统计指标。"""
        await FacFactorStats.bulk_create_or_update(
            [stat],  # type: ignore[arg-type]
            on_conflict=["factor_id", "pool_id", "calc_date", "window"],
            update_fields=["ic_mean", "ic_std", "icir", "ic_win_rate", "coverage", "factor_grade"],
        )
