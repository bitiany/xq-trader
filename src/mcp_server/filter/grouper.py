"""分组器 — 按全局 deny + group include/exclude 划分 operation。"""

from __future__ import annotations

from dataclasses import dataclass

from framework.commons.logger import get_logger
from mcp_server.config import GroupSection, RuleEntry
from mcp_server.filter.rule import MatchRule, build_rules
from mcp_server.openapi.operation import Operation

logger = get_logger("MCP_GROUPER")


@dataclass
class GroupBundle:
    """单分组在过滤后的产出。"""

    name: str
    section: GroupSection
    operations: list[Operation]


class OperationGrouper:
    """按配置完成 deny -> include -> exclude 三级过滤。"""

    def __init__(
        self,
        deny: list[RuleEntry],
        groups: dict[str, GroupSection],
    ) -> None:
        self._deny_rules = build_rules(deny)
        self._groups = groups

    def group(self, operations: list[Operation]) -> list[GroupBundle]:
        candidates = [op for op in operations if not self._matches_any(op, self._deny_rules)]
        bundles: list[GroupBundle] = []
        for name, section in self._groups.items():
            include_rules = build_rules(section.include)
            exclude_rules = build_rules(section.exclude)
            picked = [
                op
                for op in candidates
                if self._matches_any(op, include_rules)
                and not self._matches_any(op, exclude_rules)
            ]
            if not picked:
                logger.warning(
                    "Group %s matched 0 operations; skipping",
                    name,
                )
                continue
            bundles.append(GroupBundle(name=name, section=section, operations=picked))
        return bundles

    @staticmethod
    def _matches_any(op: Operation, rules: list[MatchRule]) -> bool:
        return any(r.matches(op) for r in rules)
