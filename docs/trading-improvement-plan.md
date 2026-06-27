# 交易系统改进计划（个人版评审整改）

> **版本**: v2.0
> **更新**: 2026-06-27（v2.0 扩展：新增 I-9~I-15 问题 + P1-4/P4-1~P4-5/P5-1~P5-4 改进项 + Phase 4 机构方法论复刻 + Phase 5 文档对齐与架构整改 + 平台目标章程；v1.0 基于 2026-06-26 评审）
> **来源**: 基于对实盘/模拟盘产品设计（含交互 UI）与后端两流的专业评审，并对照 CASE-AI 量化系统示例代码与业界机构方法论
> **定位**: 把评审发现的缺口转化为**可执行、可验收**的整改计划
> **关联**: [trading-system-design.md](./trading-system-design.md)（架构与设计，含 §17 平台目标章程）、[trading-product-design.md](./trading-product-design.md)、[ai-in-trading-design.md](./ai-in-trading-design.md)

---

## 一、评审结论

当前系统骨架（**两流分离 / pre_order 交接 / HITL 审批 / 账户复用 / Kill Switch**）达到个人量化平台应有水准。但目前是**「能产生信号、能下单，却看不到成交、扛不住跳空、防不了盘中大跌」的半闭环**。

整改投入应压在 **执行时点 + 盘内监控 + 真实风控** 三处，而非继续增加页面。

### v2.0 评审扩展（2026-06-27）

对照 `CASE-AI量化系统` 示例代码与业界机构方法论（Barra / WorldQuant / Qlib / 华泰 / Brinson / BHB）后，补充两类缺口：

1. **L1 实盘安全缺口**：事前风控规则仅实现 4 条（文档夸大为 8 条），`trading_session` / `signal_ttl` / `cash_sufficient`（实盘路径）/ `t_plus_1_sell`（实盘路径）/ `max_positions` / `max_order_amount` / `daily_loss_circuit` 共 7 条待补。
2. **L2 机构方法论复刻全缺**：Brinson 归因 / Morning Brief 晨会 / 策略生命周期管理 / Walk-Forward 过拟合检验 / 分级告警路由 5 大模块均未实现，而示例代码均有落地参考。
3. **文档与代码系统性不符**：`trading-system-design.md` §7.1/§12/§8/§4.2/§6/§14 存在夸大或残留旧值，本次 v2.0 已据实修订（见 P5-1）。
4. **架构级整改**：`WatchlistDecisionWorkflowService` 约 1100 行违反单类方法数 ≤10 规则；`broker.py` Protocol 已定义未接线；决策流 sizing 未与 sizer 插件打通。

平台目标定位与三层目标定义见 [trading-system-design.md §17 平台目标章程](./trading-system-design.md#十七平台目标章程)，本计划所有任务须符合该章程。

---

## 二、问题清单与分级

| 编号 | 严重度 | 问题 | 证据（代码/文档） |
|------|--------|------|-------------------|
| I-1 | 🔴 | **跨夜执行时点风险**：盘后基于 T 日 close+ATR 定限价，T+1 跳空即失效（踏空/错价） | `SignalApprovalTab.tsx::calculateAtrLimitPrice` |
| I-2 | 🔴 | **盘内监控未实现**：下单后无实时成交回报/持仓同步，WS 无生产者，实盘闭环断裂 | `trading-system-design.md` §9（全 ⏳） |
| I-3 | 🔴 | **熔断器 UI 假象**：UI 展示「熔断器 已触发/未触发」，但后端无自动熔断（IntradayRiskMonitor 未实现） | `RiskSidePanel.tsx::circuitBreakerTriggered` |
| I-4 | 🟠 | **双轨风控口径**：`pre_order.risk_check_passed` 与 `risk_event` 并存，需 UI 写文字消歧 | `SignalApprovalTab.tsx` / `RiskSidePanel.tsx` 内说明文案 |
| I-5 | 🟠 | **审批缺组合层视图**：逐标的卡片，无组合总仓位/行业集中/现金占用/超限总览 | `SignalApprovalTab.tsx` 卡片渲染 |
| I-6 | 🟠 | **操作链偏长**：审批（信号 Tab）与下单（工作流 Tab）分两段两次填操作人，易漏下单 | `SignalApprovalTab` / `WorkflowRunTab` |
| I-7 | 🟡 | **模拟成交假设手填**：滑点审批时手选，无手续费/印花税/冲击成本模型，模拟收益不可信 | `SignalApprovalTab.tsx::buildSlippage` |
| I-8 | 🟡 | **operator 机构残留**：审批/下单/全平强制填操作人且禁 system，单用户繁琐 | 多组件 `OPERATOR_STORAGE_KEY` |
| I-9 | 🔴 | **事前风控规则缺口**：文档 §7.1 标 8 条 ✅，实际仅 4 条；`trading_session`/`signal_ttl`/`cash_sufficient`(实盘)/`t_plus_1_sell`(实盘)/`max_positions`/`max_order_amount`/`daily_loss_circuit` 7 条未实现，可能在非交易时段/陈旧信号下单 | `workflow/service.py::run_risk_gateway` 仅 4 条硬编码检查 |
| I-10 | 🟠 | **Brinson 归因缺失**：实盘复盘无行业配置/选股 alpha 分解，无法解释超额收益来源 | `domain/trading/` 无 attribution 模块 |
| I-11 | 🟠 | **Morning Brief 晨会缺失**：盘前无自动化行业轮动 + 个股短名单产出，决策流标的来源依赖人工经验 | 无 `morning_brief_flow` |
| I-12 | 🟠 | **策略生命周期管理缺失**：无孵化→纸面→试用→生产→退役状态机，Promote 无门禁依据，`promote` API 缺失 | `td_paper_session.promote_to_live` 字段有但无 API |
| I-13 | 🟡 | **Walk-Forward 过拟合检验缺失**：策略上线前无 IS/OOS ratio 检验，过拟合策略可能直接进实盘 | 无 `walk_forward` 模块 |
| I-14 | 🟡 | **分级告警路由缺失**：WebSocket SPI 框架已有但无 4 级告警路由，Kill Switch/熔断/断线等事件无统一分级推送 | `ws/spi/` 无 `AlertSpi` |
| I-15 | 🟡 | **文档与代码系统性不符**：`trading-system-design.md` §7.1/§12/§8/§4.2/§6/§14 存在夸大或残留旧值，误导实施 | 见 P5-1 已据实修订 |

> **已澄清、不列为缺陷**：截面选股 vs 自选池的「割裂」经确认为**有意的 HITL 选股设计**（截面选股 → 人工挑选 → 自选池 → 决策流），已文档化于 `trading-system-design.md` §3.6；其固有代价（回测不能直接为实盘背书）已注明。**AI/LLM 介入**作为增强方向，方案见 `ai-in-trading-design.md`，纳入本计划 Phase 3。

---

## 三、改进项详述

### P0-1　T+1 开盘重定价（对应 I-1）

- **目标**：消除跨夜跳空导致的限价失效。
- **方案要点**：执行日下单前，审批/下单界面以**实时价**重算/校验限价；提供「下单前二次价格确认」；ATR offset 改为基于 T+1 实时价或参考开盘价，而非 T 日 close。
- **涉及模块**：后端 `workflow/execution_service.py`（下单前取实时价校验）、前端 `SignalApprovalTab` / `WorkflowRunTab`（展示实时价、二次确认）。
- **验收**：跳空高/低开两种构造场景下，下单前界面显示实时价与原限价偏离提示；限价不再沿用昨夜静态值。

### P0-2　盘内监控最小闭环（对应 I-2）

- **目标**：下单后能看到成交结果与持仓变化。
- **方案要点**：实现 `OrderConfirmService`（成交回报：事件 + 30s 轮询兜底）与 `PositionSyncService`（持仓/资金同步：1~5 分钟）；接通 WS `ws.trading.orders/trades/pnl/positions` 生产端。
- **涉及模块**：后端新增 `domain/trading/`（监控服务，轻量后台任务，仅交易时段运行）、QMT 回报对接；前端 `OrderFlowTab` / `PositionPnLTab` / `CockpitDashboard` 消费实时数据。
- **验收**：实盘/模拟下单后，订单状态在界面随回报推进（submitted→partial→filled），持仓与可用资金自动刷新，无需查券商软件。

### P1-1　自动熔断 + 熔断器正名（对应 I-3）

- **目标**：消除安全假象，提供真实盘中保护。
- **方案要点**：实现 `IntradayRiskMonitor`（日内亏损阈值 → 触发熔断事件 + 可选自动 Kill Switch）；在自动熔断落地前，**先把 UI「熔断器」降级为「手动全平」入口**，避免误导。
- **涉及模块**：后端 `domain/trading/`（IntradayRiskMonitor）、风控规则 `circuit_breaker`；前端 `RiskSidePanel`（措辞/能力对齐）。
- **验收**：构造日内亏损超阈值场景，系统产生熔断事件并按配置告警/自动平仓；UI 文案与实际能力一致（有自动熔断才叫熔断）。

### P1-2　统一风控单一视图（对应 I-4）

- **目标**：去掉需要文字解释的双轨口径。
- **方案要点**：统一 `risk_check_passed`（事前预检）与 `risk_event`（账户事件）为单一风控状态模型；审批卡片与风控面板共用同一口径，删除「二者不必然矛盾」消歧文案。
- **涉及模块**：后端风控模型/`RiskGatewayTool`；前端 `SignalApprovalTab` / `RiskSidePanel`。
- **验收**：审批卡片风控状态与风控面板事件来自统一来源，无需文字解释二者关系。

### P1-3　审批组合层总览（对应 I-5）

- **目标**：让批量审批具备组合视角。
- **方案要点**：审批区顶部增加组合 summary：执行后总仓位、行业/集中度、现金占用、单票超限提示（复用 `PortfolioSignalFusionTool` 已算结果）。
- **涉及模块**：后端补 fusion 结果的组合聚合返回；前端 `SignalApprovalTab` 顶部 summary 区。
- **验收**：审批一篮子信号时可见组合总仓位与集中度/超限红线提示。

### P2-1　交易成本模型下沉（对应 I-7）

- **目标**：模拟收益可逼近真实、可作实盘预期参考。
- **方案要点**：把佣金/印花税/滑点/冲击成本下沉为**账户/实例级**配置，与回测共用同一套成本假设；模拟撮合默认套用，不再每次审批手填。
- **涉及模块**：后端 `SimulatedMatchingService` + 成本配置；与 backtest 成本模型统一；前端仓位/实例配置。
- **验收**：模拟盘成交自动套用成本模型，模拟与回测成本口径一致。

### P2-2　执行日「待下单」提醒（对应 I-6）

- **目标**：缩短操作链、防漏下单。
- **方案要点**：执行日复用 TopBar 铃铛/StatusBar 给出「已批准待下单 N 条」提醒，一键跳工作流 Tab 下单。
- **涉及模块**：前端 `TopBar` / `StatusBar` / `WorkflowRunTab`。
- **验收**：存在 approved 且未下单的预订单时，执行日界面有明确提醒入口。

### P3-1　operator 降级（对应 I-8）

- **目标**：去机构残留。
- **方案要点**：operator 改为可选、默认取上次值；保留留痕但不强制阻断。
- **涉及模块**：前端各审批/下单/全平交互。
- **验收**：单用户可不重复填写即完成操作，留痕仍记录。

### P3-2　AI/LLM 旁路增强（对应增强方向）

- **目标**：在不污染主信号前提下引入 AI 价值。
- **方案要点**：按 `ai-in-trading-design.md` 落 `llm_pre_order_review`（审批守门，P0 级）与 `llm_event_scan`（风险事件告警）。
- **涉及模块**：决策流旁路节点、审批 UI 提示挂载。
- **验收**：审批卡片出现 LLM 风险提示清单，不改信号/不自动下单；旁路失败不阻断主流。

### P1-4　事前风控规则补全（对应 I-9）

- **目标**：补全 7 条缺失的事前风控规则，杜绝非交易时段/陈旧信号/超仓位/超金额下单。
- **方案要点**：
  - `run_risk_gateway` 改为从 `RiskRule` 注册表加载规则（非硬编码），实现 `trading_session` / `signal_ttl` / `max_positions` / `max_order_amount` 4 条即时校验。
  - `cash_sufficient` / `t_plus_1_sell` 在实盘 QMT 路径补校验（模拟撮合路径已有）。
  - `daily_loss_circuit` 依赖 `IntradayRiskMonitor`（T1.5），在风控网关层读取当日已实现亏损。
- **涉及模块**：`workflow/service.py::run_risk_gateway` + `trading_validator.py` + `RiskRule` 注册表加载。
- **验收**：构造非交易时段/陈旧信号/超仓位/超金额/资金不足/T+1 超卖场景，均被风控拦截并写 `risk_event`，`td_pre_order.risk_check_passed=false`。

### P4-1　Brinson 归因（对应 I-10）

- **目标**：实盘复盘可解释超额收益来源（行业配置 vs 选股 alpha）。
- **方案要点**：见 [trading-system-design.md §18](./trading-system-design.md#十八brinson-归因⏳-待实现)。BHB 三因子公式 + 申万一级 + 沪深300等权 + sim/real/csv 三数据源。
- **涉及模块**：新增 `domain/trading/attribution/` 模块 + `td_attribution_result` 表 + API + `brinson_attribution_flow`。
- **验收**：三源均能产出 BHB 三因子归因报告；与示例代码 `attribution/brinson.py` 结果对齐。

### P4-2　Morning Brief 晨会（对应 I-11）

- **目标**：盘前自动化产出行业轮动 + 个股短名单，辅助决策流标的来源。
- **方案要点**：见 [trading-system-design.md §19](./trading-system-design.md#十九morning-brief-晨会⏳-待实现)。FlowEngine 编排 4 节点 DAG + WebSocket SSE 流式推送。
- **涉及模块**：新增 `flow/morning_brief_flow.json` + 工具节点（industry_rotation / stock_picker / report_build / push）+ WebSocket SSE 推送。
- **验收**：盘前自动产出晨会报告（行业轮动排名 + 个股短名单），候选标的可人工挑选入 watchlist。

### P4-3　策略生命周期管理（对应 I-12）

- **目标**：策略上下线治理 + Promote 门禁依据。
- **方案要点**：见 [trading-system-design.md §20](./trading-system-design.md#二十策略生命周期管理⏳-待实现)。5 阶段状态机 + KPI 自动迁移 + ABTest + 资金预算建议。
- **涉及模块**：新增 `domain/trading/lifecycle/` 模块 + `td_strategy_lifecycle` 表 + KPI 评估 + 自动迁移 + `promote` API。
- **验收**：策略可按 KPI 自动迁移阶段；仅 PRODUCTION 阶段允许 promote_to_live；`promote` API 落地。

### P4-4　Walk-Forward 过拟合检验（对应 I-13）

- **目标**：策略上线前过拟合检验，作为生命周期 INCUBATING→PAPER 迁移条件。
- **方案要点**：见 [trading-system-design.md §21](./trading-system-design.md#二十一walk-forward-过拟合检验⏳-待实现)。滚动窗口 IS/OOS + overfit_score 分级。
- **涉及模块**：新增 `domain/trading/walk_forward/` 模块 + `td_walk_forward_result` 表。
- **验收**：策略可跑滚动窗口 IS/OOS 检验，产出 overfit_score 分级（ok/warn/danger）；作为 P4-3 的迁移输入。

### P4-5　分级告警路由（对应 I-14）

- **目标**：Kill Switch/熔断/断线/僵尸订单等事件统一分级推送。
- **方案要点**：见 [trading-system-design.md §22](./trading-system-design.md#二十二分级告警路由⏳-待实现)。4 级（INFO/WARN/CRITICAL/FATAL）+ 4 渠道（控制台/WS/钉钉/企微）+ deque 聚合。
- **涉及模块**：新增 `domain/trading/alerting/` 模块 + `AlertSpi`（复用 `ws/spi/`）+ 4 级 4 渠道。
- **验收**：构造 Kill Switch/熔断/断线/僵尸订单场景，事件按分级推送到对应渠道；INFO 聚合 30 分钟推送，FATAL 重试 3 次。

### P5-1　文档据实对齐（对应 I-15）— ✅ 已完成

- **目标**：消除文档与代码的系统性不符，建立"文档与代码不漂移"基线。
- **方案要点**：`trading-system-design.md` §7.1（风控规则表降级）/§12（API 端点去伪）/§8（sizer 未接线说明）/§4.2（表名 td_ 前缀）/§6（broker.py 骨架说明）/§14（LIVE_AUTO/Promote 未接通）已据实修订；新增 §17~§22 平台章程与 L2 模块设计。
- **涉及模块**：`docs/trading-system-design.md`。
- **验收**：文档所有 ✅/⏳ 标记与代码一致；新功能落地即时回写文档。
- **状态**：✅ 已完成（2026-06-27）。

### P5-2　决策流 service.py 拆分（架构整改）

- **目标**：消除上帝代码，符合项目规则"单类方法数 ≤10、单函数 ≤80 行"。
- **方案要点**：将 `WatchlistDecisionWorkflowService`（约 1100 行）拆分为职责单一的类：`ContextLoader` / `SignalComputer` / `FusionService` / `SizingService` / `PreOrderGenerator` / `RiskGatewayService`。Tool 类改为薄封装调用拆分后的服务。
- **涉及模块**：`workflow/service.py` + `workflow/tools/decision_tools.py`。
- **验收**：拆分后功能等价（黑盒测试通过），每个类方法数 ≤10，单函数 ≤80 行；`ruff check` + `mypy` 通过。

### P5-3　broker.py Protocol 接线或删除（架构整改）

- **目标**：消除死代码，兑现或放弃"四套环境统一抽象"承诺。
- **方案要点**：二选一——
  - (A) **接线**：实盘/模拟/回测均走 `BrokerAdapter` Protocol，兑现统一抽象承诺。
  - (B) **删除**：删除 `broker.py`，执行流直连 `QmtTrader` / `SimulatedMatchingService`，承认三环境各自实现。
  - 推荐 (B)：个人版无需过度抽象，直连更简单。
- **涉及模块**：`domain/trading/broker.py` + `workflow/execution_service.py`。
- **验收**：无死代码；若选 (A) 则三环境统一抽象且测试通过，若选 (B) 则 `broker.py` 删除且无引用残留。

### P5-4　决策流 sizing 与 sizer 插件打通（架构整改）

- **目标**：兑现"四套环境统一"原则，回测与实盘 sizing 一致。
- **方案要点**：
  - `PositionSizingTool` 路由到 `SizerEngine` / 插件注册表，复用 `atr_position.py` / `kelly.py`。
  - 补全组合约束层：行业集中度 / 组合波动率 / 流动性约束。
  - 补全 `fallback` 降级机制：sizing 失败时回退 `equal_weight` + 写 `risk_event(warning)` + WS 推送。
- **涉及模块**：`workflow/service.py::PositionSizingTool` + `backtest/sizer/` + `run_risk_gateway`。
- **验收**：决策流与回测 sizing 走同一 `SizerEngine`；组合约束层拦截行业集中度超限；`fallback` 触发时写 `risk_event(warning)` + WS 推送。

---

## 四、执行计划（分阶段）

> 原则：先补**实盘闭环**（能用、安全），再补**决策质量**，最后做**体验与增强**。每阶段闭环：实施 → 重启服务 → API 黑盒测试 → 验收。

### Phase 1：实盘闭环与安全（最高优先）

| 任务 | 项 | 依赖 | 验收口径 | 状态 |
|------|----|------|----------|------|
| T1.1 | P0-2 成交确认 `OrderConfirmService` | QMT 回报接口 | 订单状态随回报推进 | ⏳ |
| T1.2 | P0-2 持仓/资金同步 `PositionSyncService` | 账户快照 | 持仓/可用资金自动刷新 | ⏳ |
| T1.3 | P0-1 T+1 实时价重定价 + 二次确认 | 实时行情源 | 跳空场景限价不沿用昨值 | ⏳ |
| T1.4 | P1-1 熔断器正名（先 UI 降级） | 无 | UI 文案与能力一致 | ⏳ |
| T1.5 | P1-1 `IntradayRiskMonitor` 自动熔断 | T1.2 持仓同步 | 超阈值触发告警/自动平仓 | ⏳ |
| T1.6 | P1-4 事前风控规则补全（7 条） | T1.5（daily_loss_circuit） | 非交易时段/陈旧信号/超仓位/超金额/资金不足/T+1 超卖均被拦截 | ⏳ |

### Phase 2：决策质量

| 任务 | 项 | 依赖 | 验收口径 | 状态 |
|------|----|------|----------|------|
| T2.1 | P1-2 统一风控单一视图 | 无 | 审批/面板同源，删消歧文案 | ⏳ |
| T2.2 | P1-3 审批组合层总览 | fusion 聚合 | 审批可见组合仓位/集中度/超限 | ⏳ |
| T2.3 | P2-1 交易成本模型下沉 | backtest 成本模型 | 模拟与回测成本口径一致 | ⏳ |

### Phase 3：体验与 AI 增强

| 任务 | 项 | 依赖 | 验收口径 | 状态 |
|------|----|------|----------|------|
| T3.1 | P2-2 执行日待下单提醒 | 无 | 有 approved 未下单即提醒 | ⏳ |
| T3.2 | P3-1 operator 降级 | 无 | 单用户免重复填写 | ⏳ |
| T3.3 | P3-2 `llm_pre_order_review` 审批守门 | ai-in-trading-design | 审批卡片出现风险提示 | ⏳ |
| T3.4 | P3-2 `llm_event_scan` 风险事件告警 | 公告/新闻源 | 踩雷类事件进风控告警 | ⏳ |
| T3.5 | 补全交易域 API 端点（promote / orders/{id}/cancel / trades / circuit-breaker/reset） | T3.2 | 4 个端点均可用 | ⏳ |

### Phase 4：机构方法论复刻（L2）

> 定位：参考业界机构方法论（Brinson / BHB / PM 标配 / Pardo WF），补全个人版缺失的归因/晨会/生命周期/过拟合检验/告警 5 大模块。详见 [trading-system-design.md §18~§22](./trading-system-design.md#十八brinson-归因⏳-待实现)。

| 任务 | 项 | 依赖 | 验收口径 | 状态 |
|------|----|------|----------|------|
| T4.1 | P4-1 Brinson 归因（BHB 三因子 + 三数据源） | `td_position_snapshot` | sim/real/csv 三源产出归因报告 | ⏳ |
| T4.2 | P4-2 Morning Brief 晨会（4 节点 DAG + SSE） | 因子管线 + WebSocket SPI | 盘前自动产出行业轮动 + 个股短名单 | ⏳ |
| T4.3 | P4-4 Walk-Forward 过拟合检验 | `backtest/` 引擎 | 策略可跑 IS/OOS 滚动窗口检验 + overfit_score | ⏳ |
| T4.4 | P4-3 策略生命周期管理（5 阶段 + KPI + promote） | T4.3 | 策略按 KPI 自动迁移；promote API 落地 | ⏳ |
| T4.5 | P4-5 分级告警路由（4 级 + 4 渠道） | T1.5 `IntradayRiskMonitor` | Kill Switch/熔断/断线事件按分级推送 | ⏳ |

> 顺序建议：T4.1（归因，复盘必备）→ T4.3（WF，T4.4 依赖）→ T4.4（生命周期，promote 门禁）→ T4.2（晨会，辅助决策）→ T4.5（告警，复用 WS SPI）。T4.5 也可前置到 Phase 1 配合盘内监控一起做。

### Phase 5：文档对齐与架构整改

> 定位：消除文档与代码漂移 + 消除上帝代码与死代码，建立可持续维护的代码基线。

| 任务 | 项 | 依赖 | 验收口径 | 状态 |
|------|----|------|----------|------|
| T5.1 | P5-1 文档据实对齐（§7.1/§12/§8/§4.2/§6/§14 + §17~§22 新增） | 无 | 文档与代码一致 | ✅ 已完成（2026-06-27） |
| T5.2 | P5-2 决策流 `service.py` 拆分（消除上帝代码） | 无 | 类方法数 ≤10，单函数 ≤80 行，黑盒测试通过 | ⏳ |
| T5.3 | P5-3 `broker.py` Protocol 接线或删除（消除死代码） | 无 | 无死代码；推荐删除方案 (B) | ⏳ |
| T5.4 | P5-4 决策流 sizing 与 sizer 插件打通 | T5.2 | 决策流与回测 sizing 走同一 SizerEngine；组合约束层 + fallback 落地 | ⏳ |

> Phase 5 与 Phase 1~4 可并行：T5.1 已完成；T5.2/T5.3 无依赖可随时启动；T5.4 依赖 T5.2 拆分后才能接线 sizer。

---

## 五、质量与验收（统一口径）

每个任务遵循项目规则闭环：

1. **设计 → 规划 → 实施**：按上表方案要点实现，禁止 fallback/mock/伪代码占位。
2. **质量检查**：`ruff check src/ tests/`、`mypy src/`（禁 `--fix`）+ 逻辑自查。
3. **黑盒测试为主**：变更后**重启服务**，用 `Invoke-RestMethod` 做 API 黑盒测试，覆盖正常/异常/边界；单测为辅。
4. **验收**：满足该任务「验收口径」列；涉及数据库改动用 db-tools 验证。
5. **总结**：完成后更新本文档对应任务「状态」列与 `trading-system-design.md` 实现状态附录。

---

## 六、与现有文档关系

| 文档 | 关系 |
|------|------|
| `trading-system-design.md` | 后端架构与实现状态；本计划完成项回写其 §9 与实现状态附录；**§17 平台目标章程**为本计划的纲领 |
| `trading-product-design.md` | 前端交互；本计划 UI 项（熔断正名/组合总览/待下单提醒/operator）据此对齐 |
| `ai-in-trading-design.md` | AI 旁路设计；本计划 Phase 3 AI 项的依据 |
| `CASE-AI量化系统` 示例代码（外部） | Phase 4 机构方法论复刻的参照样本（Brinson/晨会/生命周期/WF/告警），不直接复制代码，仅借鉴设计模式 |

---

## 七、平台目标章程

> 本章节为平台开发纲领的执行口径，权威定义见 [trading-system-design.md §17 平台目标章程](./trading-system-design.md#十七平台目标章程)。本计划所有任务须符合该章程。

### 7.1 平台定位

> **xq-trader 是参考业界机构方法论（Barra / WorldQuant / Qlib / 华泰 / Brinson / BHB），面向 A 股个人投资者的单机量化平台。**

核心矛盾是「机构严谨性 vs 个人轻量化」，平衡原则：**用机构的方法论保证严谨性，用个人版的轻量工程控制复杂度**。

### 7.2 三层目标与 Phase 映射

| 层级 | 定位 | 不可妥协原则 | 本计划对应 Phase |
|------|------|--------------|------------------|
| **L1 实盘安全底线** | 实盘不亏大钱、能看见每笔成交、扛得住跳空与盘中大跌 | 决策/执行分离 + pre_order 交接 + HITL 审批 + Kill Switch + 事前风控 + 盘内监控 | Phase 1（T1.1~T1.6） |
| **L2 机构方法论复刻** | 用机构的方法论保证决策严谨与可解释 | Brinson 归因 + 策略生命周期 + Walk-Forward + Morning Brief + 分级告警 | Phase 4（T4.1~T4.5） |
| **L3 体验与 AI 增强** | 个人友好、AI 旁路守门 | 单页驾驶舱 + Promote 提示性 warning + LLM 旁路（红线禁止进主信号） | Phase 2/3（T2.x/T3.x） |
| **基线** | 文档与代码不漂移、无上帝代码与死代码 | 文档据实 + 架构整改 | Phase 5（T5.1~T5.4） |

### 7.3 优先级原则

**盘内安全 > 决策质量 > 归因复盘 > 体验增强 > 架构整改**

- Phase 1（L1）最高优先，未闭环前不启动 Phase 4。
- Phase 5（基线）可与 Phase 1~4 并行，T5.1 文档对齐已完成。
- Phase 4（L2）按价值排序：T4.1 Brinson 归因（复盘必备）> T4.4 策略生命周期（promote 门禁）> T4.2 晨会 > T4.5 告警 > T4.3 WF。

### 7.4 不照搬清单（显式裁剪）

- ❌ ML 重型合成管线（XGBoost+MLP+AutoEncoder/HDBSCAN）—— `factor-architecture v6.0` 已移除
- ❌ 7 态因子生命周期状态机 —— 简化为 2 态（active/deprecated）
- ❌ 热/温/冷三层存储 + Parquet 归档 —— 单层 TimescaleDB 自动压缩
- ❌ 强制合规对账、多角色审批、OMS/EMS 物理分离
- ❌ LLM 直接预测 T+1 涨跌（红线禁止进主信号链路）
- ❌ 参数网格搜索 + 遗传算法优化（个人算力有限，仅做固定参数 WF）
- ❌ 机构级 NOC 大屏（个人驾驶舱已有风控侧栏）

---

*本计划为评审整改的执行依据，完成项即时回写状态，确保文档与实现不漂移。所有任务须符合 [§17 平台目标章程](./trading-system-design.md#十七平台目标章程)。*
