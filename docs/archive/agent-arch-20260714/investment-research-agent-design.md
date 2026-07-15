# 投研 Agent 完整方案（编排式个股投研 · 最终目标态）

> 本文为最终目标架构，不考虑任何现状、兼容、过渡、双轨。若实施，允许推倒重来。
> 部署形态：**个人量化平台、单用户本地部署**（弱化用户级/多租户设计）。
> 记忆采用本地存储（PostgreSQL + Qdrant），不使用 git 版本化。
> 运行时框架：Nanobot（Orchestrator-Worker 编排 + MCP 工具接入）。

---

## 1. 设计目标

面向 A 股个股投研的智能体，满足：

1. **国泰君安五步法**做纯基本面前瞻推演（慢变量），产出基本面方向。
2. **技术面/情绪面/资金面独立为快变量层**，每日实时重算，**不融入五步法**。
3. **能力零重复**：每类分析能力（技术面/情绪面/研报）只在一处定义，可被编排复用。
4. **双时钟解耦**：基本面结论沉淀为论点卡（慢，可缓存）；快变量每日重算；二者在「每日简报」合并层交叉。
5. **按标的记忆**：会话与结论均按 symbol 组织，会话持久化、可跨页面查看历史。
6. **结论可审计**：所有数字来自实时数据源，所有判断可溯源、可失效。

---

## 2. 总体架构

```
                         ┌─────────────────────────────┐
   用户提问 ───────────▶ │   Orchestrator（投研总控）   │
                         │  - 意图识别与任务分解        │
                         │  - 五步法基本面推演主线      │
                         │  - 调度 Worker、汇总、择时    │
                         └───┬─────────┬─────────┬──────┘
             spawn（独立 context / 独立预算）
          ┌──────────────┼─────────┼─────────┼───────────────┐
          ▼              ▼         ▼         ▼               ▼
   ┌────────────┐ ┌────────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐
   │ 技术面      │ │ 情绪面      │ │ 研报      │ │ 资金面      │ │ 持仓/账户   │
   │ Worker     │ │ Worker     │ │ Worker   │ │ Worker     │ │ Worker     │
   └─────┬──────┘ └─────┬──────┘ └────┬─────┘ └─────┬──────┘ └─────┬──────┘
         └──────────────┴─── MCP 工具（stocks/positions/research/…）┘
                                    │
                         ┌──────────┴───────────┐
                         │      记忆与存储层      │
                         │  PostgreSQL + Qdrant  │
                         └───────────────────────┘
```

- **Orchestrator**：唯一直接面向用户的主 Agent。负责意图路由、基本面推演、spawn 各 Worker、
  合并结构化结论、生成最终报告与交易策略。
- **Worker**：单一职责的专项子 Agent，拥有独立 context 与工具预算，产出**结构化结论契约**返回主控。
- **记忆层**：PostgreSQL 存结构化事实与论点卡，Qdrant 存语义向量用于模糊召回。

---

## 3. Skill 体系（职责单一、能力唯一）

| Skill | 角色 | 职责 | 触发 |
|-------|------|------|------|
| `stock-research`（原 stock-analysis） | Orchestrator | 五步法推演 + 编排 Worker + 综合判断 + 交易策略 | 个股深度分析/每日盯盘 |
| `technical-analysis` | Worker | 趋势/动量/缠论/关键位/量价/ATR | 纯技术面问题 或 被 spawn |
| `sentiment-analysis` | Worker | 新闻/公告/情绪指数/事件驱动 | 舆情问题 或 被 spawn |
| `research-report` | Worker | 卖方评级/一致预期/目标价 | 研报问题 或 被 spawn |
| `fund-flow`（新拆） | Worker | 主力资金流/超大单/背离 | 资金问题 或 被 spawn |
| `position-review` | Worker | 持仓/资产/委托/成交 | 持仓问题 或 被 spawn |
| `compare-analysis` | Orchestrator（轻） | 跨标的/跨期对比，读各标的论点卡 | 对比问题 |
| `market-overview` | 独立 | 大盘/板块/情绪概览 | 大盘问题 |

**关键原则**：技术面、情绪面、资金面、研报的**工具与解读细节只在各自 Worker 内定义一次**。
Orchestrator 不写任何技术细节，只描述「何时委托哪个 Worker + 期望的结论契约」。

---

## 4. 五步法（纯基本面慢变量，不融合技术面）

五步法只做基本面前瞻推演，产出**基本面方向**与**证伪条件**，整体沉淀为论点卡（可长期缓存）。
**技术面/情绪面/资金面不进入五步法**——它们是快变量，若焊入五步法会把慢时钟污染成快时钟，
导致论点卡隔夜即脏。技术面与基本面的结合发生在 §5.3「每日简报」的合并层。

| 步骤 | 内容 | 数据/委托 |
|------|------|-----------|
| 一 信息差 | 市场未充分定价的边际信息（2-3 条） | overview+financials+news+announcements |
| 二 逻辑差 | 主流逻辑 vs 差异逻辑 + 自洽性检验 | + valuation |
| 三 超预期差 | 一致预期 vs 差异推演 | financials + valuation + research Worker |
| 四 催化剂 | 事件清单 + 时间轴 | news/announcements（+web_search） |
| 五 结论 | 基本面方向（关注/观望/谨慎）+ 核心假设 + **证伪条件** + 跟踪指标 | 上述全部 |

> 第五步产出的「证伪条件」同时是论点卡的失效判据（见 §5.2）——这是五步法与双时钟的接合点。

### 4.1 慢变量与快变量的边界

| 层 | 内容 | 时钟 | 归属 |
|----|------|------|------|
| 慢变量 | 五步法四差 + 基本面方向 + 证伪条件 | 事件/证伪/到期驱动 | 论点卡（Postgres） |
| 快变量 | 技术面、情绪面、资金面、ATR、持仓 | 每日实时 | Worker 临时产物，用完即弃 |

**结合点唯一**：每日简报的 Orchestrator 合并层——用论点卡定**方向**，用快变量定**时点**。

---

## 5. 双时钟：论点卡（慢） + 每日简报（快）

### 5.1 原则

一份产物只有一个刷新时钟。**可缓存的是「判断」，不是「数字」**。
- 慢变量（沉淀为论点卡）：五步法四差、方向假设、证伪条件、跟踪指标、有效期。
- 快变量（永不缓存，每次实时取）：行情、财务、ATR、PE 分位、资金流、情绪、持仓。

### 5.2 投研论点卡（Investment Thesis）

per-symbol 的慢变量结论，持久化于 PostgreSQL（见 §7）。生命周期：

```
生成/重算 ──▶ 有效（in-window）──▶ 命中失效触发器 ──▶ stale ──▶ 重算
```

失效触发器（写入论点卡的 `invalidation_rules`）：
- **事件失效**：出现财报/重大公告 → stale。
- **证伪失效**：每日快变量命中论点卡记录的「证伪条件」→ stale。
- **时间失效**：超过 `valid_until`（财报空窗期给 N 个交易日）→ stale。

### 5.3 每日简报流程（慢/快合并层）

```
用户每日提问「X 今天怎么看」
  │
  ├─ 读论点卡（Postgres, by symbol）
  │    ├─ 有效 → 直接引用（不重跑五步法），标注 as-of → 得到【基本面方向】
  │    └─ stale/缺失 → Orchestrator 重跑五步法 → 更新论点卡 → 得到【基本面方向】
  │
  ├─ 并行 spawn：technical / sentiment / fund-flow Worker（实时快变量）→ 得到【今日时点】
  │
  └─ 交叉合并（此处是唯一的慢/快结合点）：
       基本面方向 × 今日技术/情绪/资金时点
         · 共振 → 增强信心
         · 背离 → 降级方向并标注分歧
       + 持仓 + ATR → 每日交易建议（入场/止损/目标/仓位）
```

> 交叉从五步法内部移到简报合并层：论点卡保持纯基本面、可长期缓存；技术面每日实时刷新；
> 二者只在生成当日建议时相遇。这样两个时钟互不污染。

---

## 6. 会话（Session）设计

单用户本地部署，**不引入用户维度，session 直接按标的**：

| 场景 | session_key |
|------|-------------|
| 个股分析 | `stock:{symbol}` |
| 跨标的对比 | `compare:{symbol_a}-{symbol_b}` |
| 大盘/通用 | `general` |

理由：
- **上下文纯净**：不同标的的推演历史互不污染，token 不浪费。
- **与论点卡对齐**：会话与论点卡都按 symbol 组织，跨日追问「昨天你怎么看 X」精准命中。
- 对比场景不依赖会话历史，而由 Orchestrator 直接读各标的论点卡（跨会话可读）聚合。

### 6.1 会话持久化与历史查看

会话须持久化，支撑「用户在不同页面切换、随时查看某标的的历史问答」：

- **存储**：会话与消息落 PostgreSQL（`agent_session` / `agent_message`，见 §7.2），
  而非仅内存或临时文件——保证跨页面、跨重启可读。
- **按标的检索**：前端进入某标的页面时，用 `session_key = stock:{symbol}` 拉取该标的全部历史消息，
  按时间顺序渲染问答流。
- **会话列表**：提供「历史会话列表」视图，列出所有 `stock:*` 会话及其最近更新时间/预览，
  供用户在页面间跳转查看。
- **上下文预算**：注入 LLM 的是近期消息窗口；超预算的旧消息自动摘要归档（摘要同样持久化），
  但**完整历史始终保留在 DB 供查看**，查看历史不受上下文窗口限制。

---

## 7. 记忆与存储层（PostgreSQL + Qdrant，本地）

### 7.1 记忆分层与载体

| 记忆类型 | 时钟 | 载体 | 检索方式 |
|---------|------|------|---------|
| 平台事实（行情/财务/资金/持仓） | 实时 | 不落记忆，实时 MCP | — |
| 投研论点卡（per-symbol 慢结论） | 慢（事件/证伪/到期失效） | **PostgreSQL** | 主键/条件精确查询 |
| 偏好设置（风险偏好/自选/交易风格） | 慢 | **PostgreSQL（单行全局配置）** | 直接读取 |
| 会话短期历史 | 每轮 | **PostgreSQL 会话表** | by session_key |
| 经验/语义记忆（跨标的类比、历史形态相似） | 慢 | **Qdrant 向量** | 语义相似度召回 |

> 单用户本地部署，不存在多用户画像，偏好退化为**全局单行配置**。

> 明确取舍：**结构化结论（论点卡）走 Postgres，不走向量库**——投研要求「结论可审计、可精确溯源」，
> 语义召回的不确定性不适合承载核心判断。**Qdrant 只承担「模糊经验召回」补充层**，
> 例如把每次成稿的论点卡/简报摘要向量化入库，供未来「我上次遇到类似高位放量是怎么判断的」这类类比检索。

### 7.2 PostgreSQL 表设计（示意）

```sql
-- 投研论点卡（慢变量核心记忆）
CREATE TABLE research_thesis (
    id             BIGSERIAL PRIMARY KEY,
    symbol         VARCHAR(16)  NOT NULL,
    as_of          DATE         NOT NULL,          -- 数据截至日
    valid_until    DATE         NOT NULL,          -- 时间失效边界
    direction      VARCHAR(8)   NOT NULL,          -- 关注/观望/谨慎
    info_gap       JSONB        NOT NULL,          -- 信息差
    logic_gap      JSONB        NOT NULL,          -- 逻辑差
    surprise_gap   JSONB        NOT NULL,          -- 超预期差
    catalysts      JSONB        NOT NULL,          -- 催化剂 + 时间轴
    core_assumption   TEXT      NOT NULL,          -- 核心假设
    falsification     JSONB     NOT NULL,          -- 证伪条件（失效判据）
    tracking_metrics  JSONB     NOT NULL,          -- 跟踪指标
    invalidation_rules JSONB    NOT NULL,          -- 事件/证伪/时间失效规则
    status         VARCHAR(8)   NOT NULL DEFAULT 'active',  -- active/stale
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_thesis_symbol_status ON research_thesis(symbol, status);

-- 偏好设置（单用户本地部署 → 全局单行配置）
CREATE TABLE agent_preference (
    id             SMALLINT PRIMARY KEY DEFAULT 1,   -- 恒为 1，全局单行
    risk_appetite  VARCHAR(16),                    -- 保守/稳健/激进
    watchlist      JSONB,                          -- 自选股
    preferences    JSONB,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 会话（持久化，支撑跨页面历史查看）
CREATE TABLE agent_session (
    session_key    VARCHAR(128) PRIMARY KEY,       -- stock:{symbol} / compare:... / general
    title          VARCHAR(128),                   -- 会话列表展示用
    metadata       JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_session_updated ON agent_session(updated_at DESC);  -- 会话列表按最近排序

-- 会话消息（完整历史，不受上下文窗口限制）
CREATE TABLE agent_message (
    id             BIGSERIAL PRIMARY KEY,
    session_key    VARCHAR(128) NOT NULL,          -- 逻辑关联 agent_session，无物理外键
    role           VARCHAR(16)  NOT NULL,
    content        TEXT,
    tool_calls     JSONB,
    is_summary     BOOLEAN      NOT NULL DEFAULT false,  -- 是否为归档摘要
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_message_session ON agent_message(session_key, id);
```

> 遵循项目 dal-orm 规范：模型继承 `Base`/`AuditedBase`，**禁止主外键物理约束**（表间仅逻辑关联，无物理外键）。

### 7.3 Qdrant 向量库（经验召回补充层）

- **连接**：`localhost:56333`（HTTP）/ `localhost:56334`（gRPC），`prefer_grpc=True`
- **嵌入服务双后端策略**（`QDRANT_EMBEDDING_BACKEND` 配置项，策略模式 + 注册表）：
  - `local`（默认）：`LocalEmbeddingBackend`，本地 SentenceTransformer 加载 `BAAI/bge-large-zh-v1.5`（本地路径 `D:\app\models\BAAI\bge-large-zh-v1.5`，1024 维，中文优化），`normalize_embeddings=True` 模型自身完成 L2 归一化
  - `tei`：`TeiEmbeddingBackend`，HTTP 调用 TEI 服务（默认 `http://127.0.0.1:6380`，`POST /embed`，TEI 不自动归一化，代码层 `_l2_normalize` 手动归一化）；Docker 部署强制使用 `tei`，避免容器内安装模型权重
  - 两种后端产出向量等价，可混用；TEI 后端运行时强制校验返回维度 == 1024
- **嵌入服务单例**：`EmbeddingService.get_instance()`，Worker 启动时 `validate_backend()` 校验后端可达
- **Collection**：`research_memory`（向量 1024 维，Cosine 距离，首次连接时自动创建）
- **写入时机**：每次论点卡定稿/每日简报生成后，将「结论摘要 + 关键判断」embedding 入库，
  payload 含 `symbol / as_of / direction / 场景标签`。
- **召回时机**：Orchestrator 推演时可选检索 top-k 相似历史判断，作为「经验参考」注入 context（明确标注为参考、非事实）。
- **定位**：辅助，不参与数字/结论的权威来源。

### 7.4 记忆读写接口（MCP 工具 + Hook 自动能力）

记忆层分两类：**结构化业务数据**通过 MCP 工具显式读写（保持「Agent 不直连 DB」的架构纪律）；**语义经验召回/索引**已演进为 Harness Hook 自动能力，**不通过 MCP 暴露**（避免 Agent 主动调用语义召回污染推理纪律）。

**MCP 工具（Agent 显式调用）**：

| 工具 | 作用 | 存储 |
|------|------|------|
| `get_stock_thesis(symbol)` | 读论点卡（含 status/as_of） | Postgres |
| `save_stock_thesis(...)` | 写/更新论点卡 | Postgres |
| `mark_thesis_stale(symbol, reason)` | 标记失效 | Postgres |
| `get_preference()` | 读全局偏好（风险偏好/自选） | Postgres |
| `list_sessions()` | 会话列表（按最近更新，供页面切换） | Postgres |
| `get_session_history(session_key)` | 读某标的完整历史问答 | Postgres |

**Harness Hook 自动能力（不暴露 MCP，Agent 禁止主动调用）**：

| 能力 | 实现位置 | 触发时机 | 关键参数 |
|------|---------|---------|---------|
| 语义召回 | `MemoryRecallHook` | 每轮 run 首轮 `before_iteration`，仅执行一次 | `top_k=3`，`memory_types=["brief"]`，按 `symbol` 可选过滤 |
| 简报索引 | `AgentWorker` 后置 | run `COMPLETED` 后，`is_indexable_brief()` 门槛达标（≥300 字且含「投研简报」或「## 交易策略」） | payload: `{symbol, role:"assistant", type:"brief"}` |
| 论点卡索引 | `ThesisService.save_thesis` | `save_thesis` 事务内同步调用 | payload: `{symbol, as_of, direction, type:"thesis"}` |

**失败处理不对称（有意为之）**：
- 召回失败（Qdrant 连接失败 / TEI 超时）→ 异常上抛 → run 标记 `FAILED`（强依赖：确保 Agent 不在缺失经验参考时盲推）
- 索引失败（写入异常）→ `except Exception` + `logger.error(exc_info=True)` → run 保持 `COMPLETED`（弱依赖：索引是附加价值，不应阻塞已成功的对话）

**架构纪律**：`mcp_server.yml` 全局 deny `/api/v1/agent/**`，从源头切断 Agent 通过 MCP 调用 agent 域 API；Qdrant 与 TEI 完全封装在 `xqtrader.domain.agent.services` 层。

> 会话读写（追加消息、拉取历史、列表）由运行时会话层直接落 Postgres；
> `list_sessions` / `get_session_history` 供前端「历史会话查看」页面调用。
>
> **演进说明**：早期设计中曾考虑将 `search_research_memory` / `index_research_memory` 暴露为 MCP 工具，实际实现已演进为 Hook + Worker 后置索引模式。详见 [agent-memory-refactor-design.md](./agent-memory-refactor-design.md) v2.0。

---

## 8. 编排执行契约

### 8.1 Worker 返回契约（结构化）

每个 Worker 必须返回结构化结论，供 Orchestrator 无歧义合并。示例（技术面 Worker）：

```json
{
  "as_of": "2026-07-01",
  "trend": {"direction": "多头排列", "level": "日线", "adx": 28},
  "key_levels": {"support": [12.30, 11.80], "resistance": [13.50]},
  "signals": {"macd": "金叉", "kdj": "高位", "rsi": 62, "td9": null},
  "chanlun": {"structure": "上涨中枢", "buy_sell_point": "二买"},
  "volume_price": "放量突破",
  "atr": {"atr_14": 0.42, "stop_distance": 0.84},
  "conclusion": "偏多，量价配合healthy，关注13.50压力"
}
```

### 8.2 Orchestrator 合并逻辑（每日简报）

1. 读论点卡 → **基本面方向**（有效则引用，stale/缺失则重跑五步法）。
2. 并行 spawn technical/sentiment/fund-flow Worker → **今日时点**。
3. **交叉验证**：方向与技术/情绪/资金共振→增强；背离→降级并标注分歧。
4. 结合持仓与 ATR → 交易策略（入场/止损/目标/仓位）。
5. 若论点卡被重算：更新论点卡 + 向量化入库；简报摘要向量化入库。

---

## 9. 数据与安全纪律

- 数值一律来自实时 MCP 工具，禁止编造，禁止用记忆覆盖实时事实。
- 记忆存「判断」，不存「数字」；论点卡引用的数字在使用时须重新校验。
- Agent 不直连数据库，一切经 MCP 工具；交易类操作只给建议，不自动执行。
- 论点卡与简报均标注 `as_of` 与有效期，过期结论显式提示。

---

## 10. 关键设计决策一览

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| 1 | 编排模式 | Orchestrator-Worker（真 spawn） | 能力零重复、context/预算隔离、职责单一 |
| 2 | 技术面归属 | **不融入五步法**，作为独立快变量 Worker，仅在每日简报合并层交叉 | 避免快变量污染慢时钟、论点卡保持可缓存 |
| 3 | 慢/快解耦 | 论点卡（慢）+ 每日简报（快） | 时效错配的根本解 |
| 4 | 会话粒度 | 直接按标的 `stock:{symbol}`，不引入用户维度 | 单用户本地部署、上下文纯净、与论点卡对齐 |
| 5 | 会话持久化 | 落 Postgres，完整历史可跨页面查看 | 不同页面问答、历史回看 |
| 6 | 结论存储 | PostgreSQL | 精确、可审计 |
| 7 | 经验召回 | Qdrant（补充层） | 模糊语义类比 |
| 8 | 记忆版本化 | 不用 git，用 DB 记录 | 本地设施已具备、结构化可查 |
| 9 | DB 访问 | 经 MCP 工具/会话层，Agent 不直连 | 架构纪律、安全 |
