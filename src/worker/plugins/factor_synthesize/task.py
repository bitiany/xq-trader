"""周频 Alpha 合成任务 — 按样本池截面标准化后合成 Alpha 因子。

合成流程（参考 FactorEvaluateTask 的逐池循环模式）：
  1. 从 fac_factor_pool 读取样本池配置
  2. 从 fac_factor_stats 读取 A/B 级因子（按样本池维度）
  3. 逐样本池：加载截面面板 → 计算 IC/ICIR 权重 → 加权合成 → 持久化
  4. 合成结果写入 fac_factor_value，pool_id 设为对应样本池标识
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.models.factor_pool import FacFactorPool
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services.alpha_synthesizer import AlphaSynthesizer

logger = get_logger("factor.synthesize")

_RETENTION_YEARS = 5
_DEFAULT_WINDOW = 252
_DEFAULT_POOL_IDS = ["idx_300", "idx_1000"]
_ALPHA_FACTOR_IDS = [
    "alpha_value", "alpha_momentum", "alpha_volatility",
    "alpha_liquidity", "alpha_technical", "alpha_fund_flow",
    "alpha",
]


class AlphaSynthesizeTask(BaseTask):
    """周频 Alpha 合成任务。"""

    task_name = "factor.synthesize_weekly"
    description = "按样本池截面标准化后合成Alpha因子"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pool_ids = parse_list_param(kwargs.get("pool_ids")) or _DEFAULT_POOL_IDS
        factor_ids = parse_list_param(kwargs.get("factor_ids"))
        start_date = str(kwargs.get("start_date", ""))
        end_date = str(kwargs.get("end_date", ""))
        window = int(kwargs.get("window", _DEFAULT_WINDOW))

        # 从 DB 加载样本池
        pools = await FacFactorPool.filter(
            pool_id__in=pool_ids,
            status="active",
        )
        if not pools:
            return {"status": "FAILED", "message": "No active pools found"}

        # 计算日期范围
        if not end_date:
            end_date = date.today().strftime("%Y-%m-%d")
        if not start_date:
            start = date.today() - timedelta(days=_RETENTION_YEARS * 365)
            start_date = start.strftime("%Y-%m-%d")

        start_dt = date.fromisoformat(start_date)
        end_dt = date.fromisoformat(end_date)

        # 初始化合成服务
        synthesizer = AlphaSynthesizer()

        total_upserted = 0
        synthesized_pools: list[str] = []

        for pool_idx, pool in enumerate(pools, 1):
            # 解析该样本池的输入因子
            pool_factor_ids = factor_ids or await self._resolve_pool_factors(pool.pool_id)
            if not pool_factor_ids:
                logger.warning(
                    "[alpha.synth] pool=%s 无可用因子，跳过", pool.pool_id,
                )
                continue

            logger.info(
                "[alpha.synth] pool progress=%d/%d pool=%s factors=%d",
                pool_idx, len(pools), pool.pool_id, len(pool_factor_ids),
            )

            try:
                results = await synthesizer.synthesize_pool(
                    pool_id=pool.pool_id,
                    factor_ids=pool_factor_ids,
                    start_date=start_dt,
                    end_date=end_dt,
                    window=window,
                )
            except Exception as e:
                logger.error(
                    "[alpha.synth] pool=%s 合成失败: %s", pool.pool_id, e, exc_info=True,
                )
                continue

            if not results:
                continue

            # 持久化合成结果
            count = await self._persist_results(pool.pool_id, results)
            total_upserted += count
            synthesized_pools.append(pool.pool_id)

            logger.info(
                "[alpha.synth] pool=%s 完成: upserted=%d methods=%s",
                pool.pool_id, count, list(results.keys()),
            )

        logger.info(
            "[alpha.synth] 全部完成: pools=%s total_upserted=%d",
            synthesized_pools, total_upserted,
        )

        return {
            "status": "SUCCESS",
            "total_upserted": total_upserted,
            "pools": synthesized_pools,
        }

    @staticmethod
    async def _resolve_pool_factors(pool_id: str) -> list[str]:
        """解析样本池内 A/B 级因子列表。

        优先从 fac_factor_stats 读取该样本池的因子等级，
        若无评估数据则回退到注册表中全局 A/B 级因子。
        """
        # 从 stats 表读取该池的 A/B 级因子
        stats = await FacFactorStats.filter(
            pool_id=pool_id,
            factor_grade__in=["A", "B"],
        )
        if stats:
            factor_ids = list({s.factor_id for s in stats})
            logger.info(
                "[alpha.synth] pool=%s 从 stats 读取 A/B 级因子: %d",
                pool_id, len(factor_ids),
            )
            return factor_ids

        # 回退：从注册表读取全局 A/B 级因子
        registry = await FacFactorRegistry.filter(
            factor_grade__in=["A", "B"],
            status__in=["active", "testing", "draft"],
        )
        if registry:
            factor_ids = [f.factor_id for f in registry]
            logger.info(
                "[alpha.synth] pool=%s 从 registry 读取 A/B 级因子: %d",
                pool_id, len(factor_ids),
            )
            return factor_ids

        # 最终回退：使用所有已注册因子（排除 return 类、alpha_group 类和 alpha_composite 类）
        registry = await FacFactorRegistry.filter(
            status__in=["active", "testing", "draft"],
        )
        factor_ids = [
            f.factor_id for f in registry
            if f.category not in ("return", "alpha_group", "alpha_composite")
            and f.factor_id not in _ALPHA_FACTOR_IDS
        ]
        logger.info(
            "[alpha.synth] pool=%s 无等级数据，使用全部活跃因子: %d",
            pool_id, len(factor_ids),
        )
        return factor_ids

    @staticmethod
    async def _persist_results(
        pool_id: str,
        results: dict[str, Any],
    ) -> int:
        """将合成结果持久化到 fac_factor_value。"""
        rows: list[FacFactorValue] = []

        for method, df in results.items():
            if df.empty:
                continue

            col = df.columns[0]
            reset_df = df.reset_index()

            # 向量化过滤 NaN/Inf
            vals = reset_df[col].values
            valid_mask = np.isfinite(vals)

            for idx in np.where(valid_mask)[0]:
                td = reset_df.iloc[idx]["trade_date"]
                if hasattr(td, "date"):
                    td = td.date()  # type: ignore[union-attr]

                rows.append(FacFactorValue(
                    symbol=str(reset_df.iloc[idx]["symbol"]),
                    trade_date=td,
                    factor_id=method,
                    pool_id=pool_id,
                    factor_value=float(vals[idx]),
                ))

        if not rows:
            return 0

        # 批量 upsert（复合主键冲突时更新 factor_value）
        await FacFactorValue.bulk_create_or_update(
            rows,
            on_conflict=["symbol", "trade_date", "factor_id", "pool_id"],
            update_fields=["factor_value"],
        )
        return len(rows)
