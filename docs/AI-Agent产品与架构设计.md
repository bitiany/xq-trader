# xqtrader 量化平台 AI Agent 产品与架构设计

> 版本：v1.0  
> 日期：2026-05-20  
> 状态：架构设计草案  
> 适用范围：xqtrader 量化交易平台 AI Agent 子系统

---

## 1. 文档概述

### 1.1 目的

本文档从**产品视角**与**架构视角**出发，为 xqtrader 量化交易平台设计一套可落地、可演进、可审计的 AI Agent 方案。文档覆盖技术路径选型、进程部署模型、核心能力边界、安全治理，以及在「规则化量化流程」与「开放式 Agent 推理」之间的编排策略。

### 1.2 读者

| 角色 | 关注重点 |
|------|----------|
| 产品负责人 | 能力边界、人机协作、合规与用户体验 |
| 架构师 | 进程模型、技术选型、集成方式 |
| 后端/平台工程师 | API 契约、Tool Gateway、审计与权限 |
| 量化研究员 | Skills/工作流、因子/回测/数据接入 |
| 安全/合规 | 权限隔离、审批链、OS 级风险 |

### 1.3 设计原则

1. **确定性优先**：因子计算、回测、风控、下单等核心链路必须可复现、可审计。
2. **Agent 辅助而非替代**：Agent 负责理解意图、编排调用、解释结果；关键决策保留人类授权。
3. **最小权限**：Agent 不直接持有 OS 高级权限或交易柜台直连能力，通过受控 Tool Gateway 访问平台能力。
4. **分层编排**：高风险/高确定性任务走工作流；开放探索型任务走 Agent Loop。
5. **与平台解耦**：Agent 运行时独立于 API 主进程，通过标准协议集成。

---

## 2. 背景与平台上下文

### 2.1 xqtrader 平台特征

根据当前代码库结构，xqtrader 是一个以 **FastAPI + SQLAlchemy DAL + WebSocket 推送** 为核心的量化 API 服务平台：

- **数据层**：PostgreSQL/TimescaleDB，ORM 封装于 `framework/dal`
- **服务层**：REST API（`/v1/`、`/api/v1/`）、WebSocket 多 topic 订阅
- **中间件**：认证、日志、异常处理、统一响应格式
- **业务特征**：因子、指标、策略、回测、行情/财务数据等**强规则、强流程**能力

这与通用 Copilot 类产品不同——量化平台的价值在于**可复现的计算结果**与**可监管的交易行为**，Agent 必须建立在这一约束之上。

### 2.2 为什么需要 Agent

| 用户痛点 | Agent 价值 |
|----------|------------|
| 多系统、多 API、多数据源 | 自然语言统一入口，自动选择工具与参数 |
| 投研报告、舆情、宏观分析 | 多步检索、交叉验证、结构化输出 |
| 策略开发门槛高 | 引导式回测、参数解释、结果解读 |
| 复杂查询（因子/持仓/绩效） | Text-to-SQL / 语义检索降低使用成本 |
| 交易决策需上下文 | 聚合信号、持仓、风控规则后给出建议 |

Agent **不是**替代现有量化引擎，而是**编排层 + 解释层 + 交互层**。

---

## 3. 业界成熟实践参考

### 3.1 机构与平台产品模式

| 参考对象 | 模式 | 对 xqtrader 的启示 |
|----------|------|---------------------|
| **Bloomberg Terminal + AI** | 终端内嵌 AI，只读查询为主，交易走既有通道 | Agent 应嵌入工作流，而非另起交易通道 |
| **TradingAgents（Columbia/NYU 等）** | 多角色 Agent：基本面/情绪/技术/多空辩论/风控/交易员 | 投研场景适合多 Agent 分工，但需统一 Orchestrator |
| **QuantAgent** | 价格驱动多 Agent（指标/形态/趋势/风控），面向短周期 | 技术指标类任务应用**专用 Tool** 而非纯 LLM 推理 |
| **FinAgent Orchestration** | Planner + Alpha/Risk/Portfolio/Backtest/Execution/Audit/Memory | 与量化平台模块一一映射，强调 Audit Agent |
| **OpenClaw / ClawHub** | 自托管、Skills 生态、多 Agent、Human-in-the-loop 下单 | 与 nanobot Skills 模式高度同构，适合作为能力扩展参考 |
| **LangGraph Stockbroker Demo** | 有状态工作流 + `interrupt_before` 人工审批 | 下单/调仓等高风险动作的标准范式 |
| **HDGE 等 Quant OS** | 可视化工作流 + AI 编排 + 回测到实盘闭环 | 平台侧保留 Workflow Engine，Agent 负责「生成/触发/解释」 |

**共性结论**：

- 生产级量化 Agent **几乎没有**「完全自由规划 + 全自动下单」的成熟产品。
- 成熟方案均为 **「编排引擎（Workflow/Graph）+ 专用 Agent（Research/Copilot）+ 审批网关（Human-in-the-loop）」** 三层结构。

---

## 4. 技术路径选型分析

### 4.1 选型维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 与 xqtrader 集成成本 | 高 | 能否通过 HTTP/MCP/Tool 接入现有 API |
| 确定性/可审计性 | 高 | 金融场景必备 |
| 运维复杂度 | 中 | 团队规模与基础设施 |
| 扩展性（Skills/Tools） | 高 | 因子/策略/数据源持续扩展 |
| 多 Agent/工作流支持 | 中 | 投研多角色 vs 交易单链路 |
| 社区与生态 | 中 | OpenClaw Skills、LangGraph 生态等 |

### 4.2 OpenClaw

**定位**：开源、自托管的通用 AI Agent 平台，强调 Skills 市场（ClawHub）与多 Agent 协作，在 2025–2026 年大量用于交易/投研场景的实践验证。

**架构特点**：

```
Channel (Telegram/CLI/Web)
    → Message Bus
    → Agent Loop (LLM + Tools)
    → Skills (社区/自定义)
    → Execution Layer (broker/exchange API)
```

**优势**：

- Skills 生态成熟，金融类 Skill 已有数百个，可借鉴产品设计
- 多 Agent 角色划分（Research / Risk / Execution）与业界 TradingAgents 一致
- 强调生产配置：密钥分离、限流、人工审批、结构化日志
- 自托管，数据不出域

**劣势**：

- 框架较重，引入完整 OpenClaw 栈与 xqtrader 技术栈（Python FastAPI）存在重复建设
- 对「因子/回测/时序数据库」等深度集成需大量自定义 Skill
- 版本迭代快，生产依赖需严格 pin 版本

**适用场景**：需要快速搭建**多渠道触达**（IM/邮件/CLI）的投研 Copilot；或希望直接复用 ClawHub 金融 Skills 的原型验证。

**xqtrader 建议**：**借鉴其 Skills 规范、Human-in-the-loop 交易流程与多 Agent 角色划分**，不建议整体替换为 OpenClaw 运行时；可将 xqtrader Tool 以 OpenClaw Skill 兼容格式暴露，便于生态复用。

---

### 4.3 Nanobot

**定位**：港大 HKUDS 出品的**超轻量** Agent 框架（核心约 4,000 行），事件驱动四层架构：Channel → Message Bus → Agent Loop → Tool Registry。

**架构特点**：

```
InboundMessage → AgentLoop
    → ContextBuilder (AGENTS.md + Skills + Memory)
    → LLM (Provider 抽象: DashScope/OpenAI/Anthropic/...)
    → ToolRegistry (web_search / exec / file / MCP / custom)
    → OutboundMessage
```

**优势**：

- **代码量小、可读性高**，便于在 xqtrader 团队内二次开发与安全审计
- **Skills 渐进式加载**（`AGENTS.md` 常驻 + `skills/*/SKILL.md` 按需加载），与 Cursor Agent Skills 理念一致
- 已在本仓库 `example/` 中落地验证（见第 5 节）
- 支持 Hook、自定义 Tool、Session/Memory
- Provider 可插拔，可对接通义、DeepSeek 等国内模型

**劣势**：

- 无内置**有状态工作流引擎**（无原生 Graph/Checkpoint）
- `exec` 工具默认具备 shell 能力，生产需额外沙箱封装
- 多 Agent 协作需自行实现 Subagent Manager 模式
- 社区规模小于 LangChain/LangGraph

**适用场景**：

- 平台内 **Copilot / 投研助手 / Text-to-SQL / 报告生成**
- 作为 **Agent Runtime 内核**，外层由 xqtrader 提供 Workflow 与 Tool Gateway

**xqtrader 建议**：**首选 Nanobot 作为 Agent Runtime 内核**。理由：已有示例、轻量可控、Skills 模型与量化「能力包」天然契合。

---

### 4.4 DeepAgent（双轨概念，需区分）

业界存在两个不同的 「DeepAgent」：

#### A. LangChain `deepagents`（langchain-ai/deepagents）

**定位**：基于 LangGraph 的「 batteries-included 」Agent 框架。

**核心能力**：

- `write_todos` 显式规划
- 文件系统 Tool（read/write/edit/grep）
- `execute` shell（可沙箱）
- `task` 子 Agent 委派
- 输出编译为 **LangGraph Graph**，支持 Studio、Checkpointer、流式

**优势**：规划 + 子 Agent + 持久化上下文一体化；与 LangGraph 生态无缝；适合 Deep Research 类任务。

**劣势**：依赖 LangChain 栈，包体积与抽象层较多；团队若不熟悉 LangGraph，学习曲线陡峭。

#### B. RUC-NLPIR DeepAgent（学术研究）

**定位**：WWW 2026 论文框架，强调 Autonomous Memory Folding、ToolPO 强化学习、大规模 Tool 集。

**优势**：长程交互、工具发现理论先进。

**劣势**：偏研究原型，生产落地资料少，不建议作为 xqtrader 首选运行时。

**xqtrader 建议**：

- 产品化路径采用 **LangChain deepagents 的设计模式**（规划、子 Agent、文件持久化），但**不必整体引入**；可在 Nanobot 上实现 `think_tool`、子任务委派等轻量等价物（`example/CASE-nanobot使用/deep-research` 已演示 `ThinkTool`）。
- RUC DeepAgent 可作为**长期算法研究**参考，非近期工程选型。

---

### 4.5 LangGraph 工作流

**定位**：LangChain 出品的**有状态 Agent/Workflow 编排**框架，以 Graph 节点 + 边 + Checkpoint 为核心。

**架构特点**：

```
StateGraph
    → Nodes (fetch_data / analyze / backtest / prepare_order / ...)
    → Conditional Edges
    → interrupt_before (human approval)
    → Checkpointer (PostgreSQL/Redis)
    → Resume
```

**优势**：

- **确定性流程**表达力强：适合回测流水线、合规审批、ETL
- 原生 **Human-in-the-loop**（`interrupt_before`）
- 状态持久化、可恢复、可审计——金融场景关键
- 与 FastAPI 集成成熟，可独立部署为 Workflow Service

**劣势**：

- 每个新流程需开发 Graph，灵活性低于纯 Agent Loop
- 自然语言入口需额外 Router 节点判断走哪条 Graph
- 单独使用对「开放问答」体验不佳

**适用场景**：

- 策略回测标准流程
- 因子计算 + 校验 + 入库
- 下单前风控检查链
- 定时研报生成流水线

**xqtrader 建议**：**LangGraph（或自研轻量 Workflow Engine）作为「确定性编排层」**；与 Nanobot Agent Loop **并存**，由 Intent Router 分流。

---

### 4.6 选型对比矩阵

| 能力 | OpenClaw | Nanobot | deepagents | LangGraph |
|------|----------|---------|------------|-----------|
| 代码可控/可审计 | 中 | **高** | 中 | 中高 |
| Skills/Tools 扩展 | **高** | **高** | 高 | 中（需编码节点） |
| 开放对话/投研 | 高 | **高** | **高** | 低 |
| 确定性工作流 | 中 | 低 | 中 | **高** |
| Human-in-the-loop | 高 | 中（需自建） | 中 | **高** |
| 多 Agent | **高** | 中 | **高** | 高 |
| 与 xqtrader 现有示例 | 无 | **已有** | 部分对标 | 无 |
| 生产运维成本 | 中高 | **低** | 中 | 中 |

### 4.7 推荐技术组合（结论）

```
┌─────────────────────────────────────────────────────────────┐
│                    xqtrader AI Agent 栈                      │
├─────────────────────────────────────────────────────────────┤
│  交互层    │ Web UI / WS / CLI / 企业 IM（可选）              │
├─────────────────────────────────────────────────────────────┤
│  路由层    │ Intent Router（NLU + 规则 + 风险分级）           │
├──────────────────────────┬──────────────────────────────────┤
│  探索型 Agent Runtime    │  确定型 Workflow Engine           │
│  Nanobot AgentLoop       │  LangGraph / 自研 DAG Engine      │
│  + Skills + Custom Tools │  + Checkpoint + Approval Gate      │
├──────────────────────────┴──────────────────────────────────┤
│  Tool Gateway（统一鉴权、限流、审计、参数校验）                │
├─────────────────────────────────────────────────────────────┤
│  xqtrader Platform APIs（因子/数据/回测/交易/用户/审计）       │
└─────────────────────────────────────────────────────────────┘
```

**设计参考来源**：

- OpenClaw → Skills 生态、多 Agent 角色、审批式交易
- Nanobot → 轻量 Runtime、本项目已验证
- deepagents → 规划/子 Agent/Deep Research 模式
- LangGraph → 回测/下单/因子流水线、Checkpoint 与审批

---

## 5. 本项目 Nanobot 示例分析

仓库 `example/` 已提供两类 Nanobot 参考实现，是 xqtrader Agent 方案的**直接起点**。

### 5.1 CASE-AI量化助手（Charles 投研情报官）

**路径**：`example/CASE-AI量化助手（nanobot）/`

**架构要点**：

| 组件 | 作用 |
|------|------|
| `AGENTS.md` | 核心身份、方法论、全局规则（始终注入 Context） |
| `skills/*/SKILL.md` | 领域技能按需加载（渐进式披露） |
| `skills/*/scripts/*.py` | 确定性计算脚本，由 `exec` Tool 调用 |
| `config.json` | 模型、Provider、Tool 开关、迭代上限 |
| `agent.py` | 构建 `AgentLoop` + `Nanobot`，支持交互/单次模式 |
| `memory/MEMORY.md` | 跨会话上下文（如当前日期） |

**已覆盖技能域**：

- `investment-research`：五步法投研
- `sentiment-analysis`：舆情、恐慌指数、Polymarket
- `strategy-backtest`：MACD/双均线回测
- `trade-order`：miniQMT 查询/下单（**人类授权**）
- `write-report`：研报生成
- `financial-analysis` / `read-pdf` / `web-search` 等

**关键设计模式（应继承到平台）**：

1. **AI 建议，人类授权执行**（`AGENTS.md` + `trade-order/SKILL.md` 双重约束）
2. **先回测/查持仓，再给建议**（Tool 调用顺序写死在 Skill 流程中）
3. **脚本返回 JSON，Agent 负责解读**（计算与推理解耦）
4. **temperature=0.1**（投研/交易场景低随机性）

**当前局限（平台化需改造）**：

- 脚本直连 miniQMT / 本地文件，未走 xqtrader API
- `exec` 开启且 `restrict_to_workspace=false`，OS 权限过大
- 无统一审计、无多租户、无 RBAC
- 会话存储为本地 jsonl，未接入平台数据库

### 5.2 CASE-nanobot使用（通用模式库）

| 案例 | 路径 | 借鉴点 |
|------|------|--------|
| Deep Research | `example/CASE-nanobot使用/deep-research/` | 自定义 `ThinkTool`，对标 deepagents 反思循环 |
| Text-to-SQL | `example/CASE-nanobot使用/text-to-sql/` | 只读 SQL、`query_db` 替代 `exec` |
| Content Builder | `example/CASE-nanobot使用/content-builder/` | 品牌声线、结构化内容 Skill |

**Text-to-SQL 案例的安全示范**：

```markdown
# SQL Query Agent 规则（摘自 AGENTS.md）
- 使用 query_db tool 执行 SQL；NEVER 使用 exec
- 仅允许 SELECT（只读）
```

这应成为 xqtrader 所有数据访问类 Tool 的**默认安全模板**。

### 5.3 从示例到平台的映射

| 示例实现 | 平台化目标 |
|----------|------------|
| `exec python skills/.../run_backtest.py` | `POST /v1/backtest/run` Tool |
| `exec python .../query_account.py` | `GET /v1/trading/account` Tool |
| `exec python .../place_order.py` | `POST /v1/trading/orders` + **Approval Workflow** |
| 本地 PDF RAG 脚本 | `POST /v1/research/rag/query` Tool |
| `web_search` | 平台统一外部检索 Gateway（配额+审计） |
| 本地 `sessions/*.jsonl` | `agent_sessions` 表 + 对象存储 |

---

## 6. 进程架构：集成 vs 独立

### 6.1 方案对比

| 方案 | 描述 | 优点 | 缺点 |
|------|------|------|------|
| **A. 同进程集成** | Agent Loop 运行在 FastAPI 进程内（同 uvicorn worker） | 部署简单、无网络 hop | LLM 长耗时阻塞 worker；`exec` 与 API 共享 OS 用户；故障域不隔离；难以独立扩缩容 |
| **B. 同机异进程** | `xqtrader-api` + `xqtrader-agent` 两进程，localhost 通信 | 隔离较好、可独立重启 Agent | 仍共享 OS 用户时需额外沙箱 |
| **C. 独立服务（推荐）** | Agent Service 独立部署，通过 HTTP/MCP/消息队列调用 Platform API | 安全域清晰、弹性伸缩、技术栈可独立升级 | 运维组件+1、需设计服务间认证 |

### 6.2 推荐结论：**独立进程/独立服务**

**核心理由**：

1. **安全隔离**：Agent 需要 LLM、可能调用 `exec`/文件/Web；API 服务连接数据库与交易接口，攻击面必须分离。
2. **性能隔离**：LLM 单次推理 5–60s，Tool 多轮迭代可达分钟级；不应占用 API Worker 线程池。
3. **弹性伸缩**：投研高峰（开盘前报告）与 API 查询高峰时段不同，独立 HPA 更经济。
4. **发布节奏**：Agent Prompt/Skills 迭代频繁，与核心 API 发版解耦。
5. **合规审计**：Agent 服务可单独配置日志保留、数据脱敏、模型路由策略。

### 6.3 目标部署架构

```
                    ┌──────────────────┐
  用户/前端 ────────►│  xqtrader-api    │  REST / WS / 认证
                    │  (FastAPI)       │
                    └────────┬─────────┘
                             │ 内部 JWT / mTLS
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ Agent      │  │ Workflow   │  │ Tool       │
     │ Service    │  │ Service    │  │ Gateway    │
     │ (Nanobot)  │  │ (LangGraph)│  │            │
     └─────┬──────┘  └─────┬──────┘  └─────┬──────┘
           │               │               │
           └───────────────┴───────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     ┌────────────────┐       ┌────────────────┐
     │ PostgreSQL     │       │ Redis / Queue  │
     │ (业务+审计)     │       │ (会话/任务)     │
     └────────────────┘       └────────────────┘
```

### 6.4 集成协议建议

| 链路 | 协议 | 说明 |
|------|------|------|
| 前端 → API | HTTPS + WS | 用户认证在 API 层完成 |
| API → Agent | gRPC/HTTP + SSE | 流式返回 Agent 思考/Tool 事件 |
| Agent → Platform | **MCP 或 OpenAPI Tool** | 统一 Tool Schema，禁止 Agent 直连 DB |
| Workflow → Platform | 内部 Service Account | 高权限操作仍过 Tool Gateway |
| Agent 异步任务 | Redis Stream / Celery | 长时回测、批量研报 |

### 6.5 同进程集成的唯一例外

以下能力可考虑在 API 进程内以**极薄代理**形式存在（不含 LLM Loop）：

- WebSocket 转发 Agent 流式事件
- 会话 ID 与用户身份绑定
- 审批按钮回调 API（Human-in-the-loop UI）

**LLM 推理与 Tool 执行本身不应进入 API 进程。**

---

## 7. 产品设计：Agent 核心能力与职责

### 7.1 Agent 角色定义

建议采用 **「1 个 Orchestrator + N 个领域 Skill 包 + M 个 Workflow」** 模型，而非无限自由的「超级 Agent」。

| 角色 | 职责 | 是否允许自动执行 |
|------|------|------------------|
| **Copilot Orchestrator** | 理解意图、选择 Skill/Workflow、汇总输出 | 只读类可自动 |
| **Research Agent** | 投研、舆情、宏观、报告 | 可自动（外部检索+内部 RAG） |
| **Data Agent** | Text-to-SQL、因子/指标查询、数据解释 | 只读自动；写操作禁止 |
| **Strategy Agent** | 策略解释、参数建议、回测触发 | 回测可自动；参数修改需确认 |
| **Risk Advisor** | 解读风控规则、暴露度告警 | 只读自动 |
| **Execution Advisor** | 生成下单建议 | **永不自动下单** |
| **Audit Agent** | 记录 Tool 调用链、异常检测 | 系统自动 |

### 7.2 能力分层（产品功能地图）

```
L1 对话交互
  ├── 自然语言问答
  ├── 多轮上下文
  └── 流式 Tool 过程可视化（参考 CharlesHook）

L2 投研 intelligence
  ├── 研报/公告 RAG
  ├── 舆情与事件监控
  ├── 五步法结构化分析
  └── 报告导出（MD/HTML/PDF）

L3 量化 operations
  ├── 因子/指标语义查询
  ├── 策略回测发起与结果解读
  ├──  portfolio 分析
  └── 异常检测说明

L4 交易 assistance（强监管）
  ├── 信号 + 持仓 + 资金 → 建议方案
  ├── 用户显式授权
  ├── Workflow 风控校验
  └── 下单 → 状态跟踪 → 反馈

L5 平台 automation
  ├── 定时研报
  ├── 开盘前简报
  └── 告警归因（「为何触发风控」）
```

### 7.3 职责边界（必须写进产品规范）

**Agent 负责**：

- 意图识别与澄清
- 工具选择与参数填充
- 多源信息综合与**自然语言解释**
- 生成**建议**与**报告**
- 引导用户完成审批流程

**Agent 不负责**：

- 因子/指标的最终数值计算（必须由平台确定性服务完成）
- 风控规则的制定与绕过
- 未经审批的订单提交
- 直接访问原始数据库（必须经 Tool Gateway 封装）
- 持久化修改用户策略参数（需 Workflow + 确认）

### 7.4 与量化平台模块映射

| 平台模块 | Agent 接入方式 | 典型用户话术 |
|----------|----------------|--------------|
| 数据/catalog | `list_datasets`, `query_timeseries` Tool | 「拉取茅台近一年日线」 |
| 因子引擎 | `compute_factor`, `explain_factor` Tool | 「解释 ROE 因子本周排名变化」 |
| 指标/信号 | `get_indicator`, `scan_signals` Tool | 「哪些标的 MACD 金叉」 |
| 回测引擎 | Workflow: `backtest_pipeline` | 「回测双均线 on 513100」 |
| 组合/持仓 | 只读 Tool + RAG | 「我的行业暴露是否超限」 |
| 交易 | Workflow + Approval | 「按建议买入 200 股」 |
| 审计 | 自动写入 `agent_audit_log` | 合规查询 |

---

## 8. 安全架构与 OS 高级权限

### 8.1 威胁模型

| 威胁 | 来源 | 影响 |
|------|------|------|
| Prompt Injection | 恶意文档/网页/用户输入 | 越权 Tool 调用、数据泄露 |
| Tool Abuse | Agent 错误规划或被迫调用 | 误下单、批量查询敏感数据 |
| **OS Shell 逃逸** | `exec` 执行任意命令 | 读写服务器文件、横向移动 |
| 凭证泄露 | `.env`、API Key 进 Prompt | 账户被盗 |
| 供应链 | 第三方 Skill 脚本 | 后门 |
| LLM 幻觉 | 编造行情/财务数据 | 错误决策 |
| 拒绝服务 | 无限 Tool 循环 | 成本飙升、服务不可用 |

### 8.2 当前示例的安全风险

`example/CASE-AI量化助手（nanobot）/config.json`：

```json
"exec": { "enable": true, "timeout": 120 },
"restrict_to_workspace": false
```

这意味着 Agent 可通过 `exec` 在 workspace 外执行 shell——**仅适合本地开发/demo，禁止原样上生产**。

### 8.3 安全控制矩阵

| 控制项 | 开发/Demo | 生产 |
|--------|-----------|------|
| `exec` shell | 可开启（受限目录） | **默认关闭** |
| 脚本执行 | 本地 Python | **仅 Tool Gateway HTTP** |
| 文件读写 | workspace 内 | 对象存储 signed URL + 扫描 |
| 数据库 | 直连脚本 | **只读副本 + SQL 白名单** |
| 交易 | miniQMT 直连 | **API + 审批 Workflow** |
| 外部网络 | 全开 | 域名 allowlist +  egress 代理 |
| 模型 | 任意 | 内网路由 + 敏感字段脱敏 |

### 8.4 OS 权限原则

1. **Agent 进程 OS 用户**：专用低权限用户 `xqtrader-agent`，**禁止** root/Administrator。
2. **禁止能力**：`sudo`、驱动安装、修改系统配置、访问其他租户目录。
3. **沙箱选项**（按敏感度递进）：
   - **Level 0**：关闭 `exec`，纯 API Tool（生产默认）
   - **Level 1**：gVisor/Firecracker 微 VM 内运行用户 Python 策略代码
   - **Level 2**：独立 Worker 节点池，网络隔离，仅允许访问 Tool Gateway
4. **Secrets**：由 API/Workflow 注入短期 Token，**不进 Prompt、不进 Agent 磁盘**。
5. **用户策略代码执行**：若平台允许「AI 生成 Python 策略」，必须在**一次性沙箱**中运行，与 Agent Runtime 进程分离。

### 8.5 Human-in-the-loop 强制场景

| 操作 | 审批 |
|------|------|
| SELECT 查询 | 否 |
| 回测 | 否（资源配额限制） |
| 写库/发布因子 | 是 |
| 模拟盘下单 | 可配置 |
| **实盘下单** | **必须** |
| 批量导出敏感数据 | 是 |
| 修改风控参数 | 是 |

实现参考 LangGraph `interrupt_before` + 前端审批组件；与示例中「用户回复确认/好/授权后才 place_order」一致，但需**服务端校验**而非仅 Prompt 约束。

### 8.6 审计与合规

每次 Agent 运行必须记录：

```json
{
  "trace_id": "uuid",
  "user_id": "...",
  "session_id": "...",
  "intent": "...",
  "model": "qwen-plus",
  "tools_called": [{"name": "...", "args_hash": "...", "latency_ms": 123}],
  "workflow_id": null,
  "approval_id": null,
  "result_summary": "...",
  "risk_level": "L2",
  "timestamp": "..."
}
```

保留策略：至少 180 天；交易相关永久归档。

---

## 9. 工作流编排 vs Agent 自由规划

### 9.1 问题本质

量化平台的核心价值链：

```
数据 → 因子/指标 → 信号 → 风控 → 组合 → 执行 → 审计
```

每一步都是**高确定性、可复现、版本化**的。LLM Agent 的优势在于**非结构化任务**（理解意图、跨域综合、解释结果），劣势在于**数值不可靠、路径不可控**。

因此问题不是「二选一」，而是**分层混合**。

### 9.2 任务分类决策树

```
用户请求
    │
    ├─ 是否匹配已注册 Workflow 模板？
    │       ├─ 是 → LangGraph / DAG Engine（确定性）
    │       └─ 否 ↓
    │
    ├─ 是否仅涉及只读查询/解释？
    │       ├─ 是 → Agent Loop + 只读 Tools
    │       └─ 否 ↓
    │
    ├─ 是否涉及写操作/交易/发布？
    │       ├─ 是 → Agent 生成计划 → 挂载 Approval Workflow → 执行
    │       └─ 否 ↓
    │
    └─ 开放研究/探索 → Agent Loop（Deep Research 模式）
```

### 9.3 适合 Workflow 的场景（规则性/固定流程）

| 场景 | 原因 |
|------|------|
| 标准回测流水线 | 步骤固定：取数→清洗→跑策略→输出指标 |
| 因子每日批量计算 | 定时、幂等、失败重试 |
| 下单前风控链 | 合规要求逐步校验 |
| 数据质量检查 | 规则明确 |
| 报表定时生成 | 模板化 |

### 9.4 适合 Agent 自由规划的场景

| 场景 | 原因 |
|------|------|
| 「分析中芯国际 vs 台积电近期逻辑差」 | 开放研究，路径不可预设 |
| 「为什么今天策略回撤这么大」 | 需多 Tool 探索 |
| 「用自然语言查库」 | 意图解析灵活 |
| 「帮我写一份含舆情的季报点评」 | 多源综合 |

### 9.5 混合模式：Agent 编排 Workflow（推荐）

最佳实践是 **Agent 作为「调度员」而非「计算器」**：

```
用户: "帮我回测 MACD 并如果有金叉就建议是否买入"
    │
    ▼
Orchestrator Agent
    ├─ 调用 Workflow: backtest_pipeline(code=513100, strategy=macd)
    ├─ 解读 JSON 结果
    ├─ 调用 Tool: get_positions, get_cash
    ├─ 生成建议（不下单）
    └─ 若用户确认 → 触发 Workflow: order_with_risk_check
```

Agent 负责**理解串联**；Workflow 负责**可靠执行**。

### 9.6 与示例 Charles 的一致性

Charles 示例已隐含混合模式：

- `strategy-backtest/SKILL.md` 规定固定脚本调用顺序 → **Workflow 语义**
- `trade-order/SKILL.md` 规定「建议→授权→执行」→ **Approval Workflow**
- 开放投研则允许 Agent 自主选 Skill → **Agent Loop**

平台化时，应将 SKILL.md 中的「执行流程」**上升为可执行的 Workflow 定义**（YAML/Graph），Skill 只保留「何时使用、如何向用户解释」。

---

## 10. 目标架构详设

### 10.1 逻辑组件

```
┌─────────────────────────────────────────────────────────────┐
│ xqtrader-agent-service                                       │
│  ├─ Session Manager（DB-backed）                             │
│  ├─ Nanobot AgentLoop                                        │
│  ├─ Skills Registry（Git/DB 版本化）                          │
│  ├─ Custom Tools（HTTP/MCP Client → Tool Gateway）           │
│  ├─ Intent Router                                            │
│  └─ Event Stream（Tool 调用可视化）                          │
├─────────────────────────────────────────────────────────────┤
│ xqtrader-workflow-service                                    │
│  ├─ Graph Definitions（backtest / order / factor-batch）     │
│  ├─ Checkpointer（PostgreSQL）                               │
│  └─ Approval Gate API                                        │
├─────────────────────────────────────────────────────────────┤
│ xqtrader-tool-gateway                                        │
│  ├─ AuthZ（RBAC + 租户隔离）                                  │
│  ├─ Rate Limit / Quota                                       │
│  ├─ Parameter Schema Validation                              │
│  ├─ Response Sanitization（脱敏）                            │
│  └─ Audit Log Emitter                                        │
├─────────────────────────────────────────────────────────────┤
│ xqtrader-api（现有 FastAPI 平台）                             │
│  ├─ 业务 API                                                 │
│  ├─ Agent 会话代理 & WS 推送                                  │
│  └─ 用户/权限/租户                                           │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 Tool 设计规范

每个 Tool 必须：

1. OpenAPI/MCP Schema 定义入参出参
2. 标注 `risk_level`: L0(只读) / L1(写内部) / L2(交易) / L3(管理)
3. 标注 `idempotent`: true/false
4. 服务端强校验，**不信任 LLM 生成的 SQL/代码**

示例（回测 Tool）：

```yaml
name: run_backtest
risk_level: L0
idempotent: true
input:
  code: { type: string, pattern: '^[0-9]{6}\.(SH|SZ)$' }
  strategy: { enum: [macd, double_ma] }
  start: { type: string, format: date }
  count: { type: integer, maximum: 2000 }
output:
  $ref: '#/components/schemas/BacktestResult'
```

### 10.3 Skills 目录规范（延续 Nanobot）

```
skills/
  strategy-backtest/
    SKILL.md          # 触发条件、用户交互、调用哪个 Tool/Workflow
    schema.json       # 可选：参数说明
  trade-order/
    SKILL.md          # 强调 Human-in-the-loop
  factor-query/
    SKILL.md
  investment-research/
    SKILL.md
```

**SKILL.md 不再包含可执行 shell 命令**；改为引用 Tool/Workflow ID。

### 10.4 会话与记忆

| 类型 | 存储 | 用途 |
|------|------|------|
| 短期对话 | Redis + jsonl 归档 | 多轮上下文 |
| 用户偏好 | PostgreSQL | 风险偏好、常用标的 |
| 长期记忆 | 向量库 + 摘要 | 投研结论、用户关注列表 |
| 平台事实 | **禁止 Agent 私有记忆** | 行情/财务以 API 为准 |

---

## 11. 非功能需求

| 指标 | 目标 |
|------|------|
| Agent 首 Token 延迟 | P95 < 3s |
| 单轮 Tool 迭代上限 | 默认 30（可配置） |
| 并发会话 | 按租户配额 |
| 可用性 | Agent 服务 99.5%，不影响核心 API |
| 成本控制 | Token/Tool 配额；回测并发限制 |
| 可观测性 | trace_id 贯穿 API-Agent-Workflow |

---

## 12. 演进路线图

### Phase 0 — 示例加固（1–2 周）

- [ ] 关闭生产路径上的 `exec`，示例脚本改为调用 Mock API
- [ ] 统一 Tool JSON Schema
- [ ] 增加 `CharlesHook` 同款审计日志 Hook

### Phase 1 — Agent 独立服务 MVP（4–6 周）

- [ ] 部署 `xqtrader-agent-service`（Nanobot 内核）
- [ ] Tool Gateway 对接现有只读 API（行情、因子查询）
- [ ] Web UI / WS 流式对话
- [ ] 迁移 Charles 投研 Skills（不含实盘交易）

### Phase 2 — Workflow + 审批（6–8 周）

- [ ] LangGraph 回测标准流水线
- [ ] 下单 Approval Workflow + 前端确认
- [ ] Text-to-SQL Agent（只读从库）
- [ ] `agent_audit_log` 表与合规查询 API

### Phase 3 — 多 Agent 与自动化（8+ 周）

- [ ] Research / Risk / Execution 子 Agent 委派
- [ ] 定时研报、开盘简报
- [ ] 策略代码沙箱执行（与用户 Agent 隔离）
- [ ] 可选：OpenClaw Skill 导入工具

---

## 13. 关键决策摘要

| 决策点 | 结论 |
|--------|------|
| Agent Runtime | **Nanobot**（已有示例、轻量可控） |
| Workflow Engine | **LangGraph 或自研 DAG**（确定性流程） |
| 是否同进程 | **否，独立 Agent Service** |
| 是否允许 shell exec | **生产默认禁止** |
| 交易执行 | **Workflow + 人类审批** |
| 编排策略 | **混合：Workflow 执行 + Agent 编排/解释** |
| OpenClaw | 借鉴 Skills/多 Agent/审批，不引入全栈 |
| deepagents | 借鉴规划/反思模式，非必须引入 LangChain 全栈 |

---

## 14. 附录

### A. 参考链接

- [Nanobot Architecture](https://mintlify.com/HKUDS/nanobot/concepts/architecture)
- [LangChain deepagents](https://github.com/langchain-ai/deepagents)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [TradingAgents Paper](https://arxiv.org/abs/2412.20138)
- [OpenClaw Trading Guide](https://openclawforge.com/blog/openclaw-for-trading-complete-2026-guide-automated-trading-ai-agents/)

### B. 仓库内相关路径

| 路径 | 说明 |
|------|------|
| `example/CASE-AI量化助手（nanobot）/` | Charles 投研+回测+交易示例 |
| `example/CASE-nanobot使用/deep-research/` | Deep Research + ThinkTool |
| `example/CASE-nanobot使用/text-to-sql/` | 只读 SQL Agent 范例 |
| `framework/middleware/auth.py` | API 认证中间件（Agent 接入需启用） |
| `framework/ws/` | WebSocket 基础设施（Agent 事件推送可复用） |

### C. 术语表

| 术语 | 含义 |
|------|------|
| Skill | 领域能力包，含触发条件与 Tool/Workflow 调用指南 |
| Tool Gateway | Agent 访问平台能力的唯一受控入口 |
| Workflow | 确定性、有状态、可 Checkpoint 的多步流程 |
| Agent Loop | LLM 驱动的多轮 Tool 调用循环 |
| Human-in-the-loop | 高风险操作需人工显式批准 |

---

*本文档将随 xqtrader 平台 API 与 Agent MVP 落地持续迭代。*
