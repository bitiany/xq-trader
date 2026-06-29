---
name: position-review
description: 查询账户资产、持仓、当日委托与成交（仅只读）。当用户询问当前账户持仓、可用资金、当日委托/成交、单只标的盈亏时触发。
keywords: 持仓, 资产, 委托, 成交, 盘点, position, asset
---

# 持仓盘点

## 触发条件

用户询问当前账户持仓、可用资金、当日委托/成交、单只标的盈亏时触发。

## 可用工具

来自 MCP 分组 `xq_positions`（必需）与 `xq_stocks`（用于补当前价）。

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `mcp_xq_positions_xq_get_broker_asset` | 资金资产快照 | — |
| `mcp_xq_positions_xq_list_broker_positions` | 全部持仓 | — |
| `mcp_xq_positions_xq_get_broker_position` | 单只持仓 | `stock_code` |
| `mcp_xq_positions_xq_list_broker_orders` | 当日委托 | `cancelable_only` |
| `mcp_xq_positions_xq_list_broker_trades` | 当日成交 | — |
| `mcp_xq_stocks_xq_get_stock_overview` | 用于补当前价/涨跌幅 | `symbol` |

## 执行流程

1. 用户问"账户怎么样"：先 `mcp_xq_positions_xq_get_broker_asset` 再 `mcp_xq_positions_xq_list_broker_positions`，输出 总资产 / 可用 / 持仓市值 / 当日盈亏。
2. 用户问某只股票持仓：直接 `mcp_xq_positions_xq_get_broker_position`，结合 `mcp_xq_stocks_xq_get_stock_overview` 补最新价计算浮盈浮亏。
3. 用户问当日交易：分别调用 `mcp_xq_positions_xq_list_broker_orders` 和 `mcp_xq_positions_xq_list_broker_trades`，对比委托与成交差异。
4. 数据缺失或 QMT 未连接时，明确返回"行情/交易服务未连接"，不要编造。

## 约束

- 严禁触发任何下单、撤单、连接管理操作（这些都不在 MCP 暴露面中）。
- 涉及资金数据时统一以"元"为单位，金额保留 2 位小数。
- 不给出具体买卖建议。
- 输出遵守 AGENTS.md Markdown 排版规范，段落间最多 1 空行。

## 示例对话

用户: "账户怎么样"
步骤:
1. 调用 `mcp_xq_positions_xq_get_broker_asset`
2. 调用 `mcp_xq_positions_xq_list_broker_positions`
3. 输出总资产 / 可用资金 / 持仓市值 / 当日盈亏

用户: "我茅台持仓多少"
步骤:
1. 调用 `mcp_xq_positions_xq_get_broker_position`（stock_code="600519.SH"）
2. 调用 `mcp_xq_stocks_xq_get_stock_overview`（symbol="600519.SH"）补最新价
3. 计算浮盈浮亏，输出持仓明细
