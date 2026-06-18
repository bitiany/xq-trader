---
name: strategy-inspect
description: 策略与规则结构解读 — 策略列表、规则组、规则绑定、规则依赖因子。
keywords: 策略, 规则, rule, strategy, 规则组, 绑定
---

# 策略与规则结构解读

## 触发条件

用户询问平台策略组成、某策略的规则组与绑定、规则依赖哪些因子时触发。

## 可用工具

来自 MCP 分组 `xq_strategies`（必需）与 `xq_factors`（用于回查因子定义）。

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `mcp_xq_strategies_xq_list_strategies` | 策略列表 | `status`, `keyword`, `page`, `page_size` |
| `mcp_xq_strategies_xq_get_strategy` | 策略详情（含规则组与绑定） | `strategy_id` |
| `mcp_xq_strategies_xq_list_strategy_rule_groups` | 策略下的规则组 | `strategy_id` |
| `mcp_xq_strategies_xq_list_rule_group_bindings` | 规则组下的规则绑定 | `strategy_id`, `group_id` |
| `mcp_xq_strategies_xq_list_rules` | 规则注册表 | `category`, `type`, `status`, `keyword` |
| `mcp_xq_strategies_xq_get_rule` | 规则详情 | `rule_id` |
| `mcp_xq_factors_xq_get_factor` | 回查规则依赖的因子定义 | `factor_id` |

## 执行流程

1. 用户给出 `strategy_id` 时，直接 `mcp_xq_strategies_xq_get_strategy` 获取一站式视图。
2. 否则先 `mcp_xq_strategies_xq_list_strategies` 用 `keyword` 过滤候选，再让用户确认 `strategy_id`。
3. 解读规则组职责（截面 / 时序）、规则绑定的权重与方向。
4. 如需要，针对绑定的规则用 `mcp_xq_strategies_xq_get_rule` 看表达式，再 `mcp_xq_factors_xq_get_factor` 回查依赖因子。

## 约束

- 不修改任何策略、规则与绑定（read-only）。
- 输出时保留 `strategy_id`、`group_id`、`binding_id` 便于用户复查。
