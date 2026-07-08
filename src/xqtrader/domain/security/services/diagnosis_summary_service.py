"""诊股轻量解读 — 结构化评分 JSON → LLM narrative + bullets。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from agent.config import agent_settings
from framework.commons.exceptions import DataCollectionError
from framework.commons.logger import get_logger

logger = get_logger("DIAGNOSIS_SUMMARY")

_SYSTEM_PROMPT = (
    "你是 A 股诊股解读助手。根据输入的结构化评分 JSON，输出新浪风格变化解读。"
    "要求：narrative 为单段中文叙述（不超过 120 字），含综合分调整与主要变化维度，"
    "维度名用【维度名】包裹；bullets 为 2–3 条补充要点（每条不超过 40 字）；"
    "highlights 列出 narrative 中高亮维度，segments 拆分维度名前后文本。"
    "仅返回 JSON："
    '{"bullets":["..."],"narrative":"...","highlights":[{"key":"risk","label":"风险",'
    '"segments":[{"text":"【","highlight":false},{"text":"风险","highlight":true},{"text":"】","highlight":false}]}]}'
)


class DiagnosisSummaryService:
    """OpenAI 兼容接口的一次性 LLM 解读。"""

    @staticmethod
    def is_enabled() -> bool:
        return bool(agent_settings.LLM_API_KEY.strip())

    async def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self.is_enabled():
            raise DataCollectionError("LLM 未配置，无法生成 Agent 诊股解读")

        payload = {
            "model": agent_settings.LLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {agent_settings.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        url = f"{agent_settings.LLM_BASE_URL.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        try:
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            bullets_raw = parsed.get("bullets")
            if not isinstance(bullets_raw, list):
                raise ValueError("bullets 字段缺失或类型错误")
            bullets = [str(item).strip() for item in bullets_raw if str(item).strip()]
            if not bullets:
                raise ValueError("bullets 为空")
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DataCollectionError(f"LLM 诊股解读响应解析失败: {exc}") from exc

        result: dict[str, Any] = {
            "bullets": bullets[:3],
            "generated_by": "agent",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        narrative = parsed.get("narrative")
        if isinstance(narrative, str) and narrative.strip():
            result["narrative"] = narrative.strip()
        highlights = parsed.get("highlights")
        if isinstance(highlights, list) and highlights:
            result["highlights"] = highlights
        return result

    @staticmethod
    def build_context(payload: dict[str, Any]) -> dict[str, Any]:
        modules = payload.get("module_scores") or []
        return {
            "symbol": payload.get("symbol"),
            "name": payload.get("name"),
            "as_of": payload.get("as_of"),
            "overall_score": payload.get("overall_score"),
            "prev_overall_score": payload.get("prev_overall_score"),
            "prev_as_of": payload.get("prev_as_of"),
            "rating_label": payload.get("rating_label"),
            "market_percentile": payload.get("market_percentile"),
            "modules": [
                {
                    "key": module.get("key"),
                    "label": module.get("label"),
                    "score": module.get("score"),
                    "prev_score": module.get("prev_score"),
                }
                for module in modules
            ],
            "key_metrics": payload.get("key_metrics") or {},
        }
