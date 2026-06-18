"""配置模型 — 由 PyYAML 加载，Pydantic 校验。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, model_validator


class ServerSection(BaseModel):
    """MCP 服务进程级配置。"""

    name: str = "xqtrader"
    transport: Literal["sse"] = "sse"
    host: str = "127.0.0.1"
    port: int = 8097
    routes_prefix: str = "/sse"
    default_group: str | None = None
    tool_name_prefix: str = ""


class SourceSection(BaseModel):
    """OpenAPI 源配置。"""

    type: Literal["http", "file"] = "http"
    url: str = ""
    path: str = ""
    api_base_url: str = ""
    refresh_interval: int = 0

    @model_validator(mode="after")
    def _validate(self) -> SourceSection:
        if self.type == "http" and not self.url:
            raise ValueError("source.type=http 时必须提供 url")
        if self.type == "file" and not self.path:
            raise ValueError("source.type=file 时必须提供 path")
        if self.type == "http" and not self.api_base_url:
            self.api_base_url = self.url.rsplit("/", 1)[0]
        return self


class InvokerSection(BaseModel):
    """HTTP 调用器配置。"""

    timeout_seconds: float = 30.0
    max_keepalive_connections: int = 32
    unwrap_response_data: bool = True


class RuleEntry(BaseModel):
    """通用匹配规则条目（同一条目可写多个字段，AND 关系）。"""

    operation_id: str | None = None
    tag: str | None = None
    path_glob: str | None = None
    method: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> RuleEntry:
        if not any(v is not None and v != "" for v in [self.operation_id, self.tag, self.path_glob, self.method]):
            raise ValueError("rule entry 至少需要一个非空匹配字段")
        return self


class GroupSection(BaseModel):
    """单个分组定义。"""

    title: str
    description: str = ""
    include: list[RuleEntry] = Field(default_factory=list)
    exclude: list[RuleEntry] = Field(default_factory=list)


class McpServerConfig(BaseModel):
    """根配置。"""

    server: ServerSection = Field(default_factory=ServerSection)
    source: SourceSection
    invoker: InvokerSection = Field(default_factory=InvokerSection)
    deny: list[RuleEntry] = Field(default_factory=list)
    groups: dict[str, GroupSection]

    @model_validator(mode="after")
    def _validate_groups(self) -> McpServerConfig:
        if not self.groups:
            raise ValueError("groups 不能为空")
        if self.server.default_group and self.server.default_group not in self.groups:
            raise ValueError(
                f"server.default_group={self.server.default_group} 未在 groups 中定义",
            )
        return self


def load_config(path: str | Path) -> McpServerConfig:
    """读取 YAML 并构造校验后的配置。"""

    raw: Any = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件根节点必须是 dict: {path}")
    return McpServerConfig.model_validate(raw)
