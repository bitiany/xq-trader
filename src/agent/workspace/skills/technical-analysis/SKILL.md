---
name: technical-analysis
description: 个股技术面专项分析 — 通过综合技术诊断与缠论工具，输出趋势定级、关键位、买卖信号、量价配合与综合技术结论。当用户询问技术面、走势、支撑压力位、买卖点、形态、趋势、量价时触发。
keywords: 技术面, 走势, 支撑位, 压力位, 买卖点, 形态, 趋势, 量价, K线, 均线, MACD, KDJ, RSI, 缠论, 动量, 超买, 超卖, 金叉, 死叉
---

# 个股技术面专项分析

> 若用户要求「全方位分析/基本面+技术面」，路由到 stock-research。
> 本 skill 可被 stock-research 通过 spawn 委托（Worker 模式）。

**数据纪律**：MCP 工具只读查询本地已采集数据，禁止触发数据采集。

---

## 模式 A：spawn Worker（被 stock-research 委托时）

**识别**：prompt 含 `模式：spawn` 或 `[spawn-worker:technical]`。

### 工具（仅 2 个，一轮并行）

| 工具 | 职责 |
|------|------|
| `mcp_xq_stocks_xq_get_stock_technical` | 趋势+动量+ATR+量价 |
| `mcp_xq_stocks_xq_get_stock_chanlun` | 缠论结构 |

**禁止**：
- `get_stock_valuation`（Orchestrator 五步法已取估值）
- `read_file`
- Markdown 长报告

### 输出（仅 JSON，无其他文字）

> **记忆边界**：spawn 产出为快时钟快照，只供 Orchestrator 写入综合报告「技术面简报」节，
> **禁止**写入论点卡 `save_stock_thesis`。`quote.close` 须从 `recent_bars[-1].close` 提取。

```json
{
  "as_of": "2026-07-06",
  "quote": {"close": 18.31, "change_pct": -1.13, "open": 18.53, "high": 19.21, "low": 18.28},
  "trend": {"direction": "多头排列/空头排列/震荡", "level": "日线/周线", "adx": 28},
  "key_levels": {"support": [12.30, 11.80], "resistance": [13.50]},
  "signals": {"macd": "金叉/死叉", "kdj": "高位/低位", "rsi": 62, "td9": null},
  "chanlun": {"structure": "上涨中枢/下跌中枢", "buy_sell_point": "一买/二买/三买/一卖/二卖/三卖/无"},
  "volume_price": "放量突破/缩量回调/量价背离/量价配合",
  "atr": {"atr_14": 0.42, "stop_distance": 0.84},
  "conclusion": "偏多/偏空/中性 + 简述"
}
```

**迭代预算**：≤ 2 轮（1 轮取数 + 1 轮输出 JSON）。

---

## 模式 B：独立触发（用户直接问技术面）

用户直接询问技术面时，先 `read_file` 本 SKILL.md（仅一次），再执行：

### 工具

| 工具 | 职责 |
|------|------|
| `mcp_xq_stocks_xq_get_stock_technical` | 趋势+动量+ATR+量价 |
| `mcp_xq_stocks_xq_get_stock_chanlun` | 缠论 |
| `mcp_xq_stocks_xq_get_stock_valuation` | 估值配合 |

### 执行流程

1. 并行调用 `get_stock_technical` + `get_stock_chanlun` + `get_stock_valuation`
2. 输出完整 Markdown 技术面报告（六节：趋势/关键位/信号/缠论/量价估值/综合判断）

### 约束

- `symbol` 格式：`代码.市场`（如 `688322.SH`）
- 禁止已下线工具（`get_stock_kline` / `get_stock_trend` / `get_stock_momentum`）
- 参数仅 `{"symbol": "..."}` 形式
- 数值必须来自工具返回，禁止编造
