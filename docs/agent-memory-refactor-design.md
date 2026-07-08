# Agent 记忆子系统设计

> 版本：v2.0
> 日期：2026-07-08
> 定位：智能体记忆机制最终设计
> 关联：[agent-architecture.md](./agent-architecture.md) §6

---

## 1. 设计原则

| 机制 | 归属 | 调用方式 |
|------|------|---------|
| 会话历史 | Nanobot 框架 + `PgSessionManager` | 按 `session_key` 自动加载/落盘，禁止 MCP 工具 |
| 短期时序记忆 | Harness `ShortTermRecallHook` | 首轮自动注入近 N 交易日简报摘要 |
| 语义经验 | Harness 召回 + Worker 索引 | Hook 自动召回；run 成功后按门槛写入 Qdrant，禁止 MCP 工具 |
| 投研论点卡 | 业务 `research_thesis` MCP | Agent 显式读写，结构化权威结论 |

语义经验用于**跨标的模糊类比**；论点卡用于**per-symbol 权威慢变量**；二者不可互替。

---

## 2. 架构

```
前端 POST /agent/sessions/{id}/messages
        │ RunTask(session_key, context, trace_id)
        ▼
Agent Worker
  build_bot(): PgSessionManager + MCP 多端点
  bot.run(msg, session_key, hooks=[
    RedisEventHook,
    ContextInjectHook,      # page_source / stock_symbol 提示
    MemoryRecallHook,       # Qdrant 召回
    ShortTermRecallHook,    # 近 N 交易日简报
    RunCancelHook,
    OrchestratorToolPolicyHook,
    SpawnContractHook,
  ])
        │
        ├─ 会话自动加载/落盘 ──▶ PostgreSQL ag_session / ag_message
        ├─ 首轮语义召回 ──────▶ Qdrant (type=brief)
        └─ run COMPLETED 后 ──▶ is_indexable_brief → Qdrant index (type=brief)
```

---

## 3. 会话记忆（PostgreSQL）

### 3.1 `PgSessionManager`

位置：`src/agent/session_backend.py`。鸭子兼容 nanobot `SessionManager`，框架以同步方式调用，内部桥接异步 DAL。

| 成员 | 用途 |
|------|------|
| `get_or_create(key)` | 加载/新建 `Session` |
| `save(session)` | 每轮落盘 |
| `list_sessions()` / `read_session_file()` | 列表与只读视图 |
| `invalidate` / `delete_session` / `flush_all` | 缓存与生命周期 |

`Session` 复用 nanobot 原生 dataclass；`ag_message.payload` 完整存储 message dict（含 `tool_calls`/`timestamp` 等），按 `(session_key, seq)` 有序还原。

### 3.2 session_key 语义

`session_key` 由业务侧在 `POST /sessions` 时显式传入，存入 Redis session meta，经 `RunTask` 透传至 Worker。Agent 层不推导业务语义：

```python
return task.session_key or f"session:{task.session_id}"
```

`context.stock_symbol` 仅用于 `ContextInjectHook` 提示注入与 `MemoryRecallHook` 召回过滤，不参与记忆隔离。

---

## 4. 语义经验（Qdrant）

### 4.1 嵌入后端

`EmbeddingService` 按 `QDRANT_EMBEDDING_BACKEND` 策略化选择后端（如 TEI `bge-large-zh-v1.5`）。Worker 启动时 `EmbeddingService.validate_backend()` 校验配置；`MemoryService.ensure_payload_types()` 为历史向量补全 `type` 字段。

### 4.2 召回

`MemoryRecallHook.before_iteration`（仅首轮）：

- 检索：`search_memory(query, top_k=3, symbol, memory_types=["brief"])`
- 注入：`[经验参考（非权威事实，仅供类比）]` 系统提示
- 异常上抛 → run `FAILED`

### 4.3 索引

Worker 在 run `COMPLETED` 后执行，不在 Hook 内索引：

1. `is_indexable_brief(content)`：≥300 字且含「投研简报」或「## 交易策略」
2. 达标 → `index_memory(content, {symbol, role: assistant, type: brief})`
3. 索引失败仅记错误日志，run 状态保持 `COMPLETED`

论点卡保存时同步索引摘要向量（`type=thesis`），由 `ThesisService.save_thesis` 触发。

### 4.4 payload 类型

| type | 来源 | 用途 |
|------|------|------|
| `brief` | 投研简报结论 | 语义召回过滤 |
| `thesis` | 论点卡保存 | 语义召回（可选按 symbol 过滤） |

---

## 5. 短期时序记忆

`ShortTermRecallHook` 从 `PgSessionManager` 加载近 `AGENT_SHORT_TERM_TRADING_DAYS`（默认 3）个**交易日**的简报摘要，按半衰期 `AGENT_SHORT_TERM_DECAY_HALF_LIFE`（默认 1.5）加权注入。

定位：日际快变量对比参考。今日快变量仍以 spawn 实时取数为准；论点卡仍以 `research_thesis` MCP 为准。

---

## 6. 论点卡（业务能力）

读写经 `research_thesis` MCP，底层 `ThesisService`：

| 操作 | 行为 |
|------|------|
| `get_thesis` | 只读；active 且未过期返回 `{status: active, ...}`；过期返回 `{status: expired, ...}`；无记录返回 null |
| `save_thesis` | 旧 active → stale；新记录写入 + Qdrant 索引 |
| `mark_thesis_stale` | 证伪/事件触发失效 |
| `reconcile_all_expired` | Worker 定时批量将过期 active 标记 stale（默认 3600s） |

读路径无副作用；数据库 stale 标记由 Worker 治理任务或显式 `mark_thesis_stale` 完成。

---

## 7. MCP 边界

Agent 运行时**不暴露**会话/语义记忆 MCP 工具。`mcp_server.yml` 全局 deny `/api/v1/agent/**`。

记忆相关能力全部由 Harness Hook + Worker 后置索引承担；论点卡/投资者画像保持 MCP 显式调用。

---

## 8. 关键路径

| 路径 | 说明 |
|------|------|
| `src/agent/session_backend.py` | PgSessionManager |
| `src/agent/hooks.py` | MemoryRecallHook / ShortTermRecallHook |
| `src/agent/brief_content.py` | 简报索引门槛 |
| `src/agent/worker.py` | run 后索引 |
| `src/xqtrader/domain/agent/services/memory_service.py` | Qdrant 读写 |
| `src/xqtrader/domain/agent/services/embedding_service.py` | 嵌入策略 |
| `src/xqtrader/domain/agent/services/thesis_service.py` | 论点卡 + thesis 向量索引 |

---

*记忆子系统详细上下文见 [agent-architecture.md](./agent-architecture.md)。*
