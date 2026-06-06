"""调度相关 ORM 模型 — 任务定义、执行记录、编排定义。"""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class TaskDef(Base):
    """任务定义表 — SPI 插件注册时自动 upsert。"""

    __bind_key__ = "default"
    __tablename__ = "sch_task_def"

    name: Mapped[str] = mapped_column(String(100), primary_key=True, comment="任务唯一标识")
    description: Mapped[str | None] = mapped_column(String(500), default=None, comment="描述")
    module: Mapped[str] = mapped_column(String(200), comment="模块路径")
    time_limit: Mapped[int] = mapped_column(Integer, default=300, comment="超时(秒)")
    max_retries: Mapped[int] = mapped_column(Integer, default=3, comment="最大重试次数")
    prevent_concurrent: Mapped[bool] = mapped_column(Boolean, default=True, comment="防重入")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")

    __table_args__ = ({"comment": "任务定义表"},)


class TaskExec(Base):
    """任务执行记录 — 统一记录普通任务和编排任务的执行信息。

    通过 task_type 区分：
    - task: 普通任务（含编排子任务）
    - pipeline: 编排任务（父任务）

    通过 parent_id 关联：
    - parent_id=NULL: 独立任务或编排父任务
    - parent_id=<pipeline_exec_id>: 编排子任务
    """

    __bind_key__ = "default"
    __tablename__ = "sch_task_exec"

    id: Mapped[str] = mapped_column(String(50), primary_key=True, comment="任务实例ID")
    task_name: Mapped[str] = mapped_column(String(100), comment="任务标识")
    task_type: Mapped[str] = mapped_column(String(20), default="task", comment="类型: task/pipeline")
    status: Mapped[str] = mapped_column(String(20), comment="SUCCESS/FAILURE")
    args: Mapped[str | None] = mapped_column(Text, default=None, comment="入参 JSON")
    result: Mapped[str | None] = mapped_column(Text, default=None, comment="结果JSON(成功为业务数据,失败为异常信息)")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, comment="重试次数")
    parent_id: Mapped[str | None] = mapped_column(String(50), default=None, comment="父任务ID(编排场景)")
    started_at: Mapped[str | None] = mapped_column(String(50), default=None, comment="开始时间")
    finished_at: Mapped[str | None] = mapped_column(String(50), default=None, comment="结束时间")
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None, comment="耗时(毫秒)")

    __table_args__ = ({"comment": "任务执行记录表"},)


class PipelineDef(Base):
    """编排定义表 — 从 YAML 配置加载。"""

    __bind_key__ = "default"
    __tablename__ = "sch_pipeline_def"

    name: Mapped[str] = mapped_column(String(100), primary_key=True, comment="编排唯一标识")
    description: Mapped[str | None] = mapped_column(String(500), default=None, comment="描述")
    config: Mapped[str] = mapped_column(Text, comment="编排配置 JSON")
    mode: Mapped[str] = mapped_column(String(20), default="barrier", comment="编排模式: barrier/canvas")
    cron: Mapped[str | None] = mapped_column(String(50), default=None, comment="cron 表达式")
    queue: Mapped[str] = mapped_column(String(50), default="celery", comment="队列")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")

    __table_args__ = ({"comment": "编排定义表"},)
