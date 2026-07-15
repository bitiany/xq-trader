"""Intent Router — submit_message 入口分流 Agent Loop / FlowEngine / 分析师风格路由。

风格检测两层机制：
  Layer 1（关键词规则）：命中 professional/discussion 关键词 → AnalystRoute
  Layer 2（LLM 兜底）：Layer 1 未命中时，LLM 分类消息意图
  LLM 未配置/超时/失败 → AgentRoute()（不注入风格，走 Agent 默认行为）
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from framework.commons.logger import get_logger
from framework.config.settings import settings

logger = get_logger("AGENT.ROUTER")

_FLOW_PREFIX_RE = re.compile(r"^/(?:workflow|flow)\s+([a-zA-Z0-9_-]+)\s*$")
_FLOW_HASH_RE = re.compile(r"^#flow:([a-zA-Z0-9_-]+)\s*$")

# 关键词规则文件
_KEYWORDS_FILE = (
    Path(__file__).resolve().parent / "intent_keywords.yaml"
)
_keywords_cache: dict[str, list[str]] | None = None

AnalystStyle = Literal["professional", "discussion"]

# LLM 兜底分类的 system prompt
_LLM_CLASSIFY_PROMPT = (
    "你是意图分类器。判断用户消息属于哪种场景：\n"
    "- professional: 要求出报告、技术解读、数据分析、深度分析\n"
    "- discussion: 探讨走势、持仓、交易建议\n"
    "- none: 无法判断或与金融分析无关\n"
    '返回 JSON: {"style": "professional|discussion|none"}'
)
_LLM_TIMEOUT = 10.0


def _load_keywords() -> dict[str, list[str]]:
    """加载关键词规则（模块级缓存）。"""
    global _keywords_cache
    if _keywords_cache is not None:
        return _keywords_cache
    try:
        with _KEYWORDS_FILE.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.warning("意图关键词文件格式错误: %s", _KEYWORDS_FILE)
            data = {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("意图关键词文件加载失败: %s exc=%s", _KEYWORDS_FILE, exc)
        data = {}
    result: dict[str, list[str]] = {}
    for style in ("professional", "discussion"):
        section = data.get(style, {})
        if isinstance(section, dict):
            kws = section.get("keywords", [])
            if isinstance(kws, list):
                result[style] = [str(k) for k in kws]
    _keywords_cache = result
    logger.info(
        "意图关键词已加载: professional=%d discussion=%d",
        len(result.get("professional", [])),
        len(result.get("discussion", [])),
    )
    return result


def _match_keywords(message: str, keywords: list[str]) -> bool:
    """检查消息是否包含任一关键词。"""
    lower_msg = message.lower()
    return any(kw.lower() in lower_msg for kw in keywords)


async def _llm_classify_style(message: str) -> AnalystStyle | None:
    """Layer 2: LLM 兜底分类消息意图。

    LLM 未配置或调用失败时返回 None（走 AgentRoute 默认行为）。
    """
    try:
        from xqtrader.domain.event.services.llm_client import LLMClient

        if not LLMClient.is_enabled():
            return None
        client = LLMClient()
        result = await client.chat_json(
            system_prompt=_LLM_CLASSIFY_PROMPT,
            user_content=message[:500],
            temperature=0.0,
            timeout=_LLM_TIMEOUT,
        )
        style = str(result.get("style", "none")).lower()
        if style in ("professional", "discussion"):
            logger.info("LLM 兜底分类命中: style=%s", style)
            return style  # type: ignore[return-value]
        logger.info("LLM 兜底分类未命中: style=%s", style)
        return None
    except Exception as exc:
        logger.warning("LLM 兜底分类失败，走默认路由: %s", exc, exc_info=True)
        return None


@dataclass(frozen=True, slots=True)
class AgentRoute:
    """走 Agent Worker 队列（默认，不注入风格提示）。"""


@dataclass(frozen=True, slots=True)
class WorkflowRoute:
    """走 FlowEngine 同步执行。"""

    flow_id: str
    inputs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AnalystRoute:
    """走 Agent Worker 队列，附带说话风格标记。

    Attributes:
        style: professional（专业输出）或 discussion（员工-老板对话）
        source: 检测来源 "keyword" 或 "llm"
    """

    style: AnalystStyle
    source: str


class IntentRouter:
    """按显式 flow_id、消息前缀、风格关键词将请求分流到工作流或 Agent。"""

    @staticmethod
    def flow_config_path(flow_id: str) -> str:
        return os.path.join(settings.APP.ROOT_DIR, f"flow/{flow_id}.json")

    @classmethod
    def flow_exists(cls, flow_id: str) -> bool:
        return os.path.isfile(cls.flow_config_path(flow_id))

    @classmethod
    async def resolve(
        cls,
        message: str,
        *,
        flow_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentRoute | WorkflowRoute | AnalystRoute:
        ctx = context or {}
        explicit = (flow_id or str(ctx.get("flow_id") or "")).strip()
        if explicit:
            if not cls.flow_exists(explicit):
                raise ValueError(f"工作流 '{explicit}' 不存在")
            return WorkflowRoute(
                flow_id=explicit,
                inputs=cls._build_workflow_inputs(message, ctx),
            )

        stripped = message.strip()
        for pattern in (_FLOW_PREFIX_RE, _FLOW_HASH_RE):
            match = pattern.match(stripped)
            if match:
                resolved_id = match.group(1)
                if not cls.flow_exists(resolved_id):
                    raise ValueError(f"工作流 '{resolved_id}' 不存在")
                return WorkflowRoute(
                    flow_id=resolved_id,
                    inputs=cls._build_workflow_inputs(stripped, ctx),
                )

        # Layer 1: 关键词规则检测
        keywords = _load_keywords()
        if _match_keywords(message, keywords.get("professional", [])):
            logger.info("关键词命中: style=professional")
            return AnalystRoute(style="professional", source="keyword")
        if _match_keywords(message, keywords.get("discussion", [])):
            logger.info("关键词命中: style=discussion")
            return AnalystRoute(style="discussion", source="keyword")

        # Layer 2: LLM 兜底分类
        style = await _llm_classify_style(message)
        if style is not None:
            return AnalystRoute(style=style, source="llm")

        # 默认：不注入风格
        return AgentRoute()

    @staticmethod
    def _build_workflow_inputs(message: str, context: dict[str, Any]) -> dict[str, Any]:
        raw_inputs = context.get("workflow_inputs")
        if isinstance(raw_inputs, dict):
            return dict(raw_inputs)
        if isinstance(raw_inputs, str):
            try:
                parsed = json.loads(raw_inputs)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        inputs: dict[str, Any] = {"message": message}
        for key in ("symbol", "stock_symbol", "workspace_id"):
            if key in context and context[key] not in (None, ""):
                inputs[key] = context[key]
        return inputs
