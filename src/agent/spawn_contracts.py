"""spawn Worker JSON 契约校验 — 与 Skills 内联 schema 对齐。"""

from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator

_SPAWN_WORKER_RE = re.compile(r"\[spawn-worker:([a-z-]+)\]", re.IGNORECASE)

_TECHNICAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["as_of", "conclusion"],
    "properties": {
        "as_of": {"type": "string", "minLength": 1},
        "quote": {"type": "object"},
        "trend": {"type": "object"},
        "key_levels": {"type": "object"},
        "signals": {"type": "object"},
        "chanlun": {"type": "object"},
        "volume_price": {"type": "string"},
        "atr": {"type": "object"},
        "conclusion": {"type": "string", "minLength": 1},
    },
    "additionalProperties": True,
}

_SENTIMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["as_of", "sentiment_index", "conclusion"],
    "properties": {
        "as_of": {"type": "string", "minLength": 1},
        "sentiment_index": {"type": "string", "minLength": 1},
        "sentiment_score": {"type": "number"},
        "heat_score": {"type": "number"},
        "bullish_factors": {"type": "array"},
        "bearish_factors": {"type": "array"},
        "policy_impact": {"type": "string"},
        "event_signal": {"type": "string"},
        "conclusion": {"type": "string", "minLength": 1},
    },
    "additionalProperties": True,
}

_FUND_FLOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["as_of", "main_flow", "conclusion"],
    "properties": {
        "as_of": {"type": "string", "minLength": 1},
        "main_flow": {
            "type": "object",
            "required": ["direction"],
            "properties": {
                "direction": {"type": "string", "minLength": 1},
                "net_amount_wan": {"type": "number"},
                "net_pct": {"type": "number"},
            },
        },
        "super_large_order": {"type": "object"},
        "large_order": {"type": "object"},
        "divergence": {"type": "object"},
        "conclusion": {"type": "string", "minLength": 1},
    },
    "additionalProperties": True,
}

_SCHEMA_BY_WORKER: dict[str, dict[str, Any]] = {
    "technical": _TECHNICAL_SCHEMA,
    "sentiment": _SENTIMENT_SCHEMA,
    "fund-flow": _FUND_FLOW_SCHEMA,
}


class SpawnContractError(ValueError):
    """spawn Worker 输出不符合 JSON 契约。"""


def detect_spawn_worker(task_text: str, label: str = "") -> str | None:
    """从 spawn task/label 识别 worker 类型。"""
    for text in (task_text, label):
        match = _SPAWN_WORKER_RE.search(text)
        if match:
            return match.group(1).lower()
    lowered = task_text.lower()
    if "fund-flow" in lowered or "资金面" in lowered:
        return "fund-flow"
    if "sentiment" in lowered or "情绪" in lowered or "舆情" in lowered:
        return "sentiment"
    if "technical" in lowered or "技术面" in lowered:
        return "technical"
    return None


_JSON_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n(.*?)\n\s*```",
    re.DOTALL | re.IGNORECASE,
)


def extract_json_payload(text: str) -> dict[str, Any]:
    """从 spawn 结果文本提取 JSON 对象。

    支持三种格式：纯 JSON、Markdown 代码块包裹的 JSON、文本中嵌入的 JSON。
    """
    stripped = text.strip()
    if not stripped:
        raise SpawnContractError("spawn 结果为空")

    # 1. 纯 JSON 直接解析
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 2. Markdown 代码块 ```json ... ```
    for match in _JSON_CODE_FENCE_RE.finditer(stripped):
        block = match.group(1).strip()
        try:
            parsed = json.loads(block)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue

    # 3. 文本中嵌入的 JSON（第一个 { 到最后一个 }）
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(stripped[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise SpawnContractError(
                f"spawn 结果 JSON 解析失败: {exc}; "
                f"output_prefix={stripped[:200]!r}",
            ) from exc

    raise SpawnContractError(
        f"spawn 结果未包含有效 JSON 对象; output_prefix={stripped[:200]!r}",
    )


def validate_spawn_output(worker: str, payload: dict[str, Any]) -> None:
    schema = _SCHEMA_BY_WORKER.get(worker)
    if schema is None:
        return
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.path) or "(root)"
        raise SpawnContractError(
            f"spawn worker={worker} 契约校验失败: {path}: {first.message}",
        )
