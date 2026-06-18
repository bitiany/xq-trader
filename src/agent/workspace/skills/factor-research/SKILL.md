---
name: factor-research
description: 因子研究 — 浏览因子注册表、查询截面因子值、查看因子最新评估快照。
keywords: 因子, factor, IC, 选股因子, 因子值, 因子分布
---

# 因子研究

## 触发条件

用户询问因子定义、可用因子分类、某因子的当前值与统计指标时触发，例如：
- "有哪些可用的因子"
- "查一下 PE_TTM 因子的最新值"
- "这个因子的 IC 怎么样"

## 可用工具

来自 MCP 分组 `xq_factors`。

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `mcp_xq_factors_xq_list_factors` | 因子注册表分页查询 | `category`, `status`, `keyword`, `page`, `page_size` |
| `mcp_xq_factors_xq_list_factor_categories` | 因子分类聚合 | — |
| `mcp_xq_factors_xq_get_factor` | 单因子详情 | `factor_id` |
| `mcp_xq_factors_xq_get_factor_values` | 截面因子值 | `factor_id`, `trade_date`, `pool_id`, `symbols`, `limit` |
| `mcp_xq_factors_xq_get_factor_stats_latest` | 因子最新评估快照（IC/ICIR/胜率/分层） | `factor_id`, `pool_id` |

## 执行流程

1. **明确意图**：用户找因子？查值？看评估？
2. **若找因子**：先 `list_factor_categories` 显示分类，再 `list_factors` 用 `keyword` 过滤。
3. **若查因子值**：必须传 `trade_date`；如未指定 `pool_id` 默认用 `all`；symbol 可选。
4. **若看评估**：用 `get_factor_stats_latest`，结合 IC、ICIR、分层收益给出解读。
5. 输出 Markdown，对关键字段加粗，对数据来源标注 trade_date / calc_date。

## 约束

- 因子值返回为列表，必要时按 `factor_value` 排序展示前 N 行。
- 不要凭名称推断因子语义，必须先调 `get_factor` 拿 description。
