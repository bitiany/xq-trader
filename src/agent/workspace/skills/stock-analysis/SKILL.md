---
name: stock-analysis
description: 基于行情、估值、财务、技术面、资金流向、新闻公告等多维数据，按华泰五步法输出个股结构化诊断报告。当用户要求对某只股票进行分析、诊断、评估、解读时触发。
keywords: 分析, 诊断, 评估, 解读, 个股, 股票, 五步法
---

# 个股全方位分析（五步法）

## 触发条件

用户要求对某只股票进行分析、诊断、评估、解读时触发，例如：
- "分析一下 XXX"
- "XXX 这只股票怎么样"
- "帮我看看 XXX 的基本面/技术面"
- "对 XXX 做个全面分析"

## 可用工具

来自 MCP 分组 `xq_stocks`（必需）与 `xq_positions`（按需）。

| 工具名 | 用途 | 关键参数 |
|--------|------|---------|
| `mcp_xq_stocks_xq_get_stock_overview` | 行情、估值、行业、市值、公司简介 | `symbol` |
| `mcp_xq_stocks_xq_get_stock_financials` | 财务摘要（利润/资产/现金流/指标） | `symbol` |
| `mcp_xq_stocks_xq_get_stock_kline` | 日 K 与 MA/MACD/KDJ/RSI/BIAS 指标 | `symbol`, `limit` |
| `mcp_xq_stocks_xq_get_stock_fund_flow` | 主力/超大单/大单/中单/小单资金流 | `symbol`, `limit` |
| `mcp_xq_stocks_xq_get_stock_news` | 个股新闻 | `symbol` |
| `mcp_xq_stocks_xq_get_stock_announcements` | 个股公告 | `symbol` |
| `mcp_xq_stocks_xq_get_stock_diagnosis` | 平台综合诊断（辅助交叉验证） | `symbol` |
| `mcp_xq_positions_xq_get_broker_position` | 单只标的当前持仓（仅在用户提及持仓时调用） | `stock_code` |
| `web_search` | 搜索个股相关新闻、公告、研报 | `query` |
| `web_fetch` | 抓取指定 URL 的网页内容 | `url` |

**调用规范**：
- 一次只调用一个工具，禁止合并多工具参数。
- `symbol` / `stock_code` 必须是 `600519.SH` / `000001.SZ` 这种带后缀格式。

## 执行流程（五步法）

### 第一步：行业赛道分析
**调用**：`mcp_xq_stocks_xq_get_stock_overview`

要点：行业定位、生命周期、竞争格局、行业空间、政策与宏观环境。

> 行业深度数据基于 overview 中的公司简介与行业标签做逻辑推演，须明确标注"基于公开信息推断"。

### 第二步：基本面分析
**调用**：`mcp_xq_stocks_xq_get_stock_overview` + `mcp_xq_stocks_xq_get_stock_financials`（可并行）

要点：
1. 商业模式与护城河
2. 盈利能力（ROE/毛利率/净利率，与行业对比）
3. 成长性（营收/净利同比，是否同步）
4. 财务健康度（资产负债率、经营现金流、流动比率）
5. 风险排查：商誉、股权质押、主营占比、利润与现金流背离

### 第三步：估值分析
**调用**：复用第一步 `mcp_xq_stocks_xq_get_stock_overview` 的估值字段（无需重复调用）

要点：PE / PB / PS 分位、行业均值对比、股息率、市值规模，结合行业特性综合判断。

### 第四步：技术面与资金面分析
**调用**：先 `mcp_xq_stocks_xq_get_stock_kline`，再 `mcp_xq_stocks_xq_get_stock_fund_flow`（分步调用）

要点：
1. 趋势：多/空头排列、金叉/死叉
2. 动量振荡：MACD / KDJ / RSI / BIAS
3. 量价：放量/缩量、量价配合、换手率
4. 资金流：主力净流入趋势、超大/大单方向、与中小单背离
5. 关键价位：近期支撑位与压力位

### 第五步：综合评估与决策参考
**调用顺序**：`mcp_xq_positions_xq_get_broker_position`（按需，仅在用户提及持仓时）→ `web_search`（新闻）→ `mcp_xq_stocks_xq_get_stock_announcements` → `mcp_xq_stocks_xq_get_stock_diagnosis`（辅助交叉验证）

要点：
1. 新闻资讯与事件驱动（关键词："{股票名称} 最新消息"、"{股票名称} 公告"）
2. 持仓分析（无持仓则跳过）
3. 多维度综合评分（行业 15% + 基本面 25% + 估值 15% + 技术面 15% + 资金面 15% + 风险 10% + 新闻 5%）
4. 风险提示
5. 关注要点

## 报告输出格式

> **排版要求**：严格遵守 AGENTS.md 的 Markdown 排版规范——段落间/标题前后最多 1 个空行，禁止连续 2+ 空行。

```
# {股票名称}（{股票代码}）全方位分析报告
> 数据截至：{trade_date}

## 一、行业赛道分析
{行业定位、生命周期、竞争格局、行业空间、政策环境}

## 二、基本面分析
### 2.1 商业模式与护城河
{内容}
### 2.2 盈利能力
{ROE/毛利率/净利率与行业对比}
### 2.3 成长性
{营收/净利同比}
### 2.4 财务健康度
{资产负债率、现金流、流动比率}
### 2.5 风险排查
{商誉、质押、主营占比、利润与现金流背离}

## 三、估值分析
{PE/PB/PS分位、行业均值对比、股息率、市值规模}

## 四、技术面与资金面分析
### 4.1 趋势判断
{多空排列、金叉死叉}
### 4.2 动量与振荡指标
{MACD/KDJ/RSI/BIAS}
### 4.3 量价关系
{放量缩量、量价配合、换手率}
### 4.4 资金流向分析
{主力净流入、超大单方向、与中小单背离}
### 4.5 关键价位
{支撑位与压力位}

## 五、综合评估
### 5.1 新闻资讯与事件驱动
{新闻摘要与事件影响}
### 5.2 持仓分析
{持仓数据，无持仓时标注"当前无持仓，跳过持仓分析"}
### 5.3 多维度综合评分
{评分表：行业15%+基本面25%+估值15%+技术15%+资金15%+风险10%+新闻5%}
### 5.4 风险提示
{具体风险点}
### 5.5 关注要点
{后续跟踪指标}
```

## 约束

1. 所有数字必须来自工具返回，严禁编造。
2. 不给出具体买卖建议，仅提供分析参考。
3. 工具调用失败必须如实标注数据缺失。
4. 持仓为空时显式标注"当前无持仓"。
5. 估值判断必须结合行业特性。
6. 风险排查必须先于收益分析。

## 示例对话

用户: "分析一下贵州茅台"
步骤:
1. 识别 symbol = 600519.SH
2. 调用 `mcp_xq_stocks_xq_get_stock_overview`（行业+估值）
3. 并行调用 `mcp_xq_stocks_xq_get_stock_financials`（财务）
4. 调用 `mcp_xq_stocks_xq_get_stock_kline`（技术面）
5. 调用 `mcp_xq_stocks_xq_get_stock_fund_flow`（资金面）
6. 调用 `mcp_xq_stocks_xq_get_stock_news` + `web_search`（新闻）
7. 按五步法输出 Markdown 报告（遵守排版规范，段落间最多1空行）

用户: "帮我看看比亚迪的基本面"
步骤:
1. 识别 symbol = 002594.SZ，聚焦基本面（第二步）
2. 调用 `mcp_xq_stocks_xq_get_stock_overview` + `mcp_xq_stocks_xq_get_stock_financials`
3. 输出盈利能力、成长性、财务健康度、风险排查分析
