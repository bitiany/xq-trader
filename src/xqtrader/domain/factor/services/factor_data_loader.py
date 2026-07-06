"""因子截面 raw 数据加载 — 估值/财务 PIT / 逐标的因子值。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.models.financial_composite_value import (
    FacFinancialCompositeValue,
)
from xqtrader.domain.factor.models.financial_factor_value import FacFinancialFactorValue
from xqtrader.domain.factor.services.registry import get_factor
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.market.models.daily_indicator import DailyIndicator

logger = get_logger(__name__)

_QUERY_BATCH_SIZE = 2000

# 已知在 fac_factor_value 表中无数据的 pool_id 集合（任务级缓存）。
# 一旦探测到 pool_id 无数据，后续相同 pool_id 的查询直接跳过到 'all' 池，
# 避免每次浪费 100-190s 的空查询扫描。
# 现状：fac_factor_value 仅 all/idx_300/idx_1000 三个 pool_id 有数据，
# style_value/style_growth/style_blue_chip/style_large_cap 等风格池均无数据。
_EMPTY_FACTOR_POOLS: set[str] = set()

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


async def resolve_update_freq(factor_id: str) -> str:
    """从注册表读取因子 update_freq（daily/weekly/quarterly）。"""
    reg = await FacFactorRegistry.get_or_none(factor_id=factor_id)
    if reg is None or not reg.update_freq:
        return "daily"
    return reg.update_freq


def clear_empty_pool_cache() -> None:
    """清空空池缓存（任务启动时调用一次）。"""
    _EMPTY_FACTOR_POOLS.clear()


def mark_pool_empty(pool_id: str) -> None:
    """标记 pool_id 在 fac_factor_value 中无数据（后续查询直接使用 all 池）。"""
    if pool_id != "all":
        _EMPTY_FACTOR_POOLS.add(pool_id)


def is_pool_empty(pool_id: str) -> bool:
    """检查 pool_id 是否已标记为空池。"""
    return pool_id != "all" and pool_id in _EMPTY_FACTOR_POOLS


async def probe_pool_has_factor_data(pool_id: str) -> bool:
    """探测 pool_id 在 fac_factor_value 中是否有数据。

    使用 LIMIT 1 命中索引 ix_fac_fv_date_pool(trade_date, pool_id)，
    正常情况常数级响应；若已命中缓存直接返回 False。

    Returns:
        True 表示 pool_id 有数据；False 表示无数据（已同步加入空池缓存）
    """
    if pool_id == "all":
        return True
    if pool_id in _EMPTY_FACTOR_POOLS:
        return False
    records = await FacFactorValue.filter(pool_id=pool_id, limit=1)
    if records:
        return True
    _EMPTY_FACTOR_POOLS.add(pool_id)
    logger.info(
        "[factor_value] 池探测: pool=%s 在 fac_factor_value 中无数据,已加入空池缓存",
        pool_id,
    )
    return False


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
    """从 fac_factor_value 加载；优先 pool_id，无数据时回退 all。

    性能优化（2026-07-04）：
      - 批次大小 500 → 2000，5294 只标的的查询数从 11 降至 3
      - 增加批次级耗时日志，便于定位瓶颈
      - 空池缓存：已知无数据的 pool_id 直接查 all 池，避免重复 100-190s 空查询
        （style_value 等风格池在 fac_factor_value 中无数据）
    """
    if not factor_ids or not symbols:
        return pd.DataFrame()

    # 空池缓存命中: 已知无数据的 pool_id 直接切换到 all 池
    effective_pool = pool_id
    cache_hit = False
    if pool_id != "all" and pool_id in _EMPTY_FACTOR_POOLS:
        effective_pool = "all"
        cache_hit = True

    async def _query(pid: str) -> list[dict]:
        rows: list[dict] = []
        batch_count = (len(symbols) + _QUERY_BATCH_SIZE - 1) // _QUERY_BATCH_SIZE
        for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
            batch_idx = i // _QUERY_BATCH_SIZE + 1
            batch = symbols[i:i + _QUERY_BATCH_SIZE]
            t_q = pd.Timestamp.now()
            records = await FacFactorValue.filter(
                trade_date__gte=start_date,
                trade_date__lte=end_date,
                pool_id=pid,
                factor_id__in=factor_ids,
                symbol__in=batch,
            )
            q_elapsed = (pd.Timestamp.now() - t_q).total_seconds()
            for r in records:
                rows.append({
                    "trade_date": r.trade_date,
                    "symbol": r.symbol,
                    r.factor_id: r.factor_value,
                })
            logger.info(
                "[factor_value] pool=%s factor=%s 查询批次 %d/%d: batch_symbols=%d rows=%d 耗时=%.2fs",
                pid, ",".join(factor_ids), batch_idx, batch_count,
                len(batch), len(records), q_elapsed,
            )
        return rows

    if cache_hit:
        logger.info(
            "[factor_value] pool=%s 命中空池缓存,直接使用 all 池 factor=%s",
            pool_id, ",".join(factor_ids),
        )

    all_rows = await _query(effective_pool)

    # 首次查询为空且非 all 池,加入缓存并回退到 all 池
    if not all_rows and effective_pool != "all":
        logger.info(
            "[factor_value] pool=%s 首次查询为空,加入空池缓存并回退 all 池 factor=%s",
            pool_id, ",".join(factor_ids),
        )
        _EMPTY_FACTOR_POOLS.add(pool_id)
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
    batch_count = (len(symbols) + _QUERY_BATCH_SIZE - 1) // _QUERY_BATCH_SIZE
    for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
        batch_idx = i // _QUERY_BATCH_SIZE + 1
        batch = symbols[i:i + _QUERY_BATCH_SIZE]
        t_q = pd.Timestamp.now()
        records = await FacFinancialFactorValue.filter(
            symbol__in=batch,
            factor_id=factor_id,
            ann_date__lte=end_date,
        )
        q_elapsed = (pd.Timestamp.now() - t_q).total_seconds()
        valid_count = 0
        for r in records:
            if r.factor_value is not None and np.isfinite(r.factor_value):
                pit_rows.append({
                    "symbol": r.symbol,
                    "ann_date": r.ann_date,
                    factor_id: float(r.factor_value),
                })
                valid_count += 1
        logger.info(
            "[financial_pit] factor=%s 查询批次 %d/%d: batch_symbols=%d rows=%d valid=%d 耗时=%.2fs",
            factor_id, batch_idx, batch_count, len(batch), len(records), valid_count, q_elapsed,
        )

    if not pit_rows:
        logger.warning(
            "[financial_pit] factor=%s 无有效数据: requested_symbols=%d,"
            "可能财务数据采集任务未覆盖该因子,IC 计算将为空",
            factor_id, len(symbols),
        )
        return pd.DataFrame()

    fin_df = pd.DataFrame(pit_rows).sort_values(["symbol", "ann_date"])
    pit_symbols = fin_df["symbol"].nunique()
    if pit_symbols < 3:
        logger.warning(
            "[financial_pit] factor=%s 数据严重稀疏: pit_symbols=%d << requested=%d,"
            "截面 IC 计算将退化为空(需≥3只标的),建议检查财务数据采集任务覆盖率",
            factor_id, pit_symbols, len(symbols),
        )

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


async def load_financial_composite_panel(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
    pool_id: str = "all",
) -> pd.DataFrame:
    """季频合成因子 PIT 加载 + 应用层前向填充至日频。

    与 load_financial_pit_panel 的区别：
      - 数据源为 stock.fac_financial_composite_value（含 pool_id 列）
      - 优先按 pool_id 查询，无数据时回退到 all 池
      - 同样使用 merge_asof(direction='backward') 实现向前填充
    """
    if not symbols:
        return pd.DataFrame()

    # 优先按 pool_id 查询
    pit_rows: list[dict] = []
    for effective_pool in (pool_id, "all"):
        batch_count = (len(symbols) + _QUERY_BATCH_SIZE - 1) // _QUERY_BATCH_SIZE
        for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
            batch_idx = i // _QUERY_BATCH_SIZE + 1
            batch = symbols[i:i + _QUERY_BATCH_SIZE]
            t_q = pd.Timestamp.now()
            records = await FacFinancialCompositeValue.filter(
                symbol__in=batch,
                factor_id=factor_id,
                pool_id=effective_pool,
                ann_date__lte=end_date,
            )
            q_elapsed = (pd.Timestamp.now() - t_q).total_seconds()
            valid_count = 0
            for r in records:
                if r.factor_value is not None and np.isfinite(r.factor_value):
                    pit_rows.append({
                        "symbol": r.symbol,
                        "ann_date": r.ann_date,
                        factor_id: float(r.factor_value),
                    })
                    valid_count += 1
            logger.info(
                "[financial_composite] factor=%s pool=%s 查询批次 %d/%d: "
                "batch_symbols=%d rows=%d valid=%d 耗时=%.2fs",
                factor_id, effective_pool, batch_idx, batch_count,
                len(batch), len(records), valid_count, q_elapsed,
            )
        if pit_rows:
            break
        logger.info(
            "[financial_composite] factor=%s pool=%s 无数据, 回退 all 池",
            factor_id, pool_id,
        )

    if not pit_rows:
        logger.warning(
            "[financial_composite] factor=%s 无有效数据: requested_symbols=%d",
            factor_id, len(symbols),
        )
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
        # 同一 ann_date 可能有多条（不同 end_date），取最后一条
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
    batch_count = (len(symbols) + _QUERY_BATCH_SIZE - 1) // _QUERY_BATCH_SIZE
    for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
        batch_idx = i // _QUERY_BATCH_SIZE + 1
        batch = symbols[i:i + _QUERY_BATCH_SIZE]
        t_q = pd.Timestamp.now()
        records = await DailyIndicator.filter(
            symbol__in=batch,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        )
        q_elapsed = (pd.Timestamp.now() - t_q).total_seconds()
        for r in records:
            row: dict = {"trade_date": r.trade_date, "symbol": r.symbol}
            for col in cols:
                row[col] = getattr(r, col, None)
            all_rows.append(row)
        logger.info(
            "[daily_indicator] cols=%s 查询批次 %d/%d: batch_symbols=%d rows=%d 耗时=%.2fs",
            ",".join(cols), batch_idx, batch_count, len(batch), len(records), q_elapsed,
        )

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
    update_freq = await resolve_update_freq(factor_id)

    # 季频合成因子（composite_*_quarterly）— 从 fac_financial_composite_value 加载
    if update_freq == "quarterly" and origin == "computed":
        return await load_financial_composite_panel(
            start_date, end_date, factor_id, symbols, pool_id,
        )

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


# 可批量加载的 data_origin 集合：这些因子统一走 load_from_factor_value，
# 可通过一次 DB 查询批量预加载到宽表，消除每因子独立查询的 I/O 瓶颈。
_BATCH_LOADABLE_ORIGINS: frozenset[str] = frozenset({"computed", "fund_flow", "market"})


async def preload_factor_raw_panels(
    start_date: date,
    end_date: date,
    factor_ids: list[str],
    symbols: list[str],
    pool_id: str,
) -> dict[str, pd.DataFrame]:
    """批量预加载因子原始面板，消除重复 DB 查询。

    性能优化（2026-07-05）：
      - computed/fund_flow/market/derived 类因子（约 114 个）通过一次 DB 查询批量加载到宽表，
        消除原"每因子一次大查询"的 I/O 瓶颈（110s/因子 × 114 = 3.5h → 单次 ~5-10min）
      - 其他类因子（fina_indicator/daily_indicator/cross_section_*/混合）保持独立加载，
        因其加载流程依赖 PIT/Plugin 计算等复杂逻辑

    按 data_origin 分组：
      - 批量组（computed/fund_flow/market）：直接收集 factor_id
      - derived 组：收集 base_factor_id，批量加载后按列重命名
      - 独立组（其他）：每因子独立调用 load_factor_raw_chunk

    Args:
        start_date: 全量加载起始日期（取最远日期，单因子按 effective_start 切片）
        end_date: 全量加载结束日期
        factor_ids: 待预加载的因子 ID 列表
        symbols: 样本池标的列表
        pool_id: 样本池标识

    Returns:
        {factor_id: raw_panel} 字典，raw_panel 为 MultiIndex(trade_date, symbol) 单列 DataFrame
    """
    if not factor_ids or not symbols:
        return {}

    t0 = pd.Timestamp.now()
    panels: dict[str, pd.DataFrame] = {}

    # 批量查询注册表元数据（data_origin / base_factor）
    regs = await FacFactorRegistry.filter(factor_id__in=factor_ids)
    reg_map: dict[str, FacFactorRegistry] = {r.factor_id: r for r in regs}

    batch_factor_ids: list[str] = []          # 批量加载的因子 ID
    derived_pairs: list[tuple[str, str]] = []  # (factor_id, base_factor_id)
    independent_factors: list[str] = []        # 独立加载的因子 ID

    for fid in factor_ids:
        reg = reg_map.get(fid)
        if reg is None:
            independent_factors.append(fid)
            continue
        origin = reg.data_origin or "computed"
        if origin in _BATCH_LOADABLE_ORIGINS:
            batch_factor_ids.append(fid)
        elif origin == "derived":
            base_fid = reg.base_factor or ""
            if base_fid:
                derived_pairs.append((fid, base_fid))
            else:
                independent_factors.append(fid)
        else:
            independent_factors.append(fid)

    # === 批量加载：computed/fund_flow/market 因子 + derived 因子的 base_factor ===
    base_factor_ids = {bf for _, bf in derived_pairs}
    # 去重：base_factor 可能本身也在批量列表中（如 cs_main_net_pct 是 fund_flow 类）
    all_batch_ids = list(dict.fromkeys(batch_factor_ids + sorted(base_factor_ids)))

    if all_batch_ids:
        logger.info(
            "[preload] 批量预加载开始: batch_factors=%d derived_factors=%d "
            "unique_columns=%d (含 base_factor 去重)",
            len(batch_factor_ids), len(derived_pairs), len(all_batch_ids),
        )
        wide_df = await load_from_factor_value(
            start_date, end_date, all_batch_ids, symbols, pool_id,
        )
        wide_elapsed = (pd.Timestamp.now() - t0).total_seconds()

        if not wide_df.empty:
            for fid in batch_factor_ids:
                if fid in wide_df.columns:
                    panels[fid] = wide_df[[fid]].copy()
            # derived 因子：从 base_factor 列重命名为 factor_id
            for fid, base_fid in derived_pairs:
                if base_fid in wide_df.columns:
                    panels[fid] = (
                        wide_df[[base_fid]]
                        .rename(columns={base_fid: fid})
                        .copy()
                    )
        logger.info(
            "[preload] 批量预加载完成: panels=%d / expected=%d 耗时=%.2fs",
            len(panels), len(batch_factor_ids) + len(derived_pairs), wide_elapsed,
        )

    # === 独立加载：fina_indicator/daily_indicator/cross_section_*/混合 ===
    if independent_factors:
        origin_summary = sorted({
            (reg_map[f].data_origin or "computed")
            for f in independent_factors if f in reg_map
        })
        logger.info(
            "[preload] 独立加载开始: count=%d origins=%s",
            len(independent_factors), origin_summary,
        )
        ind_t0 = pd.Timestamp.now()
        for fid in independent_factors:
            panels[fid] = await load_factor_raw_chunk(
                start_date, end_date, fid, symbols, pool_id,
            )
        logger.info(
            "[preload] 独立加载完成: count=%d 耗时=%.2fs",
            len(independent_factors), (pd.Timestamp.now() - ind_t0).total_seconds(),
        )

    total_elapsed = (pd.Timestamp.now() - t0).total_seconds()
    logger.info(
        "[preload] 全部预加载完成: total=%d (batch=%d independent=%d) 总耗时=%.2fs",
        len(panels), len(batch_factor_ids) + len(derived_pairs),
        len(independent_factors), total_elapsed,
    )
    return panels


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
