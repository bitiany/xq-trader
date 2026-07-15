"""说话风格注入 Hook — 根据路由标记注入对应风格提示。

仅根据 IntentRouter 的路由结果注入风格提示，不检测情绪、不干预用户状态。
风格定义见 personas/analyst/analyst.md。
"""
from __future__ import annotations

from typing import Literal

from nanobot.agent.hook import AgentHook, AgentHookContext

from framework.commons.logger import get_logger

logger = get_logger("AGENT.STYLE")

AnalystStyle = Literal["professional", "discussion"]

_PROFESSIONAL_NOTE = (
    "[分析师风格注入·专业输出]\n"
    "老板要求出报告/技术解读/数据分析。请切换到专业输出模式：\n"
    "1. 结构化报告（标题层级、数据表、结论明确）\n"
    "2. 术语严谨，客观中立\n"
    "3. 不夹带私人情绪\n"
    "4. 数据必须来自 MCP 工具，标注时效性\n"
    "5. 风险提示具体，不可泛泛而谈"
)

_DISCUSSION_NOTE = (
    "[分析师风格注入·员工-老板对话]\n"
    "老板在探讨走势/持仓/交易建议。请切换到员工-老板对话模式：\n"
    "1. 像下属跟老板聊天，有人情味\n"
    "2. 可以表态（\"我觉得\"\"我担心的是\"\"我建议\"）\n"
    "3. 不冷冰冰，但也不越界（是员工不是朋友）\n"
    "4. 给建议时说清楚依据，最终决定权在老板\n"
    "5. 永远不问\"你感觉怎么样\"，不用心理学术语，不评判过去决策"
)


def build_style_note(style: AnalystStyle) -> str:
    """根据风格标记构建注入提示。"""
    if style == "professional":
        return _PROFESSIONAL_NOTE
    return _DISCUSSION_NOTE


class StyleInjectionHook(AgentHook):
    """说话风格注入 — 根据路由标记注入对应风格提示。

    style 为 None 时不注入任何提示（走 Agent 默认行为）。
    """

    def __init__(self, style: AnalystStyle | None = None) -> None:
        super().__init__()
        self._style = style
        self._injected = False

    async def before_iteration(self, context: AgentHookContext) -> None:
        if self._injected or self._style is None:
            return
        self._injected = True
        note = build_style_note(self._style)
        messages = context.messages
        insert_at = len(messages)
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                insert_at = i
                break
        messages.insert(insert_at, {"role": "system", "content": note})
        logger.info("分析师风格注入: style=%s", self._style)
