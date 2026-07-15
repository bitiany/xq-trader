# 策略方法论知识库

> 本目录是 strategy-timing Orchestrator 的参考资料库（非独立 skill）。
> 各策略 .md 描述该策略的核心逻辑、信号判定规则、适用市场环境与风险提示，
> 供 Orchestrator 在阶段 B（策略选择）和阶段 D（综合聚合）参考。

---

## 策略索引（13 个）

### 趋势类（trend）

| 策略 | rule_id | 消费因子 | 方法论 |
|------|---------|---------|--------|
| 均线交叉 | ts_ma_cross | ma_short, ma_long | [trend/ma_cross.md](trend/ma_cross.md) |
| 量价突破 | ts_volume_price | vol_ma_20, vol_ratio, volume | [trend/volume_price.md](trend/volume_price.md) |
| 动量趋势 | ts_momentum | mom_5d, mom_20d, mom_10d | [trend/momentum.md](trend/momentum.md) |
| MACD 金叉 | macd | macd, signal, hist, hist_slope, hist_area | （内置 SPI 插件，方法论待补充） |
| ADX 趋势 | ts_adx_trend | adx_14, adx_plus_di, adx_minus_di | （内置 SPI 插件，方法论待补充） |
| 量比突破 | ts_vol_ratio | vol_ratio, vol_ma_20 | （内置 SPI 插件，方法论待补充） |
| 海龟唐奇安 | ts_donchian_turtle | donchian_high_20, donchian_low_10, atr_14 | （内置 SPI 插件，方法论待补充） |

### 形态类（pattern）

| 策略 | rule_id | 消费因子 | 方法论 |
|------|---------|---------|--------|
| 布林带突破 | ts_bollinger_break | boll_upper, boll_middle, boll_lower | [pattern/bollinger.md](pattern/bollinger.md) |
| KDJ 金叉 | ts_kdj_cross | kdj_k, kdj_d, kdj_j | [pattern/kdj.md](pattern/kdj.md) |

### 反转类（reversal）

| 策略 | rule_id | 消费因子 | 方法论 |
|------|---------|---------|--------|
| 缠论买卖点 | ts_chanlun_signal | chan_buy_point, chan_sell_point, chan_bi_direction | [reversal/chanlun.md](reversal/chanlun.md) |
| RSI 背离 | ts_rsi_divergence | rsi_14 | [reversal/rsi_divergence.md](reversal/rsi_divergence.md) |
| 乖离反转 | ts_bias_reversal | bias_6 | [reversal/bias_reversal.md](reversal/bias_reversal.md) |
| 神奇九转 | ts_td_sequential | td_seq_buy, td_seq_sell, td_seq_count | [reversal/td_sequential.md](reversal/td_sequential.md) |

---

## 7 条核心交易理念（摘要）

完整版见 [framework/core_trading_principles.md](framework/core_trading_principles.md)。

1. **严进策略**：乖离率 < 5% 才考虑入场。
2. **趋势交易**：MA 多头排列优先，震荡市禁用纯趋势策略。
3. **量价配合**：成交量验证价格运动，买入需量能放大 20% 以上。
4. **买点偏好**：优先回踩均线支撑，追突破需量价共振确认。
5. **风险排查**：利空一票否决（联动 event-monitor）。
6. **效率优先**：量能确认趋势有效性，缩量上涨不可持续。
7. **强势趋势股放宽**：龙头股可适当放宽乖离率与量比阈值。

---

## 使用方式

- Orchestrator 在阶段 B（策略选择）参考各策略的「适用市场环境」字段。
- Orchestrator 在阶段 D（综合聚合）参考各策略的「信号权重建议」字段。
- 7 条核心交易理念作为加权聚合的先验约束，优先级高于单策略信号。
- 本目录文件**仅作为参考资料**，Orchestrator 不主动 `read_file` 加载（SKILL.md 已内联必要规则）；
  仅在需要解释某个策略的判定逻辑时按需读取对应 .md。
