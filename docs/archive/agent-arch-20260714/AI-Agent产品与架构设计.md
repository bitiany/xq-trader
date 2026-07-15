# xqtrader AI Agent 产品与架构设计（个人版）

> 版本：v2.0
> 日期：2026-06-26
> 状态：现行设计（取代 v1.0，原文档已归档至 `docs/archive/ai-agent-v1.0-20260520/`）
> 定位：**个人单机**量化平台的 AI Agent 子系统
> 关联：[ai-in-trading-design.md](./ai-in-trading-design.md)（AI 在交易决策流中的应用边界与 LLM 旁路设计）

---

## 0. 修订说明（相对 v1.0）

本版以「个人使用、单机部署、数据不出本地、无多租户/无合规审计」为前提，对 v1.0 的机构级方案做系统性裁剪：

| 项 | v1.0（机构级） | v2.0（个人版） |
|----|----------------|----------------|
| 工作流引擎 | LangGraph 或自研 DAG（二选一） | **FlowEngine**（自研，参考 Dify、对 LangGraph 的封装），唯一引擎，不再二选一 |
| 进程架构 | 三独立服务（Agent/Workflow/Tool Gateway）+ mTLS | **薄 API + Celery Worker + MCP 独立进程** |
| 权限 | RBAC + 多租户隔离 + Tool Gateway 鉴权限流 | 单用户，无 RBAC/租户；MCP 进程隔离即足够 |
| 沙箱 | gVisor/Firecracker 微 VM | `exec` 限定工作目录（Level 0/受限目录） |
| 审计 | 180 天保留 + 交易永久归档 + 字段脱敏 | 本地结构化日志，按需保留 |
| 表达式引擎 | — | **维持现状**（已在截面选股/回测落地），不在本文档范围 |

> 设计原则补充：**最少部署单元、最少新增技术栈、最大化复用既有 Celery 插件体系 / FlowEngine / `framework/dal`**。

---

## 1. 定位与设计原则

### 1.1 适用前提

- 单人使用，单机（或单一可信内网）部署，数据不出本地。
- 无多租户、无 RBAC、无外部合规审计要求。
- 目标是**降低使用门槛与提升投研效率**，而非构建可对外的 SaaS。

### 1.2 设计原则

1. **确定性优先**：因子计算、回测、风控、下单等核心链路必须可复现、可审计（本地）。
2. **Agent 辅助而非替代**：Agent 负责理解意图、编排调用、解释结果；关键决策（写库/交易）保留人工授权。
3. **分层编排**：高确定性任务走 FlowEngine 工作流；开放探索型任务走 Agent Loop。
4. **最小复杂度**：能用既有组件解决的，不引入新服务/新协议。

---

## 2. 平台上下文

xqtrader 是以 **FastAPI + SQLAlchemy DAL + Celery + WebSocket** 为核心的量化平台：

- **数据层**：PostgreSQL/TimescaleDB，ORM 封装于 `framework/dal`
- **服务层**：REST API（`/v1/`、`/api/v1/`）、WebSocket 多 topic 订阅、SSE 流式
- **任务层**：Celery 插件体系 + Beat 调度（因子计算、数据采集、回测等）
- **编排层**：FlowEngine（FlowCompiler + Checkpoint），决策流/执行流均基于此

量化平台的价值在于**可复现的计算结果**与**可控的交易行为**，Agent 必须建立在这一约束之上——Agent 是**编排层 + 解释层 + 交互层**，不是计算引擎。

---

## 3. 技术选型结论

> 完整的横向对比（OpenClaw / Nanobot / deepagents / LangGraph）见归档文档 v1.0 第 3–4 章，此处仅保留个人版结论。

| 组件 | 选型 | 理由 |
|------|------|------|
| Agent Runtime | **Nanobot** | 轻量（核心约 4k 行）、可读、本仓库 `example/` 已落地验证；Skills 渐进式加载与「能力包」天然契合 |
| 工作流引擎 | **FlowEngine（自研）** | 参考 Dify、对 LangGraph 的封装；已落地 FlowCompiler + Checkpoint，决策流/执行流复用，无需再引入 LangGraph |
| 规划/反思模式 | 借鉴 deepagents（`ThinkTool` 等轻量等价物） | 不引入 LangChain 全栈 |
| Skills 规范 | 借鉴 OpenClaw / Nanobot | 不引入 OpenClaw 运行时 |

**核心结论**：「**FlowEngine（确定性编排）+ Nanobot（开放 Agent Loop）+ Intent Router 分流**」三层混合，是个人版的目标形态。

---

## 4. 进程架构（核心）

### 4.1 现行架构：薄 API + Celery Worker + MCP 独立进程

```
                 ┌───────────────────────────────────────────┐
  用户/前端 ─────►│ xqtrader-api (FastAPI / uvicorn)           │
   HTTP/WS/SSE   │  薄层：认证 / 路由 / 参数校验 / WS·SSE 推送 │
                 │  ├─ import 量化领域服务（同进程，直接处理   │
                 │  │   只读 & 轻量查询）                       │
                 │  └─ 长任务 → Celery                         │
                 └───────┬───────────────────────┬───────────┘
                         │ Celery (Redis broker)  │ 同代码库复用
                         ▼                         ▼
                 ┌───────────────────┐   ┌───────────────────┐
                 │ Celery Worker(s)  │   │ MCP Server (独立)  │
                 │  因子/回测/批量    │   │  平台能力 → MCP    │
                 │  Agent Loop(LLM)   │   │  tools；供 Agent / │
                 │  FlowEngine 执行   │   │  Cursor / CLI 复用 │
                 └─────────┬─────────┘   └─────────┬─────────┘
                           │                       │
                 ┌─────────┴───────────────────────┴─────────┐
                 ▼                                            ▼
        ┌──────────────────┐                      ┌──────────────────┐
        │ PostgreSQL /      │                      │ Redis             │
        │ TimescaleDB       │                      │ (broker/result/   │
        │ (业务 + 会话)     │                      │  会话/缓存)        │
        └──────────────────┘                      └──────────────────┘
```

### 4.2 各进程职责

| 进程 | 职责 | 不做什么 |
|------|------|----------|
| **xqtrader-api** | 认证、路由、参数校验、轻量只读查询、WS/SSE 流式转发、审批回调 | 不跑 LLM Loop、不执行长任务、不执行不可信代码 |
| **Celery Worker** | 因子计算/回测/批量研报等重计算；**Agent Loop（LLM 多轮）**；FlowEngine 工作流执行 | 不直接面向用户网络入口 |
| **MCP Server（独立进程）** | 将平台能力暴露为 MCP tools，供 Agent / Cursor / CLI 复用；承载 `exec` 等工具执行面 | 不直接下单（交易类工具仅生成 pre_order，经审批） |
| **PostgreSQL / Redis** | 业务数据、Checkpoint、会话、Celery broker/result | — |

### 4.3 为何个人版采用此架构（对照 v1.0 三服务方案）

v1.0 反对「同进程」的核心理由，已被本架构以更低成本化解：

| v1.0 反对同进程的理由 | 本架构是否化解 |
|------------------------|----------------|
| LLM 长耗时阻塞 API worker | ✅ Agent Loop 在 Celery worker，API 不阻塞 |
| `exec` 与 API 共享 OS 用户/攻击面 | ✅ 工具执行落在 MCP 独立进程，可单独限权 |
| 故障域不隔离 | ✅ worker / MCP 崩溃不影响 API |
| 难以独立扩缩容 | ✅ 调 Celery concurrency / 加 worker 即可，个人单机足够 |
| Prompt/Skills 频繁发版耦合核心 API | ✅ MCP / worker 可独立重启，提示词热加载 |

> 结论：本架构达到了 v1.0 三服务方案追求的**性能隔离 + 故障隔离 + 安全隔离**目标，却**省去** Tool Gateway 独立服务、Workflow 独立服务、mTLS、RBAC/多租户、HPA、微 VM——这些对个人均为过度设计。

### 4.4 必须遵守的工程约定（防止实现漂移）

1. **MCP 取数路径单一化**：MCP server 复用同一 `framework/dal` 领域层（同代码库），**或**统一通过内部 API 取数，二选一；**禁止** MCP 与 API 各写一套 DB 访问逻辑。
2. **写/交易类工具不绕审批**：MCP 工具按 `risk_level` 标注，**L2（交易）只能生成 `pre_order`**，必须经「pre_order → 人工确认」审批流（沿用交易系统两流设计），MCP 不直接调用柜台下单。
3. **沙箱降级**：`exec` 仅限工作目录（受限目录），删除 gVisor/Firecracker 微 VM 方案。
4. **队列隔离**：Agent Loop / 回测使用独立 Celery 队列，与日频数据采集队列分开，避免长任务与定时任务互相饿死。
5. **引擎统一**：全文及代码统一使用 **FlowEngine**，不再出现「LangGraph 或自研」的二选一表述。

### 4.5 集成协议

| 链路 | 协议 | 说明 |
|------|------|------|
| 前端 → API | HTTPS + WS/SSE | 用户认证在 API 层完成；流式返回 Agent 思考/Tool 事件 |
| API → Worker | Celery（Redis broker） | 长任务异步派发；结果经 result backend 回传 |
| Agent → 平台能力 | **MCP** | 统一 Tool Schema；禁止 Agent 直连 DB |
| 交易类操作 | FlowEngine 执行流 + 审批 | 高权限操作经审批 Gate，落 `pre_order` |

---

## 5. Agent 能力与职责边界

### 5.1 角色模型（个人版精简）

采用 **「1 个 Copilot Orchestrator + N 个领域 Skill 包 + M 个 FlowEngine 工作流」**，不引入重型多 Agent 班子；Research/Risk/Execution 等以 **Skill 包**形式存在，而非独立服务化 Agent。

| 角色 | 职责 | 是否允许自动执行 |
|------|------|------------------|
| Copilot Orchestrator | 理解意图、选择 Skill/Workflow、汇总输出 | 只读类可自动 |
| Research Skill | 投研、舆情、宏观、报告 | 可自动（外部检索 + 内部 RAG） |
| Data Skill | Text-to-SQL、因子/指标查询、数据解释 | 只读自动；写操作禁止 |
| Strategy Skill | 策略解释、参数建议、回测触发 | 回测可自动；参数修改需确认 |
| Risk Skill | 解读风控规则、暴露度告警 | 只读自动 |
| Execution Skill | 生成下单建议 | **永不自动下单** |

### 5.2 能力分层

```
L1 对话交互     ── 自然语言问答 / 多轮上下文 / 流式 Tool 过程可视化
L2 投研         ── 研报·公告 RAG / 舆情监控 / 五步法分析 / 报告导出
L3 量化操作     ── 因子·指标语义查询 / 回测发起与解读 / 组合分析 / 异常归因
L4 交易辅助     ── 信号+持仓+资金 → 建议 → 用户授权 → FlowEngine 风控 → 下单跟踪
L5 自动化       ── 定时研报 / 开盘前简报 / 风控触发归因
```

### 5.3 职责边界（写进产品规范）

**Agent 负责**：意图识别与澄清、工具选择与参数填充、多源信息综合与自然语言解释、生成建议与报告、引导审批。

**Agent 不负责**：
- 因子/指标的最终数值计算（必须由平台确定性服务完成）
- 风控规则的制定与绕过
- 未经审批的订单提交
- 直接访问原始数据库（必须经 MCP Tool 封装）
- 持久化修改策略参数（需工作流 + 确认）

---

## 6. 安全（个人版）

### 6.1 裁剪原则

数据在本机、只有一个使用者，因此**删除**：RBAC/多租户隔离、Tool Gateway 鉴权限流、mTLS、gVisor/Firecracker 微 VM、字段脱敏、180 天合规保留。**保留**真正能防误操作/防失控成本的最小集。

### 6.2 保留的安全控制

| 控制项 | 个人版做法 |
|--------|------------|
| `exec` shell | 限定工作目录（受限目录）；默认仅开发开启，生产任务优先走 MCP Tool |
| 数据库访问 | 只读类走只读 SQL + 白名单（参考 Text-to-SQL 示例：仅 `SELECT`、禁用 `exec`） |
| 交易 | MCP 仅生成 `pre_order`，经 FlowEngine 审批 Gate + 人工确认 |
| Secrets | 由 API/Worker 注入短期 Token，**不进 Prompt、不写 Agent 磁盘** |
| 拒绝服务/成本 | 单轮 Tool 迭代上限（默认 30，可配置）；回测/Agent 并发限制 |
| LLM 幻觉 | 行情/财务事实以平台 API 为准，**禁止 Agent 私有记忆覆盖平台事实** |

### 6.3 Human-in-the-loop 强制场景

| 操作 | 是否需人工审批 |
|------|----------------|
| SELECT 查询 / 回测 | 否（回测受并发配额限制） |
| 写库 / 发布因子 | 是 |
| 模拟盘下单 | 可配置 |
| **实盘下单** | **必须** |
| 批量导出 / 修改风控参数 | 是 |

> 审批由 FlowEngine 执行流的审批节点 + 前端确认组件实现，**服务端强校验**，不依赖 Prompt 约束。

---

## 7. 工作流 vs Agent 自由规划

### 7.1 分层混合（非二选一）

量化核心价值链 `数据 → 因子/指标 → 信号 → 风控 → 组合 → 执行 → 审计` 每步都高确定性、可复现；LLM 擅长非结构化任务（理解意图、跨域综合、解释）。因此**确定性走 FlowEngine，开放探索走 Agent Loop**。

### 7.2 任务分流决策树

```
用户请求
  ├─ 匹配已注册 FlowEngine 工作流？ ─是→ FlowEngine（确定性执行）
  ├─ 仅只读查询/解释？             ─是→ Agent Loop + 只读 MCP Tools
  ├─ 涉及写/交易/发布？           ─是→ Agent 生成计划 → 审批工作流 → 执行
  └─ 开放研究/探索               ───→ Agent Loop（Deep Research 模式）
```

### 7.3 混合模式示例（Agent 当调度员，不当计算器）

```
用户: "回测 MACD on 513100，若金叉则建议是否买入"
  → Copilot Orchestrator
      ├─ 触发 FlowEngine 工作流: backtest_pipeline(code=513100, strategy=macd)
      ├─ 解读结果 JSON
      ├─ 调用 MCP Tool: get_positions / get_cash
      ├─ 生成建议（不下单）
      └─ 用户确认 → 触发 FlowEngine 执行流: order_with_risk_check
```

---

## 8. 落地组件与规范

### 8.1 MCP Tool 设计规范

每个 Tool 必须：

1. 以 MCP/JSON Schema 定义入参出参；
2. 标注 `risk_level`：L0(只读) / L1(写内部) / L2(交易) / L3(管理)；
3. 标注 `idempotent`：true/false；
4. **服务端强校验**，不信任 LLM 生成的 SQL/代码。

```yaml
name: run_backtest
risk_level: L0
idempotent: true
input:
  code:     { type: string, pattern: '^[0-9]{6}\.(SH|SZ|BJ)$' }
  strategy: { enum: [macd, double_ma] }
  start:    { type: string, format: date }
  count:    { type: integer, maximum: 2000 }
output:
  $ref: '#/components/schemas/BacktestResult'
```

### 8.2 Skills 目录规范（延续 Nanobot）

```
skills/
  strategy-backtest/  SKILL.md   # 触发条件、用户交互、调用哪个 Tool/Workflow
  trade-order/        SKILL.md   # 强调 Human-in-the-loop
  factor-query/       SKILL.md
  investment-research/SKILL.md
```

> SKILL.md **不含可执行 shell 命令**，改为引用 MCP Tool / FlowEngine 工作流 ID。

### 8.3 会话与记忆

| 类型 | 存储 | 用途 |
|------|------|------|
| 短期对话 | Redis（+ 可选 jsonl 归档） | 多轮上下文 |
| 用户偏好 | PostgreSQL | 风险偏好、常用标的 |
| 平台事实 | **禁止 Agent 私有记忆** | 行情/财务以平台 API 为准 |

> 向量库/长期记忆为**可选增强**，个人版默认不启用。

---

## 9. 演进路线（个人版）

| 阶段 | 目标 |
|------|------|
| **P0 示例加固** | 关闭生产路径 `exec`（或限定目录）；统一 MCP Tool Schema；接审计日志 Hook |
| **P1 Agent MVP** | Celery 中跑 Nanobot Agent Loop；MCP 对接只读 API（行情/因子）；Web/WS 流式对话；迁移投研 Skills（不含实盘） |
| **P2 工作流 + 审批** | FlowEngine 回测流水线；下单审批执行流 + 前端确认；Text-to-SQL（只读）；本地审计日志 |
| **P3 自动化** | 定时研报 / 开盘简报；策略代码受限目录沙箱执行；轻量子任务委派（ThinkTool 等价物） |

---

## 10. 关键决策摘要

| 决策点 | 结论 |
|--------|------|
| Agent Runtime | **Nanobot** |
| 工作流引擎 | **FlowEngine（自研，参考 Dify 封装 LangGraph）**，唯一引擎 |
| 进程架构 | **薄 API + Celery Worker + MCP 独立进程**（API 与量化服务同进程） |
| 是否拆三服务/mTLS/RBAC | **否**（个人版过度设计） |
| 是否允许 shell exec | 限定工作目录；生产任务优先走 MCP Tool |
| 交易执行 | FlowEngine 执行流 + 人工审批（MCP 仅生成 pre_order） |
| 表达式引擎 | 维持现状（截面选股/回测已落地），不在本文档范围 |
| 沙箱 | 受限目录（Level 0），删除微 VM |

---

## 附录

### A. 参考链接

- [Nanobot Architecture](https://mintlify.com/HKUDS/nanobot/concepts/architecture)
- [LangChain deepagents](https://github.com/langchain-ai/deepagents)
- [Dify](https://github.com/langgenius/dify)
- [TradingAgents Paper](https://arxiv.org/abs/2412.20138)

### B. 仓库内相关路径

| 路径 | 说明 |
|------|------|
| `example/CASE-AI量化助手（nanobot）/` | Charles 投研+回测+交易示例 |
| `example/CASE-nanobot使用/text-to-sql/` | 只读 SQL Agent 范例（安全模板） |
| `framework/middleware/auth.py` | API 认证中间件 |
| `framework/ws/` | WebSocket 基础设施（Agent 事件推送复用） |
| `docs/archive/ai-agent-v1.0-20260520/` | v1.0 原始（机构级）设计，含完整选型对比 |

### C. 术语表

| 术语 | 含义 |
|------|------|
| Skill | 领域能力包，含触发条件与 Tool/Workflow 调用指南 |
| MCP Tool | Agent 访问平台能力的受控入口（独立进程承载） |
| FlowEngine | 自研、有状态、可 Checkpoint 的工作流引擎（参考 Dify 封装 LangGraph） |
| Agent Loop | LLM 驱动的多轮 Tool 调用循环（运行于 Celery worker） |
| Human-in-the-loop | 高风险操作需人工显式批准 |

---

*本文档为个人版现行设计，随 MCP Tool 与 Agent MVP 落地持续迭代。机构级完整方案见归档 v1.0。*
