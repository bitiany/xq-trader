# 前端 Agent 集成重构设计：会话隔离 + 工具/子智能体高保真 UI

## 0. 背景

上一阶段完成了 Agent 记忆架构重构（会话记忆回归 nanobot 框架 + PgSessionManager + 语义召回 hook）。本设计聚焦**前端集成层**的两个问题：

1. 前端 `session_id` 与后端 `session_key` 错配，导致记忆分裂；且 Agent 层硬编码业务 session_key（分层违规）。
2. 工具调用展示偏简陋、子智能体（subagent）几乎无展示。

前端技术栈：**React 19 + Zustand 5 + Ant Design 6 + Vite 8 + react-markdown**。

---

## 1. 会话隔离重构

### 1.1 当前缺陷（根因）

**分层违规**：`src/agent/worker.py::_build_session_key` 硬编码了业务规则：

```python
stock_symbol = context.get("stock_symbol")
if stock_symbol:
    return f"stock:{stock_symbol}"          # ← Agent 层不该认识"股票"
return f"general:{session_id}" if session_id else "general"
```

Agent 是通用执行框架，**不应关注业务语义**（stock/factor/strategy…）。session_key 的构造属于业务决策，应由**业务侧（前端）主动创建并传入**。

**由此派生的记忆分裂**：前端全局单例 `AgentPanel` 是一个连续对话框，但后端 session_key 由 context 动态推导——同一 UI 对话被切成 `general:{session_id}` 和 `stock:600519.SH` 两条独立记忆，上下文互相读不到。

**陈旧上下文 bug**：`pageContext` 只在个股页设置、仅手动点 X 清除，离开个股页不清；在其它页提问会误写入 `stock:600519.SH`。

### 1.2 目标架构：session_key 由业务侧显式创建

**核心原则**：session_key 成为一等公民，由前端在创建会话时显式指定并全程携带；Agent/Worker 只做透传，不推导、不认识业务语义。

#### 后端改动

**（a）`CreateSessionRequest` 增加 `session_key`（业务侧显式传入）**

```python
class CreateSessionRequest(BaseModel):
    session_key: str | None = None   # 业务侧显式指定；None 时后端用 session_id 兜底
    title: str | None = None
    model: str | None = None
```

后端 `create_session` 把 `session_key` 存入 session meta（Redis）。若业务侧不传，则默认 `session_key = session_id`（保证唯一、可用）。

**（b）`RunTask` 携带 `session_key`，Worker 直接透传**

`submit_message` 时从 session meta 取出 `session_key` 放入 `RunTask`。Worker 改为：

```python
@staticmethod
def _build_session_key(task: RunTask) -> str:
    # 业务侧已在创建会话时决定 session_key，Agent 层仅透传，不推导业务语义
    return task.session_key or f"session:{task.session_id}"
```

**删除** `context.get("stock_symbol")` → `stock:{symbol}` 的硬编码分支。`context.stock_symbol` 仅保留作为**提示注入**（`_inject_context` 用它拼「用户正在查看 600519.SH」），以及给 `MemoryRecallHook` 传 symbol 做语义召回过滤——这两处是「提示/召回」用途，不参与记忆隔离，合理。

#### 前端改动

**（c）`AgentPanel` 是全局连续对话 → 统一用一个浏览器会话级 session_key**

- store 懒创建会话时，生成一个稳定的 `session_key`（如 `web:{uuid}`，存 localStorage 以支持刷新后延续），随 `createSession` 传给后端。
- **个股页的 `stock_symbol` 不再改变 session_key**，仅作为 `context` 提示注入（告诉 Agent「用户在看茅台」）+ 语义召回过滤。这样：
  - 前端连续对话 = 后端连续记忆（消除分裂）。
  - 个股信息通过 context 提示 + 论点卡工具获取（符合上一阶段设计）。

**（d）修复陈旧上下文**：个股页 `stock_symbol` 改为「随本条消息一次性传入」而非持久化到 `pageContext`；或在路由离开个股页时清除 `pageContext.stock_symbol`。推荐前者——context 跟随消息，不留全局状态。

### 1.3 session_key 命名约定

| 场景 | session_key | 说明 |
|---|---|---|
| Web 全局对话 | `web:{browser_uuid}` | 一个浏览器一个连续会话，存 localStorage |
| （未来）多会话 | `web:{browser_uuid}:{conv_id}` | 若将来支持多对话 tab |
| （未来）其它客户端 | `{client}:{id}` | 由各业务端自行决定 |

关键：**前缀语义由业务端定义**，Agent 层只当作不透明字符串。

---

## 2. 工具调用 & 子智能体高保真 UI

### 2.1 现状缺口

- 工具轨迹 [AgentTrace.tsx](file:///d:/ProgramData/xq-trader/web/src/components/layout/AgentTrace.tsx) 已有基础（图标/状态/折叠），但：
  - `tool_end.payload.detail`（返回摘要）前端未读，用户看不到工具产出。
  - 工具平铺，不按回合分组；无法展开看入参/出参。
- **子智能体零展示**：后端 `EventType` 无 subagent 事件；nanobot 的 spawn 在主 Agent 侧仅表现为一次普通 `tool_start/tool_end(name=spawn)`，子 Agent 内部执行（在独立上下文的 `_SubagentHook`）完全不经过 `RedisEventHook`，前端收不到。
- 消息模型贫瘠：`AgentMessage` 仅 `role + content:string`，无法承载富消息。

### 2.2 事件协议升级（后端 · UI 前提）

在 [protocol.py](file:///d:/ProgramData/xq-trader/src/xqtrader/domain/agent/protocol.py) `EventType` 新增：

```python
SUBAGENT_START = "subagent_start"   # payload: {task_id, label, task}
SUBAGENT_TOOL  = "subagent_tool"    # payload: {task_id, name, status, summary}
SUBAGENT_END   = "subagent_end"     # payload: {task_id, label, status, result_summary}
```

**桥接方案**：nanobot 的 `SubagentManager.spawn` 内部用 `_SubagentHook`（更新 `SubagentStatus`：phase/iteration/tool_events）。需要一个能把这些状态发到 Redis 的通道。两条可行路径（实施时定）：

- **路径 A（推荐）**：主 Agent 的 `RedisEventHook` 在检测到 `tool_start(name=spawn)` 时，发出 `subagent_start`；spawn 是异步后台任务，其完成通过 nanobot 的 message bus「announce」回主 Agent（`_announce_result`），主 Agent 下一轮会把子任务结论作为 injected 消息处理——可在此时机发 `subagent_end`。子 Agent 的中间 tool 事件受限于框架边界，**首版可只展示 start/end + 结论摘要**，不展开子工具明细。
- **路径 B（完整但侵入）**：monkey-patch/包装 `_SubagentHook`，把子 Agent 的 `before_execute_tools`/`after_iteration` 转发为 `subagent_tool` 事件（带 task_id）。可展示子 Agent 完整工具轨迹，但依赖框架内部结构，维护成本高。

**首版采用路径 A**：展示「子任务卡片（label + 状态 + 结论摘要）」，不展开子工具。路径 B 作为后续增强。

同时：`tool_end` 事件**透传 `detail`** 到前端（`RedisEventHook.after_iteration` 已有 detail，前端补读）。

### 2.3 前端数据模型升级

`AgentActivity` 从扁平列表 → 支持层级 + 富信息：

```ts
type ActivityKind = 'tool' | 'subagent'

interface AgentActivity {
  id: string
  kind: ActivityKind
  parentId?: string          // 工具挂到 subagent 节点时使用
  toolName: string
  label?: string             // subagent 标签
  summary?: string           // 入参摘要
  detail?: string            // 出参/结论摘要（新增，读 tool_end.detail / subagent result）
  status: 'running' | 'done' | 'error'
  args?: Record<string, unknown>  // 完整入参（展开用）
  timestamp: number
}
```

回合分组：活动块绑定到「最后一条 user 消息之后」的 turn（现有逻辑已如此），保持不变。

### 2.4 UI 组件设计（对齐 Trae/Cursor/Claude）

**（1）工具调用卡片 `ToolCard`**（增强现有 AgentTrace item）
- 折叠态：`[图标] 工具友好名 · 摘要 [状态图标]`
- 展开态：显示入参（格式化 JSON，可折叠）+ 出参摘要（`detail`）+ 耗时
- 状态：running（转圈）/ done（勾）/ error（红叉 + 错误详情）

**（2）子智能体卡片 `SubagentCard`**（新增）
- 折叠头：`🤖 子任务：技术面分析 · 运行中/已完成`
- 展开：层级缩进显示该子任务的结论摘要（路径 A）；未来展开子工具轨迹（路径 B）
- 视觉上用左侧竖线 + 缩进表达「父子层级」，类似 Trae subagent 嵌套

**（3）执行轨迹容器 `AgentTrace`（重构）**
- 按事件顺序渲染 tool / subagent 混合列表
- subagent 节点下缩进其 child tool（路径 B 时）
- 顶部汇总条：「执行 N 步（含 M 个子任务）· 运行中/已完成」
- 运行中默认展开，完成后折叠（保持现有交互）

**（4）思考态 `thinking`**：当前被忽略。可选：显示「思考中…」轻提示（低优先级）。

### 2.5 视觉规范（高保真要点）

- 复用 Antd 6 设计 token + 现有 `AgentPanel.css` 变量，暗色/亮色适配。
- 工具/子任务卡片：圆角 8px、`background: var(--fill-secondary)`、hover 微亮、状态色（running=蓝、done=绿、error=红）。
- 图标：lucide-react，工具按名映射（现有 `toolIcon`），subagent 用 `Bot`/`Workflow`。
- 层级缩进 16px + 左竖线，避免深层嵌套（首版最多 1 层 subagent）。
- 流式期间平滑高度过渡，避免跳动。

---

## 3. 影响面清单

### 后端
| 文件 | 改动 |
|---|---|
| `src/xqtrader/domain/agent/schemas.py` | `CreateSessionRequest` 加 `session_key`；`RunTask` 加 `session_key` |
| `src/xqtrader/domain/agent/service.py` | create_session 存 session_key；submit_message 透传到 RunTask |
| `src/xqtrader/domain/agent/protocol.py` | `EventType` 新增 subagent 三事件 |
| `src/agent/worker.py` | `_build_session_key` 改为透传 task.session_key（删业务硬编码） |
| `src/agent/hooks.py` | RedisEventHook 发 subagent 事件（路径 A）；tool_end 透传 detail |

### 前端
| 文件 | 改动 |
|---|---|
| `web/src/api/agent/chat.ts` | createSession 支持 session_key；事件类型补 subagent；tool_end 读 detail |
| `web/src/stores/agentStore.ts` | 生成/持久化 web session_key；AgentActivity 升级层级模型；处理 subagent 事件；stock_symbol 改随消息传入 |
| `web/src/components/layout/AgentTrace.tsx` | 重构：工具卡片可展开、subagent 卡片、层级渲染 |
| `web/src/components/layout/AgentPanel.tsx` | 移除持久化 pageContext.stock_symbol（改随消息） |
| `web/src/pages/stock/StockDetailPage.tsx` | AI 分析按钮：stock_symbol 随本条消息传入，不再 setPageContext 持久化 |
| `web/src/i18n/locales/*.json` | subagent/工具卡片新文案 |
| 新增 `web/src/components/layout/ToolCard.tsx` / `SubagentCard.tsx` | 高保真卡片组件 |

### 不在本轮范围
- 跨刷新/跨页查看历史对话（需新增前端只读 API 读 PG）——另开任务。
- 子智能体完整工具轨迹（路径 B）——首版用路径 A，后续增强。

---

## 4. 实施顺序（建议）

1. **后端 session_key 透传**（解决记忆分裂根因，改动小、收益大）
2. **前端 session_key 统一 + 陈旧上下文修复**
3. **后端 subagent 事件通道（路径 A）+ tool_end.detail 透传**
4. **前端数据模型升级 + ToolCard/SubagentCard/AgentTrace 重构**
5. 联调 + 端到端验证（需 API + MCP + Worker + Redis + LLM）

---

## 5. 待确认（实施前）

1. session_key 前缀约定：`web:{uuid}` 是否合适？是否需要支持多对话 tab（`web:{uuid}:{conv}`）？
2. subagent 事件桥接：确认首版走路径 A（只展示 start/end + 结论），不展开子工具？
3. 视觉参考：是否有指定的设计稿/品牌色，还是沿用现有 AgentPanel 风格 + Antd token？
