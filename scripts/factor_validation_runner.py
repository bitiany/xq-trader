"""因子验证统一测试脚本 — 整合 V1（多策略/多周期/多组合）+ V2（季频/合成因子）。

通过 YAML 配置文件定义选股策略、时序策略、回测场景，统一输出原始数据到 report/_data/。

设计原则:
  - 配置驱动：所有股池/方法/策略/场景由 YAML 定义
  - 数据分离：原始 JSON 数据 vs Markdown 报告独立生成
  - 选股复用：同池同方法只选一次，多个场景共享结果
  - 串行回测：避免 DB 连接池压力

用法:
    python scripts/factor_validation_runner.py
    python scripts/factor_validation_runner.py --config scripts/factor_validation_config.yml
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from fastapi import FastAPI

# 确保 src 在 path 中
_SRC = str(Path(__file__).resolve().parent.parent / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from framework.commons.logger import get_logger  # noqa: E402
from framework.config.settings import settings  # noqa: E402
from framework.dal.datasource_loader import DatasourceLoader  # noqa: E402
from framework.dal.register import register_datasource  # noqa: E402

import xqtrader.lifespan  # noqa: F401, E402
from xqtrader.domain.factor.models.factor_value import FacFactorValue  # noqa: E402
from xqtrader.domain.factor.services.cross_section_reader import (  # noqa: E402
    CrossSectionReader,
)
from xqtrader.domain.factor.services.factor_data_loader import (  # noqa: E402
    load_financial_composite_panel,
    load_financial_pit_panel,
)
from xqtrader.domain.trading.backtest.service import BacktestService  # noqa: E402

logger = get_logger("factor_validation")

# ─── 路径常量 ────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
_REPORT_DIR = _PROJECT_ROOT / "report"
_DATA_DIR = _REPORT_DIR / "_data"
_SELECTION_DIR = _DATA_DIR / "selection"
_BACKTEST_DIR = _DATA_DIR / "backtest"

# 因子数据文件
_DAILY_AB_JSON = _SCRIPTS_DIR / "_daily_ab_factors.json"
_QUARTERLY_AB_JSON = _SCRIPTS_DIR / "_quarterly_ab_factors.json"
_COMPOSITE_REGISTRY_JSON = _SCRIPTS_DIR / "_composite_registry.json"

# 默认配置
_DEFAULT_CONFIG = _SCRIPTS_DIR / "factor_validation_config.yml"

# 资金面因子关键字
FUND_FLOW_KEYWORDS = {"main_net", "big_net", "small_net", "fund_flow", "moneyflow"}
# 技术面因子关键字
TECHNICAL_KEYWORDS = {
    "hist_vol", "atr", "natr", "adx", "macd", "rsi",
    "boll", "bias", "mom",
}


# ─── 配置数据类 ──────────────────────────────────────────

@dataclass
class SelectionResult:
    """选股结果。"""
    pool_id: str
    pool_name: str
    method: str
    method_name: str
    method_type: str  # basic / extended
    signal_date: str = ""
    daily_factor_count: int = 0
    quarterly_factor_count: int = 0
    composite_factor_count: int = 0
    top_weights: dict[str, float] = field(default_factory=dict)
    top10: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool_id": self.pool_id,
            "pool_name": self.pool_name,
            "method": self.method,
            "method_name": self.method_name,
            "method_type": self.method_type,
            "signal_date": self.signal_date,
            "daily_factor_count": self.daily_factor_count,
            "quarterly_factor_count": self.quarterly_factor_count,
            "composite_factor_count": self.composite_factor_count,
            "top_weights": self.top_weights,
            "top10": self.top10,
            "error": self.error,
        }


# ─── 工具函数 ────────────────────────────────────────────

def _load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def _build_icir_weights(factors: list[dict[str, Any]]) -> dict[str, float]:
    """构建因子 ICIR 权重（同因子取最大 |ICIR|）。"""
    icir_map: dict[str, float] = {}
    for f in factors:
        fid = f["factor_id"]
        icir = f.get("icir") or 0.0
        if fid not in icir_map or abs(icir) > abs(icir_map[fid]):
            icir_map[fid] = float(icir)
    total = sum(abs(v) for v in icir_map.values())
    if total <= 0:
        return {}
    return {fid: v / total for fid, v in icir_map.items()}


def _calc_period_dates(signal_date: date, trading_days: int) -> tuple[date, date]:
    """根据信号日和交易日数计算回测起止日期。"""
    end_date = signal_date
    calendar_days = int(trading_days * 1.5)
    start_date = end_date - timedelta(days=calendar_days)
    return start_date, end_date


def _filter_factors_by_keyword(
    pool_factors: list[dict[str, Any]],
    keywords: set[str],
) -> list[dict[str, Any]]:
    """按关键字过滤因子子集。"""
    return [
        f for f in pool_factors
        if any(kw in f["factor_id"].lower() for kw in keywords)
    ]


# ─── 选股：基础方法（V1：仅日频 A/B 因子） ──────────────

async def _get_latest_factor_date(factor_ids: list[str]) -> date | None:
    """查询 FacFactorValue 中这些因子的最新交易日期。"""
    if not factor_ids:
        return None
    for fid in factor_ids:
        records = await FacFactorValue.filter(
            pool_id="all",
            factor_id=fid,
            order_by=FacFactorValue.trade_date.desc(),
            limit=1,
        )
        if records:
            return records[0].trade_date
    return None


async def _load_daily_factor_snapshot(
    factor_ids: list[str],
    symbols: list[str],
    signal_date: date,
) -> pd.DataFrame:
    """加载日频/周频因子在信号日的截面快照（PIT）。

    - 日频因子：按 signal_date 精确匹配
    - 周频因子（合成因子）：取 signal_date 当天或之前最新值
    """
    if not factor_ids or not symbols:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for fid in factor_ids:
        latest = await FacFactorValue.filter(
            trade_date__lte=signal_date,
            pool_id="all",
            factor_id=fid,
            order_by=FacFactorValue.trade_date.desc(),
            limit=1,
        )
        if not latest:
            continue
        latest_date = latest[0].trade_date
        records = await FacFactorValue.filter(
            trade_date=latest_date,
            pool_id="all",
            factor_id=fid,
            symbol__in=symbols,
        )
        for r in records:
            if r.factor_value is not None:
                rows.append({"symbol": r.symbol, fid: float(r.factor_value)})

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.groupby("symbol").agg("first")


async def _load_quarterly_factor_snapshot(
    factor_ids: list[str],
    symbols: list[str],
    signal_date: date,
) -> pd.DataFrame:
    """加载季频单因子在信号日的截面快照（PIT + 向前填充）。"""
    if not factor_ids or not symbols:
        return pd.DataFrame()

    start_date = signal_date - timedelta(days=400)
    end_date = signal_date

    parts: dict[str, pd.Series] = {}
    for fid in factor_ids:
        panel = await load_financial_pit_panel(start_date, end_date, fid, symbols)
        if panel.empty:
            continue
        panel = panel.reset_index()
        panel["trade_date"] = pd.to_datetime(panel["trade_date"])
        target_ts = pd.Timestamp(signal_date)
        valid = panel[panel["trade_date"] <= target_ts]
        if valid.empty:
            continue
        latest_date = valid["trade_date"].max()
        snapshot = valid[valid["trade_date"] == latest_date].set_index("symbol")[fid]
        parts[fid] = snapshot

    if not parts:
        return pd.DataFrame()
    return pd.DataFrame(parts)


async def _load_quarterly_composite_snapshot(
    factor_ids: list[str],
    symbols: list[str],
    signal_date: date,
    pool_id: str,
) -> pd.DataFrame:
    """加载季频合成因子在信号日的截面快照（PIT + 向前填充）。"""
    if not factor_ids or not symbols:
        return pd.DataFrame()

    start_date = signal_date - timedelta(days=400)
    end_date = signal_date

    parts: dict[str, pd.Series] = {}
    for fid in factor_ids:
        panel = await load_financial_composite_panel(
            start_date, end_date, fid, symbols, pool_id=pool_id,
        )
        if panel.empty:
            continue
        panel = panel.reset_index()
        panel["trade_date"] = pd.to_datetime(panel["trade_date"])
        target_ts = pd.Timestamp(signal_date)
        valid = panel[panel["trade_date"] <= target_ts]
        if valid.empty:
            continue
        latest_date = valid["trade_date"].max()
        snapshot = valid[valid["trade_date"] == latest_date].set_index("symbol")[fid]
        parts[fid] = snapshot

    if not parts:
        return pd.DataFrame()
    return pd.DataFrame(parts)


async def select_basic_method(
    pool_id: str,
    pool_name: str,
    method_id: str,
    method_name: str,
    factor_filter: str,
    daily_ab: list[dict[str, Any]],
    reader: CrossSectionReader,
    top_n: int,
) -> SelectionResult:
    """基础选股方法（V1）：仅日频 A/B 因子，按因子子集过滤。"""
    result = SelectionResult(
        pool_id=pool_id, pool_name=pool_name,
        method=method_id, method_name=method_name,
        method_type="basic",
    )

    pool_factors = [f for f in daily_ab if f["pool_id"] == pool_id]
    if not pool_factors:
        result.error = "无 A/B 因子"
        return result

    # 因子过滤
    if factor_filter == "fund_flow":
        filtered = _filter_factors_by_keyword(pool_factors, FUND_FLOW_KEYWORDS)
        if len(filtered) < 3:
            filtered = pool_factors
    elif factor_filter == "technical":
        filtered = _filter_factors_by_keyword(pool_factors, TECHNICAL_KEYWORDS)
        if len(filtered) < 3:
            filtered = pool_factors
    else:
        filtered = pool_factors

    factor_ids = sorted({f["factor_id"] for f in filtered})
    weights = _build_icir_weights(filtered)
    if not weights:
        result.error = "ICIR 权重为空"
        return result

    signal_date = await _get_latest_factor_date(factor_ids)
    if signal_date is None:
        result.error = "无因子值数据"
        return result
    result.signal_date = str(signal_date)

    pool_symbols = await reader.load_pool_symbols(pool_id)
    if not pool_symbols:
        result.error = "池标的为空"
        return result

    available_factors = [f for f in factor_ids if f in weights]
    snapshot = await _load_daily_factor_snapshot(available_factors, pool_symbols, signal_date)
    if snapshot.empty:
        result.error = "截面因子值为空"
        return result

    # Z-score + ICIR 加权
    z_cols: list[str] = []
    for fid, weight in weights.items():
        if fid not in snapshot.columns:
            continue
        col = snapshot[fid]
        std = col.std()
        z_col = f"{fid}_z"
        if std > 0:
            snapshot[z_col] = (col - col.mean()) / std
        else:
            snapshot[z_col] = 0.0
        snapshot[z_col] = snapshot[z_col].fillna(0.0) * weight
        z_cols.append(z_col)

    if not z_cols:
        result.error = "无可用因子列"
        return result

    snapshot["composite_score"] = snapshot[z_cols].sum(axis=1)
    snapshot = snapshot.sort_values("composite_score", ascending=False)
    top10_df = snapshot.head(top_n)

    for rank, (symbol, row) in enumerate(top10_df.iterrows(), 1):
        result.top10.append({
            "symbol": str(symbol),
            "score": round(float(row["composite_score"]), 4),
            "rank": rank,
        })

    result.daily_factor_count = len(available_factors)
    result.top_weights = {
        k: round(v, 4) for k, v in sorted(
            weights.items(), key=lambda x: -abs(x[1]),
        )[:5]
    }

    logger.info(
        "[选股-基础] pool=%s method=%s factors=%d Top%d: %s",
        pool_id, method_id, len(available_factors), len(result.top10),
        ", ".join(f"{s['symbol']}({s['score']:.2f})" for s in result.top10[:3]),
    )
    return result


async def select_extended_method(
    pool_id: str,
    pool_name: str,
    method_id: str,
    method_name: str,
    method_cfg: dict[str, Any],
    daily_ab: list[dict[str, Any]],
    quarterly_ab: list[dict[str, Any]],
    composite_reg: list[dict[str, Any]],
    reader: CrossSectionReader,
    top_n: int,
) -> SelectionResult:
    """扩展选股方法（V2）：可包含日频/季频/合成因子。"""
    result = SelectionResult(
        pool_id=pool_id, pool_name=pool_name,
        method=method_id, method_name=method_name,
        method_type="extended",
    )

    include_daily = method_cfg.get("include_daily", True)
    include_quarterly = method_cfg.get("include_quarterly", False)
    include_composite = method_cfg.get("include_composite", False)
    composite_weight_per = float(method_cfg.get("composite_weight", 0.3))

    pool_daily = [f for f in daily_ab if f["pool_id"] == pool_id] if include_daily else []
    pool_quarterly = [f for f in quarterly_ab if f["pool_id"] == pool_id] if include_quarterly else []
    all_composite = list(composite_reg) if include_composite else []

    # 合成因子按是否季频分组
    daily_composite_ids = sorted({
        f["factor_id"] for f in all_composite
        if not f["factor_id"].endswith("_quarterly")
    })
    quarterly_composite_ids = sorted({
        f["factor_id"] for f in all_composite
        if f["factor_id"].endswith("_quarterly")
    })

    daily_ids = sorted({f["factor_id"] for f in pool_daily})
    quarterly_ids = sorted({f["factor_id"] for f in pool_quarterly})

    result.daily_factor_count = len(daily_ids) + len(daily_composite_ids)
    result.quarterly_factor_count = len(quarterly_ids) + len(quarterly_composite_ids)
    result.composite_factor_count = len(daily_composite_ids) + len(quarterly_composite_ids)

    # 构建 ICIR 权重
    weights = _build_icir_weights(pool_daily + pool_quarterly)
    composite_count = len(daily_composite_ids) + len(quarterly_composite_ids)
    if composite_count > 0:
        composite_weight_total = composite_weight_per * composite_count
        if weights:
            scale = max(0.0, 1.0 - composite_weight_total)
            weights = {k: v * scale for k, v in weights.items()}
        for fid in daily_composite_ids + quarterly_composite_ids:
            weights[fid] = composite_weight_per
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}

    if not weights:
        result.error = "ICIR 权重为空"
        return result

    # 信号日
    signal_date = await _get_latest_factor_date(daily_ids)
    if signal_date is None and daily_composite_ids:
        signal_date = await _get_latest_factor_date(daily_composite_ids)
    if signal_date is None:
        result.error = "无信号日数据"
        return result
    result.signal_date = str(signal_date)

    pool_symbols = await reader.load_pool_symbols(pool_id)
    if not pool_symbols:
        result.error = "池标的为空"
        return result

    # 加载各类因子截面
    snapshots: list[pd.DataFrame] = []
    daily_all_ids = daily_ids + daily_composite_ids
    if daily_all_ids:
        snap = await _load_daily_factor_snapshot(daily_all_ids, pool_symbols, signal_date)
        if not snap.empty:
            snapshots.append(snap)
    if quarterly_ids:
        snap = await _load_quarterly_factor_snapshot(quarterly_ids, pool_symbols, signal_date)
        if not snap.empty:
            snapshots.append(snap)
    if quarterly_composite_ids:
        snap = await _load_quarterly_composite_snapshot(
            quarterly_composite_ids, pool_symbols, signal_date, pool_id,
        )
        if not snap.empty:
            snapshots.append(snap)

    if not snapshots:
        result.error = "所有因子截面为空"
        return result

    combined = snapshots[0]
    for snap in snapshots[1:]:
        combined = combined.join(snap, how="outer")

    available_factors = [fid for fid in weights.keys() if fid in combined.columns]
    if not available_factors:
        result.error = "无可用因子列"
        return result

    z_cols: list[str] = []
    for fid in available_factors:
        col = combined[fid]
        std = col.std()
        z_col = f"{fid}_z"
        if std > 0:
            combined[z_col] = (col - col.mean()) / std
        else:
            combined[z_col] = 0.0
        combined[z_col] = combined[z_col].fillna(0.0) * weights[fid]
        z_cols.append(z_col)

    combined["composite_score"] = combined[z_cols].sum(axis=1)
    combined = combined.sort_values("composite_score", ascending=False)
    top10_df = combined.head(top_n)

    for rank, (symbol, row) in enumerate(top10_df.iterrows(), 1):
        result.top10.append({
            "symbol": str(symbol),
            "score": round(float(row["composite_score"]), 4),
            "rank": rank,
        })

    result.top_weights = {
        k: round(v, 4) for k, v in sorted(
            weights.items(), key=lambda x: -abs(x[1]),
        )[:5]
    }

    logger.info(
        "[选股-扩展] pool=%s method=%s daily=%d quarterly=%d composite=%d Top%d: %s",
        pool_id, method_id, result.daily_factor_count,
        result.quarterly_factor_count, result.composite_factor_count,
        len(result.top10),
        ", ".join(f"{s['symbol']}({s['score']:.2f})" for s in result.top10[:3]),
    )
    return result


# ─── 选股调度 ────────────────────────────────────────────

async def run_selection(
    config: dict[str, Any],
    daily_ab: list[dict[str, Any]],
    quarterly_ab: list[dict[str, Any]],
    composite_reg: list[dict[str, Any]],
    reader: CrossSectionReader,
) -> dict[str, SelectionResult]:
    """执行所有选股：基础方法 + 扩展方法。

    Returns: dict[key=f"{pool_id}__{method_id}", SelectionResult]
    """
    sel_cfg = config["selection"]
    pools = sel_cfg["pools"]
    basic_methods = sel_cfg.get("basic_methods", [])
    extended_methods = sel_cfg.get("extended_methods", [])
    top_n = config["backtest"]["top_n"]

    results: dict[str, SelectionResult] = {}

    logger.info("=" * 60)
    logger.info("选股阶段 — %d 池 × %d 基础方法 + %d 扩展方法",
                len(pools), len(basic_methods), len(extended_methods))
    logger.info("=" * 60)

    for pool in pools:
        pool_id = pool["id"]
        pool_name = pool["name"]

        # 基础方法
        for m in basic_methods:
            method_id = m["id"]
            key = f"{pool_id}__{method_id}"
            logger.info("[选股] %s / %s", pool_id, method_id)
            result = await select_basic_method(
                pool_id=pool_id,
                pool_name=pool_name,
                method_id=method_id,
                method_name=m["name"],
                factor_filter=m.get("factor_filter", "all"),
                daily_ab=daily_ab,
                reader=reader,
                top_n=top_n,
            )
            results[key] = result

        # 扩展方法
        for m in extended_methods:
            method_id = m["id"]
            key = f"{pool_id}__{method_id}"
            logger.info("[选股] %s / %s", pool_id, method_id)
            result = await select_extended_method(
                pool_id=pool_id,
                pool_name=pool_name,
                method_id=method_id,
                method_name=m["name"],
                method_cfg=m,
                daily_ab=daily_ab,
                quarterly_ab=quarterly_ab,
                composite_reg=composite_reg,
                reader=reader,
                top_n=top_n,
            )
            results[key] = result

    return results


# ─── 回测模块 ────────────────────────────────────────────

async def run_backtest(
    strategy_id: str,
    symbols: list[str],
    start_date: date,
    end_date: date,
    initial_cash: float,
    commission: float,
) -> dict[str, Any]:
    """执行单次回测。"""
    if not symbols:
        return {"strategy_id": strategy_id, "status": "skipped", "metrics_per_symbol": {}}

    service = BacktestService()
    try:
        result = await service.execute(
            strategy_id=strategy_id,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            commission=commission,
        )
        return result
    except Exception as e:
        logger.error("[回测] 失败 strategy=%s: %s", strategy_id, e, exc_info=True)
        return {
            "strategy_id": strategy_id,
            "status": "failed",
            "error": str(e),
            "metrics_per_symbol": {},
        }


def _build_backtest_entry(
    scenario_id: str,
    pool_id: str,
    pool_name: str,
    strategy_id: str,
    strategy_name: str,
    start_date: date,
    end_date: date,
    trading_days: int,
    symbols: list[str],
    method: str = "",
    method_name: str = "",
    period_key: str = "",
    period_name: str = "",
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建回测结果 entry。"""
    entry: dict[str, Any] = {
        "scenario_id": scenario_id,
        "pool_id": pool_id,
        "pool_name": pool_name,
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "method": method,
        "method_name": method_name,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "trading_days": trading_days,
        "symbols": symbols,
        "result": result or {},
    }
    if period_key:
        entry["period_key"] = period_key
        entry["period_name"] = period_name
    return entry


# ─── 回测场景执行 ────────────────────────────────────────

async def run_scenarios(
    config: dict[str, Any],
    selection_results: dict[str, SelectionResult],
    signal_date: date,
) -> dict[str, dict[str, Any]]:
    """执行所有回测场景。

    Returns: dict[scenario_id, dict[key, backtest_entry]]
    """
    bt_cfg = config["backtest"]
    scenarios = config.get("scenarios", [])
    initial_cash = float(bt_cfg["initial_cash"])
    commission = float(bt_cfg["commission"])
    default_trading_days = int(bt_cfg.get("default_trading_days", 252))
    periods_cfg = {p["id"]: p for p in bt_cfg.get("periods", [])}

    # 策略名映射
    strategy_name_map: dict[str, str] = {}
    for s in config["strategies"].get("technical_group", []):
        strategy_name_map[s["id"]] = s["name"]
    for s in config["strategies"].get("composite_group", []):
        strategy_name_map[s["id"]] = s["name"]

    scenario_results: dict[str, dict[str, Any]] = {}

    for scenario in scenarios:
        if not scenario.get("enabled", True):
            logger.info("[场景] %s 已禁用，跳过", scenario["id"])
            continue

        sc_id = scenario["id"]
        sc_name = scenario["name"]
        logger.info("\n" + "=" * 50)
        logger.info("[场景] %s — %s", sc_id, sc_name)
        logger.info("=" * 50)

        results: dict[str, Any] = {}
        symbols_cache: dict[str, list[str]] = {}

        def _get_symbols(pool_id: str, method: str) -> list[str]:
            cache_key = f"{pool_id}__{method}"
            if cache_key not in symbols_cache:
                sel = selection_results.get(cache_key)
                symbols_cache[cache_key] = (
                    [s["symbol"] for s in sel.top10] if sel else []
                )
            return symbols_cache[cache_key]

        # 场景1: 多策略对比
        if sc_id == "multi_strategy_compare":
            pools = scenario.get("pools", [])
            method = scenario.get("selection_method", "icir_all")
            strategies = scenario.get("strategies", [])
            trading_days = int(scenario.get("trading_days", default_trading_days))
            start_date, end_date = _calc_period_dates(signal_date, trading_days)

            for pool_id in pools:
                pool_name = _get_pool_name(config, pool_id)
                symbols = _get_symbols(pool_id, method)
                if not symbols:
                    logger.warning("[场景] %s 池 %s 无选股结果", sc_id, pool_id)
                    continue

                for strategy_id in strategies:
                    strategy_name = strategy_name_map.get(strategy_id, strategy_id)
                    logger.info(
                        "[场景] %s pool=%s strategy=%s symbols=%d",
                        sc_id, pool_id, strategy_id, len(symbols),
                    )
                    bt = await run_backtest(
                        strategy_id, symbols, start_date, end_date,
                        initial_cash, commission,
                    )
                    key = f"{pool_id}__{strategy_id}"
                    results[key] = _build_backtest_entry(
                        sc_id, pool_id, pool_name, strategy_id, strategy_name,
                        start_date, end_date, trading_days, symbols,
                        method=method, method_name=method, result=bt,
                    )

        # 场景2: 多周期分析
        elif sc_id == "multi_period_analysis":
            pools = scenario.get("pools", [])
            method = scenario.get("selection_method", "icir_all")
            strategies = scenario.get("strategies", ["ts_macd_cross"])
            period_ids = scenario.get("periods", ["short", "medium", "long"])
            strategy_id = strategies[0] if strategies else "ts_macd_cross"
            strategy_name = strategy_name_map.get(strategy_id, strategy_id)

            for pool_id in pools:
                pool_name = _get_pool_name(config, pool_id)
                symbols = _get_symbols(pool_id, method)
                if not symbols:
                    continue

                for period_id in period_ids:
                    period = periods_cfg.get(period_id)
                    if not period:
                        continue
                    trading_days = int(period["days"])
                    start_date, end_date = _calc_period_dates(signal_date, trading_days)
                    logger.info(
                        "[场景] %s pool=%s period=%s(%d天)",
                        sc_id, pool_id, period_id, trading_days,
                    )
                    bt = await run_backtest(
                        strategy_id, symbols, start_date, end_date,
                        initial_cash, commission,
                    )
                    key = f"{pool_id}__{period_id}"
                    results[key] = _build_backtest_entry(
                        sc_id, pool_id, pool_name, strategy_id, strategy_name,
                        start_date, end_date, trading_days, symbols,
                        method=method, method_name=method,
                        period_key=period_id, period_name=period["name"],
                        result=bt,
                    )

        # 场景3: 选股方法对比（V1）
        elif sc_id == "selection_method_compare":
            pools = scenario.get("pools", [])
            methods = scenario.get("selection_methods", [])
            strategies = scenario.get("strategies", ["ts_macd_cross"])
            trading_days = int(scenario.get("trading_days", default_trading_days))
            strategy_id = strategies[0] if strategies else "ts_macd_cross"
            strategy_name = strategy_name_map.get(strategy_id, strategy_id)
            start_date, end_date = _calc_period_dates(signal_date, trading_days)

            for pool_id in pools:
                pool_name = _get_pool_name(config, pool_id)
                for method_id in methods:
                    symbols = _get_symbols(pool_id, method_id)
                    if not symbols:
                        logger.warning("[场景] %s 池 %s 方法 %s 无选股结果",
                                       sc_id, pool_id, method_id)
                        continue
                    method_name = _get_method_name(config, method_id)
                    logger.info(
                        "[场景] %s pool=%s method=%s symbols=%d",
                        sc_id, pool_id, method_id, len(symbols),
                    )
                    bt = await run_backtest(
                        strategy_id, symbols, start_date, end_date,
                        initial_cash, commission,
                    )
                    key = f"{pool_id}__{method_id}"
                    results[key] = _build_backtest_entry(
                        sc_id, pool_id, pool_name, strategy_id, strategy_name,
                        start_date, end_date, trading_days, symbols,
                        method=method_id, method_name=method_name, result=bt,
                    )

        # 场景4: 合成因子策略对比（V2）
        elif sc_id == "composite_strategy_compare":
            pools = scenario.get("pools", [])
            method = scenario.get("selection_method", "daily_plus_quarterly")
            strategies = scenario.get("strategies", [])
            trading_days = int(scenario.get("trading_days", default_trading_days))
            start_date, end_date = _calc_period_dates(signal_date, trading_days)

            for pool_id in pools:
                pool_name = _get_pool_name(config, pool_id)
                symbols = _get_symbols(pool_id, method)
                if not symbols:
                    logger.warning("[场景] %s 池 %s 无选股结果", sc_id, pool_id)
                    continue

                for strategy_id in strategies:
                    strategy_name = strategy_name_map.get(strategy_id, strategy_id)
                    logger.info(
                        "[场景] %s pool=%s strategy=%s symbols=%d",
                        sc_id, pool_id, strategy_id, len(symbols),
                    )
                    bt = await run_backtest(
                        strategy_id, symbols, start_date, end_date,
                        initial_cash, commission,
                    )
                    key = f"{pool_id}__{strategy_id}"
                    results[key] = _build_backtest_entry(
                        sc_id, pool_id, pool_name, strategy_id, strategy_name,
                        start_date, end_date, trading_days, symbols,
                        method=method, method_name=method, result=bt,
                    )

        # 场景5: 扩展选股方法对比（V2）
        elif sc_id == "extended_method_compare":
            pools = scenario.get("pools", [])
            methods = scenario.get("selection_methods", [])
            strategies = scenario.get("strategies", ["ts_composite_alpha_threshold"])
            trading_days = int(scenario.get("trading_days", default_trading_days))
            strategy_id = strategies[0] if strategies else "ts_composite_alpha_threshold"
            strategy_name = strategy_name_map.get(strategy_id, strategy_id)
            start_date, end_date = _calc_period_dates(signal_date, trading_days)

            for pool_id in pools:
                pool_name = _get_pool_name(config, pool_id)
                for method_id in methods:
                    symbols = _get_symbols(pool_id, method_id)
                    if not symbols:
                        continue
                    method_name = _get_method_name(config, method_id)
                    logger.info(
                        "[场景] %s pool=%s method=%s symbols=%d",
                        sc_id, pool_id, method_id, len(symbols),
                    )
                    bt = await run_backtest(
                        strategy_id, symbols, start_date, end_date,
                        initial_cash, commission,
                    )
                    key = f"{pool_id}__{method_id}__{strategy_id}"
                    results[key] = _build_backtest_entry(
                        sc_id, pool_id, pool_name, strategy_id, strategy_name,
                        start_date, end_date, trading_days, symbols,
                        method=method_id, method_name=method_name, result=bt,
                    )

        scenario_results[sc_id] = results
        logger.info("[场景] %s 完成: %d 次回测", sc_id, len(results))

    return scenario_results


def _get_pool_name(config: dict[str, Any], pool_id: str) -> str:
    for p in config["selection"]["pools"]:
        if p["id"] == pool_id:
            return p["name"]
    return pool_id


def _get_method_name(config: dict[str, Any], method_id: str) -> str:
    for m in config["selection"].get("basic_methods", []):
        if m["id"] == method_id:
            return m["name"]
    for m in config["selection"].get("extended_methods", []):
        if m["id"] == method_id:
            return m["name"]
    return method_id


# ─── 数据保存 ────────────────────────────────────────────

def _save_selection(
    selection_results: dict[str, SelectionResult],
    config: dict[str, Any],
) -> None:
    """保存选股结果，按方法类型分组。"""
    _SELECTION_DIR.mkdir(parents=True, exist_ok=True)

    # 按方法类型分组
    basic_results: dict[str, Any] = {}
    extended_results: dict[str, Any] = {}

    for key, result in selection_results.items():
        if result.method_type == "basic":
            basic_results[key] = result.to_dict()
        else:
            extended_results[key] = result.to_dict()

    # 保存基础方法选股
    basic_path = _SELECTION_DIR / "basic_selection.json"
    basic_path.write_text(
        json.dumps(
            {"config": {"methods": config["selection"]["basic_methods"]},
             "results": basic_results},
            indent=2, ensure_ascii=False, default=str,
        ),
        encoding="utf-8",
    )
    logger.info("[保存] 基础选股结果: %s (%d 组)", basic_path, len(basic_results))

    # 保存扩展方法选股
    extended_path = _SELECTION_DIR / "extended_selection.json"
    extended_path.write_text(
        json.dumps(
            {"config": {"methods": config["selection"]["extended_methods"]},
             "results": extended_results},
            indent=2, ensure_ascii=False, default=str,
        ),
        encoding="utf-8",
    )
    logger.info("[保存] 扩展选股结果: %s (%d 组)", extended_path, len(extended_results))


def _save_backtests(
    scenario_results: dict[str, dict[str, Any]],
) -> None:
    """保存回测结果，每个场景一个文件。"""
    _BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    summary: dict[str, int] = {}
    for sc_id, results in scenario_results.items():
        path = _BACKTEST_DIR / f"{sc_id}.json"
        path.write_text(
            json.dumps(results, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        summary[sc_id] = len(results)
        logger.info("[保存] 回测结果: %s (%d 次)", path, len(results))

    # 保存汇总索引
    summary_path = _BACKTEST_DIR / "_index.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ─── 主流程 ───────────────────────────────────────────────

async def main(config_path: Path) -> None:
    logger.info("=" * 60)
    logger.info("因子验证统一测试 — 配置驱动")
    logger.info("配置文件: %s", config_path)
    logger.info("=" * 60)

    # 加载配置
    config = _load_config(config_path)

    # 初始化目录
    _SELECTION_DIR.mkdir(parents=True, exist_ok=True)
    _BACKTEST_DIR.mkdir(parents=True, exist_ok=True)

    # 初始化 DB
    logger.info("[Init] 初始化数据库连接...")
    loader = DatasourceLoader(settings.APP.DB_CONFIG_PATH)
    app = FastAPI()
    register_datasource(
        app,
        datasource_config=loader.datasources,
        generate_schema=False,
        timescale_config=loader.timescale_config,
    )

    async with app.router.lifespan_context(app):
        logger.info("[Init] DB 连接成功")

        # 加载因子数据
        daily_ab = _load_json(_DAILY_AB_JSON)
        quarterly_ab = _load_json(_QUARTERLY_AB_JSON)
        composite_reg = _load_json(_COMPOSITE_REGISTRY_JSON)
        logger.info(
            "[Init] 因子: 日频A/B=%d, 季频A/B=%d, 合成因子=%d",
            len(daily_ab), len(quarterly_ab), len(composite_reg),
        )

        reader = CrossSectionReader()

        # ===== 选股阶段 =====
        selection_results = await run_selection(
            config, daily_ab, quarterly_ab, composite_reg, reader,
        )
        _save_selection(selection_results, config)

        # 获取基准信号日（用 style_growth 的任一方法）
        signal_date = None
        for method in ["icir_all", "daily_only"]:
            base = selection_results.get(f"style_growth__{method}")
            if base and base.signal_date:
                signal_date = date.fromisoformat(base.signal_date)
                break
        if signal_date is None:
            logger.error("[Main] 无法获取基准信号日，退出")
            return
        logger.info("[Main] 基准信号日: %s", signal_date)

        # ===== 回测阶段 =====
        scenario_results = await run_scenarios(
            config, selection_results, signal_date,
        )
        _save_backtests(scenario_results)

    logger.info("=" * 60)
    logger.info("统一测试完成")
    logger.info("  选股结果: %s", _SELECTION_DIR)
    logger.info("  回测结果: %s", _BACKTEST_DIR)
    logger.info("=" * 60)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="因子验证统一测试脚本")
    parser.add_argument(
        "--config", type=Path, default=_DEFAULT_CONFIG,
        help=f"配置文件路径（默认: {_DEFAULT_CONFIG})",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args.config))
