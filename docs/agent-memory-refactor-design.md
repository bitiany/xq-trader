# Agent 记忆架构重构设计

## 1. 背景与问题

上一轮实现把「会话历史」与「语义经验召回」都做成了 `agent_memory` 分组下的 MCP 工具，由 Agent 依据 `AGENTS.md` 规则主动调用。经对 nanobot 框架源码的一手核查，确认当前架构存在三处割裂：

1. **会话历史被错误地建模为 MCP 工具**（`list_sessions` / `get_session_history`）。
   nanobot 框架已原生支持「按 `session_key` 自动加载历史 → 自动注入 LLM 上下文 → 每轮自动落盘」，无需 Agent 主动调用工具。把它做成工具，既功能重复，又依赖 LLM「记得去翻历史」，不可靠。

2. **双重持久化（双写同一份数据）**。
   `src/agent/worker.py::_persist_session` 手动把每轮对话写入 PostgreSQL（`ag_session`/`ag_message`），而 nanobot 框架**同时**已把同一份对话写入 `{workspace}/sessions/*.jsonl`。两套存储、同一份数据。

3. **框架记忆能力被关闭后又在外部重造**。
   `src/agent/config.py::DISABLED_SKILLS` 禁用了框架内置 `memory` skill，却在外部用 MCP 工具重建了一套更弱的记忆机制（`search/index_research_memory`）。

此外，前端 `web/src/api/agent/chat.ts` 仅调用 `/agent/sessions` + SSE，**从未调用** `agent_memory` 的 sessions/memory 端点，佐证这些工具属于冗余。

### 概念边界（本次重构的判定基准）

| 机制 | 本质 | 正确场景 | 判定标准 |
|---|---|---|---|
| MCP 工具 | 让 LLM 调用应用侧业务功能 | 查行情、查论点卡等需 Agent 主动决策的业务动作/数据 | 「Agent 要不要做这件事」是一个推理决策 |
| Skill | 给 Agent 的领域方法论（prompt 层知识） | 五步法流程、技术分析方法 | 是「怎么做」的指导，不是数据 |
| Agent 内置记忆 | 对话上下文的自动管理 | 每轮自动加载历史、自动注入 context、自动落盘 | 不需要 Agent 决策，框架每次自动执行 |

结论：
- **会话历史**属于「Agent 内置记忆」→ 应回归框架，改用 PostgreSQL 后端。
- **语义经验召回**属于长期记忆增强 → 应通过 hook 每轮自动注入，而非 MCP 工具。
- **论点卡 / 偏好**是结构化业务知识（跨会话共享、被前端 UI 展示、Agent 需主动决策引用）→ 保持 MCP 工具，**不动**。

## 2. nanobot 框架能力核查（一手源码结论）

安装路径：`d:\ProgramData\xq-trader\.conda\Lib\site-packages\nanobot\`

### 2.1 会话后端可注入

- `nanobot/agent/loop.py` `AgentLoop.__init__(..., session_manager: SessionManager | None = None)`，
  第 262 行：`self.sessions = session_manager or SessionManager(workspace)` —— 支持注入自定义会话后端。
- `AgentLoop.from_config(config, **extra)` 明确透传 `session_manager`。
- **但** `nanobot/nanobot.py` `Nanobot.from_config` 写死了不透传 `session_manager`。

**解法**：`build_bot()` 改为
```python
loop = AgentLoop.from_config(config, session_manager=PgSessionManager(...),
                             image_generation_provider_configs=...)
bot = Nanobot(loop)
```
绕过 `Nanobot.from_config` 门面。这是官方 docstring 认可的用法。

### 2.2 无抽象接口，需鸭子兼容

框架未定义 `SessionStore` ABC/Protocol。全量扫描 57 处 `self.sessions.*` 调用面后，`PgSessionManager` 必须鸭子兼容以下成员：

| 成员 | 签名 | 用途 |
|---|---|---|
| `get_or_create(key)` | `-> Session` | 加载/新建会话（loop/consolidator/autocompact/command 等高频调用） |
| `save(session, *, fsync=False)` | `-> None` | 落盘（每轮 `_state_save` 调用） |
| `invalidate(key)` | `-> None` | 清缓存 |
| `delete_session(key)` | `-> bool` | 删除会话 |
| `list_sessions()` | `-> list[dict]` | AutoCompact 扫描 + WebUI 列表 |
| `read_session_file(key)` | `-> dict \| None` | 只读视图（HTTP 只读端点） |
| `flush_all()` | `-> int` | 优雅关闭时刷盘 |
| `safe_key(key)` [staticmethod] | `-> str` | key→稳定标识 |
| 属性 `workspace` / `sessions_dir` | | 部分工具读取 |

**关键约束**：框架所有 `session_manager` 调用均为**同步**方法（`get_or_create`/`save` 等非 async）。而 xqtrader 的 DAL 是异步 SQLAlchemy。因此 `PgSessionManager` 需在同步方法内桥接异步 DB 访问（见 §4.3）。

`Session` 是纯 dataclass（`key/messages/created_at/updated_at/metadata/last_consolidated`），**直接复用框架 `Session` 类**，只替换存储层——复杂的 `get_history` 裁剪/整合逻辑无需改动。

### 2.3 记忆层不可插拔（不影响本方案）

`MemoryStore`/`Consolidator`/`Dream` 在 `AgentLoop.__init__` 内硬编码构造，无注入点。它们操作 workspace 文件（`MEMORY.md`/`history.jsonl` 等），与会话/语义记忆是不同职责，**保持框架默认即可**，本方案不触碰。

### 2.4 hook 机制

`nanobot/agent/hook.py` `AgentHook` 提供生命周期钩子：`before_iteration` / `before_execute_tools` / `after_iteration` / `finalize_content` 等。
`AgentHookContext` 暴露可变 `messages`（就地被 runner 复用），可在 `before_iteration` 注入上下文。

**关键约束**：`AgentHookContext` **不含 `session_key`/`symbol`**。因此语义召回 hook 需**按 run 构造**（每次 `bot.run` 传入独立 hook 实例，携带该 run 的 symbol），不能用进程级单例 hook。

## 3. 目标架构

```
                    ┌─────────────────────────────────────────┐
   前端 chat.ts ───▶│ POST /agent/sessions/{id}/messages       │
                    │ (入队 RunTask 到 Redis)                   │
                    └──────────────┬──────────────────────────┘
                                   │ Redis 队列
                    ┌──────────────▼──────────────────────────┐
                    │ Agent Worker (python -m agent)           │
                    │  build_bot():                            │
                    │    AgentLoop.from_config(                │
                    │      session_manager=PgSessionManager)   │
                    │    Nanobot(loop)                         │
                    │  bot.run(msg, session_key,               │
                    │          hooks=[RedisEventHook,          │
                    │                 MemoryRecallHook(symbol)])│
                    └───┬───────────────────┬──────────────────┘
                        │ 会话自动加载/落盘   │ 每轮自动检索/注入
                        ▼                    ▼
              ┌──────────────────┐   ┌──────────────────┐
              │ PostgreSQL       │   │ Qdrant           │
              │ ag_session       │   │ (语义经验向量)     │
              │ ag_message       │   │  BGE-large-zh    │
              └──────────────────┘   └──────────────────┘
```

- 会话记忆：框架自动管理，PostgreSQL 后端，单一数据源。
- 语义召回：hook 在 `before_iteration` 自动检索 Qdrant 并注入 `context.messages`；对话结束在 `finalize_content` 自动 index。
- 论点卡/偏好：保持 MCP 工具（`get/save/mark_stale_thesis`、`get_preference`）。

## 4. 详细设计

### 4.1 表结构重设（drop 旧表重建）

现有 `ag_session`/`ag_message` 为旧 MCP 工具设计，字段与 nanobot `Session` 不匹配（缺 `last_consolidated` 游标，message 缺 `timestamp`/`tool_calls`/`reasoning_content`/`thinking_blocks`/`media` 等）。重设为：

**`ag_session`（会话元数据表）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `session_key` | String, PK | nanobot session key（如 `stock:600519.SH`） |
| `metadata` | JSONB | nanobot Session.metadata（含 title 等） |
| `last_consolidated` | Integer, default 0 | 已整合消息游标 |
| `created_at` | DateTime(tz) | 会话创建时间 |
| `updated_at` | DateTime(tz) | 最近更新时间 |

> 注意：ORM 属性名避免使用 `metadata`（与 SQLAlchemy 内置冲突），用 `meta` 属性 + 无显式列名（沿用上一轮修复经验），或用 `session_metadata`。二选一，实现时统一。

**`ag_message`（消息表）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BigInteger, PK, autoincrement | 自增主键，保证顺序 |
| `session_key` | String, indexed | 外键语义（不建物理外键，遵循项目规范） |
| `seq` | Integer | 会话内序号（与 messages 列表顺序一致） |
| `payload` | JSONB | **完整** nanobot message dict（role/content/timestamp/tool_calls/reasoning_content/…） |
| `created_at` | DateTime(tz) | 落库时间 |

设计要点：
- message 用单个 `payload` JSONB 完整存储原始 dict，**无损保留** nanobot 全部字段，避免字段映射丢信息。
- `(session_key, seq)` 唯一，读取按 `seq` 正序还原 `Session.messages`。
- 通过 `GENERATE_SCHEMA_ON_START` 自动建表。旧表 drop 后重建。

### 4.2 `PgSessionManager` 设计

位置：`src/agent/session_backend.py`（Agent 侧，因为它是喂给 nanobot 框架的适配器）。

职责：鸭子兼容 §2.2 全部成员，把 nanobot `Session` 与 PG 表互转。

```python
class PgSessionManager:
    """鸭子兼容 nanobot SessionManager 的 PostgreSQL 会话后端。

    框架以同步方式调用（get_or_create/save/...），内部桥接异步 DAL。
    带进程内缓存 _cache，与框架 SessionManager 行为一致。
    """
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.sessions_dir = workspace / "sessions"  # 兼容属性，不实际使用
        self._cache: dict[str, Session] = {}

    @staticmethod
    def safe_key(key: str) -> str: ...

    def get_or_create(self, key: str) -> Session: ...   # 缓存命中直接返回；否则 DB 加载或新建
    def save(self, session: Session, *, fsync: bool = False) -> None: ...
    def invalidate(self, key: str) -> None: ...
    def delete_session(self, key: str) -> bool: ...
    def list_sessions(self) -> list[dict]: ...
    def read_session_file(self, key: str) -> dict | None: ...
    def flush_all(self) -> int: ...
```

`Session` 复用 `from nanobot.session.manager import Session`。

### 4.3 同步→异步桥接方案

框架同步调用 + xqtrader 异步 DAL 的矛盾，是本方案的**最大技术风险点**，需谨慎选型：

- Agent Worker 主流程运行在 asyncio 事件循环内（`worker.py::_async_main`）。框架的同步 `save/get_or_create` 是在该事件循环的调用栈中被同步调用的——**不能在运行的事件循环里 `asyncio.run()` 或 `loop.run_until_complete()`**（项目规范也禁止 `asyncio.run()` 嵌套）。

候选方案（实现前需最终确认）：
1. **专用 DB 线程 + 独立事件循环**：`PgSessionManager` 持有一个后台线程运行独立 event loop，同步方法通过 `asyncio.run_coroutine_threadsafe(coro, bg_loop).result()` 阻塞取结果。**推荐**——彻底隔离，无嵌套循环风险。
2. **同步 psycopg 直连**：`PgSessionManager` 内部用同步 DB driver（psycopg3 sync）单独连接 PG，不复用异步 DAL。简单直接，但引入第二套 DB 访问方式，偏离 dal-orm 规范。

倾向方案 1（保持单一 DB 访问栈），方案 2 作为备选。**此点在实施阶段需再与用户确认。**

### 4.4 `MemoryRecallHook` 设计（语义召回自动注入）

位置：`src/agent/hooks.py`（与 RedisEventHook 同处）。

```python
class MemoryRecallHook(AgentHook):
    """每轮迭代前自动检索 Qdrant 经验并注入上下文；对话结束自动 index。

    按 run 构造，携带本 run 的 symbol / user_message。
    """
    def __init__(self, symbol: str | None, query: str) -> None:
        super().__init__()
        self._symbol = symbol
        self._query = query
        self._injected = False

    async def before_iteration(self, context: AgentHookContext) -> None:
        # 仅首轮注入一次，避免重复
        if self._injected:
            return
        results = MemoryService.get_instance().search_memory(
            query=self._query, top_k=3, symbol=self._symbol,
        )
        if results:
            recall_text = _format_recall(results)   # "经验参考（非权威）：..."
            context.messages.insert(_pos, {"role": "system", "content": recall_text})
        self._injected = True

    def finalize_content(self, context, content):
        # 对话结束后把本轮结论 index 进 Qdrant（异步桥接，见 4.3）
        ...
        return content
```

要点：
- 每轮 run 在 `worker.py::_execute_run` 内构造 `MemoryRecallHook(symbol, task.message)`，与 `RedisEventHook` 一并传入 `bot.run(hooks=[...])`。
- 检索结果标注「经验参考（非权威事实）」，与论点卡（权威结论）区分。
- index 时机与桥接方式复用 §4.3 结论。
- `MemoryService`（Qdrant + BGE）保持现状，无需改动，仅调用方从 API 端点改为 hook。

### 4.5 worker.py 改动

- 删除 `_persist_session`（框架自动落盘，不再手动双写）。
- 删除 `from ...session_service import SessionService` 调用。
- `_execute_run` 内构造 `MemoryRecallHook` 并加入 hooks 列表。

### 4.6 runtime.py 改动

`build_bot()` 从 `Nanobot.from_config(...)` 改为：
```python
from nanobot.agent.loop import AgentLoop
from nanobot.providers.image_generation import image_gen_provider_configs
from nanobot.config.loader import load_config, resolve_config_env_vars

config = resolve_config_env_vars(load_config(_CONFIG_PATH))
config.agents.defaults.workspace = str(_WORKSPACE)
loop = AgentLoop.from_config(
    config,
    session_manager=PgSessionManager(_WORKSPACE),
    image_generation_provider_configs=image_gen_provider_configs(config),
)
bot = Nanobot(loop)
```
（`bot._loop.model` 覆盖逻辑保留。）

### 4.7 MCP 工具与 API 清理

删除以下 4 个端点（`src/xqtrader/api/v1/agent_memory/router.py`）及其 service 方法：
- `list_sessions`（GET /sessions）
- `get_session_history`（GET /sessions/{key}/messages）
- `search_research_memory`（GET /memory/search）
- `index_research_memory`（POST /memory/index）

`mcp_server.yml` `agent_memory` group 白名单相应删除这 4 个 operation_id，仅保留：
`get_stock_thesis` / `save_stock_thesis` / `mark_thesis_stale` / `get_preference`。

`SessionService`（`session_service.py`）整体删除（其职责已由 `PgSessionManager` 承接）。
`MemoryService` 保留（改由 hook 调用）。

### 4.8 前端历史展示（如需要）

当前前端未使用会话历史列表功能。若后续需要「跨页查看历史」，新增**普通只读 API**（非 MCP）读 PG `ag_session`/`ag_message`，不再经 Agent 工具。本次重构**不新增**该功能，仅保证数据在 PG 中可查。

## 5. 影响面清单

| 文件 | 改动 |
|---|---|
| `src/xqtrader/domain/agent/models/session.py` | 重设 `ag_session`/`ag_message` 表结构 |
| `src/agent/session_backend.py` | 新建 `PgSessionManager` |
| `src/agent/hooks.py` | 新增 `MemoryRecallHook` |
| `src/agent/runtime.py` | `build_bot` 改走 `AgentLoop.from_config(session_manager=...)` |
| `src/agent/worker.py` | 删除 `_persist_session`；构造并传入 `MemoryRecallHook` |
| `src/xqtrader/api/v1/agent_memory/router.py` | 删除 4 个端点（sessions×2 + memory×2） |
| `src/xqtrader/domain/agent/services/session_service.py` | 整体删除 |
| `src/xqtrader/domain/agent/services/memory_service.py` | 保留（调用方改为 hook） |
| `mcp_server.yml` | `agent_memory` group 白名单删除 4 个 operation_id |
| `src/agent/workspace/AGENTS.md` | 删除「会话历史」「经验召回」工具说明；改为说明记忆自动生效 |
| `src/agent/config.py` | `DISABLED_SKILLS` 是否保留禁用 `memory` skill（见 §6 待确认） |
| DB | drop 旧 `ag_session`/`ag_message`，重建 |

## 6. 待确认事项（实施前）

1. **同步→异步桥接方案**（§4.3）：方案 1（专用 DB 线程+独立循环）vs 方案 2（同步 psycopg 直连）。倾向方案 1。
2. **框架内置 memory skill**（`DISABLED_SKILLS` 含 `memory`）：本次是否恢复启用？该 skill 是让模型 grep `history.jsonl` 长期记忆文件的指令，与 Qdrant 召回职责不同，可独立决策。倾向保持禁用（避免与 hook 召回重复）。
3. **多 Worker 并发**：PG 后端天然支持多 worker 共享会话；但 `_cache` 是进程内缓存，多 worker 下需考虑缓存一致性（同一 session_key 是否会被多 worker 同时处理）。当前 `session_key` 按标的隔离 + 单 worker 部署，暂无冲突；多 worker 部署前需评估。

## 7. 验证方案（实施后）

真正的 Agent 端到端验证（弥补上一轮缺口），需同时运行 **API(8096) + MCP(8097) + Agent Worker(python -m agent) + Redis + LLM**：

1. `POST /agent/sessions` 建会话 → `POST /agent/sessions/{id}/messages`（带 `context.stock_symbol`）提交投研问题 → SSE 订阅 `/agent/runs/{run_id}/stream`。
2. 验证 Agent 正确产出结论，且**未**调用 `list_sessions`/`get_session_history`/`search_research_memory` 工具（这些已删除）。
3. 验证会话自动落盘 PG（查 `ag_message` 有本轮 user+assistant 记录，`payload` 含完整字段）。
4. 二次追问同一 session_key，验证框架自动加载历史上下文（Agent 能引用上一轮内容）。
5. 验证 `MemoryRecallHook` 在 before_iteration 注入了 Qdrant 经验（日志可见），对话结束后 Qdrant point 增加。
6. 论点卡 MCP 工具链路回归测试（save/get/stale 仍正常）。
