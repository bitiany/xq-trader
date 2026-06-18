"""Agent Worker 配置。"""

from __future__ import annotations

import os
from pathlib import Path

from framework.config.settings import settings

_AGENT_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AgentSettings:
    """Agent Worker 配置 — 从 framework settings 和 .env 读取。"""

    def __init__(self) -> None:
        self.REDIS_URL = settings.REDIS.url
        self.LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
        self.LLM_API_KEY = os.getenv("LLM_API_KEY", "")
        self.LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "Qwen/Qwen3-235B-A22B-Instruct-2507")
        self.WORKSPACE = str(_AGENT_ROOT / "workspace")
        self.MAX_CONCURRENT_RUNS = 8
        self.QUEUE_BLOCK_SECONDS = 5
        self.SSE_BLOCK_MS = 5000
        self.WORKER_ID = "worker-1"
        self.SERVICE_BASE_URL = f"http://127.0.0.1:{settings.APP.PORT}"
        self.MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://127.0.0.1:8097")
        self.MCP_GROUPS = [
            g.strip()
            for g in os.getenv(
                "MCP_GROUPS",
                "stocks,factors,strategies,selection,positions",
            ).split(",")
            if g.strip()
        ]
        self.MCP_TOOL_TIMEOUT = int(os.getenv("MCP_TOOL_TIMEOUT", "30"))


agent_settings = AgentSettings()
