"""样本池初始化服务 — 初始化默认样本池到 fac_factor_pool。

指数样本池从 sdc_index_weight 读取成分股。
行业/风格样本池通过 definition 规则动态计算。
"""

from __future__ import annotations

import logging

from framework.dal.transaction import transactional
from xqtrader.domain.factor.models.factor_pool import FacFactorPool

logger = logging.getLogger(__name__)


class FactorPoolInitializer:
    """样本池初始化器 — 初始化默认样本池到数据库。"""

    # 默认样本池定义
    DEFAULT_POOLS = [
        {
            "pool_id": "all",
            "pool_name": "全A股",
            "pool_type": "index",
            "definition": {"type": "all", "filter": "listed,not_st"},
            "refresh_freq": "daily",
        },
        {
            "pool_id": "idx_50",
            "pool_name": "上证50",
            "pool_type": "index",
            "definition": {"type": "index", "index_code": "000016.SH"},
            "refresh_freq": "quarterly",
        },
        {
            "pool_id": "idx_300",
            "pool_name": "沪深300",
            "pool_type": "index",
            "definition": {"type": "index", "index_code": "000300.SH"},
            "refresh_freq": "quarterly",
        },
        {
            "pool_id": "idx_500",
            "pool_name": "中证500",
            "pool_type": "index",
            "definition": {"type": "index", "index_code": "000905.SH"},
            "refresh_freq": "quarterly",
        },
        {
            "pool_id": "idx_1000",
            "pool_name": "中证1000",
            "pool_type": "index",
            "definition": {"type": "index", "index_code": "000852.SH"},
            "refresh_freq": "quarterly",
        },
        {
            "pool_id": "style_growth",
            "pool_name": "成长股",
            "pool_type": "style",
            "definition": {"type": "style", "tag": "growth"},
            "refresh_freq": "quarterly",
        },
        {
            "pool_id": "style_value",
            "pool_name": "价值股",
            "pool_type": "style",
            "definition": {"type": "style", "tag": "value"},
            "refresh_freq": "quarterly",
        },
        {
            "pool_id": "style_large_cap",
            "pool_name": "大盘股",
            "pool_type": "style",
            "definition": {"type": "style", "tag": "large_cap"},
            "refresh_freq": "quarterly",
        },
    ]

    @staticmethod
    @transactional(bind_key="research")
    async def init_pools() -> dict[str, int]:
        """初始化默认样本池。

        Returns:
            {"inserted": int, "skipped": int}
        """
        inserted = 0
        skipped = 0

        for pool_def in FactorPoolInitializer.DEFAULT_POOLS:
            existing = await FacFactorPool.get_or_none(pool_id=pool_def["pool_id"])
            if existing is None:
                await FacFactorPool.create(
                    pool_id=pool_def["pool_id"],
                    pool_name=pool_def["pool_name"],
                    pool_type=pool_def["pool_type"],
                    definition=pool_def["definition"],
                    refresh_freq=pool_def["refresh_freq"],
                    status="active",
                )
                inserted += 1
                logger.info("初始化样本池: %s (%s)", pool_def["pool_id"], pool_def["pool_name"])
            else:
                skipped += 1

        logger.info("样本池初始化完成: inserted=%d, skipped=%d", inserted, skipped)
        return {"inserted": inserted, "skipped": skipped}
