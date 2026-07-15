---
name: sentiment-analysis
description: 监控个股新闻舆情、分析市场情绪倾向、捕捉事件驱动信号。当用户询问某股票近期新闻、舆情风向、重大事件影响、市场情绪时触发。
keywords: 舆情, 情绪, 新闻, 消息面, 事件驱动, 利好, 利空, 公告
---

# 舆情与情绪面分析

> 本 skill 可被 stock-research 通过 spawn 委托（Worker 模式）。
> 资金流向由 fund-flow Worker 负责，本 skill 不调用资金流工具。

**数据纪律**：MCP 工具只读查询本地已采集数据，禁止触发数据采集。

---

## 模式 A：spawn Worker（被 stock-research 委托时）

**识别**：prompt 含 `模式：spawn` 或 `[spawn-worker:sentiment]`。

> **记忆边界**：产出为快时钟快照，只进综合报告「情绪面简报」节，禁止写入论点卡。

### 工具（仅 1 个）

| 工具 | 职责 |
|------|------|
| `mcp_xq_sentiment_xq_get_stock_sentiment` | 个股舆情快照（情感分/热度/关键词） |

**禁止**：
- `get_stock_news` / `get_stock_announcements`（Orchestrator 五步法已取，避免重复查库）
- `web_search` / `web_fetch`
- `read_file`（含 references）
- Markdown 长报告

情绪研判基于舆情快照的 `sentiment_score`、`heat_score`、正负面提及数与关键词即可。

### 输出（仅 JSON，无其他文字）

```json
{
  "as_of": "2026-07-06",
  "sentiment_index": "贪婪/中性/恐慌",
  "sentiment_score": 0.35,
  "heat_score": 72.5,
  "bullish_factors": ["..."],
  "bearish_factors": ["..."],
  "policy_impact": "...",
  "event_signal": "偏多/偏空/中性",
  "conclusion": "情绪偏多/偏空/中性 + 简述"
}
```

**迭代预算**：≤ 2 轮。

---

## 模式 B：独立触发（用户直接问舆情/新闻）

用户直接询问舆情、新闻、公告时，先 `read_file` 本 SKILL.md（仅一次），再执行：

### 工具

| 工具 | 用途 |
|------|------|
| `mcp_xq_sentiment_xq_get_stock_sentiment` | 个股舆情快照 |
| `mcp_xq_stocks_xq_get_stock_news` | 个股新闻 |
| `mcp_xq_stocks_xq_get_stock_announcements` | 个股公告 |
| `mcp_xq_events_xq_detect_events` | 轻量事件检测（两层：关键词+LLM，补充事件信号） |
| `web_search` | 补充搜索（最多 1 次） |

### 执行流程

1. 并行调用 `get_stock_sentiment` + `get_stock_news` + `get_stock_announcements` + `detect_events`
2. 综合舆情快照、新闻公告与事件检测，研判情绪指数（贪婪/中性/恐慌）
3. 输出完整 Markdown 舆情报告（含事件信号节）

### 情绪指数规则（内联）

- `sentiment_score > 0.3` 且正面提及占优 → 贪婪
- `sentiment_score < -0.3` 且负面提及占优 → 恐慌
- 其余 → 中性

### 输出格式（模式 B）

```markdown
# {symbol} 舆情与事件报告（{date}）

## 情绪快照
- 情绪指数：贪婪/中性/恐慌（得分 {score}）
- 热度：{heat_score}
- 偏多因素：...
- 偏空因素：...

## 近期新闻
（新闻列表，标注来源与时间）

## 近期公告
（公告列表，标注类型与时间）

## 事件信号
- 利好事件：...（来自 detect_events，若有）
- 利空事件：...（若有）
- 交易信号映射：...（severity ≥ 4 的事件附历史统计影响）

## 结论
情绪偏多/偏空/中性 + 关键事件提示
```

### 约束

- 情绪判断须基于工具返回数据，不可凭空推断
- 信号方向仅给「偏多/偏空/中性」，不输出具体买卖建议
- 事件检测仅输出信号摘要，不触发论点卡失效（论点卡失效由 event-monitor Orchestrator 负责）
