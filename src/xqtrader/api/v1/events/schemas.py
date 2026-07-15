"""事件驱动 Pydantic Schemas。"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class EventDetectRequest(BaseModel):
    """事件检测请求。"""

    symbols: list[str] | None = Field(
        default=None,
        description="标的代码列表（None 表示全部标的的新闻）",
    )
    event_types: list[str] | None = Field(
        default=None,
        description="事件类型过滤（如 ['资产重组', '股东减持']，None 表示全部）",
    )
    days: int = Field(default=7, ge=1, le=90, description="回溯天数")
    as_of: date | None = Field(default=None, description="基准日期（None 表示今天）")


class EventImpactRequest(BaseModel):
    """事件→论点卡影响评估请求。"""

    symbol: str = Field(..., description="标的代码")
    events: list[dict[str, Any]] = Field(
        ...,
        description="事件列表（detect_events 返回的 events 数组）",
    )
    as_of: date | None = Field(default=None, description="基准日期（None 表示今天）")


class EventAssetAllocationRequest(BaseModel):
    """事件→资产配置影响评估请求（s6-3）。"""

    event_types: list[str] = Field(
        ...,
        description="事件类型列表（如 ['货币宽松', '股东减持', '退市风险']）",
    )
