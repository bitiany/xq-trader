---
name: sentiment-analysis
description: 监控个股新闻舆情、分析市场情绪倾向、捕捉事件驱动信号。当用户询问某股票近期新闻、舆情风向、重大事件影响、市场情绪时触发。
keywords: 舆情, 情绪, 新闻, 消息面, 事件驱动, 利好, 利空, 公告
---

# 舆情与情绪面分析

## 触发条件

用户询问某股票的近期新闻、舆情风向、重大事件影响、市场情绪时触发，例如：
- "XXX 最近有什么新闻"
- "XXX 最近的舆情怎么样"
- "XXX 有资产重组的消息吗"
- "市场情绪如何"

## 可用工具

来自 MCP 分组 `xq_stocks` 与 web 工具。

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `mcp_xq_stocks_xq_get_stock_news` | 个股新闻列表 | `symbol` |
| `mcp_xq_stocks_xq_get_stock_announcements` | 个股公告列表 | `symbol` |
| `web_search` | 搜索市场情绪、行业政策、突发事件 | `query` |
| `web_fetch` | 抓取指定新闻全文 | `url` |

> 本 skill 可被 stock-research 通过 spawn 委托执行（作为 Worker）。
> 资金流向验证由 fund-flow Worker 负责，本 skill 不调用资金流工具。

## 执行流程

1. **加载方法**：先 `read_file` 读取 `skills/sentiment-analysis/references/sentiment-classification.md`，获取关键词体系、分类标签、批量分类 prompt 模板与情绪指数计算规则。
2. **获取新闻**：调用 `mcp_xq_stocks_xq_get_stock_news` 拉取个股近期新闻。
3. **获取公告**：调用 `mcp_xq_stocks_xq_get_stock_announcements` 拉取近期公告。
4. **补充搜索**：如新闻不足，用 `web_search` 搜索 "{股票名称} 最新消息" / "{股票名称} 重大事件"。
5. **情感分类**：按 references 中的批量分类 prompt 模板，对新闻+公告批量做情感分类，得到每条的 sentiment/intensity/event_type。
6. **情绪研判**：识别重大事件（利好/利空/政策）分类归集；按 references 情绪指数计算规则汇总生成情绪指数（贪婪/中性/恐慌）。
7. **输出报告**：新闻摘要 + 情绪研判 + 事件驱动信号 + 风险提示。

## 输出格式

```
# {股票名称}（{股票代码}）舆情与情绪面分析
> 数据截至：{trade_date}

## 一、新闻摘要
{近期重要新闻列表，每条标注来源与日期}

## 二、公告要点
{近期关键公告摘要}

## 三、情绪研判
- 情绪指数：{贪婪/中性/恐慌}
- 利好因素：{具体事件}
- 利空因素：{具体事件}
- 政策影响：{政策类事件}

## 四、事件驱动信号
- 信号方向：{偏多/偏空/中性}
- 依据：{事件与资金流向综合判断}

## 五、风险提示
{需关注的潜在风险}
```

## 约束

- 新闻仅作辅助参考，不替代平台结构化数据。
- 情绪判断须基于具体新闻内容，不可凭空推断。
- 资金流向与情绪矛盾时必须提示分歧。
- 信号方向仅给「偏多/偏空/中性」方向性判断，不输出具体买卖建议。

## Worker 返回契约（被 spawn 调用时）

当被 stock-research 通过 spawn 委托时，除输出上述报告外，在最后附上结构化 JSON 结论：

```json
{
  "as_of": "2026-07-01",
  "sentiment_index": "贪婪/中性/恐慌",
  "bullish_factors": ["...", "..."],
  "bearish_factors": ["...", "..."],
  "policy_impact": "...",
  "event_signal": "偏多/偏空/中性",
  "conclusion": "情绪偏多/偏空/中性 + 简述"
}
```

## 示例对话

用户: "比亚迪最近有什么新闻"
步骤:
1. `read_file` 加载 `skills/sentiment-analysis/references/sentiment-classification.md`
2. 调用 `mcp_xq_stocks_xq_get_stock_news`（symbol="002594.SZ"）
3. 调用 `mcp_xq_stocks_xq_get_stock_announcements`（symbol="002594.SZ"）
4. 按 references 批量分类 prompt 模板对新闻+公告做情感分类
5. 汇总情绪指数（贪婪/中性/恐慌）
6. 输出舆情报告
