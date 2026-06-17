# 实盘交易决策流实施计划

> 更新: 2026-06-16

## 一、决策流七步架构

```
T日18:00 触发（依赖 alpha_signal_compute 完成）
  │
  ▼
Step1: LoadPortfolioContextTool ─ 加载持仓+自选池+资金
  │
  ▼
Step2: CrossSectionSelectTool ─ 截面因子选股（复用 CrossSectionReader）
  │
  ▼
Step3: SymbolSignalTool ─ 逐标的时序信号生成
  │
  ▼
Step4: SignalFusionTool ─ 截面×时序信号融合
  │
  ▼
Step5: PositionSizingTool ─ 仓位管理（8种可插拔策略）
  │
  ▼
Step6: OrderIntentGeneratorTool ─ 生成预订单
  │
  ▼
Step7: RiskGatewayTool ─ 事前风控预检
  │
  ▼
pre_order(status=pending_approval) → 人工审批窗口
```

## 二、现有资产 vs 需新建

| 类别 | 已有 | 需新建 |
|------|------|--------|
| ORM 模型 | 22 张表全部就绪 | — |
| 因子数据 | CrossSectionReader + FacFactorValue | — |
| 工作流框架 | FlowEngine + FlowCompiler + Checkpoint | trading_decision.json |
| Broker | QmtTrader + QmtConnection + Callback | BrokerAdapter Protocol |
| Celery | 插件体系 + Beat 调度 | trading_decision Task |
| **7 个 Tool 节点** | — | 全部需实现 |
| **规则引擎** | — | 表达式引擎 + SPI 插件 + 5 种组合策略 |
| **策略引擎** | — | StrategyEngine + SignalFusion |
| **仓位管理** | — | SizingStrategy 注册表 + 8 种策略 |
| **风控网关** | — | RiskGateway + 8 条内置规则 |
| **审批服务** | — | ApprovalService + API |

## 三、分阶段实施计划

### P0 — 决策流最小闭环（可端到端跑通）

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | `flow/trading_decision.json` | 工作流定义，7 个 Tool 节点线性编排 |
| 2 | `LoadPortfolioContextTool` | 读取 StrategyInstance/PositionSnapshot/Watchlist/AccountSnapshot |
| 3 | `CrossSectionSelectTool` | 复用 CrossSectionReader，先硬编码等权选股 TopN |
| 4 | `SymbolSignalTool` | 先硬编码简单动量信号，后续接入规则引擎 |
| 5 | `SignalFusionTool` | 按文档融合规则表实现（截面×时序） |
| 6 | `PositionSizingTool` | 先实现 `equal_weight` 一种策略 |
| 7 | `OrderIntentGeneratorTool` | 纯计算：目标权重 vs 当前权重 → open/add/reduce/close |
| 8 | `RiskGatewayTool` | 先实现 3 条核心规则（仓位限制/现金充足/T+1 卖出） |
| 9 | `TradingDecisionTask` | Celery 触发任务，调用 FlowEngine |
| 10 | `ApprovalService + API` | `POST /trading/approval/{id}` 逐条 + 批量审批 |

**P0 验收标准**：Celery Beat T日18:00触发 → 7步执行 → pre_order 落库 → 人工审批 → pre_order 状态变更

### P1 — 规则引擎 + 策略引擎

| # | 交付物 | 说明 |
|---|--------|------|
| 11 | `ExpressionEvaluator` | 词法/语法/AST/求值器 + 7 个截面算子 |
| 12 | `RulePlugin` ABC | SPI 插件基类 + RuleContext/RuleSignal 数据类 |
| 13 | 6 个 SPI 插件 | MACD/KDJ/布林/缠论/K线形态/放量突破 |
| 14 | 5 种 `CombinationStrategy` | AND/OR/weighted_score/weighted_vote/ic_weighted |
| 15 | `StrategyEngine` | 加载策略→执行规则组→产出信号 |
| 16 | 接入 Step2/Step3 | CrossSectionSelectTool 和 SymbolSignalTool 接入规则引擎 |

### P2 — 仓位管理 + 风控完善

| # | 交付物 | 说明 |
|---|--------|------|
| 17 | 8 种 `SizingStrategy` | signal_weight/inverse_volatility/volatility_target/atr_risk/kelly_fraction/fixed_fraction/max_position_cap |
| 18 | `PortfolioConstraints` | 行业集中度/组合波动率/权重总和/流动性约束 |
| 19 | RiskGateway 完整 8 条规则 | 交易时段/日亏损熔断/仓位限制/金额限制/持仓数/T+1/现金/信号TTL |
| 20 | `IntradayRiskMonitor` | 事中风控（日内亏损/单票暴跌/权重偏离/部分成交超时） |

### P3 — 执行流 + OMS + 盘内监控

| # | 交付物 | 说明 |
|---|--------|------|
| 21 | `flow/trading_execution.json` + 4 个 Tool | 执行流：加载审批单→风控复查→Broker提交→确认 |
| 22 | `OrderManager` + OMS 状态机 | 8 状态 + 7 转换 |
| 23 | `BrokerAdapter` Protocol | QmtBrokerAdapter / SimulatedBrokerAdapter / BacktestBrokerAdapter |
| 24 | 盘内监控服务 | PositionSync/OrderConfirm/PaperMatcher/Reconciliation |
| 25 | 交易 API 全量 | 9 组 API 路由 |

## 四、关键设计决策

| 决策点 | 方案 | 理由 |
|--------|------|------|
| Step3 并行策略 | Tool 内部串行遍历标的 | 标的数少（<30），规则评估毫秒级，fan-out 分支过多增加 checkpoint 开销 |
| 风控拦截处理 | RiskGatewayTool 返回 passed/blocked 标志，不中断流程 | 被拦截的 pre_order 标记 `risk_check_passed=False`，通过的继续，保证全链路可追溯 |
| Tool 节点规范 | 继承 `langchain_core.tools.BaseTool`，实现 `_arun` | 与 FlowCompiler/ToolNode 框架一致 |
| 策略模式 | SizingStrategy/CombinationStrategy/RiskRule 均为策略类+注册表 | 符合项目架构规则，禁止 if/elif 长串 |
| 幂等性 | `PreOrder.idempotency_key = {instance_id}:{signal_date}:{symbol}:{side}` | 同一信号日同一标的不会重复生成 |

## 五、决策流七步详细数据契约

### Step1: LoadPortfolioContextTool

- **输入**: `instance_id`, `signal_date`
- **职责**: 加载 StrategyInstance 配置、PositionSnapshot 持仓、Watchlist/WatchlistItem 自选池、AccountSnapshot 资金
- **输出**: `{positions, watchlist, cash, total_asset, config}`
- **落库**: 无新记录，纯读取

### Step2: CrossSectionSelectTool

- **输入**: `instance_id`, `signal_date`, `universe_pool`, 截面规则组配置
- **职责**: 通过 CrossSectionReader 加载因子截面；评估截面规则；筛选候选标的
- **输出**: `{selected_symbols, scores}`
- **落库**: `SelectionResult` — 每个入选标的一条记录

### Step3: SymbolSignalTool

- **输入**: `selected_symbols`, `signal_date`, 时序规则组配置
- **职责**: 逐标的加载因子值；评估时序规则；产出 direction + confidence
- **输出**: `{symbol: {direction, confidence, contributing_signals}}`
- **落库**: `TradingSignal` — 每个标的每条信号一条记录

### Step4: SignalFusionTool

- **输入**: 截面选股 scores + 时序信号 direction/confidence
- **职责**: 按融合规则合并截面与时序信号
- **输出**: `{symbol: {direction, fused_score, contributing_signals}}`
- **落库**: `SignalFusionResult` — 每个标的一条记录

### Step5: PositionSizingTool

- **输入**: SignalFusionResult + AccountSnapshot + PositionSnapshot + SizingStrategy 配置
- **职责**: 选择配仓策略；计算 target_weight/target_qty；应用组合约束
- **输出**: `{symbol: {target_weight, target_qty, current_weight, sizing_strategy, sizing_params, raw_score}}`
- **落库**: `PositionSizingResult` — 每个标的一条记录

### Step6: OrderIntentGeneratorTool

- **输入**: PositionSizingResult + PositionSnapshot
- **职责**: 对比目标 vs 当前权重，决定 open/add/reduce/close；计算目标数量；生成幂等键
- **输出**: `{pre_orders: [{symbol, side, target_weight, current_weight, target_qty, order_type, limit_price, sizing_strategy, idempotency_key}]}`
- **落库**: `PreOrder` — status=pending_approval, risk_check_passed=null

### Step7: RiskGatewayTool

- **输入**: PreOrder 列表 + RiskRule 规则集 + AccountSnapshot + PositionSnapshot
- **职责**: 执行事前风控规则；通过/拦截标记；写入 RiskEvent
- **输出**: `{passed: bool, blocked_orders, risk_events}`
- **落库**: 更新 PreOrder.risk_check_passed + risk_check_detail；写入 RiskEvent
