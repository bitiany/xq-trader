"""因子验证统一报告生成器 — 整合选股报告 + 回测报告 + 综合分析报告。

读取 report/_data/ 下的 JSON 数据，生成 4 份 Markdown 报告：
  - 00_overview.md          总览与文档导航
  - 01_selection_report.md  选股报告（基础+扩展方法）
  - 02_backtest_report.md   回测报告（5个场景）
  - 03_analysis_report.md   综合分析报告

用法:
    python scripts/factor_validation_report_generator.py
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
_REPORT_DIR = _PROJECT_ROOT / "report"
_DATA_DIR = _REPORT_DIR / "_data"
_SELECTION_DIR = _DATA_DIR / "selection"
_BACKTEST_DIR = _DATA_DIR / "backtest"
_CONFIG_PATH = _SCRIPTS_DIR / "factor_validation_config.yml"

POOL_NAMES = {
    "style_value": "价值股", "style_large_cap": "大盘股",
    "style_growth": "成长股", "idx_300": "沪深300",
}

STRATEGY_GROUP_NAMES = {
    "technical_group": "技术分析策略组",
    "composite_group": "合成因子策略组",
}

SCENARIO_NAMES = {
    "multi_strategy_compare": "多策略对比",
    "multi_period_analysis": "多周期分析",
    "selection_method_compare": "选股方法对比",
    "composite_strategy_compare": "合成因子策略对比",
    "extended_method_compare": "扩展选股方法对比",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_config() -> dict[str, Any]:
    return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))


def _parse_pct(s: Any) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    if isinstance(s, str):
        s = s.strip().rstrip("%")
        try:
            return float(s)
        except ValueError:
            return 0.0
    return 0.0


def _parse_sharpe(s: Any) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    if isinstance(s, str) and s.upper() != "N/A":
        try:
            return float(s)
        except ValueError:
            return 0.0
    return 0.0


def _aggregate_metrics(metrics_per_symbol: dict[str, Any]) -> dict[str, float]:
    """将 per-symbol 指标聚合为 backtest 级别平均值。"""
    if not metrics_per_symbol:
        return {
            "avg_return": 0.0, "avg_sharpe": 0.0, "avg_max_drawdown": 0.0,
            "avg_win_rate": 0.0, "total_trades": 0, "win_rate_pct": 0.0,
            "profitable_count": 0, "total_symbols": 0,
        }
    returns: list[float] = []
    sharpes: list[float] = []
    drawdowns: list[float] = []
    win_rates: list[float] = []
    total_trades = 0
    profitable = 0
    for _sym, m in metrics_per_symbol.items():
        ret = _parse_pct(m.get("total_return", "0%"))
        returns.append(ret)
        if ret > 0:
            profitable += 1
        sharpes.append(_parse_sharpe(m.get("sharpe_ratio", "N/A")))
        drawdowns.append(_parse_pct(m.get("max_drawdown", "0%")))
        win_rates.append(_parse_pct(m.get("win_rate", "0%")))
        total_trades += int(m.get("num_trades", 0))
    n = len(returns)
    return {
        "avg_return": sum(returns) / n,
        "avg_sharpe": sum(sharpes) / n,
        "avg_max_drawdown": sum(drawdowns) / n,
        "avg_win_rate": sum(win_rates) / n,
        "total_trades": total_trades,
        "win_rate_pct": profitable / n * 100,
        "profitable_count": profitable,
        "total_symbols": n,
    }


def _fmt(v: float) -> str:
    return f"{v:+.2f}%"


# ─── 报告 1：选股报告 ─────────────────────────────────

def gen_selection_report(
    config: dict[str, Any],
    basic_data: dict[str, Any],
    extended_data: dict[str, Any],
) -> str:
    pools = config["selection"]["pools"]
    basic_methods = config["selection"]["basic_methods"]
    extended_methods = config["selection"]["extended_methods"]
    basic_results = basic_data.get("results", {})
    extended_results = extended_data.get("results", {})

    lines: list[str] = [
        "# 因子验证报告 — 截面选股",
        "",
        "## 1. 概述",
        "",
        "### 1.1 选股目标",
        "",
        "通过 ICIR 加权截面选股方法，验证不同因子组合（日频 A/B、季频、合成因子）",
        "在不同股池上的选股效果，为后续时序策略回测提供标的池。",
        "",
        "### 1.2 选股方法说明",
        "",
        "#### 1.2.1 基础方法（仅日频 A/B 因子）",
        "",
        "| 方法 ID | 名称 | 因子过滤 | 说明 |",
        "|---|---|---|---|",
    ]
    filter_desc_map = {
        "all": "全部因子",
        "fund_flow": "资金面关键字过滤",
        "technical": "技术面关键字过滤",
    }
    for m in basic_methods:
        fd = filter_desc_map.get(m.get("factor_filter", "all"), "all")
        lines.append(f"| `{m['id']}` | {m['name']} | {fd} | 按 ICIR 加权截面排序选 Top10 |")

    lines.extend([
        "",
        "#### 1.2.2 扩展方法（引入季频/合成因子）",
        "",
        "| 方法 ID | 名称 | 日频 | 季频 | 合成因子 | 合成权重 |",
        "|---|---|---|---|---|---|",
    ])
    for m in extended_methods:
        d = "✓" if m.get("include_daily") else "—"
        q = "✓" if m.get("include_quarterly") else "—"
        c = "✓" if m.get("include_composite") else "—"
        lines.append(f"| `{m['id']}` | {m['name']} | {d} | {q} | {c} | {m.get('composite_weight', 0.0)} |")

    lines.extend([
        "",
        "### 1.3 数据填充方案",
        "",
        "| 因子类型 | 更新频率 | 存储表 | 填充方式 |",
        "|---|---|---|---|",
        "| 日频 A/B 因子 | daily | `stock.fac_factor_value` | 按信号日精确匹配 |",
        "| 日频合成因子（composite_alpha 等） | weekly | `stock.fac_factor_value` | "
        "PIT：取信号日当天或之前最新值 |",
        "| 季频单因子（fina_indicator） | quarterly | "
        "`stock.fac_financial_factor_value` | "
        "PIT + `merge_asof(direction='backward')` 向前填充 |",
        "| 季频合成因子（composite_*_quarterly） | quarterly | "
        "`stock.fac_financial_composite_value` | "
        "PIT + `merge_asof(direction='backward')` 向前填充 |",
        "",
        "---",
        "",
        "## 2. 基础方法选股结果",
        "",
        "### 2.1 选股汇总",
        "",
        "| 股池 | 方法 | 信号日 | 因子数 | Top1 | Top1得分 |",
        "|---|---|---|---|---|---|",
    ])
    for pool in pools:
        for m in basic_methods:
            key = f"{pool['id']}__{m['id']}"
            sel = basic_results.get(key, {})
            if not sel or sel.get("error"):
                lines.append(f"| {pool['name']} | {m['name']} | - | - | 错误 | - |")
                continue
            top1 = sel.get("top10", [{}])[0] if sel.get("top10") else {}
            lines.append(
                f"| {pool['name']} | {m['name']} | {sel.get('signal_date', '')} | "
                f"{sel.get('daily_factor_count', 0)} | {top1.get('symbol', '')} | "
                f"{top1.get('score', 0):.4f} |"
            )

    lines.append("")
    lines.append("### 2.2 基础方法 Top10 明细")
    lines.append("")
    for pool in pools:
        lines.append(f"#### {pool['name']}")
        lines.append("")
        header = "| 排名 |"
        sep = "|---|"
        for m in basic_methods:
            header += f" {m['name']} | 得分 |"
            sep += "---|---|"
        lines.append(header)
        lines.append(sep)
        for i in range(10):
            row = f"| {i+1} |"
            for m in basic_methods:
                key = f"{pool['id']}__{m['id']}"
                sel = basic_results.get(key, {})
                top10 = sel.get("top10", [])
                top = top10[i] if i < len(top10) else {}
                row += f" {top.get('symbol', '-')} | {top.get('score', 0):.4f} |"
            lines.append(row)
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 3. 扩展方法选股结果（季频/合成因子）",
        "",
        "### 3.1 选股汇总",
        "",
        "| 股池 | 方法 | 信号日 | 日频因子 | 季频因子 | 合成因子 | Top1 | Top1得分 |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for pool in pools:
        for m in extended_methods:
            key = f"{pool['id']}__{m['id']}"
            sel = extended_results.get(key, {})
            if not sel or sel.get("error"):
                lines.append(f"| {pool['name']} | {m['name']} | - | - | - | - | 错误 | - |")
                continue
            top1 = sel.get("top10", [{}])[0] if sel.get("top10") else {}
            lines.append(
                f"| {pool['name']} | {m['name']} | {sel.get('signal_date', '')} | "
                f"{sel.get('daily_factor_count', 0)} | "
                f"{sel.get('quarterly_factor_count', 0)} | "
                f"{sel.get('composite_factor_count', 0)} | "
                f"{top1.get('symbol', '')} | "
                f"{top1.get('score', 0):.4f} |"
            )

    lines.append("")
    lines.append("### 3.2 扩展方法 Top10 明细")
    lines.append("")
    for pool in pools:
        lines.append(f"#### {pool['name']}")
        lines.append("")
        header = "| 排名 |"
        sep = "|---|"
        for m in extended_methods:
            header += f" {m['name']} | 得分 |"
            sep += "---|---|"
        lines.append(header)
        lines.append(sep)
        for i in range(10):
            row = f"| {i+1} |"
            for m in extended_methods:
                key = f"{pool['id']}__{m['id']}"
                sel = extended_results.get(key, {})
                top10 = sel.get("top10", [])
                top = top10[i] if i < len(top10) else {}
                row += f" {top.get('symbol', '-')} | {top.get('score', 0):.4f} |"
            lines.append(row)
        lines.append("")

    lines.extend([
        "---",
        "",
        "## 4. 选股方法对比分析",
        "",
        "### 4.1 扩展方法间重合度",
        "",
        "| 股池 | daily_only ∩ daily_plus_composite | "
        "daily_only ∩ daily_plus_quarterly | "
        "daily_plus_composite ∩ daily_plus_quarterly |",
        "|---|---|---|---|",
    ])
    for pool in pools:
        sels = {}
        for m in extended_methods:
            key = f"{pool['id']}__{m['id']}"
            top10 = extended_results.get(key, {}).get("top10", [])
            sels[m["id"]] = {s["symbol"] for s in top10}
        o_dc = len(sels.get("daily_only", set()) & sels.get("daily_plus_composite", set()))
        o_dq = len(sels.get("daily_only", set()) & sels.get("daily_plus_quarterly", set()))
        o_cq = len(sels.get("daily_plus_composite", set()) & sels.get("daily_plus_quarterly", set()))
        lines.append(f"| {pool['name']} | {o_dc}/10 | {o_dq}/10 | {o_cq}/10 |")

    lines.extend([
        "",
        "### 4.2 基础方法间重合度",
        "",
        "| 股池 | icir_all ∩ fund_flow | icir_all ∩ technical | "
        "fund_flow ∩ technical |",
        "|---|---|---|---|",
    ])
    for pool in pools:
        sels = {}
        for m in basic_methods:
            key = f"{pool['id']}__{m['id']}"
            top10 = basic_results.get(key, {}).get("top10", [])
            sels[m["id"]] = {s["symbol"] for s in top10}
        o_if = len(sels.get("icir_all", set()) & sels.get("fund_flow_focus", set()))
        o_it = len(sels.get("icir_all", set()) & sels.get("technical_focus", set()))
        o_ft = len(sels.get("fund_flow_focus", set()) & sels.get("technical_focus", set()))
        lines.append(f"| {pool['name']} | {o_if}/10 | {o_it}/10 | {o_ft}/10 |")

    lines.extend([
        "",
        "*原始数据：`report/_data/selection/basic_selection.json`、"
        "`report/_data/selection/extended_selection.json`*",
    ])
    return "\n".join(lines)


# ─── 报告 2：回测报告 ─────────────────────────────────

def _gen_scenario_summary(results: dict[str, Any], sc_id: str) -> str:
    lines: list[str] = []
    pool_groups: dict[str, list[dict[str, Any]]] = {}
    for entry in results.values():
        pool_groups.setdefault(entry.get("pool_id", ""), []).append(entry)

    if sc_id == "multi_period_analysis":
        lines.append("| 股池 | 周期 | 平均收益率 | 平均夏普 | 平均最大回撤 | 总交易次数 | 盈利标的 |")
        lines.append("|---|---|---|---|---|---|---|")
        for entries in pool_groups.values():
            for entry in entries:
                m = entry.get("result", {}).get("metrics_per_symbol", {})
                agg = _aggregate_metrics(m)
                lines.append(
                    f"| {entry.get('pool_name', '')} | "
                    f"{entry.get('period_name', '')} | "
                    f"{_fmt(agg['avg_return'])} | {agg['avg_sharpe']:.2f} | "
                    f"{agg['avg_max_drawdown']:.2f}% | {agg['total_trades']} | "
                    f"{agg['profitable_count']}/{agg['total_symbols']} |"
                )
    elif sc_id in ("selection_method_compare", "extended_method_compare"):
        lines.append("| 股池 | 方法 | 平均收益率 | 平均夏普 | 平均最大回撤 | 总交易次数 | 盈利标的 |")
        lines.append("|---|---|---|---|---|---|---|")
        for entries in pool_groups.values():
            for entry in entries:
                m = entry.get("result", {}).get("metrics_per_symbol", {})
                agg = _aggregate_metrics(m)
                lines.append(
                    f"| {entry.get('pool_name', '')} | "
                    f"{entry.get('method_name', '')} | "
                    f"{_fmt(agg['avg_return'])} | {agg['avg_sharpe']:.2f} | "
                    f"{agg['avg_max_drawdown']:.2f}% | {agg['total_trades']} | "
                    f"{agg['profitable_count']}/{agg['total_symbols']} |"
                )
    else:
        lines.append("| 股池 | 策略 | 平均收益率 | 平均夏普 | 平均最大回撤 | 总交易次数 | 盈利标的 |")
        lines.append("|---|---|---|---|---|---|---|")
        for entries in pool_groups.values():
            for entry in entries:
                m = entry.get("result", {}).get("metrics_per_symbol", {})
                agg = _aggregate_metrics(m)
                lines.append(
                    f"| {entry.get('pool_name', '')} | "
                    f"{entry.get('strategy_name', '')} | "
                    f"{_fmt(agg['avg_return'])} | {agg['avg_sharpe']:.2f} | "
                    f"{agg['avg_max_drawdown']:.2f}% | {agg['total_trades']} | "
                    f"{agg['profitable_count']}/{agg['total_symbols']} |"
                )
    return "\n".join(lines)


def _gen_scenario_detail(results: dict[str, Any], sc_id: str) -> str:
    lines: list[str] = []
    pool_groups: dict[str, list[dict[str, Any]]] = {}
    for entry in results.values():
        pool_groups.setdefault(entry.get("pool_id", ""), []).append(entry)

    for entries in pool_groups.values():
        pool_name = entries[0].get("pool_name", "")
        lines.append(f"#### {pool_name}")
        lines.append("")

        if sc_id == "multi_period_analysis":
            col = "周期"
            col_field = "period_name"
        elif sc_id in ("selection_method_compare", "extended_method_compare"):
            col = "方法"
            col_field = "method_name"
        else:
            col = "策略"
            col_field = "strategy_name"

        lines.append(f"| {col} | 标的 | 收益率 | 夏普 | 最大回撤 | 交易次数 | 胜率 |")
        lines.append("|---|---|---|---|---|---|---|")
        for entry in entries:
            m = entry.get("result", {}).get("metrics_per_symbol", {})
            col_val = entry.get(col_field, "")
            sorted_syms = sorted(
                m.items(),
                key=lambda x: _parse_pct(x[1].get("total_return", "0%")),
                reverse=True,
            )
            for sym, mm in sorted_syms:
                ret = _parse_pct(mm.get("total_return", "0%"))
                sh = mm.get("sharpe_ratio", "N/A")
                sh_str = f"{_parse_sharpe(sh):.2f}" if sh != "N/A" else "N/A"
                dd = _parse_pct(mm.get("max_drawdown", "0%"))
                tr = mm.get("num_trades", 0)
                wr = _parse_pct(mm.get("win_rate", "0%"))
                lines.append(
                    f"| {col_val} | {sym} | {_fmt(ret)} | {sh_str} | "
                    f"{dd:.2f}% | {tr} | {wr:.1f}% |"
                )
        lines.append("")
    return "\n".join(lines)


def gen_backtest_report(
    config: dict[str, Any],
    scenario_results: dict[str, dict[str, Any]],
) -> str:
    lines: list[str] = [
        "# 因子验证报告 — 时序策略回测",
        "",
        "## 1. 概述",
        "",
        "### 1.1 回测场景",
        "",
        "| 场景 ID | 名称 | 说明 |",
        "|---|---|---|",
    ]
    sc_descs = {
        "multi_strategy_compare": "4池 × 3技术策略 × 252天 — 经典技术分析策略对比",
        "multi_period_analysis": "2池 × 1策略 × 3周期 — 短/中/长期回测对比",
        "selection_method_compare": "4池 × 2方法 × 1策略 — 基础选股方法对比",
        "composite_strategy_compare": "4池 × 3合成因子策略 × 252天 — 合成因子策略对比",
        "extended_method_compare": "1池 × 3方法 × 1策略 — 扩展选股方法对比",
    }
    for sc_id, sc_name in SCENARIO_NAMES.items():
        desc = sc_descs.get(sc_id, "")
        count = len(scenario_results.get(sc_id, {}))
        lines.append(f"| `{sc_id}` | {sc_name} | {desc}（{count} 次回测） |")

    lines.extend([
        "",
        "### 1.2 回测参数",
        "",
        f"- **初始资金**: {config['backtest']['initial_cash']:,.0f}",
        f"- **手续费**: {config['backtest']['commission']}",
        f"- **每组合标的数**: Top{config['backtest']['top_n']}",
        f"- **默认回测周期**: {config['backtest']['default_trading_days']} 交易日",
        "",
        "### 1.3 策略说明",
        "",
    ])

    for group_id, group_name in STRATEGY_GROUP_NAMES.items():
        strategies = config["strategies"].get(group_id, [])
        lines.append(f"#### {group_name}")
        lines.append("")
        lines.append("| 策略 ID | 名称 |")
        lines.append("|---|---|")
        for s in strategies:
            lines.append(f"| `{s['id']}` | {s['name']} |")
        lines.append("")

    lines.extend(["---", ""])

    sc_idx = 2
    for sc_id, sc_name in SCENARIO_NAMES.items():
        results = scenario_results.get(sc_id, {})
        if not results:
            continue
        lines.append(f"## {sc_idx}. 场景：{sc_name}")
        lines.append("")
        lines.append(f"**场景 ID**: `{sc_id}`")
        lines.append("")
        lines.append(f"### {sc_idx}.1 汇总")
        lines.append("")
        lines.append(_gen_scenario_summary(results, sc_id))
        lines.append("")
        lines.append(f"### {sc_idx}.2 各标的明细")
        lines.append("")
        lines.append(_gen_scenario_detail(results, sc_id))
        lines.append("")
        sc_idx += 1

    lines.extend([
        "---",
        "",
        "*原始数据：`report/_data/backtest/*.json`*",
    ])
    return "\n".join(lines)


# ─── 报告 3：综合分析报告 ─────────────────────────────

def gen_analysis_report(
    config: dict[str, Any],
    basic_data: dict[str, Any],
    extended_data: dict[str, Any],
    scenario_results: dict[str, dict[str, Any]],
) -> str:
    basic_results = basic_data.get("results", {})
    extended_results = extended_data.get("results", {})
    pools = config["selection"]["pools"]
    basic_methods = config["selection"]["basic_methods"]
    extended_methods = config["selection"]["extended_methods"]

    lines: list[str] = [
        "# 因子验证综合分析报告",
        "",
        "## 1. 验证目标与范围",
        "",
        "### 1.1 验证目标",
        "",
        "1. **季频因子纳入截面选股**：通过 PIT + 向前填充方式，将季频财务因子",
        "（按公告日向前填充到日频）纳入截面选股",
        "2. **合成因子纳入截面选股**：将日频合成因子（composite_alpha 等，周频更新）",
        "和季频合成因子（composite_alpha_quarterly 等）纳入截面选股",
        "3. **A/B 因子 + 合成因子组合时序策略**：验证时序相关 A/B 因子与合成因子",
        "组合成策略进行回测的可行性与绩效表现",
        "",
        "### 1.2 验证范围",
        "",
        f"- **股池**: {', '.join(p['name'] for p in pools)}",
        f"- **基础选股方法**: {', '.join(m['name'] for m in basic_methods)}",
        f"- **扩展选股方法**: {', '.join(m['name'] for m in extended_methods)}",
        f"- **技术策略组**: {', '.join(s['name'] for s in config['strategies']['technical_group'])}",
        f"- **合成因子策略组**: {', '.join(s['name'] for s in config['strategies']['composite_group'])}",
        f"- **回测周期**: {config['backtest']['default_trading_days']} 交易日",
        f"- **每组合标的数**: Top{config['backtest']['top_n']}",
        "",
        "### 1.3 验证场景",
        "",
        "| 场景 | 回测次数 |",
        "|---|---|",
    ]
    total_bt = 0
    for sc_id, sc_name in SCENARIO_NAMES.items():
        count = len(scenario_results.get(sc_id, {}))
        total_bt += count
        lines.append(f"| {sc_name} | {count} |")
    lines.append(f"| **合计** | **{total_bt}** |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. 选股效果分析",
        "",
        "### 2.1 基础方法选股效果",
        "",
        "| 股池 | 方法 | 因子数 | Top1得分 |",
        "|---|---|---|---|",
    ])
    for pool in pools:
        for m in basic_methods:
            key = f"{pool['id']}__{m['id']}"
            sel = basic_results.get(key, {})
            if not sel or sel.get("error"):
                lines.append(f"| {pool['name']} | {m['name']} | - | - |")
                continue
            top1 = sel.get("top10", [{}])[0] if sel.get("top10") else {}
            lines.append(
                f"| {pool['name']} | {m['name']} | "
                f"{sel.get('daily_factor_count', 0)} | "
                f"{top1.get('score', 0):.4f} |"
            )

    lines.extend([
        "",
        "### 2.2 扩展方法选股效果",
        "",
        "| 股池 | 方法 | 日频因子 | 季频因子 | 合成因子 | Top1得分 |",
        "|---|---|---|---|---|---|",
    ])
    for pool in pools:
        for m in extended_methods:
            key = f"{pool['id']}__{m['id']}"
            sel = extended_results.get(key, {})
            if not sel or sel.get("error"):
                lines.append(f"| {pool['name']} | {m['name']} | - | - | - | - |")
                continue
            top1 = sel.get("top10", [{}])[0] if sel.get("top10") else {}
            lines.append(
                f"| {pool['name']} | {m['name']} | "
                f"{sel.get('daily_factor_count', 0)} | "
                f"{sel.get('quarterly_factor_count', 0)} | "
                f"{sel.get('composite_factor_count', 0)} | "
                f"{top1.get('score', 0):.4f} |"
            )

    lines.extend([
        "",
        "### 2.3 选股方法重合度分析",
        "",
        "| 股池 | daily_only ∩ daily_plus_composite | "
        "daily_only ∩ daily_plus_quarterly | "
        "daily_plus_composite ∩ daily_plus_quarterly |",
        "|---|---|---|---|",
    ])
    total_o_dq = 0
    n_pools = 0
    for pool in pools:
        sels = {}
        for m in extended_methods:
            key = f"{pool['id']}__{m['id']}"
            top10 = extended_results.get(key, {}).get("top10", [])
            sels[m["id"]] = {s["symbol"] for s in top10}
        o_dc = len(sels.get("daily_only", set()) & sels.get("daily_plus_composite", set()))
        o_dq = len(sels.get("daily_only", set()) & sels.get("daily_plus_quarterly", set()))
        o_cq = len(sels.get("daily_plus_composite", set()) & sels.get("daily_plus_quarterly", set()))
        lines.append(f"| {pool['name']} | {o_dc}/10 | {o_dq}/10 | {o_cq}/10 |")
        total_o_dq += o_dq
        n_pools += 1

    avg_o_dq = total_o_dq / n_pools if n_pools > 0 else 0
    inc_pct = (10 - avg_o_dq) / 10 * 100
    conclusion = (
        "说明季频+合成因子对纯日频因子有显著的增量信息贡献。"
        if inc_pct > 30 else
        "说明季频+合成因子对纯日频因子的增量信息有限。"
    )
    lines.extend([
        "",
        f"**分析**：扩展方法 `daily_plus_quarterly` 相对 `daily_only` 的平均重合度为 "
        f"{avg_o_dq:.1f}/10，新增选股比例约 {inc_pct:.1f}%，{conclusion}",
        "",
        "---",
        "",
        "## 3. 时序策略回测绩效分析",
        "",
    ])

    sc_idx = 1
    for sc_id, sc_name in SCENARIO_NAMES.items():
        results = scenario_results.get(sc_id, {})
        if not results:
            continue
        lines.append(f"### 3.{sc_idx} 场景：{sc_name}")
        lines.append("")

        if sc_id in ("multi_strategy_compare", "composite_strategy_compare"):
            groups: dict[str, list[dict[str, Any]]] = {}
            for entry in results.values():
                groups.setdefault(entry.get("strategy_id", ""), []).append(entry)
            lines.append("| 策略 | 跨池平均收益 | 平均夏普 | 平均回撤 | 平均盈利占比 |")
            lines.append("|---|---|---|---|---|")
            for entries in groups.values():
                aggs = []
                for e in entries:
                    m = e.get("result", {}).get("metrics_per_symbol", {})
                    if m:
                        aggs.append(_aggregate_metrics(m))
                if not aggs:
                    continue
                ar = sum(a["avg_return"] for a in aggs) / len(aggs)
                ash = sum(a["avg_sharpe"] for a in aggs) / len(aggs)
                add = sum(a["avg_max_drawdown"] for a in aggs) / len(aggs)
                aw = sum(a["win_rate_pct"] for a in aggs) / len(aggs)
                lines.append(
                    f"| {entries[0].get('strategy_name', '')} | "
                    f"{_fmt(ar)} | {ash:.2f} | {add:.2f}% | {aw:.1f}% |"
                )
        elif sc_id == "multi_period_analysis":
            groups = {}
            for entry in results.values():
                groups.setdefault(entry.get("period_key", ""), []).append(entry)
            lines.append("| 周期 | 跨池平均收益 | 平均夏普 | 平均回撤 | 平均盈利占比 |")
            lines.append("|---|---|---|---|---|")
            for entries in groups.values():
                aggs = []
                for e in entries:
                    m = e.get("result", {}).get("metrics_per_symbol", {})
                    if m:
                        aggs.append(_aggregate_metrics(m))
                if not aggs:
                    continue
                ar = sum(a["avg_return"] for a in aggs) / len(aggs)
                ash = sum(a["avg_sharpe"] for a in aggs) / len(aggs)
                add = sum(a["avg_max_drawdown"] for a in aggs) / len(aggs)
                aw = sum(a["win_rate_pct"] for a in aggs) / len(aggs)
                lines.append(
                    f"| {entries[0].get('period_name', '')} | "
                    f"{_fmt(ar)} | {ash:.2f} | {add:.2f}% | {aw:.1f}% |"
                )
        elif sc_id in ("selection_method_compare", "extended_method_compare"):
            groups = {}
            for entry in results.values():
                groups.setdefault(entry.get("method", ""), []).append(entry)
            lines.append("| 方法 | 跨池平均收益 | 平均夏普 | 平均回撤 | 平均盈利占比 |")
            lines.append("|---|---|---|---|---|")
            for entries in groups.values():
                aggs = []
                for e in entries:
                    m = e.get("result", {}).get("metrics_per_symbol", {})
                    if m:
                        aggs.append(_aggregate_metrics(m))
                if not aggs:
                    continue
                ar = sum(a["avg_return"] for a in aggs) / len(aggs)
                ash = sum(a["avg_sharpe"] for a in aggs) / len(aggs)
                add = sum(a["avg_max_drawdown"] for a in aggs) / len(aggs)
                aw = sum(a["win_rate_pct"] for a in aggs) / len(aggs)
                lines.append(
                    f"| {entries[0].get('method_name', '')} | "
                    f"{_fmt(ar)} | {ash:.2f} | {add:.2f}% | {aw:.1f}% |"
                )
        lines.append("")
        sc_idx += 1

    # 股池表现对比
    lines.extend([
        "---",
        "",
        "## 4. 股池表现对比",
        "",
        "| 股池 | 跨场景平均收益 | 平均夏普 | 平均回撤 | 平均盈利占比 |",
        "|---|---|---|---|---|",
    ])
    pool_groups: dict[str, list[dict[str, Any]]] = {}
    for results in scenario_results.values():
        for entry in results.values():
            pool_groups.setdefault(entry.get("pool_id", ""), []).append(entry)
    pool_summary: dict[str, dict[str, float]] = {}
    for pool_id, entries in pool_groups.items():
        aggs = []
        for e in entries:
            m = e.get("result", {}).get("metrics_per_symbol", {})
            if m:
                aggs.append(_aggregate_metrics(m))
        if not aggs:
            continue
        pool_summary[pool_id] = {
            "name": entries[0].get("pool_name", pool_id),
            "avg_return": sum(a["avg_return"] for a in aggs) / len(aggs),
            "avg_sharpe": sum(a["avg_sharpe"] for a in aggs) / len(aggs),
            "avg_dd": sum(a["avg_max_drawdown"] for a in aggs) / len(aggs),
            "avg_win": sum(a["win_rate_pct"] for a in aggs) / len(aggs),
        }
    for pool in pools:
        s = pool_summary.get(pool["id"])
        if s:
            lines.append(
                f"| {s['name']} | {_fmt(s['avg_return'])} | "
                f"{s['avg_sharpe']:.2f} | {s['avg_dd']:.2f}% | "
                f"{s['avg_win']:.1f}% |"
            )
    if pool_summary:
        best_p = max(pool_summary.keys(), key=lambda p: pool_summary[p]["avg_return"])
        bp = pool_summary[best_p]
        lines.extend([
            "",
            f"**最佳股池**：{bp['name']}（平均收益 {_fmt(bp['avg_return'])}，"
            f"夏普 {bp['avg_sharpe']:.2f}）",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## 5. 综合结论",
        "",
        "### 5.1 PIT + 向前填充方案验证",
        "",
        "1. 季频单因子通过 `pd.merge_asof(direction='backward')` 成功填充到日频，",
        "   财务未披露前使用最近一次数据，避免了未来函数",
        "2. 季频合成因子通过 `load_financial_composite_panel` 实现 PIT + 向前填充",
        "3. 日频合成因子（周频更新）通过应用层 PIT 取最新值实现向前填充",
        "",
        "### 5.2 选股效果结论",
        "",
    ])

    ext_results = scenario_results.get("extended_method_compare", {})
    method_returns: dict[str, float] = {}
    for entry in ext_results.values():
        method = entry.get("method", "")
        m = entry.get("result", {}).get("metrics_per_symbol", {})
        if m:
            agg = _aggregate_metrics(m)
            method_returns[method] = agg["avg_return"]
    if method_returns:
        do_ret = method_returns.get("daily_only", 0)
        dc_ret = method_returns.get("daily_plus_composite", 0)
        dq_ret = method_returns.get("daily_plus_quarterly", 0)
        lines.extend([
            "基于 `extended_method_compare` 场景"
            "（style_growth + ts_composite_alpha_threshold）：",
            "",
            f"- `daily_only`（基准）: {_fmt(do_ret)}",
            f"- `daily_plus_composite`: {_fmt(dc_ret)}",
            f"  （相对基准增量 {_fmt(dc_ret - do_ret)}）",
            f"- `daily_plus_quarterly`: {_fmt(dq_ret)}",
            f"  （相对基准增量 {_fmt(dq_ret - do_ret)}）",
            "",
        ])

    lines.append("### 5.3 策略回测结论")
    lines.append("")

    ms_results = scenario_results.get("multi_strategy_compare", {})
    if ms_results:
        groups: dict[str, list[dict[str, Any]]] = {}
        for entry in ms_results.values():
            groups.setdefault(entry.get("strategy_id", ""), []).append(entry)
        best_s = None
        best_r = -float("inf")
        for entries in groups.values():
            aggs = []
            for e in entries:
                m = e.get("result", {}).get("metrics_per_symbol", {})
                if m:
                    aggs.append(_aggregate_metrics(m))
            if aggs:
                ar = sum(a["avg_return"] for a in aggs) / len(aggs)
                if ar > best_r:
                    best_r = ar
                    best_s = entries[0].get("strategy_name", "")
        if best_s:
            lines.extend([
                f"**多策略对比**：技术分析策略组中，`{best_s}` 表现最佳"
                f"（跨池平均收益 {_fmt(best_r)}）",
                "",
            ])

    cs_results = scenario_results.get("composite_strategy_compare", {})
    if cs_results:
        groups = {}
        for entry in cs_results.values():
            groups.setdefault(entry.get("strategy_id", ""), []).append(entry)
        best_c = None
        best_r = -float("inf")
        for entries in groups.values():
            aggs = []
            for e in entries:
                m = e.get("result", {}).get("metrics_per_symbol", {})
                if m:
                    aggs.append(_aggregate_metrics(m))
            if aggs:
                ar = sum(a["avg_return"] for a in aggs) / len(aggs)
                if ar > best_r:
                    best_r = ar
                    best_c = entries[0].get("strategy_name", "")
        if best_c:
            lines.extend([
                f"**合成因子策略对比**：合成因子策略组中，`{best_c}` 表现最佳"
                f"（跨池平均收益 {_fmt(best_r)}）",
                "",
            ])

    lines.extend([
        "### 5.4 组合策略可行性",
        "",
        "1. **表达式策略可行**：通过 `ExpressionPlugin` 的 `buy_expr`/`sell_expr`，",
        "   可直接引用合成因子名作为信号变量，回测引擎自动从 DB 加载因子值",
        "2. **多规则组策略可行**：通过 `td_strategy` 的 `groups` + `group_fusion` 配置，",
        "   可将合成因子组和 A/B 因子组按权重融合",
        "3. **混合因子加载可行**：BacktestService 支持日频/季频/合成因子的混合加载，",
        "   并自动进行向前填充",
        "",
        "### 5.5 改进建议",
        "",
        "1. **优化合成因子更新频率**：日频合成因子为周频更新，可考虑提升到日频",
        "2. **扩展季频合成因子覆盖**：部分季频合成因子数据较稀疏，需补充计算",
        "3. **引入动态权重**：当前合成因子等权 0.3/个，可考虑基于 ICIR 动态调整",
        "4. **多策略组合**：可将技术策略组与合成因子策略组本身进行组合",
        "5. **多周期验证**：可扩展到 63/126 天短中期周期",
        "",
        "---",
        "",
        "## 附录：原始数据文件",
        "",
        "| 类型 | 文件路径 |",
        "|---|---|",
        "| 基础选股 | `report/_data/selection/basic_selection.json` |",
        "| 扩展选股 | `report/_data/selection/extended_selection.json` |",
        "| 回测场景 | `report/_data/backtest/<scenario_id>.json` |",
        "| 回测索引 | `report/_data/backtest/_index.json` |",
        "",
        "*报告由 `scripts/factor_validation_report_generator.py` 自动生成*",
    ])
    return "\n".join(lines)


# ─── 总览报告 ────────────────────────────────────────────

def gen_overview(
    config: dict[str, Any],
    scenario_results: dict[str, dict[str, Any]],
) -> str:
    lines: list[str] = [
        "# 因子验证总览",
        "",
        "## 文档结构",
        "",
        "| 文档 | 内容 |",
        "|---|---|",
        "| [00_overview.md](00_overview.md) | 本文档：验证总览与文档导航 |",
        "| [01_selection_report.md](01_selection_report.md) | "
        "选股报告：基础+扩展方法的截面选股结果 |",
        "| [02_backtest_report.md](02_backtest_report.md) | "
        "回测报告：5个场景的时序策略回测结果 |",
        "| [03_analysis_report.md](03_analysis_report.md) | "
        "综合分析报告：选股效果、策略绩效、综合结论 |",
        "",
        "## 验证范围",
        "",
        f"- **股池**: {', '.join(p['name'] for p in config['selection']['pools'])}",
        f"- **基础选股方法**: {len(config['selection']['basic_methods'])} 个",
        f"- **扩展选股方法**: {len(config['selection']['extended_methods'])} 个",
        f"- **技术策略组**: {len(config['strategies']['technical_group'])} 个",
        f"- **合成因子策略组**: {len(config['strategies']['composite_group'])} 个",
        f"- **回测场景**: {len(config['scenarios'])} 个",
        "",
        "## 验证场景概览",
        "",
        "| 场景 | 名称 | 回测次数 |",
        "|---|---|---|",
    ]
    total = 0
    for sc_id, sc_name in SCENARIO_NAMES.items():
        count = len(scenario_results.get(sc_id, {}))
        total += count
        lines.append(f"| `{sc_id}` | {sc_name} | {count} |")
    lines.append(f"| | **合计** | **{total}** |")

    lines.extend([
        "",
        "## 配置文件",
        "",
        "- **配置文件**: `scripts/factor_validation_config.yml`",
        "- **测试脚本**: `scripts/factor_validation_runner.py`",
        "- **报告生成器**: `scripts/factor_validation_report_generator.py`",
        "",
        "## 原始数据",
        "",
        "所有原始数据保存在 `report/_data/` 下：",
        "",
        "```",
        "report/_data/",
        "├── selection/",
        "│   ├── basic_selection.json       # 基础方法选股结果",
        "│   └── extended_selection.json    # 扩展方法选股结果",
        "└── backtest/",
        "    ├── _index.json                 # 场景索引",
        "    ├── multi_strategy_compare.json",
        "    ├── multi_period_analysis.json",
        "    ├── selection_method_compare.json",
        "    ├── composite_strategy_compare.json",
        "    └── extended_method_compare.json",
        "```",
    ])
    return "\n".join(lines)


# ─── 主流程 ───────────────────────────────────────────────

def main() -> None:
    print("[1/4] 加载配置...")
    config = _load_config()

    print("[2/4] 加载数据文件...")
    basic_data = _load_json(_SELECTION_DIR / "basic_selection.json")
    extended_data = _load_json(_SELECTION_DIR / "extended_selection.json")

    scenario_results: dict[str, dict[str, Any]] = {}
    for sc_id in SCENARIO_NAMES.keys():
        sc_path = _BACKTEST_DIR / f"{sc_id}.json"
        if sc_path.exists():
            scenario_results[sc_id] = _load_json(sc_path)
            print(f"  {sc_id}: {len(scenario_results[sc_id])} 次回测")
        else:
            print(f"  {sc_id}: 文件不存在，跳过")

    print("[3/4] 生成报告...")
    overview = gen_overview(config, scenario_results)
    selection_report = gen_selection_report(config, basic_data, extended_data)
    backtest_report = gen_backtest_report(config, scenario_results)
    analysis_report = gen_analysis_report(
        config, basic_data, extended_data, scenario_results,
    )

    print("[4/4] 保存报告...")
    reports = [
        ("00_overview.md", overview),
        ("01_selection_report.md", selection_report),
        ("02_backtest_report.md", backtest_report),
        ("03_analysis_report.md", analysis_report),
    ]
    for filename, content in reports:
        path = _REPORT_DIR / filename
        path.write_text(content, encoding="utf-8")
        size_kb = path.stat().st_size / 1024
        print(f"  {filename}: {size_kb:.1f} KB")

    print("\n[OK] 4 份报告已生成到 report/")


if __name__ == "__main__":
    main()
