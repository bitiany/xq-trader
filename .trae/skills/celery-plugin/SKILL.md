---
name: "celery-plugin"
description: "Celery 任务插件开发规范。在开发新的定时任务、编排任务、或涉及 worker/plugins 目录时必须遵循本 skill。"
---

# Celery 任务插件开发规范

## 1. 插件结构

每个插件是 `src/worker/plugins/` 下的独立模块包：

```
plugins/
└── my_task/                 # 插件目录（下划线命名）
    ├── __init__.py          # 导出 Task 类
    ├── plugin.yaml          # 声明式配置
    └── task.py              # 任务类（继承 BaseTask）
```

## 2. 编写任务类

在 `task.py` 中继承 `BaseTask`，定义 `task_name` + `_run_impl()`：

```python
from framework.scheduler.base_task import BaseTask

class MyTask(BaseTask):
    task_name = "my.module.task"   # 全局唯一标识
    description = "任务描述"

    async def _run_impl(self, **kwargs):
        # 业务逻辑
        return {"status": "SUCCESS", "data": [...]}
```

**要点**：
- `task_name` 必须全局唯一，建议 `模块.动作` 格式
- `_run_impl()` 支持 `async def` 或 `def`，框架自动桥接
- `kwargs` 接收任务入参；canvas 模式下 `upstream` 参数自动接收前一步结果
- 返回值会自动记录到执行日志
- **不要重写 `run()` 方法**，`run()` 由框架管理（处理 `upstream` 参数传递等）

## 3. 编写 plugin.yaml

```yaml
name: my_task
celery_task_name: my.module.task    # 与 task.py 中的 task_name 一致
version: "1.0.0"
task_name: 我的任务
task_name_en: My Task
description: 任务详细描述
category: compute                    # compute / io / data
task_type: scheduled                 # scheduled（定时）/ on_demand（按需）
queue: celery                        # 队列名
timeout: 300                         # 超时秒数
retry_config:
  max_retries: 3
  retry_backoff: true
  retry_backoff_max: 600
schedule: "30 15 * * 1-5"           # cron 表达式，仅 task_type=scheduled 时生效
params_schema:                       # 入参 JSON Schema
  type: object
  properties:
    symbol:
      type: string
      title: 证券代码
```

**字段说明**：
- `celery_task_name`：必须与 `task.py` 中 `task_name` 一致
- `task_type`：`scheduled` 会注册到 Beat 定时调度；`on_demand` 仅手动触发
- `schedule`：标准 5 段 cron 表达式（分 时 日 月 周）
- `timeout`：覆盖 BaseTask 默认的 300 秒

## 4. 编写 __init__.py

```python
from worker.plugins.my_task.task import MyTask  # noqa: F401
```

## 5. 编排配置

在 `schedules/` 目录下创建 YAML 文件定义编排流水线：

```yaml
name: daily_pipeline
description: "每日处理流水线"
mode: canvas                     # 编排模式: barrier（默认）或 canvas
cron: "30 16 * * 1-5"            # 可选，有则注册到 Beat（仅 canvas 模式支持 cron）
queue: celery
enabled: true

steps:
  - name: collect
    task: market.collect_daily   # 引用插件的 celery_task_name
    args: {}

  - name: calc
    task: factor.calc_daily
    depends_on: [collect]        # 依赖上一步
    args: {}
```

**要点**：
- `depends_on` 声明步骤间依赖，形成 DAG
- 编排配置启动时自动持久化到 `sch_pipeline_def` 表
- 编排步骤名（`name`）在所有编排中必须全局唯一，避免 DAG 节点冲突

### 5.1 编排模式（barrier vs canvas）

编排支持两种执行模式，通过 `mode` 字段区分：

| 模式 | 说明 | cron 支持 | 适用场景 |
|------|------|-----------|----------|
| `barrier`（默认） | 子任务独立 Celery 任务，通过 Redis 屏障计数器协调依赖 | 不支持 | 子任务需要独立调度、失败重试 |
| `canvas` | 编排作为整体 Celery 任务，使用 Celery Canvas 原语（chain/group/chord） | 支持 | 编排需要定时调度、步骤间自动传递结果 |

**barrier 模式**：
- 每个子任务是独立的 Celery 任务
- 通过 Redis 屏障计数器协调依赖关系
- 上游任务完成后通知 BarrierResolver，满足条件后触发下游
- 子任务不需要 cron 调度

**canvas 模式**：
- 编排作为整体 Celery 任务执行
- 使用 Celery Canvas 原语（chain/group/chord）构建 DAG 拓扑工作流
- 同层步骤并行（group），层间串行（chain）
- 前一步的结果自动传递给下游（`upstream` 参数）
- 支持 cron 定时调度（Beat 触发编排触发器任务）
- 编排状态在所有步骤完成后自动更新为 SUCCESS/FAILED

**选择建议**：
- 需要定时调度整个编排 → 使用 `canvas`
- 子任务需要独立执行和重试 → 使用 `barrier`
- 简单的线性/并行流程 → 两种均可，`canvas` 更简洁

### 5.2 编排架构

编排器采用 **双模式架构**（barrier 屏障触发 + canvas 工作流），核心组件：

| 组件 | 路径 | 职责 |
|------|------|------|
| DAGBuilder | `worker/scheduler/dag_builder.py` | 从配置构建 DAG，拓扑排序+环检测 |
| BarrierResolver | `worker/scheduler/barrier_resolver.py` | Redis 原子计数器实现分布式屏障（barrier 模式） |
| CanvasBuilder | `worker/orchestrator/canvas_builder.py` | 从 DAG 构建 Celery Canvas 工作流（canvas 模式） |
| CycleManager | `worker/scheduler/cycle_manager.py` | 管理调度周期 ID |
| OrchestrationTracker | `worker/orchestrator/orchestration_tracker.py` | 编排生命周期元数据（Redis + sch_task_exec） |
| CheckpointManager | `worker/orchestrator/checkpoint_manager.py` | 检查点持久化（Redis），支持断点续跑 |
| RecoveryManager | `worker/orchestrator/recovery_manager.py` | 基于检查点恢复失败编排 |

编排执行流程：
1. `worker.orchestration.trigger_pipeline` Celery 任务接收触发请求
2. 创建编排记录（OrchestrationTracker），注入 `cycle_id`/`orchestration_id`/`dag_node_name`/`step_index`
3. 根据 `mode` 分发到不同执行路径：
   - **barrier 模式**：分发根任务（无依赖的步骤），通过 DAG 屏障触发器协调依赖
   - **canvas 模式**：CanvasBuilder 构建 Canvas 工作流，作为整体 Celery 任务执行
4. barrier 模式：根任务完成后，BaseTask 自动通知屏障触发器，满足条件则触发下游
5. canvas 模式：Celery Canvas 自动按拓扑执行，前一步结果传递给下游
6. 编排状态在所有步骤完成后自动更新为 SUCCESS/FAILED

### 5.2 编排执行记录

编排执行记录统一写入 `sch_task_exec` 表，通过 `task_type` 和 `parent_id` 区分：

| 字段 | 说明 |
|------|------|
| `task_type=pipeline` | 编排父记录（编排本身） |
| `task_type=task` | 子任务记录（编排中的每个步骤） |
| `parent_id=NULL` | 独立任务或编排父记录 |
| `parent_id=<pipeline_exec_id>` | 编排子任务，指向编排父记录 |

查询编排子任务：`GET /api/v1/scheduler/pipelines/{pipeline_name}/executions/{exec_id}/children`

### 5.3 编排重试策略（断点续跑）

编排失败后，基于检查点实现断点续跑，仅重新执行失败的子任务，已成功的子任务跳过：

- BaseTask 在 `on_success`/`on_failure` 时自动保存检查点到 Redis
- 检查点记录每个步骤的执行状态（SUCCESS/FAILED）
- 重试时，RecoveryManager 从检查点找到第一个非 SUCCESS 的步骤，只分发该步骤及后续步骤
- 重试在同一编排 ID 下创建新的子任务记录（不创建新编排记录）

重试 API：`POST /api/v1/scheduler/pipelines/{pipeline_name}/executions/{exec_id}/retry`

仅 `status` 为 `FAILURE` 或 `FAILED` 的编排执行记录可以重试。

## 6. 框架自动提供的能力

业务侧**无需关心**以下内容，框架全部自动处理：

| 能力 | 说明 |
|------|------|
| Celery 注册 | 插件自动发现并注册为 Celery Task |
| Beat 调度 | `task_type=scheduled` 的插件自动注册定时调度；canvas 模式编排支持 cron |
| 防重入 | Redis 分布式锁，同一任务不会并发执行 |
| 异步桥接 | `async def run()` 自动在同步 Worker 中运行 |
| 执行日志 | 每次执行自动写入 `sch_task_exec` 表（使用 `bulk_create_or_update`） |
| 控制台日志 | 标准化输出：`[START]` `[SUCCESS]` `[FAILURE]` `[RETRY]` |
| 重试 | 指数退避重试，次数由 `retry_config.max_retries` 控制 |
| 超时 | 硬超时 + 软超时保护 |
| 配置合并 | `plugin.yaml` 配置自动覆盖 BaseTask 默认值 |
| 屏障通知 | 编排任务完成后自动通知屏障触发器，触发下游任务（barrier 模式） |
| Canvas 状态检查 | 编排任务完成后自动检查编排是否全部完成，更新编排状态（canvas 模式） |
| 检查点保存 | 编排任务完成后自动保存检查点到 Redis，支持断点续跑 |
| Worker 崩溃恢复 | `acks_late=True` + `task_reject_on_worker_lost=True`，未确认任务自动重新入队 |

## 7. 启动命令

```powershell
conda activate .\.conda
$env:ENV=".env"
$env:PYTHONPATH="src"

# Worker（4 并发，线程池，监听三队列）
celery -A worker.celery_entry worker -c 4 -P threads -Q celery,factor,market --loglevel=info

# Beat
celery -A worker.celery_entry beat --loglevel=info

# 或使用 pyproject.toml 中定义的入口（Worker 参数与上一行等价）
xqtrader-worker
xqtrader-beat
```

**并发说明**：

- `-P threads -c 4`：最多 4 个 Celery 任务并行；Windows 必须用 threads，禁止 solo（solo 下 `-c` 无效）。
- 同名任务默认 `prevent_concurrent=True`，Redis 锁保证不重复执行；不同任务可并行。
- 插件内 `concurrency` / `max_workers` 是任务内部并行度，与 Worker `-c` 无关。

## 8. 开发检查清单

- [ ] `task_name` 全局唯一
- [ ] `plugin.yaml` 的 `celery_task_name` 与 `task.py` 一致
- [ ] `__init__.py` 正确导出 Task 类
- [ ] 编排配置中 `task` 引用的 `celery_task_name` 已注册
- [ ] `params_schema` 与 `run()` 的 `kwargs` 匹配
- [ ] 编排模式选择：需要 cron 调度用 `canvas`，子任务独立重试用 `barrier`
- [ ] `mode` 字段与 `sch_pipeline_def.mode` 一致
