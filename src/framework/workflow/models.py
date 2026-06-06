"""工作流执行记录模型。

存储每次工作流执行的状态、checkpoint 映射、当前节点等信息，
使业务侧只需关心 flow_id + run_id，无需暴露内部 thread_id 等细节。
"""
from __future__ import annotations

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class WorkflowRun(AuditedBase):
    """工作流执行记录表。

    核心设计（参照 Dify workflow_run_id）：
    - run_id: 对外暴露的执行实例 ID，业务侧唯一标识
    - thread_id: LangGraph checkpoint 的 thread_id，内部使用
    - flow_id: 工作流定义 ID
    - status: 执行状态 (running / paused / succeeded / failed / stopped)
    - current_node_id: 当前执行到的节点 ID
    - inputs: 工作流输入参数 (JSON)
    - outputs: 工作流输出结果 (JSON)
    - error: 错误信息
    - total_steps: 总节点数
    - elapsed_time: 执行耗时（秒）
    """
    __bind_key__ = "default"
    __tablename__ = "t_workflow_run"

    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="执行实例ID")
    flow_id: Mapped[str] = mapped_column(String(64), index=True, comment="工作流定义ID")
    workspace_id: Mapped[str] = mapped_column(String(64), default="", comment="工作空间ID")
    thread_id: Mapped[str] = mapped_column(String(128), default="", comment="LangGraph checkpoint thread_id")
    status: Mapped[str] = mapped_column(
        String(20), default="running", index=True,
        comment="执行状态: running/paused/succeeded/failed/stopped"
    )
    current_node_id: Mapped[str] = mapped_column(String(64), default="", comment="当前节点ID")
    current_node_title: Mapped[str] = mapped_column(String(128), default="", comment="当前节点名称")
    inputs: Mapped[str] = mapped_column(Text, default="{}", comment="工作流输入参数(JSON)")
    outputs: Mapped[str] = mapped_column(Text, default="{}", comment="工作流输出结果(JSON)")
    interrupt_data: Mapped[str] = mapped_column(Text, default="{}", comment="中断信息(JSON)")
    error: Mapped[str] = mapped_column(Text, default="", comment="错误信息")
    total_steps: Mapped[int] = mapped_column(Integer, default=0, comment="总节点数")
    elapsed_time: Mapped[float] = mapped_column(default=0.0, comment="执行耗时(秒)")
    finished_at: Mapped[str | None] = mapped_column(
        DateTime, default=None, server_default=func.now(), comment="完成时间"
    )
