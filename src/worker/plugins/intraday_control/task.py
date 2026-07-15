"""盘内监控控制信号任务 — Celery Beat 定时发布 start/stop Redis 控制信号。

由 Celery Beat 在 09:15 / 15:30 调用，通过 Redis Pub/Sub 发布控制信号，
FastAPI 内的 IntradayMonitorTask 监听 intraday.control 频道被唤醒/休眠。
"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from xqtrader.domain.market.intraday.publishers import publish_control

logger = get_logger(__name__)


class IntradayControlTask(BaseTask):
    """盘内监控控制信号任务。

    通过 Redis Pub/Sub 发布 start/stop 信号，IntradayMonitorTask 监听后执行
    对应的启动/停止流程。Celery 不拉起独立进程，不跑实时行情。
    """

    task_name = "market.intraday_control"
    description = "盘内监控控制信号（start/stop）"
    time_limit = 60
    soft_time_limit = 50
    max_retries = 2
    prevent_concurrent = False

    def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        action: str = (kwargs.get("action") or "").strip()

        if action not in ("start", "stop"):
            raise ValueError(
                f"无效的 action: '{action}'，仅支持 start/stop。"
                f"请在任务中心触发时选择动作（start 启动 / stop 停止）。"
            )

        publish_control(action)

        logger.info("[intraday_control] 控制信号已发布: action=%s", action)
        return {"action": action, "channel": "intraday.control", "status": "published"}
