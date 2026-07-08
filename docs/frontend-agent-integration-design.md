# 前端 Agent 集成设计：会话隔离 + 工具/子智能体 UI

> 版本：v2.0
> 日期：2026-07-08
> 定位：前端与 Agent Harness 集成的最终设计
> 关联：[agent-architecture.md](./agent-architecture.md) §13

前端技术栈：**React 19 + Zustand 5 + Ant Design 6 + Vite 8 + react-markdown**。

---

## 1. 会话隔离

### 1.1 设计原则

`session_key` 是一等公民：由业务侧（前端）在创建会话时显式指定并全程携带；Agent/Worker 只做透传，不推导业务语义。

| 角色 | 职责 |
|------|------|
| 前端 | 生成稳定 `session_key`（如 `web:{uuid}`），`createSession` 传入；`stock_symbol` 随单条消息 `context` 传入 |
| API | `CreateSessionRequest.session_key` 存入 Redis meta；`submit_message` 透传至 `RunTask` |
| Worker | `task.session_key or f"session:{task.session_id}"` |

`context.stock_symbol` 用途：

- `ContextInjectHook`：「用户正在查看 {symbol}」提示注入
- `MemoryRecallHook`：语义召回按 symbol 过滤

不参与 `session_key` 构造，避免记忆分裂。

### 1.2 session_key 命名约定

| 场景 | session_key | 说明 |
|------|-------------|------|
| Web 全局对话 | `web:{browser_uuid}` | 存 localStorage，刷新后延续 |
| 多会话 tab | `web:{browser_uuid}:{conv_id}` | 按 tab 隔离 |
| 其它客户端 | `{client}:{id}` | 各业务端自行定义 |

前缀语义由业务端定义，Agent 层视为不透明字符串。

### 1.3 上下文传递

个股页 `stock_symbol` **随本条消息**传入 `context`，不持久化到全局 `pageContext`。离开个股页后不会携带陈旧 symbol。

---

## 2. 事件协议与后端能力

### 2.1 SSE 事件类型

`run_start` · `token` · `tool_start` · `tool_end` · `subagent_start` · `subagent_end` · `message` · `done` · `error`

事件 payload 附带 `trace_id`（请求头 `X-Trace-Id`）与 `run_id`。

| 端点 | 行为 |
|------|------|
| `GET /runs/{id}/stream` | run 不存在时 404（响应开始前预检 meta） |
| `POST /runs/{id}/cancel` | 设置取消标记，Worker `RunCancelHook` 下轮生效 |

### 2.2 子智能体事件（路径 A）

`RedisEventHook` 在检测到 `spawn` 工具时发布：

| 事件 | payload |
|------|---------|
| `subagent_start` | `task_id`, `label`, `task` |
| `subagent_end` | `task_id`, `label`, `status`, `result_summary` |

首版展示子任务卡片（label + 状态 + 结论摘要），不展开子 Agent 内部工具轨迹。`subagent_tool` 事件类型已预留，完整子工具轨迹为后续增强。

`tool_end` 事件透传 `detail`（出参/结果摘要，截断至 1000 字符）。

---

## 3. 前端数据模型

```ts
type ActivityKind = 'tool' | 'subagent'

interface AgentActivity {
  id: string
  kind: ActivityKind
  parentId?: string
  toolName: string
  label?: string
  summary?: string
  detail?: string            // tool_end.detail / subagent result_summary
  status: 'running' | 'done' | 'error'
  args?: Record<string, unknown>
  timestamp: number
}
```

回合分组：活动块绑定到「最后一条 user 消息之后」的 turn。

---

## 4. UI 组件

### 4.1 工具调用卡片 `ToolCard`

- 折叠态：`[图标] 工具友好名 · 摘要 [状态图标]`
- 展开态：入参 JSON + `detail` 出参摘要
- 状态：running / done / error

### 4.2 子智能体卡片 `SubagentCard`

- 折叠头：`子任务：{label} · 运行中/已完成`
- 展开：`result_summary` 结论摘要
- 左侧竖线 + 16px 缩进表达层级

### 4.3 执行轨迹容器 `AgentTrace`

- 按事件顺序渲染 tool / subagent 混合列表
- 顶部汇总：「执行 N 步（含 M 个子任务）· 运行中/已完成」
- 运行中默认展开，完成后折叠

### 4.4 视觉规范

- Ant Design 6 token + `AgentPanel.css` 变量，暗色/亮色适配
- 卡片：圆角 8px、`var(--fill-secondary)` 背景
- 状态色：running=蓝、done=绿、error=红
- 图标：lucide-react；subagent 用 `Bot`/`Workflow`

---

## 5. 前端实现清单

| 文件 | 职责 |
|------|------|
| `web/src/api/agent/chat.ts` | `createSession(session_key)`；SSE 事件解析含 subagent；读 `tool_end.detail` |
| `web/src/stores/agentStore.ts` | 生成/持久化 `web:{uuid}` session_key；`AgentActivity` 层级模型；subagent 事件处理 |
| `web/src/components/layout/AgentTrace.tsx` | 工具/子任务混合渲染 |
| `web/src/components/layout/ToolCard.tsx` | 工具卡片（可展开） |
| `web/src/components/layout/SubagentCard.tsx` | 子任务卡片 |
| `web/src/components/layout/AgentPanel.tsx` | `stock_symbol` 随消息传入，无全局 pageContext 持久化 |
| `web/src/pages/stock/StockDetailPage.tsx` | AI 分析：`stock_symbol` 随本条消息 context |

历史回载：`GET /agent/history?session_key=...` 从 PG 读取完整对话（含 tool_calls 轨迹）。

---

## 6. 后端已实现能力（前端对接前提）

| 能力 | 状态 |
|------|------|
| `session_key` 创建与透传 | ✅ |
| Worker 不推导业务 session_key | ✅ |
| `subagent_start` / `subagent_end` 事件 | ✅ |
| `tool_end.detail` 透传 | ✅ |
| SSE 404 预检 / cancel API | ✅ |
| `trace_id` 事件附带 | ✅ |

---

*架构全貌见 [agent-architecture.md](./agent-architecture.md)。*
