"""样本池初始化服务 — 从 DB 读取指数/行业/标签数据，写入 fac_factor_pool。

样本池类型：
  - index: 指数池，标的来自 sdc_index_weight
  - industry: 行业池，标的来自 sdc_sw_industry_member
  - style: 风格池，标的来自 sdc_stock_tag
  - market: 全市场池，标的来自 sdc_security

factor_scope 定义每个样本池评估的因子范围：
  - null: 评估全量活跃因子（默认）
  - {"include": ["ma_5", "rsi_14"]}: 仅评估指定因子
  - {"exclude": ["adv_20"]}: 排除指定因子
  - {"category": ["tech", "momentum"]}: 按因子分类筛选
"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_pool import FacFactorPool
from xqtrader.domain.factor.services.registry import get_factor_definitions

logger = get_logger("factor.pool_init")

# 默认样本池配置 — 评估任务启动时自动同步到 DB
_DEFAULT_POOLS: list[dict[str, Any]] = [
    {
        "pool_id": "all",
        "pool_name": "全A股",
        "pool_type": "market",
        "definition": {"source": "sdc_security", "filter": {"list_status": "L"}},
        "factor_scope": None,
    },
    {
        "pool_id": "idx_50",
        "pool_name": "上证50",
        "pool_type": "index",
        "definition": {"index_code": "000016.SH"},
        "factor_scope": None,
    },
    {
        "pool_id": "idx_300",
        "pool_name": "沪深300",
        "pool_type": "index",
        "definition": {"index_code": "000300.SH"},
        "factor_scope": None,
    },
    {
        "pool_id": "idx_500",
        "pool_name": "中证500",
        "pool_type": "index",
        "definition": {"index_code": "000905.SH"},
        "factor_scope": None,
    },
    {
        "pool_id": "idx_1000",
        "pool_name": "中证1000",
        "pool_type": "index",
        "definition": {"index_code": "000852.SH"},
        "factor_scope": None,
    },
    {
        "pool_id": "idx_kcb50",
        "pool_name": "科创50",
        "pool_type": "index",
        "definition": {"index_code": "000688.SH"},
        "factor_scope": None,
    },
    {
        "pool_id": "idx_cybz",
        "pool_name": "创业板指",
        "pool_type": "index",
        "definition": {"index_code": "399006.SZ"},
        "factor_scope": None,
    },
]


class PoolInitService:
    """样本池初始化服务 — 同步默认样本池配置到 DB。"""

    async def sync_default_pools(self) -> int:
        """将默认样本池配置同步到 fac_factor_pool 表（upsert）。

        Returns:
            同步的记录数
        """
        records: list[FacFactorPool] = []
        for cfg in _DEFAULT_POOLS:
            records.append(FacFactorPool(
                pool_id=cfg["pool_id"],
                pool_name=cfg["pool_name"],
                pool_type=cfg["pool_type"],
                definition=cfg.get("definition"),
                factor_scope=cfg.get("factor_scope"),
                refresh_freq="daily",
                status="active",
            ))

        await FacFactorPool.bulk_create_or_update(
            records,
            on_conflict=["pool_id"],
            update_fields=["pool_name", "pool_type", "definition", "factor_scope", "refresh_freq"],
            batch_size=100,
        )
        logger.info("样本池初始化完成: %d 个样本池已同步", len(records))
        return len(records)

    @staticmethod
    async def resolve_factor_ids(pool: FacFactorPool, all_factor_ids: list[str]) -> list[str]:
        """根据样本池的 factor_scope 配置解析实际评估的因子列表。

        Args:
            pool: 样本池配置
            all_factor_ids: 全量活跃因子 ID 列表

        Returns:
            该样本池实际评估的因子 ID 列表
        """
        scope = pool.factor_scope
        if scope is None:
            return all_factor_ids

        if "include" in scope:
            included = set(scope["include"])
            return [fid for fid in all_factor_ids if fid in included]

        if "exclude" in scope:
            excluded = set(scope["exclude"])
            return [fid for fid in all_factor_ids if fid not in excluded]

        if "category" in scope:
            categories = set(scope["category"])
            definitions = {d.factor_id: d for d in get_factor_definitions()}
            return [
                fid for fid in all_factor_ids
                if fid in definitions and definitions[fid].category in categories
            ]

        return all_factor_ids
