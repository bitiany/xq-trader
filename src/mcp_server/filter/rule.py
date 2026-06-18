"""匹配规则 — 策略模式 + 注册表，禁止 if/elif 长串。"""

from __future__ import annotations

import fnmatch
from abc import ABC, abstractmethod
from collections.abc import Callable

from mcp_server.config import RuleEntry
from mcp_server.openapi.operation import Operation


class MatchRule(ABC):
    """单条匹配规则；命中返回 True。"""

    @abstractmethod
    def matches(self, op: Operation) -> bool:
        ...


class OperationIdRule(MatchRule):
    def __init__(self, value: str) -> None:
        self._value = value

    def matches(self, op: Operation) -> bool:
        return op.operation_id == self._value or op.fallback_id == self._value


class TagRule(MatchRule):
    def __init__(self, value: str) -> None:
        self._value = value

    def matches(self, op: Operation) -> bool:
        return self._value in op.tags


class PathGlobRule(MatchRule):
    def __init__(self, value: str) -> None:
        self._value = value

    def matches(self, op: Operation) -> bool:
        return fnmatch.fnmatchcase(op.path, self._value)


class MethodRule(MatchRule):
    def __init__(self, value: str) -> None:
        self._value = value.upper()

    def matches(self, op: Operation) -> bool:
        return op.method.upper() == self._value


_RULE_BUILDERS: dict[str, Callable[[str], MatchRule]] = {
    "operation_id": OperationIdRule,
    "tag": TagRule,
    "path_glob": PathGlobRule,
    "method": MethodRule,
}


class CompositeRule(MatchRule):
    """RuleEntry 的多字段 AND 组合。"""

    def __init__(self, entry: RuleEntry) -> None:
        self._rules: list[MatchRule] = []
        for field_name, builder in _RULE_BUILDERS.items():
            value = getattr(entry, field_name)
            if value is not None:
                self._rules.append(builder(value))
        if not self._rules:
            raise ValueError("RuleEntry 必须至少包含一个字段")

    def matches(self, op: Operation) -> bool:
        return all(r.matches(op) for r in self._rules)


def build_rules(entries: list[RuleEntry]) -> list[MatchRule]:
    """批量构造规则，便于 grouper 使用。"""

    return [CompositeRule(e) for e in entries]
