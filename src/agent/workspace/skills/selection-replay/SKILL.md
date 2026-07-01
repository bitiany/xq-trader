---
name: selection-replay
description: 浏览样本池、按策略/日期检索历史选股结果。当用户希望查看某策略在某信号日的入选标的、复盘历史选股、浏览样本池构成时触发。
keywords: 选股, 选股结果, 样本池, universe, 复盘, 候选
---

# 选股复盘

## 触发条件

用户希望查看某策略在某信号日的入选标的、复盘历史选股、浏览样本池构成时触发。

## 可用工具

来自 MCP 分组 `xq_selection`（必需）与 `xq_stocks`（用于补股票名称等）。

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `mcp_xq_selection_xq_list_universe_pools` | 样本池列表（内置 + 数据库） | `include_db` |
| `mcp_xq_selection_xq_get_universe_pool_symbols` | 样本池内的标的 | `pool_id`, `keyword`, `page` |
| `mcp_xq_selection_xq_list_selection_results` | 历史选股结果分页查询 | `strategy_id`, `signal_date`, `instance_id` |
| `mcp_xq_selection_xq_list_selection_result_dates` | 某策略的所有信号日 | `strategy_id`, `instance_id` |
| `mcp_xq_stocks_xq_get_stock_overview` | 获取某入选标的的最新行情 | `symbol` |

## 执行流程

1. 若用户未指定信号日：先 `mcp_xq_selection_xq_list_selection_result_dates` 取最新若干日。
2. 用 `mcp_xq_selection_xq_list_selection_results` 拉某日入选标的（按 rank 排序）。
3. 必要时对前 3 只入选标的并行调用 `mcp_xq_stocks_xq_get_stock_overview` 补充实时行情。
4. 输出 Markdown 表格：rank / symbol / name / score / direction / 关键因子值。

## 约束

- 不进行实时选股运行（避免 POST），只做历史结果复盘。
- 因子值字段含 `factor_values_flat`，渲染时取前 5 个最具代表性的字段即可。

## 示例对话

用户: "昨天选股选了哪些"
步骤:
1. 调用 `mcp_xq_selection_xq_list_selection_result_dates` 取最近信号日
2. 调用 `mcp_xq_selection_xq_list_selection_results`（signal_date=最新日）
3. 输出 rank / symbol / name / score / direction 表格

用户: "样本池有哪些"
步骤:
1. 调用 `mcp_xq_selection_xq_list_universe_pools`（include_db=true）
2. 输出样本池列表（pool_id / name / count）
