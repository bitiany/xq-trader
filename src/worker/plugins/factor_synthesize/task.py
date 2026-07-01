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
from sqlalchemy import text

from framework.commons.concurrent import ConcurrentRunner
from framework.commons.logger import get_logger
from framework.dal.enginee import engines_manager
from framework.scheduler.base_task import BaseTask
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.models.factor_pool import FacFactorPool
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services.alpha_synthesizer import (
    GROUP_FACTOR_ID_MAP,
    AlphaSynthesizer,
    build_group_factor_ids,
)
from xqtrader.domain.factor.services.pool_init import PoolInitService
from xqtrader.domain.factor.services.registry import auto_discover_factors, register_factor_variants

logger = get_logger("factor.synthesize")

_RETENTION_YEARS = 5
_DEFAULT_WINDOW = 252
_PERSIST_BATCH_SIZE = 5000
_SYNTH_CONCURRENCY = 4  # 合成持久化消费者数量
_COMPOSITE_FACTOR_IDS = [
    "composite_value", "composite_momentum", "composite_volatility",
    "composite_liquidity", "composite_technical", "composite_fund_flow",
    "composite_alpha",
    # D4 交互因子（合成产物，不作为输入因子加载）
    "mom_vol_cross", "adx_rsi_cross", "vol_ratio_mom_cross",
    "rsi_bbands_cross", "macd_adx_cross", "vol_mom_accel_cross",
]


class AlphaSynthesizeTask(BaseTask):
    """周频 Alpha 合成任务。"""

    task_name = "factor.synthesize_weekly"
    description = "按样本池截面标准化后合成Alpha因子"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pool_ids = parse_list_param(kwargs.get("pool_ids"))
        factor_ids = parse_list_param(kwargs.get("factor_ids"))
        start_date = str(kwargs.get("start_date", ""))
        end_date = str(kwargs.get("end_date", ""))
        window = int(kwargs.get("window", _DEFAULT_WINDOW))

        # 同步默认样本池配置（与评估任务共用 status=active 的 all + idx_300）
        await PoolInitService().sync_default_pools()

        auto_discover_factors()
        register_factor_variants()

        # 从 DB 加载样本池
        if pool_ids:
            pools = await FacFactorPool.filter(
                pool_id__in=pool_ids,
                status="active",
            )
        else:
            pools = await FacFactorPool.filter(status="active")
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

        # 持久化前预解压目标时间范围的已压缩 chunks
        # 合成任务写入 5 年数据，upsert 命中已压缩 chunk 会触发同步解压导致写入变慢
        await self._decompress_factor_chunks(start_dt, end_dt)

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
                # 从注册表加载合成因子配置（血缘 + 合成方式）
                composite_configs = await self._load_composite_configs()

                results = await synthesizer.synthesize_pool(
                    pool_id=pool.pool_id,
                    factor_ids=pool_factor_ids,
                    start_date=start_dt,
                    end_date=end_dt,
                    window=window,
                    composite_configs=composite_configs,
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

            # 更新合成因子的注册信息（血缘 + 合成标记）
            await self._update_composite_registry(pool_factor_ids, composite_configs)

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
    async def _decompress_factor_chunks(start_date: date, end_date: date) -> int:
        """预解压 fac_factor_value 表中目标时间范围的已压缩 chunks。

        合成任务写入 5 年数据时，upsert 命中已压缩 chunk 会触发同步解压，
        导致写入性能急剧下降。持久化前预解压可避免此问题；
        解压后的 chunks 由晚间 23:00 的压缩任务按 age 策略重新压缩。

        Returns:
            解压的 chunk 数量
        """
        engine = engines_manager.get_engine("stock")
        query_sql = text("""
            SELECT chunk_schema, chunk_name
            FROM timescaledb_information.chunks
            WHERE hypertable_name = 'fac_factor_value'
              AND is_compressed = true
              AND range_end >= :start_date
              AND range_start <= :end_date
            ORDER BY range_start
        """)

        async with engine.begin() as conn:
            result = await conn.execute(
                query_sql, {"start_date": start_date, "end_date": end_date},
            )
            chunks = result.fetchall()

        if not chunks:
            logger.info(
                "[alpha.synth] 无需预解压的 chunks (range=%s~%s)",
                start_date, end_date,
            )
            return 0

        logger.info(
            "[alpha.synth] 预解压 %d 个已压缩 chunks (range=%s~%s)",
            len(chunks), start_date, end_date,
        )

        count = 0
        for chunk_schema, chunk_name in chunks:
            qualified = f'"{chunk_schema}"."{chunk_name}"'
            try:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(f"SELECT decompress_chunk('{qualified}'::regclass)"),
                    )
                count += 1
                logger.info("[alpha.synth] 解压 chunk: %s", qualified)
            except Exception as e:
                logger.warning(
                    "[alpha.synth] 解压 chunk 失败 %s: %s", qualified, e, exc_info=True,
                )

        logger.info("[alpha.synth] 预解压完成: %d/%d 成功", count, len(chunks))
        return count

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
            status="active",
        )
        if registry:
            factor_ids = [f.factor_id for f in registry]
            logger.info(
                "[alpha.synth] pool=%s 从 registry 读取 A/B 级因子: %d",
                pool_id, len(factor_ids),
            )
            return factor_ids

        # 最终回退：使用注册表中非 return/composite/chanlun 类的活跃因子，按 ICIR 降序取 top N
        registry = await FacFactorRegistry.filter(
            status="active",
        )
        candidate_ids = [
            f.factor_id for f in registry
            if f.category not in ("return", "chanlun", "composite_group", "composite_cross", "interaction")
            and f.factor_id not in _COMPOSITE_FACTOR_IDS
        ]

        # 尝试从 stats 表获取 ICIR 排序，取 top 30
        stats = await FacFactorStats.filter(
            pool_id=pool_id,
            factor_id__in=candidate_ids,
        )
        if stats:
            icir_map = {s.factor_id: (s.icir or 0) for s in stats}
            candidate_ids.sort(key=lambda fid: abs(icir_map.get(fid, 0)), reverse=True)
            candidate_ids = candidate_ids[:30]

        logger.info(
            "[alpha.synth] pool=%s 无等级数据，使用 top %d 活跃因子",
            pool_id, len(candidate_ids),
        )
        return candidate_ids

    async def _persist_results(
        self,
        pool_id: str,
        results: dict[str, Any],
    ) -> int:
        """将合成结果持久化到 fac_factor_value（分因子并发 upsert）。

        各合成因子的 DataFrame 相互独立，通过 ConcurrentRunner 并发持久化，
        单因子内仍按 _PERSIST_BATCH_SIZE 分片写入以控制内存峰值。
        """
        # 筛选非空且有效数值的合成因子
        items: list[tuple[str, Any]] = [
            (method, df) for method, df in results.items() if not df.empty
        ]
        if not items:
            return 0

        runner = ConcurrentRunner[tuple[str, Any], int](
            concurrency=_SYNTH_CONCURRENCY,
            log_name=f"factor.synth.persist[{pool_id}]",
        )
        result = await runner.run_items(
            items=items,
            processor=lambda item: self._persist_single_factor(pool_id, item[0], item[1]),
        )
        return sum(result.succeeded)

    async def _persist_single_factor(
        self, pool_id: str, method: str, df: Any,
    ) -> int:
        """持久化单个合成因子的 DataFrame（分片 upsert）。"""
        col = df.columns[0]
        reset_df = df.reset_index()
        vals = reset_df[col].to_numpy(dtype=float)
        valid_mask = np.isfinite(vals)
        if not valid_mask.any():
            return 0

        reset_df = reset_df.loc[valid_mask]
        vals = vals[valid_mask]
        n = len(reset_df)
        total = 0

        for start in range(0, n, _PERSIST_BATCH_SIZE):
            end = min(start + _PERSIST_BATCH_SIZE, n)
            chunk = reset_df.iloc[start:end]
            chunk_vals = vals[start:end]
            rows: list[FacFactorValue] = []
            for idx in range(len(chunk)):
                row = chunk.iloc[idx]
                td = row["trade_date"]
                if hasattr(td, "date"):
                    td = td.date()  # type: ignore[union-attr]
                rows.append(FacFactorValue(
                    symbol=str(row["symbol"]),
                    trade_date=td,
                    factor_id=method,
                    pool_id=pool_id,
                    factor_value=float(chunk_vals[idx]),
                ))

            total += await FacFactorValue.bulk_create_or_update(
                rows,
                on_conflict=["symbol", "trade_date", "factor_id", "pool_id"],
                update_fields=["factor_value"],
            )
            if end == n or end % (_PERSIST_BATCH_SIZE * 10) == 0:
                logger.info(
                    "[alpha.synth] pool=%s factor=%s persist progress=%d/%d",
                    pool_id, method, end, n,
                )

        return total

    @staticmethod
    async def _load_composite_configs() -> dict[str, dict]:
        """从注册表加载合成因子配置（血缘 + 合成方式）。"""
        composites = await FacFactorRegistry.filter(
            is_composite=1,
        )
        configs: dict[str, dict] = {}
        for c in composites:
            # 合成因子 = 组内等权(composite_group) + 跨组ICIR(composite_cross) + 交互(interaction)
            # 不能用 factor_id 前缀过滤，否则 6 个 interaction 因子会被跳过
            if c.category not in ("composite_group", "composite_cross", "interaction"):
                continue
            configs[c.factor_id] = {
                "composite_factor_ids": c.composite_factor_ids or "",
                "composite_method": c.composite_method or "equal_weight",
            }
        logger.info("[alpha.synth] 加载合成配置: %d 个合成因子", len(configs))
        return configs

    @staticmethod
    async def _update_composite_registry(
        input_factor_ids: list[str],
        composite_configs: dict[str, dict],
    ) -> None:
        """合成完成后更新注册表：设置 is_composite=1，记录 composite_factor_ids 血缘。

        从 composite_configs 中提取实际合成时的分组关系，确保注册表血缘与合成逻辑一致。
        """
        if not composite_configs:
            group_ids = await build_group_factor_ids()
            composite_configs = {}
            for group_name, fids in group_ids.items():
                composite_fid = GROUP_FACTOR_ID_MAP.get(group_name, f"composite_{group_name}")
                actual = sorted(fid for fid in fids if fid in input_factor_ids)
                if actual:
                    composite_configs[composite_fid] = {
                        "composite_factor_ids": ",".join(actual),
                        "composite_method": "equal_weight",
                    }

        # 从 composite_configs 提取每个合成因子实际使用的输入因子
        for composite_fid, config in composite_configs.items():
            if composite_fid == "composite_alpha":
                continue  # 跨组合成因子单独处理
            child_ids_str = config.get("composite_factor_ids", "")
            if not child_ids_str:
                continue
            child_ids = [fid.strip() for fid in child_ids_str.split(",") if fid.strip()]
            # 只记录本次实际参与合成的因子
            actual_child_ids = sorted(fid for fid in child_ids if fid in input_factor_ids)
            if not actual_child_ids:
                continue
            await FacFactorRegistry.update_by(
                {
                    "is_composite": 1,
                    "composite_factor_ids": ",".join(actual_child_ids),
                    "composite_method": config.get("composite_method", "equal_weight"),
                },
                factor_id=composite_fid,
            )

        # 更新跨组合成因子 composite_alpha（血缘为所有组内合成因子）
        group_composite_fids = [
            fid for fid in composite_configs
            if fid != "composite_alpha" and fid.startswith("composite_")
        ]
        if group_composite_fids:
            await FacFactorRegistry.update_by(
                {
                    "is_composite": 1,
                    "composite_factor_ids": ",".join(sorted(group_composite_fids)),
                    "composite_method": "icir_weight",
                },
                factor_id="composite_alpha",
            )
