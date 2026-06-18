"""通用 Operation 抽象 — 与具体业务无关。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Parameter:
    """OpenAPI parameter 元素的扁平化表示。"""

    name: str
    location: str  # path | query | header
    required: bool
    schema: dict[str, Any]
    description: str = ""


@dataclass
class Operation:
    """OpenAPI operation 的标准化表示。"""

    operation_id: str
    method: str  # GET / POST / ...
    path: str
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    body_schema: dict[str, Any] | None = None
    body_required: bool = False

    @property
    def fallback_id(self) -> str:
        """无 operation_id 时使用的回退命名。"""

        cleaned = self.path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
        return f"{self.method.lower()}_{cleaned}"
