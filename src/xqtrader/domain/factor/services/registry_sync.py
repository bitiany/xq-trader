"""因子注册表同步服务 — 代码声明 upsert 到 fac_factor_registry。

启动时调用 FactorRegistrySyncer.sync_all()，将 FactorDefinition 的静态属性同步到数据库。
运行时状态（factor_grade, status）由评估管线动态更新，同步时保留数据库值。
"""

from __future__ import annotations

import logging
from typing import Any

from framework.dal.transaction import transactional
from xqtrader.domain.factor.definitions.base import get_all_definitions
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry

logger = logging.getLogger(__name__)

# 同步时保留的运行时字段（不从代码覆盖，保留数据库值）
_RUNTIME_FIELDS = frozenset({"factor_grade", "status"})


class FactorRegistrySyncer:
    """因子注册表同步器 — 将代码声明同步到数据库。"""

    @staticmethod
    @transactional(bind_key="research")
    async def sync_all() -> dict[str, int]:
        """将所有 FactorDefinition 同步到 fac_factor_registry。

        Returns:
            {"inserted": int, "updated": int, "skipped": int}
        """
        definitions = get_all_definitions()
        inserted = 0
        updated = 0
        skipped = 0

        for defn in definitions:
            data = defn.to_registry_dict()
            existing = await FacFactorRegistry.get_or_none(factor_id=defn.factor_id)

            if existing is None:
                data["status"] = "testing"
                data["factor_grade"] = None
                await FacFactorRegistry.create(**data)
                inserted += 1
                logger.info("注册新因子: %s (%s)", defn.factor_id, defn.display_name)
            else:
                update_data = {
                    k: v for k, v in data.items() if k not in _RUNTIME_FIELDS
                }
                changed = _detect_changes(existing, update_data)
                if changed:
                    await existing.update(update_data)
                    updated += 1
                    logger.info(
                        "更新因子: %s, 变更字段: %s", defn.factor_id, changed
                    )
                else:
                    skipped += 1

        logger.info(
            "注册表同步完成: inserted=%d, updated=%d, skipped=%d",
            inserted, updated, skipped,
        )
        return {"inserted": inserted, "updated": updated, "skipped": skipped}


def _detect_changes(
    existing: FacFactorRegistry, update_data: dict[str, Any]
) -> list[str]:
    """检测需要更新的字段。"""
    changed = []
    for key, new_value in update_data.items():
        old_value = getattr(existing, key, None)
        if old_value != new_value:
            changed.append(key)
    return changed
