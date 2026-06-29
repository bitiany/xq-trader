"""因子截面 raw 数据加载 — 估值/财务 PIT / 逐标的因子值。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.models.financial_factor_value import FacFinancialFactorValue
from xqtrader.domain.factor.services.registry import get_factor
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.market.models.daily_indicator import DailyIndicator

logger = get_logger(__name__)

_QUERY_BATCH_SIZE = 500

# daily_indicator 表可直接读取的列
_DAILY_INDICATOR_COLUMNS = frozenset({
    "close", "turnover_rate", "turnover_rate_f", "volume_ratio",
    "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm",
    "total_share", "float_share", "free_share", "total_mv", "circ_mv",
    "ev", "ebitda", "ev_ebitda", "peg", "pcf",
})


async def resolve_data_origin(factor_id: str) -> str:
    """从注册表读取因子 data_origin。"""
    reg = await FacFactorRegistry.get_or_none(factor_id=factor_id)
    if reg is None or not reg.data_origin:
        return "computed"
    return reg.data_origin


async def load_trade_dates(
    start_date: date,
    end_date: date,
    symbols: list[str],
) -> list[date]:
    """加载区间内的交易日列表（取样本池首标的的 K 线日期）。"""
    if not symbols:
        return []
    anchor = symbols[0]
    records = await CandlestickDaily.filter(
        symbol=anchor,
        trade_date__gte=start_date,
        trade_date__lte=end_date,
        order_by=CandlestickDaily.trade_date.asc(),
    )
    return [r.trade_date for r in records]


async def load_from_factor_value(
    start_date: date,
    end_date: date,
    factor_ids: list[str],
    symbols: list[str],
    pool_id: str,
) -> pd.DataFrame:
    """从 fac_factor_value 加载；优先 pool_id，无数据时回退 all。"""
    if not factor_ids or not symbols:
        return pd.DataFrame()

    async def _query(pid: str) -> list[dict]:
        rows: list[dict] = []
        for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
            batch = symbols[i:i + _QUERY_BATCH_SIZE]
            records = await FacFactorValue.filter(
                trade_date__gte=start_date,
                trade_date__lte=end_date,
                pool_id=pid,
                factor_id__in=factor_ids,
                symbol__in=batch,
            )
            rows.extend(
                {"trade_date": r.trade_date, "symbol": r.symbol, r.factor_id: r.factor_value}
                for r in records
            )
        return rows

    all_rows = await _query(pool_id)
    if not all_rows and pool_id != "all":
        all_rows = await _query("all")

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.groupby(["trade_date", "symbol"]).agg("first").reset_index()
    return df.set_index(["trade_date", "symbol"])


async def load_financial_pit_panel(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
) -> pd.DataFrame:
    """财务因子 PIT 加载 + 应用层前向填充至日频。"""
    if not symbols:
        return pd.DataFrame()

    pit_rows: list[dict] = []
    for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
        batch = symbols[i:i + _QUERY_BATCH_SIZE]
        records = await FacFinancialFactorValue.filter(
            symbol__in=batch,
            factor_id=factor_id,
            ann_date__lte=end_date,
        )
        for r in records:
            if r.factor_value is not None and np.isfinite(r.factor_value):
                pit_rows.append({
                    "symbol": r.symbol,
                    "ann_date": r.ann_date,
                    factor_id: float(r.factor_value),
                })

    if not pit_rows:
        return pd.DataFrame()

    fin_df = pd.DataFrame(pit_rows).sort_values(["symbol", "ann_date"])
    trade_dates = await load_trade_dates(start_date, end_date, symbols)
    if not trade_dates:
        return pd.DataFrame()

    trade_index = pd.DataFrame({"trade_date": pd.to_datetime(trade_dates)})
    parts: list[pd.DataFrame] = []
    for symbol in symbols:
        sym_fin = fin_df[fin_df["symbol"] == symbol]
        if sym_fin.empty:
            continue
        sym_pit = sym_fin.rename(columns={"ann_date": "trade_date"})[
            ["trade_date", factor_id]
        ].drop_duplicates("trade_date", keep="last")
        sym_pit["trade_date"] = pd.to_datetime(sym_pit["trade_date"])
        merged = pd.merge_asof(
            trade_index.sort_values("trade_date"),
            sym_pit.sort_values("trade_date"),
            on="trade_date",
            direction="backward",
        )
        merged["symbol"] = symbol
        merged = merged.dropna(subset=[factor_id])
        if merged.empty:
            continue
        parts.append(merged.set_index(["trade_date", "symbol"])[[factor_id]])

    if not parts:
        return pd.DataFrame()
    return pd.concat(parts)


async def load_daily_indicator_raw(
    start_date: date,
    end_date: date,
    symbols: list[str],
    columns: list[str],
) -> pd.DataFrame:
    """加载 daily_indicator 原始列，MultiIndex(trade_date, symbol)。"""
    cols = [c for c in columns if c in _DAILY_INDICATOR_COLUMNS]
    if not symbols or not cols:
        return pd.DataFrame()

    all_rows: list[dict] = []
    for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
        batch = symbols[i:i + _QUERY_BATCH_SIZE]
        records = await DailyIndicator.filter(
            symbol__in=batch,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        )
        for r in records:
            row: dict = {"trade_date": r.trade_date, "symbol": r.symbol}
            for col in cols:
                row[col] = getattr(r, col, None)
            all_rows.append(row)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    return df.set_index(["trade_date", "symbol"]).sort_index()


def compute_plugin_panel(
    factor_id: str,
    raw_panel: pd.DataFrame,
) -> pd.DataFrame:
    """按标的时序调用 FactorPlugin.compute，输出单因子面板。"""
    plugin = get_factor(factor_id)
    if plugin is None or raw_panel.empty:
        return pd.DataFrame()

    parts: list[pd.Series] = []
    for symbol in raw_panel.index.get_level_values("symbol").unique():
        sym_slice = raw_panel.xs(symbol, level="symbol").sort_index()
        sym_df = sym_slice.to_frame() if isinstance(sym_slice, pd.Series) else sym_slice
        if sym_df.empty:
            continue
        computed = plugin.compute(sym_df)
        if factor_id not in computed.columns:
            continue
        series = computed[factor_id]
        mi = pd.MultiIndex.from_arrays(
            [series.index, [symbol] * len(series)],
            names=["trade_date", "symbol"],
        )
        parts.append(pd.Series(series.values, index=mi, name=factor_id))

    if not parts:
        return pd.DataFrame()
    result: pd.DataFrame = pd.concat(parts).to_frame(factor_id)
    return result


async def load_daily_indicator_factor_panel(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
) -> pd.DataFrame:
    """估值类因子：daily_indicator 直读 + Plugin 计算。"""
    plugin = get_factor(factor_id)
    if plugin is None:
        return pd.DataFrame()
    deps = [d for d in plugin.dependencies if d in _DAILY_INDICATOR_COLUMNS]
    if not deps:
        return pd.DataFrame()
    raw = await load_daily_indicator_raw(start_date, end_date, symbols, deps)
    return compute_plugin_panel(factor_id, raw)


async def load_mixed_factor_panel(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
) -> pd.DataFrame:
    """混合频率因子：daily_indicator + 财务 PIT 合并后 Plugin 计算。"""
    plugin = get_factor(factor_id)
    if plugin is None:
        return pd.DataFrame()

    daily_deps = [d for d in plugin.dependencies if d in _DAILY_INDICATOR_COLUMNS]
    fina_deps = [d for d in plugin.dependencies if d not in _DAILY_INDICATOR_COLUMNS]

    raw = await load_daily_indicator_raw(start_date, end_date, symbols, daily_deps)
    for dep_id in fina_deps:
        fin_panel = await load_financial_pit_panel(start_date, end_date, dep_id, symbols)
        if fin_panel.empty:
            continue
        if raw.empty:
            raw = fin_panel
        else:
            raw = raw.join(fin_panel, how="outer")

    if raw.empty:
        return pd.DataFrame()
    return compute_plugin_panel(factor_id, raw)


async def load_factor_raw_chunk(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
    pool_id: str,
) -> pd.DataFrame:
    """按 data_origin 分流加载单因子原始面板（未经截面预处理）。"""
    origin = await resolve_data_origin(factor_id)

    if origin == "fina_indicator":
        return await load_financial_pit_panel(start_date, end_date, factor_id, symbols)

    if "," in origin:
        return await load_mixed_factor_panel(start_date, end_date, factor_id, symbols)

    if origin in ("daily_indicator", "daily_derived"):
        return await load_daily_indicator_factor_panel(start_date, end_date, factor_id, symbols)

    if origin == "derived":
        return await load_derived_factor_panel(
            start_date, end_date, factor_id, symbols, pool_id,
        )

    if origin == "cross_section_beta":
        return await load_beta_factor_panel(
            start_date, end_date, factor_id, symbols,
        )

    if origin == "cross_section_compute":
        return await load_cross_section_compute_panel(
            start_date, end_date, factor_id, symbols,
        )

    return await load_from_factor_value(
        start_date, end_date, [factor_id], symbols, pool_id,
    )


async def load_derived_factor_panel(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
    pool_id: str,
) -> pd.DataFrame:
    """派生因子加载 — 从 base_factor 原值加载并重命名列为 factor_id。

    用于 z_ 前缀截面 Z-score 因子（z_main_net_pct, z_turnover）。
    CrossSectionReader 后续会做截面 Z-score。
    """
    reg = await FacFactorRegistry.get_or_none(factor_id=factor_id)
    if reg is None or not reg.base_factor:
        logger.warning("[derived] 因子 %s 未配置 base_factor，回退到 fac_factor_value", factor_id)
        return await load_from_factor_value(start_date, end_date, [factor_id], symbols, pool_id)

    base_factor_id = reg.base_factor
    df = await load_from_factor_value(
        start_date, end_date, [base_factor_id], symbols, pool_id,
    )
    if df.empty or base_factor_id not in df.columns:
        return df

    # z_ 因子：直接重命名列，CrossSectionReader 后续做 Z-score
    return df.rename(columns={base_factor_id: factor_id})


async def load_beta_factor_panel(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
) -> pd.DataFrame:
    """Beta 因子加载 — 个股收益 + 市场收益滚动回归。

    支持 beta_250（全样本）和 beta_down（仅负收益日）。
    """
    from xqtrader.domain.factor.services.cross_section_factor_calculator import (
        compute_beta_panel,
    )

    reg = await FacFactorRegistry.get_or_none(factor_id=factor_id)
    params = reg.params if reg and reg.params else {}
    index_code = params.get("index_code", "000300.SH")
    window = params.get("window", 250)
    downside_only = params.get("downside_only", False)

    return await compute_beta_panel(
        start_date=start_date,
        end_date=end_date,
        factor_id=factor_id,
        symbols=symbols,
        index_code=index_code,
        window=window,
        downside_only=downside_only,
    )


async def load_cross_section_compute_panel(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
) -> pd.DataFrame:
    """截面计算因子加载 — nl_size/stom 等需要专门计算的因子。"""
    from xqtrader.domain.factor.services.cross_section_factor_calculator import (
        compute_cross_section_factor,
    )

    return await compute_cross_section_factor(
        start_date=start_date,
        end_date=end_date,
        factor_id=factor_id,
        symbols=symbols,
    )
