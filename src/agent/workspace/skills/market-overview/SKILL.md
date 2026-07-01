---
name: market-overview
description: 查看大盘指数走势、行业板块表现、市场情绪指标。当用户询问大盘行情、市场走势、板块表现、市场情绪时触发。
keywords: 大盘, 市场, 指数, 板块, 行业, 走势, 市场情绪, 涨跌, 概览
---

# 大盘与板块概览

## 触发条件

用户询问大盘行情、市场走势、板块表现、市场情绪时触发，例如：
- "大盘怎么样"
- "今天市场走势如何"
- "哪些板块涨得好"
- "市场情绪如何"

## 可用工具

指数数据来自 MCP 分组 `xq_indices`，板块/要闻来自 web 工具。

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `mcp_xq_indices_xq_list_indices` | 指数列表（按名称过滤） | `keyword`, `index_type`, `page`, `page_size` |
| `mcp_xq_indices_xq_get_index_overview` | 指数概览（点位/涨跌幅/成交额） | `symbol` |
| `mcp_xq_indices_xq_get_index_kline` | 指数日K线 + MA/MACD/KDJ/RSI/BIAS | `symbol`, `limit` |
| `web_search` | 搜索市场要闻、板块异动、政策动态 | `query` |

> 指数资金流向无数据源，`get_index_overview` 返回 `fund_flow_available=false`，分析中标注"指数资金流向暂不可用"，不要用个股资金流工具查指数。

## 主要指数代码

| 指数 | 代码 |
|------|------|
| 上证指数 | 000001.SH |
| 深证成指 | 399001.SZ |
| 创业板指 | 399006.SZ |
| 科创50 | 000688.SH |
| 沪深300 | 000300.SH |
| 中证500 | 000905.SH |
| 中证1000 | 000852.SH |

> 这些是指数代码，必须用 `mcp_xq_indices_xq_*` 工具查询，**不要**用 `mcp_xq_stocks_xq_*`（个股工具会把 000001.SH 解析为平安银行）。

## 执行流程

1. **确认范围**：用户问"大盘"默认看上证指数 + 创业板指；问"板块"走板块分析流程。
2. **指数行情**：调用 `mcp_xq_indices_xq_get_index_overview` 获取指数点位、涨跌幅、成交额。
3. **趋势分析**：调用 `mcp_xq_indices_xq_get_index_kline`（limit=20）获取近 20 日 K 线与技术指标，分析趋势。
4. **市场要闻**：调用 `web_search`（query="今日A股市场要闻 板块异动"）补充市场动态。
5. **输出报告**：指数表现 + 趋势判断 + 板块表现 + 市场要闻 + 市场情绪。

## 输出要求

`# 市场概览`，含五节：指数表现（表格）/ 趋势研判 / 板块表现 / 市场要闻 / 市场情绪（贪婪·中性·恐慌 + 依据）。标注数据截至日期；板块表现与要闻须标注来源。资金面节标注"指数资金流向暂不可用"。

## 约束

- 指数数据必须来自 `mcp_xq_indices_xq_*` 工具返回，严禁编造。
- 禁止用 `mcp_xq_stocks_xq_*` 个股工具查询指数代码。
- 板块表现如无直接数据源，用 `web_search` 补充并标注来源。
- 市场情绪判断须基于多项指标综合分析，不可单一指标定论。

## 示例对话

用户: "大盘怎么样"
步骤:
1. 调用 `mcp_xq_indices_xq_get_index_overview`（symbol="000001.SH"）
2. 调用 `mcp_xq_indices_xq_get_index_overview`（symbol="399006.SZ"）
3. 调用 `mcp_xq_indices_xq_get_index_kline`（symbol="000001.SH", limit=20）
4. 调用 `web_search`（query="今日A股市场要闻 板块异动"）
5. 输出市场概览报告

用户: "今天哪些板块涨得好"
步骤:
1. 调用 `web_search`（query="今日A股板块涨幅排名"）
2. 整理板块表现，标注来源
3. 对热门板块中的龙头股调用 `mcp_xq_stocks_xq_get_stock_overview` 补充详情
