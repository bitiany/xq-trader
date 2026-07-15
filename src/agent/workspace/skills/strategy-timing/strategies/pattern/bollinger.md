# 布林带突破策略（bollinger）

> rule_id: `ts_bollinger_break` | 类别: pattern | SPI 插件: BollingerPlugin
> 消费因子: `boll_upper`, `boll_middle`, `boll_lower`

---

## 核心逻辑

布林带通过统计学标准差衡量价格波动范围，是兼具趋势识别与波动率衡量的形态策略。

- **突破上轨**：价格突破 boll_upper，强势突破信号，多头加速。
- **跌破下轨**：价格跌破 boll_lower，弱势跌破信号，空头加速。
- **轨道收敛**：boll_upper - boll_lower 收窄，预示变盘临近。
- **中轨支撑/压力**：boll_middle（MA20）是中期支撑或压力位。

---

## 信号判定规则

| 信号 | 条件 |
|------|------|
| buy | 价格突破 boll_upper，且 boll_width 处于扩张状态 |
| sell | 价格跌破 boll_lower，且 boll_width 处于扩张状态 |
| neutral | 价格在 boll_upper 与 boll_lower 之间运行 |

**收敛变盘预警**：boll_width 处于近 60 日低位（< 20% 分位）时，
不发交易信号但标注「变盘临近」，提示 Orchestrator 关注后续突破方向。

---

## 适用市场环境

| market_regime | 适用性 | 权重调整 |
|---------------|--------|---------|
| trending_up | ⚠️ 仅突破上轨信号有效 | ×1.0 |
| trending_down | ⚠️ 仅跌破下轨信号有效 | ×1.0 |
| sideways | ✅ 强适用（变盘预警） | ×1.3 |
| volatile | ✅ 适用（波动率扩张） | ×1.1 |

---

## 信号权重建议

- 默认权重：1.0
- 突破伴随放量（vol_ratio > 1.5）：权重 ×1.2
- 轨道收敛后突破（变盘信号）：权重 ×1.3，置信度 +0.1
- 突破后回踩中轨（boll_middle）获支撑：权重 ×1.1

---

## 风险提示

1. 布林带突破是**形态信号**，需配合趋势类策略（ma_cross/momentum）确认方向。
2. 强趋势中价格可能沿上轨或下轨运行较长时间，过早反向操作风险高。
3. 轨道收敛后的变盘方向需结合 market_regime 与基本面方向判断。
4. 单独使用胜率有限，建议作为共振策略而非主信号。
