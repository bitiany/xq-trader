# xqtrader 智能体架构设计

> 版本：v3.0
> 日期：2026-07-06
> 定位：个人单机量化平台的 AI Agent 子系统最终架构
> 关联：[ai-in-trading-design.md](./ai-in-trading-design.md)

---

## 1. 设计定位

xqtrader 智能体子系统是量化平台的**编排层、解释层、交互层**，不承担因子计算、回测执行、风控判定、订单提交等确定性计算职责。

设计前提：

- 单人使用，单机部署，数据不出本地
- 确定性计算结果可复现、可审计
- Agent 辅助决策，关键写操作与交易须经人工授权

核心原则：

1. **确定性计算归平台服务，推理解释归 Agent**
2. **框架能力内建，业务能力外放**——会话/语义记忆是 Harness 内建能力；论点卡/行情/持仓是 MCP 业务工具
3. **慢变量与快变量分离**——基本面论点卡（PostgreSQL）与技术/情绪/资金实时取数（MCP）职责分明
4. **任务分流**——开放探索走 Agent Loop，确定性流水线走 FlowEngine

---

## 2. 分层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户 / 前端                                   │
│              HTTP · WebSocket · SSE（Agent 流式事件）                  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────┐
│  API 层（薄路由）                                                     │
│  /agent/* 会话与 Run 入队    /workflow/* 工作流执行    业务 REST       │
└───────┬───────────────────────────────────────┬───────────────────────┘
        │                                       │
┌───────▼────────────────────┐     ┌────────────▼──────────────────────┐
│  Agent Harness（平台包裹层）  │     │  FlowEngine（确定性编排层）         │
│  Intent Router             │     │  JSON → LangGraph StateGraph      │
│  Hook 扩展 · 事件总线        │     │  Checkpoint · HumanInput          │
│  验证治理 · 生命周期         │     │  回测/审批/下单流水线              │
└───────┬────────────────────┘     └────────────┬──────────────────────┘
        │                                       │
┌───────▼────────────────────┐                │
│  Nanobot Runtime（框架内核）  │                │
│  AgentLoop · AgentRunner     │                │
│  ContextBuilder · spawn      │                │
│  Skills · ToolRegistry · MCP │                │
└───────┬────────────────────┘                │
        │                                       │
        └───────────────────┬───────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│  MCP Server（业务工具网关，独立进程）                                   │
│  stocks · factors · research_thesis · investor_profile · ...          │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────────┐
│  平台领域服务 + PostgreSQL / TimescaleDB / Redis / Qdrant            │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.1 四层职责边界

| 层级 | 职责 | 不属于 |
|------|------|--------|
| **Nanobot 框架** | LLM 多轮循环、Skills 加载、spawn 子 Agent、Tool 注册与执行、上下文压缩 | 业务数据存储、平台 API、审批流 |
| **Agent Harness** | 会话后端注入、语义召回 Hook、页面上下文注入、Redis 事件流、并发控制、Intent Router | 五步法逻辑、因子计算 |
| **FlowEngine** | 预定义 DAG 执行、Checkpoint 恢复、人工审批节点 | 自然语言理解、开放探索 |
| **业务 Skill + MCP** | 投研方法论、工具调用顺序、论点卡读写、结构化产出契约 | 会话管理、LLM 调度 |

---

## 3. Harness 六元模型

智能体可靠性由 Harness 决定，而非单一模型能力。平台 Harness 覆盖六元：

| 符号 | 组件 | 实现 |
|------|------|------|
| **R** | 推理基底 | Nanobot `AgentLoop` + 可配置 LLM Provider |
| **M** | 记忆存储 | PostgreSQL 会话表 + Qdrant 语义向量 |
| **C** | 上下文构造 | `ContextBuilder` + `ContextInjectHook` + `MemoryRecallHook` |
| **S** | 技能路由 | Skills 渐进加载 + `spawn` 子 Agent + MCP Tool 分组 |
| **O** | 编排循环 | Redis 队列 Worker + Intent Router + FlowEngine 触发 |
| **G** | 验证治理 | MCP `risk_level` 标注 + FlowEngine 审批节点 + Worker JSON 契约 |

---

## 4. 进程架构

| 进程 | 职责 |
|------|------|
| **xqtrader-api** | 认证、路由、参数校验、轻量只读查询、Agent Run 入队、SSE 事件转发 |
| **Agent Worker** | 消费 Redis 队列，执行 Nanobot Loop，发布 Tool/Token 事件 |
| **MCP Server** | 将平台 OpenAPI 能力转换为 MCP Tool，独立进程承载工具执行面 |
| **Celery Worker** | 因子计算、回测、FlowEngine 长任务 |
| **PostgreSQL / Redis / Qdrant** | 业务数据、会话、队列、语义向量 |

工程约定：

1. MCP 与 API 共用 `framework/dal` 领域层，禁止重复 DB 访问逻辑
2. Agent Loop 不阻塞 API；长任务走 Celery 或 FlowEngine
3. Agent 禁止直连数据库，一切业务动作经 MCP
4. 交易类 MCP 工具仅生成 `pre_order`，经 FlowEngine 审批 Gate 后执行

---

## 5. Nanobot 框架能力（内建，非 MCP）

以下为框架运行时自动提供的能力，Agent **不得**通过工具主动调用：

| 能力 | 机制 | 存储 |
|------|------|------|
| 多轮对话 | `SessionManager` 按 `session_key` 加载/落盘 | PostgreSQL（`PgSessionManager`） |
| 系统提示构造 | `ContextBuilder`：AGENTS.md + Skills + 运行时元数据 | workspace 文件 |
| Skills 渐进披露 | `read_file` 按需加载 `skills/*/SKILL.md` | workspace 文件 |
| Tool 循环 | `AgentRunner`：LLM ↔ Tool 迭代、上下文压缩 | 内存 |
| 子 Agent | `spawn` + `SubagentManager`：独立 context 与工具预算 | 内存 |
| MCP 工具挂载 | 多 SSE 端点动态注册 | MCP Server |
| Web 检索 | `web_search` / `web_fetch`（配置启用时） | 外部 API |

框架禁用的能力（生产配置）：

- `exec` shell：关闭，计算走 MCP 或 FlowEngine
- `memory` skill：关闭，语义召回由 Harness Hook 承担

---

## 6. Agent Harness 扩展（平台包裹层）

| 组件 | 文件 | 职责 |
|------|------|------|
| Runtime 工厂 | `agent/runtime.py` | 构建 `AgentLoop`、注入 `PgSessionManager`、配置 MCP 端点 |
| Worker | `agent/worker.py` | Redis 消费、并发信号量、取消检测、Hook 装配 |
| `ContextInjectHook` | `agent/hooks.py` | 首轮注入页面上下文（`stock_symbol`、`page_source`） |
| `MemoryRecallHook` | `agent/hooks.py` | 首轮 Qdrant 语义召回；对话结束自动 index |
| `ShortTermRecallHook` | `agent/hooks.py` | 近 N 交易日会话简报摘要注入（日际快变量对比） |
| `RedisEventHook` | `agent/hooks.py` | Token/Tool/Subagent 事件 → Redis Stream → SSE |
| `PgSessionManager` | `agent/session_backend.py` | 鸭子兼容 nanobot `SessionManager`，PostgreSQL 持久化 |
| Intent Router | API / Worker 入口 | 请求分类：FlowEngine / Agent Loop |

### 6.1 记忆三分法

| 记忆类型 | 归属 | 载体 | Agent 调用方式 |
|---------|------|------|---------------|
| 会话历史 | 框架能力 | PostgreSQL `ag_session` / `ag_message` | 自动注入，禁止工具调用 |
| 短期时序记忆 | Harness 能力 | 会话历史 + 交易日历 | `ShortTermRecallHook` 自动注入（近 3 交易日） |
| 语义经验 | Harness 能力 | Qdrant `research_memory` | Hook 自动召回/index，禁止工具调用 |
| 投研论点卡 | 业务能力 | PostgreSQL `ag_research_thesis` | `research_thesis` MCP 显式读写 |

语义经验定位为**模糊类比补充**，论点卡定位为**结构化权威结论**，二者不可互替。

---

## 7. FlowEngine 确定性编排

FlowEngine 基于 LangGraph，通过 `flow/*.json` 声明工作流图，参照 Dify 节点模型设计。

### 7.1 节点类型

| 类型 | 用途 |
|------|------|
| `start` / `end` | 入参声明与输出映射 |
| `tool` | 调用平台 Python Tool 类 |
| `switch` | 条件分支 |
| `parallel` | 并行 `Send` |
| `human_input` | `langgraph.interrupt()` 人工审批 |
| `subgraph` | 嵌套子工作流 |

### 7.2 适用场景

- 策略回测标准流水线
- 预订单 → 风控 → 下单执行链
- 定时研报生成流水线
- 因子计算校验入库

### 7.3 与 Agent 的关系

Intent Router 将匹配已注册 `flow_id` 的请求直接派发到 FlowEngine；Agent 在需要确定性执行时通过 MCP 工具 `run_workflow` 触发工作流，自身负责参数填充与结果解读。

---

## 8. Intent Router

用户请求进入系统后，Router 按以下决策树分流：

```
用户请求
  ├─ 匹配已注册 FlowEngine flow_id → FlowEngine 执行
  ├─ 涉及写库/交易/发布 → Agent 生成计划 → FlowEngine 审批流
  ├─ 只读查询/解释 → Agent Loop + 只读 MCP
  └─ 开放研究/探索 → Agent Loop（stock-research 等 Orchestrator Skill）
```

Router 在 API `submit_message` 层实现规则匹配，必要时辅以轻量 LLM 分类。

---

## 9. MCP 业务工具分组

MCP Server 将 OpenAPI `operation_id` 按业务域分组暴露，命名规则：`mcp_xq_<group>_xq_<operation_id>`。

| 分组 | 业务域 | 代表工具 |
|------|--------|---------|
| `stocks` | 个股研究 | overview, technical, financials, news, fund_flow |
| `factors` | 因子时序 | get_stock_factor_series |
| `strategies` | 策略规则 | list_strategies, get_rule |
| `selection` | 选股样本池 | list_universe_pools, list_selection_results |
| `positions` | 持仓盘点 | list_broker_positions, get_broker_asset |
| `indices` | 指数行情 | list_indices, get_index_kline |
| `research` | 券商研报 | list_stock_research_reports |
| `sentiment` | 舆情快照 | get_market_sentiment, get_stock_sentiment |
| **`research_thesis`** | **投研论点卡** | get_stock_thesis, save_stock_thesis, mark_thesis_stale |
| **`investor_profile`** | **投资者画像** | get_preference |
| `workflow` | 工作流触发 | run_workflow, get_workflow_status |

全局 deny：`/api/v1/agent/**`（Agent 运行时 API 不暴露为 MCP）。

每个 Tool 标注 `risk_level`：L0 只读 / L1 写内部 / L2 交易 / L3 管理。

---

## 10. Skill 体系

### 10.1 分类

| 类型 | 职责 | 示例 |
|------|------|------|
| **Orchestrator Skill** | 意图识别、业务数据读写、spawn Worker、合并结论 | stock-research, compare-analysis |
| **Worker Skill** | 单一维度专项分析，产出结构化 JSON 契约 | technical-analysis, sentiment-analysis, fund-flow |
| **独立 Skill** | 不依赖 spawn 的完整场景 | market-overview, factor-research, position-review |

### 10.2 目录规范

```
workspace/
  AGENTS.md                 # 全局身份、能力边界、框架/业务分界
  skills/
    stock-research/SKILL.md # Orchestrator：五步法 + 论点卡 + spawn
    technical-analysis/     # Worker：技术面 JSON 契约
    sentiment-analysis/     # Worker：情绪面
    fund-flow/              # Worker：资金面
    compare-analysis/       # Orchestrator（轻）：跨标的对比
    ...
```

SKILL.md 定义方法论与工具调用顺序，不含可执行 shell；工具引用 MCP operation_id。

### 10.3 spawn 编排契约

- 仅 Orchestrator Skill 使用 `spawn`
- 无依赖 Worker 并行 spawn
- Worker 必须在输出末尾附结构化 JSON 结论
- Orchestrator 交叉验证后方可纳入最终报告

---

## 11. 投研双时钟与论点卡

### 11.1 双时钟

| 时钟 | 内容 | 载体 | 刷新规则 |
|------|------|------|---------|
| 慢变量 | 五步法四差、方向、证伪条件 | `ag_research_thesis` | 事件/证伪/到期驱动 |
| 快变量 | 技术、情绪、资金、ATR、持仓 | MCP 实时取数 | 每次分析必取 |

结合点：stock-research Orchestrator 的「交叉验证」层——论点卡定方向，快变量定时点。

### 11.2 论点卡生命周期

```
get_stock_thesis
  ├─ active 且未过期 → 慢时钟引用
  ├─ 缺失 / stale / 过期 → 全量五步法 → save_stock_thesis
  └─ 快变量命中证伪条件 → mark_thesis_stale → 下次重算
```

### 11.3 论点卡数据模型

表 `ag_research_thesis`：symbol, as_of, valid_until, direction, info_gap, logic_gap, surprise_gap, catalysts, core_assumption, falsification, tracking_metrics, invalidation_rules, status。

---

## 12. 安全与治理

| 控制项 | 做法 |
|--------|------|
| 数据库访问 | 只读查询走 MCP；Agent 禁止直连 |
| 交易 | MCP 生成 pre_order → FlowEngine HumanInput 审批 → 执行流 |
| 幻觉防护 | 行情/财务数字以 MCP 返回为准；论点卡引用标注 as-of |
| 成本控制 | `max_tool_iterations` 上限；Worker 并发限制 |
| Secrets | 环境变量注入，不进 Prompt、不写 workspace |

Human-in-the-loop 强制场景：写库、发布因子、实盘下单、批量导出、修改风控参数。

---

## 13. 协议与接口

| 链路 | 协议 |
|------|------|
| 前端 → API | HTTPS + SSE |
| API → Worker | Redis 队列（`RunTask`） |
| Worker → 前端 | Redis Stream 事件 → SSE |
| Agent → 业务 | MCP SSE |
| Agent → 工作流 | MCP `run_workflow` 或 API 直接触发 |
| 论点卡 API | `GET/POST /api/v1/research-thesis/*` |
| 投资者画像 API | `GET /api/v1/investor-profile` |

### 13.1 Run 事件类型

`run_start` · `token` · `tool_start` · `tool_end` · `subagent_start` · `subagent_end` · `message` · `done` · `error`

---

## 14. 存储

| 数据 | 存储 | 访问路径 |
|------|------|---------|
| 会话元数据/消息 | PostgreSQL | Harness `PgSessionManager` |
| 投研论点卡 | PostgreSQL | MCP `research_thesis` |
| 投资者偏好 | PostgreSQL | MCP `investor_profile` |
| 语义经验向量 | Qdrant | Harness `MemoryRecallHook` |
| Run 事件 | Redis Stream | `AgentRedisBus` |
| 工作流 Checkpoint | PostgreSQL | FlowEngine `PostgresSaver` |

---

## 15. 部署单元

```
xqtrader-api          # FastAPI，含 Agent 薄 API + 业务 REST
agent-worker          # python -m agent
mcp-server            # MCP 转换器（8097）
celery-worker         # 因子/回测/FlowEngine
postgresql + redis + qdrant
```

Agent Worker 与 MCP Server 可独立重启；Skills 与 AGENTS.md 支持热加载。

---

## 附录 A：术语表

| 术语 | 含义 |
|------|------|
| Harness | 包裹 LLM 的运行时环境：记忆、上下文、编排、验证 |
| Skill | 领域能力包，含触发条件与 MCP/工作流调用指南 |
| 论点卡 | 五步法基本面慢变量结论，per-symbol 结构化存储 |
| spawn | Nanobot 子 Agent 委派，独立 context 与工具预算 |
| FlowEngine | 基于 LangGraph 的 JSON 配置工作流引擎 |
| MCP Tool | Agent 访问平台能力的受控入口 |

## 附录 B：关键路径

| 路径 | 说明 |
|------|------|
| `src/agent/` | Harness + Worker + Hooks + workspace |
| `src/framework/workflow/` | FlowEngine + FlowCompiler |
| `mcp_server.yml` | MCP 分组白名单 |
| `flow/*.json` | 工作流定义 |
| `src/xqtrader/api/v1/research_thesis/` | 论点卡 REST API |
| `src/xqtrader/api/v1/investor_profile/` | 投资者画像 REST API |

---

*本文档为智能体子系统最终架构，随 Skill 与 MCP 扩展持续迭代。*
