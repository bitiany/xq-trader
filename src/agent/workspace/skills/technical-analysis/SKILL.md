---
name: technical-analysis
description: 个股技术面专项分析 — 通过综合技术诊断与缠论工具，输出趋势定级、关键位、买卖信号、量价配合与综合技术结论。当用户询问技术面、走势、支撑压力位、买卖点、形态、趋势、量价时触发。
keywords: 技术面, 走势, 支撑位, 压力位, 买卖点, 形态, 趋势, 量价, K线, 均线, MACD, KDJ, RSI, 缠论, 动量, 超买, 超卖, 金叉, 死叉
---

# 个股技术面专项分析

## 触发条件

用户询问个股技术面相关问题时触发，例如：
- "XXX 技术面怎么样"
- "XXX 支撑位压力位在哪"
- "XXX 有没有买卖信号"
- "XXX 趋势如何/量价配合怎么样"
- "用缠论分析一下 XXX"
- "对 XXX 进行技术面分析，并提供交易建议"

> 若用户要求"全方位分析/基本面+技术面"，路由到 stock-research；纯技术面问题才用本 skill。
> 本 skill 可被 stock-research 通过 spawn 委托执行（作为 Worker）。

## 可用工具

来自 MCP 分组 `xq_stocks`。

| 工具名 | 职责 | 关键参数 |
|--------|------|---------|
| `mcp_xq_stocks_xq_get_stock_technical` | **连续型技术指标一次性返回**：趋势 + 动量 + ATR 波动 + 近30日量价 | `symbol` |
| `mcp_xq_stocks_xq_get_stock_chanlun` | 缠论诊断（笔/段/中枢/买卖点，非连续数据单独调用） | `symbol` |
| `mcp_xq_stocks_xq_get_stock_valuation` | 估值诊断（PE/PB分位/市值/换手率/量比） | `symbol` |

**调用规范**：
- `symbol` 必须带后缀（如 `688322.SH`）。
- **禁止**调用已下线的拆分工具（`get_stock_kline` / `get_stock_trend` / `get_stock_momentum` / `get_stock_kline_bars`）。
- 连续型指标只调用 `get_stock_technical` 一次；缠论单独调用 `get_stock_chanlun`。
- 参数只能是 `{"symbol": "688322.SH"}` 形式，**禁止**传入 `bars`、`limit` 等响应字段或可选参数。

## 执行流程

1. **综合技术诊断**：调用 `get_stock_technical` → 从 `trend` 读取方向/均线/ADX/BOLL；从 `momentum` 读取 MACD/KDJ/RSI/TD9；从 `volatility` 读取 `atr_14`/`stop_distance`/止损目标位；从 `recent_bars` 分析量价。
2. **缠论买卖点**：调用 `get_stock_chanlun` → 读取笔/段/中枢结构，识别缠论买卖点。
3. **估值配合**：调用 `get_stock_valuation` → 读取估值分位与换手/量比，判断技术面位置与估值是否匹配。
4. **综合技术结论**：综合前三步形成技术面判断与明日交易建议（方向性，不含具体价位/仓位）。

## 输出要求

`# {股票名称}（{代码}）技术面分析`，含六节：
1. **趋势研判**：方向 + 级别 + 均线排列 + ADX 强度
2. **关键位**：支撑位/压力位（基于 BOLL 上下轨、均线、缠论中枢）
3. **信号清单**：MACD/KDJ/RSI/TD9 当前信号（表格）
4. **缠论结构**：当前笔/段/中枢 + 买卖点
5. **量价与估值**：量价配合状态 + 估值分位
6. **技术综合判断与交易建议**：方向（偏多/偏空/中性）+ 明日关注要点 + 风险提示

标注数据截至日期；所有结论须来自工具返回，禁止编造。

## 约束

1. 技术面数据必须来自 `mcp_xq_stocks_xq_*` 工具返回，严禁编造指标数值。
2. 信号解读须基于工具返回的 `signal`/`direction` 字段，不可主观臆测。
3. 缠论买卖点须基于 `get_stock_chanlun` 返回结构推断，标注所依据的笔/段/中枢。
4. 不输出具体买卖价位、仓位与止损；仅给方向性技术判断与关键位参考。
5. 工具调用失败必须如实标注数据缺失。

## Worker 返回契约（被 spawn 调用时）

当被 stock-research 通过 spawn 委托时，除输出上述报告外，在最后附上结构化 JSON 结论：

```json
{
  "as_of": "2026-07-01",
  "trend": {"direction": "多头排列/空头排列/震荡", "level": "日线/周线", "adx": 28},
  "key_levels": {"support": [12.30, 11.80], "resistance": [13.50]},
  "signals": {"macd": "金叉/死叉", "kdj": "高位/低位", "rsi": 62, "td9": null},
  "chanlun": {"structure": "上涨中枢/下跌中枢", "buy_sell_point": "一买/二买/三买/一卖/二卖/三卖/无"},
  "volume_price": "放量突破/缩量回调/量价背离/量价配合",
  "atr": {"atr_14": 0.42, "stop_distance": 0.84},
  "conclusion": "偏多/偏空/中性 + 简述"
}
```

## 示例对话

用户: "请对奥比中光（688322.SH）进行技术面分析，并提供明日的交易建议"
步骤:
1. 调用 `get_stock_technical`({"symbol": "688322.SH"})
2. 并行调用 `get_stock_chanlun`({"symbol": "688322.SH"}) + `get_stock_valuation`({"symbol": "688322.SH"})
3. 汇总趋势/动量/量价/缠论/估值 → 输出技术面分析与明日交易建议
