# xq-trader 因子→规则→策略 架构设计

> **更新**: 2026-06-11
> **前置**: [factor-architecture.md](./factor-architecture.md)（因子系统）、[trading-system-design.md](./trading-system-design.md)（交易系统）
> **参考**: Qlib Pipeline / WorldQuant BRAIN / Zipline Pipeline API / Quantopian Factor-Classifier-Filter

---

## 一、设计目标

| 目标 | 说明 |
|------|------|
| 因子→规则→策略三层分离 | 因子是数值特征，规则是因子上的判断逻辑，策略是多规则的组合与决策 |
| 双引擎规则 | 表达式规则（类 Qlib/WorldQuant）+ SPI 插件规则（MACD 金叉、布林带等） |
| 截面/时序规则分离 | 截面选股规则 vs 时序信号规则，不同算子、不同输出 |
| 信号带方向+置信度 | 每条规则产出 BUY/SELL/NEUTRAL + confidence，而非二元布尔 |
| 多规则组合 | AND/OR 逻辑、加权评分、投票多数决、IC 加权等 |
| 可配置可复用 | 规则与策略均为数据库配置，前端可编辑，策略实例可复用 |

---

## 二、核心概念

### 2.1 三层模型

```mermaid
flowchart LR
    subgraph "因子层 (Factor)"
        F1[fac_factor_value<br/>连续实数值]
        F2[fac_signal_value<br/>离散信号值]
    end

    subgraph "规则层 (Rule)"
        R1[表达式规则<br/>ROE > 5]
        R2[SPI 插件规则<br/>MACD 金叉]
    end

    subgraph "策略层 (Strategy)"
        S1[截面选股策略<br/>多规则 → 候选池]
        S2[时序信号策略<br/>多规则 → BUY/SELL]
        S3[组合策略<br/>选股 + 信号 + 配仓]
    end

    F1 --> R1
    F2 --> R2
    F1 --> R2
    R1 --> S1
    R1 --> S2
    R2 --> S2
    S1 --> S3
    S2 --> S3
```

### 2.2 概念定义

| 概念 | 定义 | 产出 | 示例 |
|------|------|------|------|
| **因子** | 从原始数据提取的数值特征 | 连续实数值 | `roe=12.5`, `rsi_14=65.3` |
| **规则** | 对因子/信号施加的判断逻辑 | 方向 + 置信度 | `RSI > 70 → SELL(0.8)` |
| **策略** | 多规则的组合 + 决策逻辑 | 最终交易信号 | 3 条规则投票 → BUY |

### 2.3 规则 vs 因子的关系

**每条规则至少依赖一个因子**：

```mermaid
flowchart TD
    Factor1[roe] --> Rule1[ROE > 5]
    Factor2[rsi_14] --> Rule2[RSI < 30: BUY, RSI > 70: SELL]
    Factor3[macd_hist + signal_line] --> Rule3[MACD 金叉: BUY, MACD 死叉: SELL]
    Factor4[mom_20d + hist_vol_20] --> Rule4[动量×波动交互 > 阈值]
    Factor5[chan_signal_buy1] --> Rule5[缠论一买确认]
```

---

## 三、规则引擎设计

### 3.1 规则类型

| 类型 | 实现方式 | 适用场景 | 业界参考 |
|------|---------|---------|---------|
| **表达式规则** | 声明式表达式引擎，类 Qlib/WorldQuant | 阈值判断、排名筛选、因子组合 | Qlib Alpha158, WQ BRAIN FastExpression |
| **SPI 插件规则** | Python 类继承 RulePlugin，编码实现 | 复杂模式识别、交叉检测、多因子联合判断 | vnpy CtaTemplate, TradingView Pine Script |

### 3.2 表达式规则

**语法设计**（参考 WorldQuant FastExpression + Qlib 表达式引擎）：

```
# 基本比较
roe > 5
rsi_14 < 30
pe_ttm < 30 and roe > 10

# 截面排名
rank(mom_20d) > 0.8          # 动量排名前 20%
rank(ep_ttm) > 0.7           # 盈利收益率排名前 30%

# 时序算子
delta(rsi_14, 5) > 10        # RSI 5日变化 > 10
cross_above(macd_dif, macd_dea)  # MACD 金叉
cross_below(macd_dif, macd_dea)  # MACD 死叉

# 组合表达式
rank(mom_20d) > 0.7 and rank(ep_ttm) > 0.5 and hist_vol_20 < 0.3
```

**表达式算子**：

| 类别 | 算子 | 说明 |
|------|------|------|
| 比较 | `>`, `<`, `>=`, `<=`, `==`, `!=` | 阈值判断 |
| 逻辑 | `and`, `or`, `not` | 条件组合 |
| 截面 | `rank(x)`, `zscore(x)`, `percentile(x)` | 截面排名/标准化 |
| 时序 | `delta(x, n)`, `ma(x, n)`, `std(x, n)` | 时序变化/均值/标准差 |
| 交叉 | `cross_above(a, b)`, `cross_below(a, b)` | 金叉/死叉检测 |
| 数学 | `abs(x)`, `log(x)`, `sign(x)`, `max(a,b)`, `min(a,b)` | 数学运算 |

**表达式规则配置**：

```json
{
  "rule_id": "r_roe_filter",
  "name": "ROE 过滤",
  "category": "cross_section",
  "type": "expression",
  "expression": "roe > 5 and rank(roe) > 0.5",
  "factors": ["roe"],
  "signal_mapping": {
    "true": {"direction": "LONG", "confidence_expr": "zscore(roe)"},
    "false": {"direction": "NEUTRAL", "confidence": 0}
  }
}
```

**关键设计**：`signal_mapping` 定义表达式结果到信号的映射：
- 表达式为 `true` → 产生信号（方向 + 置信度）
- 表达式为 `false` → NEUTRAL（无信号）
- `confidence_expr` 支持表达式计算置信度（如 `zscore(roe)` 表示 ROE 的 Z-score 作为置信度）

### 3.3 SPI 插件规则

**基类设计**：

```python
class RulePlugin(ABC):
    """规则插件基类。"""

    rule_id: str           # 规则唯一标识
    name: str              # 规则名称
    category: str          # cross_section / time_series
    factors: list[str]     # 依赖因子列表

    @abstractmethod
    def evaluate(self, ctx: RuleContext) -> RuleSignal:
        """评估规则，返回信号。"""

    def get_config_schema(self) -> dict:
        """返回配置参数 JSON Schema（前端动态渲染表单）。"""
        return {}
```

**RuleContext**：

```python
@dataclass
class RuleContext:
    """规则执行上下文。"""
    symbol: str                    # 当前标的
    trade_date: date               # 当前交易日
    factor_values: dict[str, float]  # 因子值 {factor_id: value}
    signal_values: dict[str, Any]    # 信号值 {signal_id: value}
    kline_df: DataFrame | None      # K线数据（SPI 插件可能需要）
    config: dict                    # 规则配置参数
```

**RuleSignal**：

```python
@dataclass
class RuleSignal:
    """规则产出的信号。"""
    direction: str         # BUY / SELL / NEUTRAL
    confidence: float      # 置信度 0.0 ~ 1.0
    reason: str            # 信号原因（审计用）
    detail: dict | None    # 信号详情（如 MACD 值、金叉位置等）
```

**SPI 插件示例 — MACD 金叉死叉**：

```python
class MACDCrossRule(RulePlugin):
    rule_id = "macd_cross"
    name = "MACD 金叉死叉"
    category = "time_series"
    factors = ["macd_hist_ratio", "macd_hist_delta"]

    def evaluate(self, ctx: RuleContext) -> RuleSignal:
        hist = ctx.factor_values.get("macd_hist_ratio")
        hist_prev = ctx.kline_df["macd_hist_ratio"].iloc[-2] if ctx.kline_df is not None else None

        if hist is None or hist_prev is None:
            return RuleSignal(NEUTRAL, 0.0, "数据不足")

        # 金叉：前一日 MACD 柱 < 0，当日 MACD 柱 >= 0
        if hist_prev < 0 and hist >= 0:
            strength = min(abs(hist - hist_prev) / 0.02, 1.0)  # 归一化
            return RuleSignal(BUY, strength, f"MACD金叉 hist={hist:.4f}")

        # 死叉：前一日 MACD 柱 > 0，当日 MACD 柱 <= 0
        if hist_prev > 0 and hist <= 0:
            strength = min(abs(hist - hist_prev) / 0.02, 1.0)
            return RuleSignal(SELL, strength, f"MACD死叉 hist={hist:.4f}")

        return RuleSignal(NEUTRAL, 0.0, "无交叉信号")
```

**SPI 插件示例 — 布林带规则**：

```python
class BollingerBandRule(RulePlugin):
    rule_id = "bollinger_band"
    name = "布林带突破"
    category = "time_series"
    factors = ["boll_position", "boll_width"]

    def get_config_schema(self) -> dict:
        return {
            "oversold_threshold": {"type": "number", "default": 0.1, "title": "超卖阈值"},
            "overbought_threshold": {"type": "number", "default": 0.9, "title": "超买阈值"},
        }

    def evaluate(self, ctx: RuleContext) -> RuleSignal:
        pos = ctx.factor_values.get("boll_position")
        width = ctx.factor_values.get("boll_width")
        oversold = ctx.config.get("oversold_threshold", 0.1)
        overbought = ctx.config.get("overbought_threshold", 0.9)

        if pos is None:
            return RuleSignal(NEUTRAL, 0.0, "数据不足")

        if pos < oversold:
            conf = min((oversold - pos) / oversold, 1.0)
            return RuleSignal(BUY, conf, f"布林带超卖 pos={pos:.2f}")

        if pos > overbought:
            conf = min((pos - overbought) / (1 - overbought), 1.0)
            return RuleSignal(SELL, conf, f"布林带超买 pos={pos:.2f}")

        return RuleSignal(NEUTRAL, 0.0, "布林带中性区间")
```

### 3.4 规则类别

| 类别 | 说明 | 输出 | 执行时机 |
|------|------|------|---------|
| **cross_section** | 截面选股规则 | 是否入选 + 截面得分 | T 日决策流（步骤 2 CrossSectionSelect） |
| **time_series** | 时序信号规则 | BUY/SELL/NEUTRAL + 置信度 | T 日决策流（步骤 3 SymbolSignal） |

**截面规则**：在全市场标的上执行，筛选出候选池。规则产出为 `pass/fail` + `score`。

**时序规则**：在候选池标的上逐标的执行，产生交易信号。规则产出为 `BUY/SELL/NEUTRAL` + `confidence`。

### 3.5 规则注册表

规则通过数据库表管理，支持前端配置和动态加载：

| 字段 | 类型 | 说明 |
|------|------|------|
| rule_id | String(64) PK | 规则唯一标识 |
| name | String(128) | 规则名称 |
| category | Enum | `cross_section` / `time_series` |
| type | Enum | `expression` / `spi` |
| expression | Text | 表达式规则的表达式字符串（type=expression 时） |
| spi_class | String(256) | SPI 插件类路径（type=spi 时），如 `xqtrader.trading.rules.macd_cross.MACDCrossRule` |
| factors | JSON | 依赖因子列表 `["roe", "rsi_14"]` |
| signal_mapping | JSON | 信号映射配置（表达式规则专用） |
| config_schema | JSON | 参数 JSON Schema（前端动态渲染） |
| default_config | JSON | 默认配置参数 |
| description | Text | 规则说明 |
| is_builtin | Boolean | 是否内置规则 |
| status | Enum | `active` / `deprecated` |

---

## 四、策略引擎设计

### 4.1 策略结构

```mermaid
flowchart TD
    subgraph "策略 (Strategy)"
        CS[截面选股规则组]
        TS[时序信号规则组]
        PS[仓位管理配置]
        RK[风控规则覆盖]
    end

    subgraph "截面规则组"
        CS_R1[规则1: ROE > 5] --> CS_COMB[组合: AND]
        CS_R2[规则2: 动量排名 > 0.7] --> CS_COMB
        CS_R3[规则3: 波动率 < 0.3] --> CS_COMB
        CS_COMB --> CS_OUT[候选标的池]
    end

    subgraph "时序规则组"
        TS_R1[规则4: MACD 金叉] --> TS_COMB[组合: 加权投票]
        TS_R2[规则5: RSI 超卖] --> TS_COMB
        TS_R3[规则6: 缠论一买] --> TS_COMB
        TS_COMB --> TS_OUT[BUY/SELL + 置信度]
    end

    CS_OUT --> FUSION[信号融合]
    TS_OUT --> FUSION
    FUSION --> SIGNAL[最终交易信号<br/>direction + confidence]
    SIGNAL --> SIZING[仓位管理]
    SIZING --> PRE_ORDER[预订单]
```

### 4.2 策略配置

```json
{
  "strategy_id": "alpha_rebalance_01",
  "name": "Alpha 再平衡策略",
  "cross_section_rules": {
    "rules": [
      {"rule_id": "r_roe_filter", "weight": 0.3, "config": {"threshold": 5}},
      {"rule_id": "r_momentum_rank", "weight": 0.4, "config": {"top_pct": 0.3}},
      {"rule_id": "r_volatility_filter", "weight": 0.3, "config": {"max_vol": 0.3}}
    ],
    "combination": "weighted_score",
    "min_score": 0.5,
    "max_stocks": 20
  },
  "time_series_rules": {
    "rules": [
      {"rule_id": "macd_cross", "weight": 0.3, "config": {}},
      {"rule_id": "bollinger_band", "weight": 0.3, "config": {"oversold_threshold": 0.1}},
      {"rule_id": "rsi_signal", "weight": 0.2, "config": {"oversold": 30, "overbought": 70}},
      {"rule_id": "chan_buy_signal", "weight": 0.2, "config": {}}
    ],
    "combination": "weighted_vote",
    "buy_threshold": 0.5,
    "sell_threshold": -0.5
  },
  "position_sizing": {
    "strategy": "atr_risk",
    "params": {"atr_period": 14, "risk_budget_pct": 0.02}
  }
}
```

### 4.3 规则组合方式

#### 方式一：AND 逻辑组合

所有规则必须通过：

```
result = rule1.pass AND rule2.pass AND rule3.pass
score = min(rule1.score, rule2.score, rule3.score)
```

适用场景：严格筛选，如"ROE > 5 AND PE < 30 AND 动量排名 > 0.7"

#### 方式二：OR 逻辑组合

任一规则通过即可：

```
result = rule1.pass OR rule2.pass OR rule3.pass
score = max(rule1.score, rule2.score, rule3.score)
```

适用场景：宽松筛选，如"MACD 金叉 OR RSI 超卖 OR 缠论一买"

#### 方式三：加权评分

各规则加权得分求和：

```
score = Σ(w_i × rule_i.score)
result = score ≥ threshold
```

适用场景：截面选股，如"ROE 得分 × 0.3 + 动量得分 × 0.4 + 波动率得分 × 0.3 ≥ 0.5"

#### 方式四：加权投票

各规则投票，BUY=+1, SELL=-1, NEUTRAL=0：

```
vote = Σ(w_i × direction_i)    # BUY=+1, SELL=-1, NEUTRAL=0
confidence = |vote| / Σ(w_i)   # 归一化置信度

if vote > buy_threshold:  → BUY(confidence)
if vote < sell_threshold: → SELL(confidence)
else:                     → NEUTRAL
```

适用场景：时序信号，如"MACD 金叉(0.3) + RSI 超卖(0.3) + 缠论一买(0.2) + 布林超卖(0.2)"

#### 方式五：IC 加权

使用因子历史 IC 作为权重（仅截面选股）：

```
w_i = ICIR_i / Σ|ICIR_j|    # ICIR 归一化权重
score = Σ(w_i × zscore(rule_i.factor_value))
```

适用场景：机构级多因子选股，权重随因子评估自动更新。

### 4.4 信号融合

截面选股与时序信号的融合：

```mermaid
flowchart TD
    CS[截面选股结果<br/>候选标的池 + 截面得分] --> MERGE[信号融合]
    TS[时序信号结果<br/>BUY/SELL + 置信度] --> MERGE
    MERGE --> SIGNAL[最终信号]

    subgraph "融合逻辑"
        F1[标的在候选池中?]
        F2[时序信号方向?]
        F3[综合置信度]

        F1 -->|是| F2
        F1 -->|否| OUT_NEUTRAL[NEUTRAL 不交易]
        F2 -->|BUY| F3_BUY[BUY confidence = cs_score × ts_confidence]
        F2 -->|SELL| F3_SELL[SELL confidence = ts_confidence]
        F2 -->|NEUTRAL| OUT_HOLD[HOLD 持有观察]
    end
```

**融合规则**：

| 截面结果 | 时序信号 | 最终信号 | 说明 |
|---------|---------|---------|------|
| 入选 + 高分 | BUY | BUY(confidence = cs_score × ts_conf) | 强买入 |
| 入选 + 低分 | BUY | BUY(confidence = cs_score × ts_conf) | 弱买入 |
| 入选 | SELL | SELL(confidence = ts_conf) | 卖出（不看截面得分） |
| 入选 | NEUTRAL | HOLD | 持有观察 |
| 未入选 | BUY | NEUTRAL | 不在候选池，不买入 |
| 未入选 | SELL | SELL(confidence = ts_conf) | 不在候选池，卖出 |
| 未入选 | NEUTRAL | NEUTRAL | 不交易 |

### 4.5 置信度计算

**单规则置信度**：

| 规则类型 | 置信度计算 |
|---------|-----------|
| 表达式规则 | `confidence_expr` 表达式计算（如 `zscore(roe)`） |
| SPI 插件规则 | 插件 `evaluate()` 返回的 `confidence` 字段 |

**多规则组合置信度**：

| 组合方式 | 置信度公式 |
|---------|-----------|
| AND | `min(conf_1, conf_2, ...)` |
| OR | `max(conf_1, conf_2, ...)` |
| 加权评分 | `Σ(w_i × conf_i) / Σ(w_i)` |
| 加权投票 | `|Σ(w_i × direction_i × conf_i)| / Σ(w_i)` |
| IC 加权 | `Σ(ICIR_i × zscore_i) / Σ|ICIR_i|` |

**最终信号置信度**：

```
final_confidence = cross_section_score × time_series_confidence
```

最终置信度用于仓位管理：`target_weight = sizing_strategy(final_confidence, ...)`

---

## 五、与交易系统集成

### 5.1 在 trading_decision 流中的位置

```mermaid
flowchart TD
    S1[1. LoadPortfolioContext] --> S2
    S2[2. CrossSectionSelect<br/>截面选股规则组] --> S3
    S3[3. SymbolSignal x N<br/>时序信号规则组] --> S4
    S4[4. SignalFusion<br/>信号融合] --> S5
    S5[5. PositionSizing<br/>仓位管理] --> S6
    S6[6. OrderIntentGenerator] --> S7
    S7[7. RiskGateway]
```

| 步骤 | 使用规则 | 说明 |
|------|---------|------|
| 步骤 2 CrossSectionSelect | 截面规则组 | 执行截面选股规则，产出候选标的池 |
| 步骤 3 SymbolSignal | 时序规则组 | 逐标的执行时序规则，产出 BUY/SELL 信号 |
| 步骤 4 SignalFusion | 融合逻辑 | 截面得分 × 时序置信度 → 最终信号 |

### 5.2 CrossSectionSelectTool 实现

```python
class CrossSectionSelectTool:
    """截面选股工具节点。"""

    async def execute(self, state: dict) -> dict:
        strategy = await self.load_strategy(state["instance_id"])
        cross_section_rules = strategy.cross_section_rules

        # 1. 加载全市场因子截面
        factor_df = await self.cross_section_reader.load(
            trade_date=state["signal_date"],
            factor_ids=self._collect_factor_ids(cross_section_rules),
            pool_id=strategy.universe_pool
        )

        # 2. 逐规则评估
        scores = {}
        for rule_config in cross_section_rules.rules:
            rule = self.rule_registry.get(rule_config.rule_id)
            rule_results = rule.evaluate_cross_section(factor_df, rule_config.config)
            for symbol, result in rule_results.items():
                scores.setdefault(symbol, {})[rule_config.rule_id] = result

        # 3. 组合
        combination = self._get_combination(cross_section_rules.combination)
        selected = combination.combine(scores, cross_section_rules)

        # 4. 写入 selection_result
        await self.persist_selection(state, selected)
        return {"selected_symbols": list(selected.keys())}
```

### 5.3 SymbolSignalTool 实现

```python
class SymbolSignalTool:
    """逐标的信号生成工具节点。"""

    async def execute(self, state: dict) -> dict:
        strategy = await self.load_strategy(state["instance_id"])
        ts_rules = strategy.time_series_rules
        symbols = state["selected_symbols"]

        signals = {}
        for symbol in symbols:
            # 1. 加载标的因子值 + K线
            ctx = await self.build_context(symbol, state["signal_date"], ts_rules)

            # 2. 逐规则评估
            rule_signals = {}
            for rule_config in ts_rules.rules:
                rule = self.rule_registry.get(rule_config.rule_id)
                signal = rule.evaluate(ctx)
                rule_signals[rule_config.rule_id] = signal

            # 3. 组合
            combination = self._get_combination(ts_rules.combination)
            final_signal = combination.combine(rule_signals, ts_rules)
            signals[symbol] = final_signal

        # 4. 写入 trading_signal
        await self.persist_signals(state, signals)
        return {"signals": signals}
```

---

## 六、领域模型

### 6.1 ER 关系

```mermaid
erDiagram
    STRATEGY ||--o{ STRATEGY_RULE_GROUP : "1:N"
    STRATEGY_RULE_GROUP ||--o{ STRATEGY_RULE_BINDING : "1:N"
    RULE_REGISTRY ||--o{ STRATEGY_RULE_BINDING : "1:1"
    RULE_REGISTRY ||--o{ RULE_FACTOR_DEP : "1:N"
    FAC_FACTOR_REGISTRY ||--o{ RULE_FACTOR_DEP : "1:1"
    STRATEGY ||--o{ STRATEGY_INSTANCE : "1:N"

    STRATEGY {
        uuid id PK
        string strategy_id UK
        string name
        string description
        json cross_section_config
        json time_series_config
        json position_sizing_config
        json risk_overrides
        string status
    }

    STRATEGY_RULE_GROUP {
        uuid id PK
        uuid strategy_id FK
        string group_type
        string combination_method
        json combination_params
        float threshold
    }

    STRATEGY_RULE_BINDING {
        uuid id PK
        uuid group_id FK
        string rule_id FK
        float weight
        json config_override
        int sort_order
    }

    RULE_REGISTRY {
        string rule_id PK
        string name
        string category
        string type
        text expression
        string spi_class
        json factors
        json signal_mapping
        json config_schema
        json default_config
        string status
    }

    RULE_FACTOR_DEP {
        uuid id PK
        string rule_id FK
        string factor_id FK
        string usage
    }
```

### 6.2 表定义

#### strategy（策略定义）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| strategy_id | String(64) unique | 策略编码 |
| name | String(128) | 策略名称 |
| description | Text | 策略说明 |
| cross_section_config | JSON | 截面选股规则组配置 |
| time_series_config | JSON | 时序信号规则组配置 |
| position_sizing_config | JSON | 仓位管理配置 |
| risk_overrides | JSON | 风控规则覆盖 |
| universe_pool | String(16) | 默认样本池 |
| status | Enum | `draft` / `active` / `deprecated` |

#### strategy_rule_group（规则组）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| strategy_id | UUID FK | 所属策略 |
| group_type | Enum | `cross_section` / `time_series` |
| combination_method | Enum | `and` / `or` / `weighted_score` / `weighted_vote` / `ic_weighted` |
| combination_params | JSON | 组合参数（如 buy_threshold, sell_threshold） |
| threshold | Float | 通过阈值 |

#### strategy_rule_binding（规则-策略绑定）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| group_id | UUID FK | 所属规则组 |
| rule_id | String(64) FK → rule_registry | 规则 ID |
| weight | Float | 权重（0-1，加权组合时使用） |
| config_override | JSON | 覆盖默认配置 |
| sort_order | Integer | 排序 |

#### rule_registry（规则注册表）

| 字段 | 类型 | 说明 |
|------|------|------|
| rule_id | String(64) PK | 规则唯一标识 |
| name | String(128) | 规则名称 |
| category | Enum | `cross_section` / `time_series` / `both` |
| type | Enum | `expression` / `spi` |
| expression | Text | 表达式（type=expression） |
| spi_class | String(256) | SPI 类路径（type=spi） |
| factors | JSON | 依赖因子 `["roe", "rsi_14"]` |
| signal_mapping | JSON | 信号映射（表达式规则） |
| config_schema | JSON | 参数 JSON Schema |
| default_config | JSON | 默认配置 |
| description | Text | 规则说明 |
| is_builtin | Boolean | 是否内置 |
| status | Enum | `active` / `deprecated` |

#### rule_factor_dep（规则-因子依赖）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | |
| rule_id | String(64) FK | 规则 ID |
| factor_id | String(32) FK | 因子 ID |
| usage | String | 用途说明（如"阈值判断"、"交叉检测"） |

---

## 七、内置规则

### 7.1 截面选股规则

| rule_id | 名称 | 类型 | 表达式/逻辑 | 依赖因子 |
|---------|------|------|------------|---------|
| `cs_roe_filter` | ROE 过滤 | expression | `roe > {threshold}` | roe |
| `cs_pe_filter` | PE 过滤 | expression | `pe_ttm < {threshold}` | pe_ttm |
| `cs_momentum_rank` | 动量排名 | expression | `rank(mom_20d) > {top_pct}` | mom_20d |
| `cs_value_momentum` | 价值动量组合 | expression | `rank(ep_ttm) > 0.5 and rank(mom_20d) > 0.5` | ep_ttm, mom_20d |
| `cs_low_volatility` | 低波过滤 | expression | `hist_vol_20 < {max_vol}` | hist_vol_20 |
| `cs_fund_flow` | 资金流过滤 | expression | `cs_main_net_pct > 0 and rank(cs_main_net_pct) > 0.6` | cs_main_net_pct |
| `cs_quality_growth` | 质量成长 | expression | `roe > 10 and q_or_yoy > 20` | roe, q_or_yoy |

### 7.2 时序信号规则

| rule_id | 名称 | 类型 | 逻辑 | 依赖因子 |
|---------|------|------|------|---------|
| `ts_rsi_signal` | RSI 超买超卖 | expression | `rsi_14 < {oversold}: BUY, rsi_14 > {overbought}: SELL` | rsi_14 |
| `ts_boll_signal` | 布林带突破 | expression | `boll_position < {lower}: BUY, boll_position > {upper}: SELL` | boll_position |
| `ts_momentum_signal` | 动量突破 | expression | `delta(mom_20d, 5) > {threshold}: BUY` | mom_20d |
| `ts_macd_cross` | MACD 金叉死叉 | spi | MACD 柱由负转正/由正转负 | macd_hist_ratio |
| `ts_kdj_cross` | KDJ 金叉死叉 | spi | K 线上穿/下穿 D 线 | kdj_k, kdj_d |
| `ts_bollinger_band` | 布林带规则 | spi | 位置 < 阈值: BUY, 位置 > 阈值: SELL | boll_position, boll_width |
| `ts_chan_buy1` | 缠论一买 | spi | 缠论一买信号确认 | chan_signal_buy1 |
| `ts_chan_sell1` | 缠论一卖 | spi | 缠论一卖信号确认 | chan_signal_sell1 |
| `ts_cdl_pattern` | K线形态组合 | spi | 看涨/看跌形态频次判断 | cdl_bull_freq_20, cdl_bear_freq_20 |
| `ts_volume_break` | 放量突破 | spi | 量比 > 阈值 + 价格突破 | cs_volume_ratio, mom_20d |

### 7.3 双类别规则（截面 + 时序）

| rule_id | 名称 | 截面用法 | 时序用法 |
|---------|------|---------|---------|
| `ts_rsi_signal` | RSI | 截面排名 RSI 最低的标的 | RSI < 30: BUY, RSI > 70: SELL |
| `ts_momentum_signal` | 动量 | 截面排名动量最高的标的 | 动量由负转正: BUY |
| `ts_bollinger_band` | 布林带 | 截面排名布林位置最低的标的 | 位置 < 0.1: BUY, 位置 > 0.9: SELL |

---

## 八、表达式引擎实现

### 8.1 架构

```mermaid
flowchart TD
    INPUT[表达式字符串] --> LEXER[词法分析]
    LEXER --> PARSER[语法分析]
    PARSER --> AST[抽象语法树]
    AST --> EVAL[求值器]

    FACTORS[因子值字典] --> EVAL
    SIGNALS[信号值字典] --> EVAL

    EVAL --> RESULT[规则结果<br/>pass/fail + score]
```

### 8.2 表达式语法

```
expression := or_expr
or_expr    := and_expr ('or' and_expr)*
and_expr   := cmp_expr ('and' cmp_expr)*
cmp_expr   := primary (('>=' | '<=' | '>' | '<' | '==' | '!=') primary)?
primary    := NUMBER | FACTOR_ID | FUNC_CALL | '(' expression ')'
FUNC_CALL  := FUNC_NAME '(' arg_list ')'
FUNC_NAME  := 'rank' | 'zscore' | 'delta' | 'ma' | 'std' |
              'cross_above' | 'cross_below' | 'abs' | 'log' | 'sign' |
              'max' | 'min' | 'percentile'
FACTOR_ID  := [a-z_][a-z0-9_]*    # 匹配 factor_registry 中的 factor_id
NUMBER     := [0-9]+('.'[0-9]+)?
```

### 8.3 求值器

```python
class ExpressionEvaluator:
    """表达式求值器。"""

    def evaluate(self, expr: str, factor_values: dict, kline_df: DataFrame = None) -> bool | float:
        ast = self.parse(expr)
        return self._eval_node(ast, factor_values, kline_df)

    def _eval_node(self, node, factors, kline):
        if node.type == "FACTOR_ID":
            return factors[node.value]
        if node.type == "NUMBER":
            return node.value
        if node.type == "COMPARE":
            left = self._eval_node(node.left, factors, kline)
            right = self._eval_node(node.right, factors, kline)
            return self._compare(left, right, node.op)
        if node.type == "FUNC_CALL":
            args = [self._eval_node(a, factors, kline) for a in node.args]
            return self._call_func(node.name, args, factors, kline)
        # ... and, or, not
```

### 8.4 cross_above / cross_below 实现

这两个算子需要前一日数据：

```python
def cross_above(self, current, previous):
    """当前值上穿：前一日 < 参考值，当日 >= 参考值。"""
    if previous is None or current is None:
        return False
    return previous < 0 and current >= 0  # 用于 MACD 柱

def cross_above_series(self, series_a, series_b):
    """序列 A 上穿序列 B：前一日 A < B，当日 A >= B。"""
    prev_a, prev_b = series_a.iloc[-2], series_b.iloc[-2]
    curr_a, curr_b = series_a.iloc[-1], series_b.iloc[-1]
    return prev_a < prev_b and curr_a >= curr_b
```

---

## 九、目录结构

```
src/xqtrader/
├── trading/
│   ├── rules/                           # 规则引擎
│   │   ├── __init__.py
│   │   ├── base.py                      # RulePlugin ABC + RuleContext + RuleSignal
│   │   ├── registry.py                  # RuleRegistry 注册表
│   │   ├── expression/                  # 表达式规则引擎
│   │   │   ├── __init__.py
│   │   │   ├── lexer.py                 # 词法分析
│   │   │   ├── parser.py                # 语法分析
│   │   │   ├── evaluator.py             # 求值器
│   │   │   └── operators.py             # 内置算子 (rank, delta, cross_above...)
│   │   ├── combination/                 # 规则组合
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  # CombinationStrategy ABC
│   │   │   ├── and_or.py                # AND/OR 逻辑组合
│   │   │   ├── weighted_score.py        # 加权评分
│   │   │   ├── weighted_vote.py         # 加权投票
│   │   │   └── ic_weighted.py           # IC 加权
│   │   └── plugins/                     # SPI 插件规则
│   │       ├── __init__.py
│   │       ├── macd_cross.py            # MACD 金叉死叉
│   │       ├── kdj_cross.py             # KDJ 金叉死叉
│   │       ├── bollinger_band.py        # 布林带规则
│   │       ├── chan_signal.py           # 缠论信号规则
│   │       ├── cdl_pattern.py           # K线形态规则
│   │       └── volume_break.py          # 放量突破
│   ├── strategy/                        # 策略引擎
│   │   ├── __init__.py
│   │   ├── engine.py                    # StrategyEngine 策略执行
│   │   └── fusion.py                    # SignalFusion 信号融合
│   └── ...
├── domain/trading/
│   ├── models/
│   │   ├── strategy.py                  # strategy, strategy_rule_group, strategy_rule_binding
│   │   ├── rule.py                      # rule_registry, rule_factor_dep
│   │   └── ...
│   └── ...
```

---

## 十、前端交互设计

### 10.1 规则管理页

```
┌─ 规则管理 ────────────────────────────────────────────────────────────────┐
│  [截面规则] [时序规则] [全部]                                               │
│  筛选: [类型▼ 表达式/SPI] [状态▼]                                         │
├──────────────────────────────────────────────────────────────────────────┤
│  rule_id       名称          类型    类别      依赖因子         状态      │
│  cs_roe_filter ROE过滤       表达式  截面      roe             active    │
│  ts_macd_cross MACD金叉死叉  SPI     时序      macd_hist_ratio active    │
│  ts_rsi_signal RSI超买超卖   表达式  时序      rsi_14          active    │
│  ...                                                                      │
│  [+ 新建表达式规则] [+ 新建 SPI 规则]                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

### 10.2 新建表达式规则

```
┌─ 新建表达式规则 ─────────────────────────────────────────────────────────┐
│  规则 ID: [cs_custom_01        ]                                         │
│  名称:   [自定义价值动量规则    ]                                         │
│  类别:   [截面选股 ▼]                                                     │
│                                                                          │
│  表达式:                                                                 │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ rank(ep_ttm) > 0.5 and rank(mom_20d) > 0.5 and hist_vol_20 < 0.3│  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  可用因子: [ep_ttm] [mom_20d] [hist_vol_20] [roe] [pe_ttm] ...         │
│  可用算子: [rank()] [zscore()] [delta()] [ma()] [cross_above()] ...     │
│                                                                          │
│  信号映射:                                                               │
│  条件为 true:  方向 [LONG ▼]  置信度表达式 [zscore(ep_ttm) + zscore(mom_20d)] │
│  条件为 false: 方向 [NEUTRAL ▼] 置信度 [0]                               │
│                                                                          │
│  [验证表达式]  [保存]                                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

### 10.3 策略配置页（驾驶舱"自选&策略" Tab 中）

```
┌─ 策略配置: Alpha-Rebalance-01 ──────────────────────────────────────────┐
│                                                                          │
│  ┌─ 截面选股规则 ─────────────────────────────────────────────────────┐  │
│  │ 组合方式: [加权评分 ▼]  通过阈值: [0.5]                             │  │
│  │                                                                    │  │
│  │ 规则              权重    配置                         [↑↓] [×]    │  │
│  │ ROE 过滤          0.3    threshold=5                        [×]    │  │
│  │ 动量排名          0.4    top_pct=0.3                        [×]    │  │
│  │ 低波过滤          0.3    max_vol=0.3                        [×]    │  │
│  │ [+ 添加规则]                                                       │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ 时序信号规则 ─────────────────────────────────────────────────────┐  │
│  │ 组合方式: [加权投票 ▼]  买入阈值: [0.5]  卖出阈值: [-0.5]          │  │
│  │                                                                    │  │
│  │ 规则              权重    配置                         [↑↓] [×]    │  │
│  │ MACD 金叉死叉     0.3    (默认)                              [×]    │  │
│  │ RSI 超买超卖      0.3    oversold=30, overbought=70         [×]    │  │
│  │ 缠论一买/一卖     0.2    (默认)                              [×]    │  │
│  │ 布林带规则        0.2    oversold=0.1, overbought=0.9        [×]    │  │
│  │ [+ 添加规则]                                                       │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─ 仓位管理 ────────────────────────────────────────────────────────┐  │
│  │ 策略: [ATR 风险 ▼]  ATR周期: [14]  风险预算: [2%]                  │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  [保存配置]  [回测验证]  [上线运行]                                       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 十一、与因子系统的数据流

```mermaid
flowchart TD
    subgraph "因子系统 (已有)"
        FC[FactorComputeTask<br/>日频因子计算]
        FV[fac_factor_value<br/>131 因子]
        SV[fac_signal_value<br/>30 信号]
        CSR[CrossSectionReader<br/>截面加载+标准化]
    end

    subgraph "规则引擎 (新增)"
        RE[RuleRegistry<br/>规则注册表]
        EE[ExpressionEvaluator<br/>表达式求值]
        RP[RulePlugin<br/>SPI 插件]
        RC[CombinationStrategy<br/>规则组合]
    end

    subgraph "策略引擎 (新增)"
        SE[StrategyEngine<br/>策略执行]
        SF[SignalFusion<br/>信号融合]
    end

    subgraph "交易系统 (已有)"
        CS[CrossSectionSelectTool]
        SS[SymbolSignalTool]
        FS[SignalFusionTool]
        PS[PositionSizingTool]
    end

    FV --> EE
    FV --> RP
    SV --> RP
    CSR --> EE
    CSR --> RP

    RE --> EE
    RE --> RP
    EE --> RC
    RP --> RC
    RC --> SE
    SE --> SF

    SF --> CS
    SF --> SS
    SF --> FS
    FS --> PS
```

---

## 十二、业界参考

| 平台 | 借鉴点 | xq-trader 对应 |
|------|--------|---------------|
| WorldQuant BRAIN | FastExpression 表达式即策略 | 表达式规则引擎 + signal_mapping |
| Qlib | 因子表达式 + ML 模型端到端 | 表达式引擎 + SPI 插件双引擎 |
| Zipline Pipeline | Factor/Classifier/Filter 三类型 | 截面规则(Filter) + 时序规则(Factor→Signal) |
| AQR / Two Sigma | ICIR 加权 + IR = IC × √N | IC 加权组合方式 |
| vnpy | CTA 信号交叉检测 | SPI 插件规则 (MACD/KDJ/布林) |
| TradingView | Pine Script 布尔逻辑 | 表达式 AND/OR + cross_above/cross_below |
| DolphinDB | 流批一体 + CEP 事件规则 | SPI 插件支持复杂事件检测 |
