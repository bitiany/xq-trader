---
name: fund-flow
description: 个股资金面专项分析 — 主力资金流向、超大单/大单/中单/小单分布、资金与价格背离信号。当用户询问资金流向、主力资金、超大单、资金净流入流出时触发。
keywords: 资金面, 资金流向, 主力资金, 超大单, 大单, 净流入, 净流出, 资金背离
---

# 个股资金面专项分析

> 本 skill 可被 stock-research 通过 spawn 委托（Worker 模式）。
> **资金面取数的唯一职责方**：在 stock-research 编排中，仅本 Worker 调用 `get_stock_fund_flow`。

**数据纪律**：`get_stock_fund_flow` 只读查询 PostgreSQL 已采集资金流（`sdc_fund_flow_individual`），**不是** Celery 采集任务，禁止触发数据采集。

---

## 模式 A：spawn Worker（被 stock-research 委托时）

**识别**：prompt 含 `模式：spawn` 或 `[spawn-worker:fund-flow]`。

> **记忆边界**：产出为快时钟快照，只进综合报告「资金面简报」节，禁止写入论点卡。

### 工具（仅 1 个）

| 工具 | 职责 |
|------|------|
| `mcp_xq_stocks_xq_get_stock_fund_flow` | 近 N 日主力/超大单/大单净流入 |

参数：`{"symbol": "603993.SH"}`，禁止传 `limit`。

### 分析要点

1. 主力趋势：连续净流入/净流出/震荡
2. 超大单方向与力度
3. 资金与价格背离：顶背离/底背离/无

### 输出（仅 JSON，无其他文字）

```json
{
  "as_of": "2026-07-06",
  "main_flow": {"direction": "持续流入/持续流出/震荡", "net_amount": 1234567.89},
  "super_large_order": {"net_amount": 987654.32, "trend": "流入/流出"},
  "divergence": {"type": "顶背离/底背离/无", "description": "..."},
  "conclusion": "偏多/偏空/中性 + 简述"
}
```

**迭代预算**：≤ 2 轮。

---

## 模式 B：独立触发（用户直接问资金面）

用户直接询问资金面时，先 `read_file` 本 SKILL.md（仅一次），再执行：

1. 调用 `get_stock_fund_flow`
2. 输出完整 Markdown 资金面报告（主力概况/超大单/背离/综合判断）

### 约束

- 数值必须来自工具返回，禁止编造
- 信号方向仅给「偏多/偏空/中性」
