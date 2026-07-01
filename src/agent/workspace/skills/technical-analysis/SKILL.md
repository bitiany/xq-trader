---
name: technical-analysis
description: 个股技术面专项分析 — 通过趋势/动量/缠论/估值等诊断工具，输出趋势定级、关键位、买卖信号、量价配合与综合技术结论。当用户询问技术面、走势、支撑压力位、买卖点、形态、趋势、量价时触发。
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

> 若用户要求"全方位分析/基本面+技术面"，路由到 stock-analysis；纯技术面问题才用本 skill。

## 可用工具

来自 MCP 分组 `xq_stocks`。

| 工具名 | 职责 | 关键参数 |
|--------|------|---------|
| `mcp_xq_stocks_xq_get_stock_kline_bars` | 纯 OHLCV 行情（量价原始数据） | `symbol`, `limit` |
| `mcp_xq_stocks_xq_get_stock_trend` | 趋势诊断（方向/均线排列/ADX/BOLL位置/价格vs MA60） | `symbol`, `limit` |
| `mcp_xq_stocks_xq_get_stock_momentum` | 动量诊断（MACD/KDJ/RSI/TD9 信号） | `symbol`, `limit` |
| `mcp_xq_stocks_xq_get_stock_chanlun` | 缠论诊断（笔/段/中枢/买卖点） | `symbol` |
| `mcp_xq_stocks_xq_get_stock_valuation` | 估值诊断（PE/PB分位/市值/换手率/量比） | `symbol` |

**调用规范**：`symbol` 必须带后缀（如 `002049.SZ`）；独立工具可并行调用。

## 执行流程

1. **趋势定级**：调用 `get_stock_trend` → 读取 `direction`（多头/空头/震荡）、`ma_alignment`（多头/空头排列/纠缠）、`adx_label`（趋势强度）、`boll_position`、`price_vs_ma60`。确定趋势方向与级别。
2. **动量信号扫描**：调用 `get_stock_momentum` → 读取 MACD `signal`（金叉/死叉/多头运行/背离）、KDJ `signal`（金叉/死叉/超买/超卖）、RSI `signal`、TD9 `signal`（买入/卖出 setup 完成）。汇总当前买卖信号清单。
3. **缠论买卖点**：调用 `get_stock_chanlun` → 读取当前笔/段/中枢结构，识别缠论买卖点（一买/二买/三买/一卖/二卖/三卖）。
4. **量价配合**：调用 `get_stock_kline_bars`（limit=30）→ 观察近期量价关系（放量上涨/缩量下跌/量价背离/天量见天价）。
5. **估值配合**：调用 `get_stock_valuation` → 读取 `valuation_label`（高估/合理/低估）、`pe_ttm_percentile`、`turnover_rate`、`volume_ratio`，判断技术面位置与估值是否匹配。
6. **综合技术结论**：综合前五步形成技术面判断。

## 输出要求

`# {股票名称}（{代码}）技术面分析`，含六节：
1. **趋势研判**：方向 + 级别 + 均线排列 + ADX 强度
2. **关键位**：支撑位/压力位（基于 BOLL 上下轨、均线、缠论中枢）
3. **信号清单**：MACD/KDJ/RSI/TD9 当前信号（表格）
4. **缠论结构**：当前笔/段/中枢 + 买卖点
5. **量价与估值**：量价配合状态 + 估值分位
6. **技术综合判断**：方向（偏多/偏空/中性）+ 依据 + 风险提示

标注数据截至日期；所有结论须来自工具返回，禁止编造。

## 约束

1. 技术面数据必须来自 `mcp_xq_stocks_xq_*` 工具返回，严禁编造指标数值。
2. 信号解读须基于工具返回的 `signal`/`direction` 字段，不可主观臆测。
3. 缠论买卖点须基于 `get_stock_chanlun` 返回结构推断，标注所依据的笔/段/中枢。
4. 不输出具体买卖价位、仓位与止损；仅给方向性技术判断与关键位参考。
5. 工具调用失败必须如实标注数据缺失。

## 示例对话

用户: "紫光国微技术面怎么样"
步骤:
1. 并行调用 `get_stock_trend`(002049.SZ) + `get_stock_momentum`(002049.SZ) + `get_stock_chanlun`(002049.SZ) + `get_stock_valuation`(002049.SZ)
2. 调用 `get_stock_kline_bars`(002049.SZ, limit=30) 看量价
3. 汇总趋势/动量/缠论/量价/估值 → 输出技术面分析报告

用户: "茅台有没有买卖信号"
步骤:
1. 并行调用 `get_stock_trend` + `get_stock_momentum` + `get_stock_chanlun`
2. 聚焦 MACD/KDJ/RSI/TD9 信号 + 缠论买卖点
3. 输出信号清单与综合判断
