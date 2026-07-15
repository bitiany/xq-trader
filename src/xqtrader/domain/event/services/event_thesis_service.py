"""事件→论点卡触发服务 — 事件命中证伪条件时标记论点卡失效，利好事件更新催化剂。

架构文档 §11.3.3 第三层：事件→论点卡触发 + §11.4 事件→资产配置映射。

触发逻辑：
  1. 持仓股命中利空（减持/违规/业绩预减）→ 查论点卡 invalidation_rules
     - 命中证伪条件 → mark_thesis_stale(reason=事件命中证伪条件)
     - 未命中 → 保持现状
  2. 持仓股命中利好（资产重组/回购/业绩预增）→ 更新论点卡 catalysts 字段
  3. 宏观恐慌极端 → 不直接失效论点卡，标注市场环境恶化
  4. 事件→资产配置映射（§11.4）：基于事件类型给出资产配置维度的偏好提示

invalidation_rules 结构示例：
  {
    "event_triggers": {
      "股东减持": {"condition": "减持比例>5%", "action": "mark_stale"},
      "违规处罚": {"condition": "any", "action": "mark_stale"},
      "业绩预减": {"condition": "降幅>30%", "action": "mark_stale"}
    },
    "falsification_triggers": [...],
    "time_triggers": {"valid_until": "2026-12-31"}
  }
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from framework.commons.logger import get_logger
from xqtrader.domain.agent.services.thesis_service import ThesisService
from xqtrader.domain.event.models import AssetAllocationHint, DetectedEvent, ThesisImpactResult

logger = get_logger("EVENT.THESIS")

# 事件→资产配置映射表（模块级懒加载缓存）
_ALLOCATION_FILE = (
    Path(__file__).resolve().parent.parent / "keywords" / "event_asset_allocation.yaml"
)
_allocation_cache: dict[str, dict[str, Any]] | None = None


def _load_allocation_mapping() -> dict[str, dict[str, Any]]:
    """加载事件→资产配置映射表（模块级缓存）。"""
    global _allocation_cache
    if _allocation_cache is not None:
        return _allocation_cache
    try:
        with _ALLOCATION_FILE.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning("事件→资产配置映射表格式错误: %s", _ALLOCATION_FILE)
            data = {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("事件→资产配置映射表加载失败: %s exc=%s", _ALLOCATION_FILE, exc)
        data = {}
    _allocation_cache = data
    logger.info(
        "事件→资产配置映射表已加载: types=%s",
        list(data.keys()) if isinstance(data, dict) else [],
    )
    return data


class EventThesisService:
    """事件→论点卡触发服务 + 事件→资产配置映射。"""

    def __init__(self) -> None:
        self._thesis_service = ThesisService()

    async def evaluate_impact(
        self,
        symbol: str,
        events: list[DetectedEvent],
        as_of: date | None = None,
    ) -> ThesisImpactResult:
        """评估事件对标的论点卡的影响，并执行相应动作。

        Args:
            symbol: 标的代码
            events: 该标的的事件列表（已过滤到该 symbol）
            as_of: 基准日期（None 表示今天）

        Returns:
            ThesisImpactResult 含建议动作与触发规则
        """
        ref_date = as_of or date.today()
        if not events:
            return ThesisImpactResult(
                symbol=symbol,
                thesis_status="none",
                triggered_rules=[],
                action="none",
                reason="无事件",
            )

        thesis = await self._thesis_service.get_thesis(symbol)
        expired_reason = ""
        if thesis is None:
            thesis_status = "none"
        elif isinstance(thesis, dict) and thesis.get("status") == "expired":
            thesis_status = "expired"
            expired_reason = str(thesis.get("reason", ""))
        else:
            thesis_status = "active"

        if thesis_status != "active":
            return ThesisImpactResult(
                symbol=symbol,
                thesis_status=thesis_status,
                triggered_rules=[],
                action="none",
                reason="无有效论点卡，无需触发" if thesis_status == "none"
                else f"论点卡已过期: {expired_reason}",
            )

        invalidation_rules = thesis.get("invalidation_rules", {}) if thesis else {}
        event_triggers = (
            invalidation_rules.get("event_triggers", {})
            if isinstance(invalidation_rules, dict)
            else {}
        )

        bearish_events = [e for e in events if e.event_category == "利空"]
        bullish_events = [e for e in events if e.event_category == "利好"]

        triggered_rules: list[str] = []
        for event in bearish_events:
            rule = event_triggers.get(event.event_type)
            if rule is None:
                continue
            if isinstance(rule, dict):
                action = rule.get("action", "")
                condition = rule.get("condition", "any")
                if action == "mark_stale":
                    triggered_rules.append(
                        f"{event.event_type}(condition={condition})"
                    )

        if triggered_rules:
            reason = (
                f"事件命中证伪条件: {', '.join(triggered_rules)} "
                f"(as_of={ref_date.isoformat()})"
            )
            affected = await self._thesis_service.mark_stale(symbol, reason=reason)
            logger.info(
                "论点卡已标记 stale: symbol=%s reason=%s affected=%d",
                symbol, reason, affected,
            )
            return ThesisImpactResult(
                symbol=symbol,
                thesis_status="stale",
                triggered_rules=triggered_rules,
                action="mark_thesis_stale",
                reason=reason,
            )

        if bullish_events:
            catalyst_types = [e.event_type for e in bullish_events]
            reason = (
                f"利好事件更新催化剂: {', '.join(catalyst_types)} "
                f"(as_of={ref_date.isoformat()})"
            )
            logger.info(
                "论点卡催化剂更新建议: symbol=%s events=%s",
                symbol, catalyst_types,
            )
            return ThesisImpactResult(
                symbol=symbol,
                thesis_status="active",
                triggered_rules=[],
                action="update_catalysts",
                reason=reason,
            )

        return ThesisImpactResult(
            symbol=symbol,
            thesis_status="active",
            triggered_rules=[],
            action="none",
            reason="事件未命中证伪条件，无需触发",
        )

    def evaluate_asset_allocation(
        self,
        event_types: list[str],
    ) -> list[AssetAllocationHint]:
        """基于事件类型列表，给出资产配置维度的偏好提示。

        架构文档 §11.4 事件→资产配置映射。

        Args:
            event_types: 事件类型列表（如 ["货币宽松", "股东减持", "退市风险"]）

        Returns:
            AssetAllocationHint 列表（每个事件类型一条配置提示）
        """
        mapping = _load_allocation_mapping()
        hints: list[AssetAllocationHint] = []
        for event_type in event_types:
            rule = mapping.get(event_type)
            if not isinstance(rule, dict):
                logger.debug("事件→资产配置映射未命中: %s", event_type)
                continue
            hints.append(
                AssetAllocationHint(
                    event_type=event_type,
                    affected_dimension=str(rule.get("affected_dimension", "")),
                    direction=str(rule.get("direction", "")),
                    suggested_weight_change=str(rule.get("suggested_weight_change", "0")),
                    rationale=str(rule.get("rationale", "")),
                )
            )
        logger.info(
            "事件→资产配置映射完成: input=%s matched=%d",
            event_types, len(hints),
        )
        return hints
