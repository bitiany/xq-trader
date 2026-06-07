"""管道上下文 — 每条数据独立上下文，线程安全。"""

from __future__ import annotations

from typing import Any


class PipelineContext:
    """管线上下文 — 每条数据在管线处理过程中的状态容器。

    每个 item 在进入 Pipeline 时创建独立上下文，贯穿所有 Stage 和 Aspect。
    用于在 Stage 之间传递中间结果，在 Aspect 中读写元数据（如水位日期）。

    线程安全：每个 Worker 线程处理不同 item，各自持有独立上下文实例。
    """

    def __init__(self, pipeline_name: str, item: Any, init_data: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(init_data) if init_data else {}
        self.pipeline_name = pipeline_name
        self.item = item

    def get(self, key: str, default: Any = None) -> Any:
        """获取上下文值。"""
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """设置上下文值。"""
        self._data[key] = value

    def update(self, data: dict[str, Any]) -> None:
        """批量设置上下文值。"""
        self._data.update(data)

    def contains(self, key: str) -> bool:
        """检查上下文是否包含指定键。"""
        return key in self._data

    def to_dict(self) -> dict[str, Any]:
        """导出上下文为字典。"""
        return {
            "pipeline_name": self.pipeline_name,
            "item": self.item,
            **self._data,
        }
