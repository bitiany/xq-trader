---
name: factor-research
description: 查询平台全部活跃因子元数据及单标的宽表时序（按 trade_date 一行、factor_id 为列）。当用户询问因子定义、因子值、IC 评估、某标的因子面板时触发。
keywords: 因子, factor, IC, 选股因子, 因子值, 因子分布, 宽表
---

# 因子研究

## 触发条件

用户询问因子定义、因子值、评估指标或某标的因子面板时触发，例如：
- "有哪些可用的因子"
- "查一下 688322.SH 的因子时序"
- "PE_TTM 因子最新值是多少"
- "这个因子的 IC 怎么样"

## 可用工具

来自 MCP 分组 `xq_factors`，**仅一个工具**：

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `mcp_xq_factors_xq_get_stock_factor_series` | 平台全部 active 因子元数据 + 单标的宽表时序 | `symbol` |

**可选参数**（一般可不传，使用默认近 120 交易日）：
- `start_date` / `end_date`：YYYY-MM-DD
- `pool_id`：默认 `all`

**调用规范**：
- 参数格式：`{"symbol": "688322.SH"}`，禁止传入响应字段（如 `rows`、`factors`）。
- 返回结构：
  - `factors`：全部活跃因子元数据（含 `description`、`latest_stats`）
  - `columns`：`["trade_date", factor_id, ...]`
  - `rows`：宽表时序，每行 `trade_date` + 各因子平级字段

## 执行流程

1. **明确标的**：必须提供 `symbol`（带后缀，如 `688322.SH`）。
2. **调用** `mcp_xq_factors_xq_get_stock_factor_series` 一次即可，无需拆分多工具。
3. **若用户问「有哪些因子」**：从返回的 `factors` 数组列出 `factor_id` / `display_name` / `category`。
4. **若用户问某因子最新值**：取 `rows` 最后一行对应 `factor_id` 列。
5. **若用户问 IC/评估**：从 `factors[].latest_stats` 读取 IC/ICIR/胜率/分层等指标解读。
6. 输出 Markdown，标注 `start_date`/`end_date`/`trade_date` 数据来源。

## 约束

- 不要凭名称推断因子语义，以返回的 `factors[].description` 为准。
- 宽表缺失值以 `null` 表示，解读时说明缺失原因（如截面因子未覆盖该日期）。
- 禁止调用已下线的拆分工具（`list_factors` / `get_factor_values` 等）。

## 示例对话

用户: "688322.SH 有哪些因子值"
步骤:
1. 调用 `get_stock_factor_series`({"symbol": "688322.SH"})
2. 从 `factors` 展示因子目录，从 `rows` 最近一行展示主要因子值

用户: "ma_bias_5 因子 IC 怎么样"
步骤:
1. 调用 `get_stock_factor_series`({"symbol": "688322.SH"})（或用户上下文中的 symbol）
2. 在 `factors` 中找到 `ma_bias_5`，读取 `latest_stats` 解读 IC/ICIR
