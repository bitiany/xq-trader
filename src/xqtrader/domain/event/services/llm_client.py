"""轻量 LLM 客户端 — 直接调用 OpenAI 兼容接口（chat/completions）。

复用 agent_settings 的 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL_NAME 三元组，
绕过 Nanobot Agent Loop（过重），适合 EventDetector Layer 2 的单轮精细识别。

参考实现：xqtrader/domain/security/services/diagnosis_summary_service.py
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from agent.config import agent_settings
from framework.commons.exceptions import DataCollectionError
from framework.commons.logger import get_logger

logger = get_logger("EVENT.LLM")


class LLMClient:
    """OpenAI 兼容接口的轻量 LLM 客户端 — 单轮 chat completion + JSON 输出。"""

    @staticmethod
    def is_enabled() -> bool:
        """LLM 是否已配置（api_key 非空）。"""
        return bool(agent_settings.LLM_API_KEY.strip())

    async def chat_json(
        self,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.2,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """单轮 LLM 调用，返回 JSON 解析结果。

        Args:
            system_prompt: 系统提示词（含 JSON 输出格式约束）
            user_content: 用户消息内容（文本或 JSON 字符串）
            temperature: 温度参数（事件识别用 0.2，偏确定性）
            timeout: 超时秒数

        Returns:
            LLM 返回的 JSON 解析后的 dict

        Raises:
            DataCollectionError: LLM 未配置或响应解析失败
        """
        if not self.is_enabled():
            raise DataCollectionError(
                "LLM 未配置（AGENT_LLM_API_KEY/LLM_API_KEY 为空），无法执行 Layer 2 LLM 精细识别"
            )

        payload = {
            "model": agent_settings.LLM_MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {agent_settings.LLM_API_KEY}",
            "Content-Type": "application/json",
        }
        url = f"{agent_settings.LLM_BASE_URL.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        try:
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError(f"LLM 返回非 JSON 对象: {type(parsed).__name__}")
            return parsed
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.error(
                "LLM 响应解析失败: url=%s error=%s",
                url, exc, exc_info=True,
            )
            raise DataCollectionError(f"LLM 响应解析失败: {exc}") from exc
