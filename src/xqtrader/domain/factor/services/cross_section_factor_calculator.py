"""截面计算因子引擎 — beta / 非线性规模 / 月换手率。

由 factor_data_loader 的 cross_section_beta / cross_section_compute 路由调用。
与 CrossSectionReader 协作：本模块产出原始因子值，CrossSectionReader 后续做
MAD 去极值 + Z-score + 行业/市值中性化。

因子清单：
  - beta_250: 250 日 Beta，半衰期 63 日指数加权 Cov(ret, mkt_ret)/Var(mkt_ret)
  - beta_down: 仅市场负收益日的下行 Beta
  - nl_size: log_mv 三次方对 Size 正交化取残差（Barra 非线性规模）
  - stom: log(Σ(21 日, turnover_rate/100))，Barra 月换手率

数据源：
  - CandlestickDaily.pct_chg 个股收益率
  - IndexDaily.pct_chg 市场收益率（沪深300 / 中证500 等）
  - DailyIndicator.total_mv 总市值（万元）
  - DailyIndicator.turnover_rate 换手率（%）
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from xqtrader.domain.index.models.index_daily import IndexDaily
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.market.models.daily_indicator import DailyIndicator

logger = get_logger(__name__)

# 单次 IN 查询分片大小
_QUERY_BATCH_SIZE = 500

# 滚动窗口前需要的预热天数（覆盖 beta 250 日窗口 + 缓冲）
_WARMUP_DAYS = 400

# 半衰期 → 指数衰减系数 α：使得 α^halflife = 0.5
def _halflife_to_alpha(halflife: int) -> float:
    if halflife <= 0:
        return 1.0
    return float(np.power(0.5, 1.0 / halflife))


async def _load_individual_returns(
    start_date: date,
    end_date: date,
    symbols: list[str],
) -> pd.DataFrame:
    """加载个股日收益率面板。

    使用 CandlestickDaily.pct_chg（已为百分比单位），转为比率后返回。
    Returns:
        MultiIndex(trade_date, symbol), columns=["ret"]
    """
    if not symbols:
        return pd.DataFrame()

    rows: list[dict] = []
    for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
        batch = symbols[i:i + _QUERY_BATCH_SIZE]
        records = await CandlestickDaily.filter(
            symbol__in=batch,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        )
        for r in records:
            pct = r.pct_chg
            ret = float(pct) / 100.0 if pct is not None else np.nan
            rows.append({
                "trade_date": r.trade_date,
                "symbol": r.symbol,
                "ret": ret,
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["trade_date", "symbol"], keep="last")
    return df.set_index(["trade_date", "symbol"]).sort_index()


async def _load_market_returns(
    start_date: date,
    end_date: date,
    index_code: str,
) -> pd.Series:
    """加载指数市场日收益率序列。

    使用 IndexDaily.pct_chg（百分比单位）转为比率。
    Returns:
        Series, index=trade_date, name="mkt_ret"
    """
    records = await IndexDaily.filter(
        symbol=index_code,
        trade_date__gte=start_date,
        trade_date__lte=end_date,
    )

    if not records:
        return pd.Series(dtype=float, name="mkt_ret")

    data = {
        "trade_date": [r.trade_date for r in records],
        "mkt_ret": [
            float(r.pct_chg) / 100.0 if r.pct_chg is not None else np.nan
            for r in records
        ],
    }
    df = pd.DataFrame(data).set_index("trade_date").sort_index()
    # 去重：同一交易日可能有多条记录，保留最后一条
    df = df[~df.index.duplicated(keep="last")]
    return df["mkt_ret"]


def _rolling_weighted_beta(
    ret: pd.Series,
    mkt_ret: pd.Series,
    window: int,
    alpha: float,
    downside_only: bool,
) -> pd.Series:
    """单标的的滚动加权 Beta。

    对每个时点 t，取 [t-window+1, t] 内的 (ret, mkt_ret) 配对：
      1. 若 downside_only：仅保留 mkt_ret < 0 的样本
      2. 应用指数衰减权重 w_i = alpha^(t-i)，i 越近权重越大
      3. beta = Σw*(ret-mean_ret)*(mkt-mean_mkt) / Σw*(mkt-mean_mkt)²
      4. 样本数 < min_periods 时返回 NaN
    """
    if ret.empty or mkt_ret.empty:
        return pd.Series(np.nan, index=ret.index, name="beta")

    # 对齐索引
    common_idx = ret.index.intersection(mkt_ret.index)
    ret_aligned = ret.reindex(common_idx)
    mkt_aligned = mkt_ret.reindex(common_idx)

    n = len(common_idx)
    out = np.full(n, np.nan)

    # 预计算每个时点的指数权重向量（从最远到最近，权重递增）
    # w_i = alpha^(window-1-i), i=0..window-1 (最远 i=0)
    weights_template = np.array(
        [alpha ** (window - 1 - i) for i in range(window)],
        dtype=float,
    )

    min_periods = max(60, window // 5)

    ret_vals = ret_aligned.to_numpy(dtype=float)
    mkt_vals = mkt_aligned.to_numpy(dtype=float)

    for t in range(window - 1, n):
        r_window = ret_vals[t - window + 1: t + 1]
        m_window = mkt_vals[t - window + 1: t + 1]

        # 过滤 NaN
        valid = np.isfinite(r_window) & np.isfinite(m_window)
        if downside_only:
            valid = valid & (m_window < 0)

        if valid.sum() < min_periods:
            continue

        r_v = r_window[valid]
        m_v = m_window[valid]
        w_v = weights_template[-len(r_v):] if len(r_v) < window else weights_template

        # 加权均值
        w_sum = w_v.sum()
        if w_sum <= 0:
            continue
        r_mean = (w_v * r_v).sum() / w_sum
        m_mean = (w_v * m_v).sum() / w_sum

        # 加权协方差 / 加权方差
        m_dev = m_v - m_mean
        r_dev = r_v - r_mean
        var_m = (w_v * m_dev * m_dev).sum() / w_sum
        if var_m <= 1e-12:
            continue
        cov = (w_v * r_dev * m_dev).sum() / w_sum
        out[t] = cov / var_m

    return pd.Series(out, index=common_idx, name="beta")


async def compute_beta_panel(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
    index_code: str = "000300.SH",
    window: int = 250,
    downside_only: bool = False,
) -> pd.DataFrame:
    """Beta 因子面板计算 — 个股收益对市场收益的滚动加权回归。

    Args:
        start_date: 因子值起始日期
        end_date: 因子值结束日期
        factor_id: "beta_250" 或 "beta_down"
        symbols: 样本池标的列表
        index_code: 市场基准指数代码
        window: 滚动窗口（默认 250 日）
        downside_only: True=仅市场负收益日（下行 Beta）

    Returns:
        MultiIndex(trade_date, symbol), columns=[factor_id]
    """
    if not symbols:
        return pd.DataFrame()

    # 预热数据：向前多取 window + 缓冲天数
    warmup_start = start_date - timedelta(days=_WARMUP_DAYS)

    ret_panel = await _load_individual_returns(warmup_start, end_date, symbols)
    if ret_panel.empty:
        logger.warning("[beta] %s 个股收益率数据为空", factor_id)
        return pd.DataFrame()

    mkt_series = await _load_market_returns(warmup_start, end_date, index_code)
    if mkt_series.empty:
        logger.warning("[beta] %s 市场收益率数据为空 (index=%s)", factor_id, index_code)
        return pd.DataFrame()

    # 逐标的计算滚动 Beta
    halflife = 63
    alpha = _halflife_to_alpha(halflife)

    parts: list[pd.Series] = []
    for symbol in symbols:
        try:
            sym_ret = ret_panel.xs(symbol, level="symbol")["ret"]
        except KeyError:
            continue
        if sym_ret.empty:
            continue

        beta_series = _rolling_weighted_beta(
            sym_ret, mkt_series, window, alpha, downside_only,
        )
        if beta_series.empty:
            continue

        # 截断到 [start_date, end_date]（统一转 Timestamp 比较，避免 date vs Timestamp 类型错误）
        idx_ts = pd.to_datetime(beta_series.index)
        mask = (idx_ts >= pd.Timestamp(start_date)) & (
            idx_ts <= pd.Timestamp(end_date)
        )
        beta_series = beta_series.loc[mask].dropna()
        if beta_series.empty:
            continue

        mi = pd.MultiIndex.from_arrays(
            [beta_series.index, [symbol] * len(beta_series)],
            names=["trade_date", "symbol"],
        )
        parts.append(pd.Series(beta_series.values, index=mi, name=factor_id))

    if not parts:
        return pd.DataFrame()

    concatenated = pd.concat(parts)
    result: pd.DataFrame = concatenated.to_frame(factor_id)
    result = result.sort_index()
    logger.info(
        "[beta] %s 计算完成: symbols=%d rows=%d",
        factor_id, len(symbols), len(result),
    )
    return result


async def compute_cross_section_factor(
    start_date: date,
    end_date: date,
    factor_id: str,
    symbols: list[str],
) -> pd.DataFrame:
    """截面计算因子分发 — nl_size / stom。

    Args:
        start_date: 因子值起始日期
        end_date: 因子值结束日期
        factor_id: "nl_size" 或 "stom"
        symbols: 样本池标的列表

    Returns:
        MultiIndex(trade_date, symbol), columns=[factor_id]
    """
    if factor_id == "nl_size":
        return await _compute_nl_size(start_date, end_date, symbols)
    if factor_id == "stom":
        return await _compute_stom(start_date, end_date, symbols)
    if factor_id == "stoq":
        return await _compute_stoq(start_date, end_date, symbols)
    logger.warning("[cross_section_compute] 未知因子 %s", factor_id)
    return pd.DataFrame()


async def _load_daily_indicator_field(
    start_date: date,
    end_date: date,
    symbols: list[str],
    field: str,
) -> pd.DataFrame:
    """加载 daily_indicator 单字段面板。

    Returns:
        MultiIndex(trade_date, symbol), columns=[field]
    """
    if not symbols:
        return pd.DataFrame()

    rows: list[dict] = []
    for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
        batch = symbols[i:i + _QUERY_BATCH_SIZE]
        records = await DailyIndicator.filter(
            symbol__in=batch,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
        )
        for r in records:
            val = getattr(r, field, None)
            rows.append({
                "trade_date": r.trade_date,
                "symbol": r.symbol,
                field: float(val) if val is not None else np.nan,
            })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["trade_date", "symbol"], keep="last")
    return df.set_index(["trade_date", "symbol"]).sort_index()


async def _compute_nl_size(
    start_date: date,
    end_date: date,
    symbols: list[str],
) -> pd.DataFrame:
    """非线性规模因子 — log_mv 三次方对 Size 正交化取残差。

    Barra CNE6 非线性规模因子算法（每个截面日）：
      1. log_mv = log(total_mv)
      2. Size = Z-score(log_mv)  截面标准化
      3. Size³ = Size ** 3
      4. OLS 回归: Size³ = a + b * Size + ε
      5. nl_size = ε（残差）

    方向 ASC：高 nl_size 表示相对同规模股票更"被低估"的非线性部分。
    """
    mv_panel = await _load_daily_indicator_field(
        start_date, end_date, symbols, "total_mv",
    )
    if mv_panel.empty:
        logger.warning("[nl_size] total_mv 数据为空")
        return pd.DataFrame()

    df = mv_panel.copy()
    # total_mv 单位为万元，需保证 > 0
    df["log_mv"] = np.log(df["total_mv"].where(df["total_mv"] > 0))

    # 按截面日 Z-score（复制 Barra Size 因子）
    df["size"] = df.groupby(level="trade_date")["log_mv"].transform(
        lambda s: (s - s.mean()) / (s.std(ddof=0) if s.std(ddof=0) > 0 else np.nan)
    )
    df["size_cubed"] = df["size"] ** 3

    # 截面回归取残差
    def _residualize(group: pd.DataFrame) -> pd.Series:
        x = group["size"].to_numpy(dtype=float)
        y = group["size_cubed"].to_numpy(dtype=float)
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() < 30:
            return pd.Series(np.nan, index=group.index)
        x_v = x[valid]
        y_v = y[valid]
        # OLS: y = a + b*x
        x_mean = x_v.mean()
        y_mean = y_v.mean()
        denom = ((x_v - x_mean) ** 2).sum()
        if denom <= 1e-12:
            return pd.Series(np.nan, index=group.index)
        beta = ((x_v - x_mean) * (y_v - y_mean)).sum() / denom
        alpha = y_mean - beta * x_mean
        resid = np.full(len(group), np.nan)
        resid[valid] = y_v - (alpha + beta * x_v)
        return pd.Series(resid, index=group.index)

    df["nl_size"] = df.groupby(level="trade_date", group_keys=False).apply(_residualize)

    result = df[["nl_size"]].dropna(subset=["nl_size"])
    if result.empty:
        logger.warning("[nl_size] 残差计算结果为空")
        return pd.DataFrame()

    logger.info("[nl_size] 计算完成: rows=%d", len(result))
    return result


async def _compute_stom(
    start_date: date,
    end_date: date,
    symbols: list[str],
) -> pd.DataFrame:
    """月换手率因子 — log(Σ(21 日, turnover_rate/100))。

    Barra CNE6 流动性因子 STOM：
      - turnover_rate 单位为 %，需除以 100 转为比率
      - 按 symbol 时序滚动 21 日求和
      - 取 log（求和要求 > 0）
    """
    # 预热 21 日窗口
    warmup_start = start_date - timedelta(days=60)

    turnover_panel = await _load_daily_indicator_field(
        warmup_start, end_date, symbols, "turnover_rate",
    )
    if turnover_panel.empty:
        logger.warning("[stom] turnover_rate 数据为空")
        return pd.DataFrame()

    df = turnover_panel.copy()
    # turnover_rate (%) → 比率
    df["tr_ratio"] = df["turnover_rate"] / 100.0

    # 按 symbol 滚动 21 日求和
    df["stom_raw"] = df.groupby(level="symbol")["tr_ratio"].transform(
        lambda s: s.rolling(window=21, min_periods=15).sum()
    )
    # log(Σ) — 求和值 > 0 才有效
    df["stom"] = np.log(df["stom_raw"].where(df["stom_raw"] > 0))

    # 截断到 [start_date, end_date]（统一转 Timestamp 比较）
    td_idx = pd.to_datetime(df.index.get_level_values("trade_date"))
    mask = (td_idx >= pd.Timestamp(start_date)) & (
        td_idx <= pd.Timestamp(end_date)
    )
    df = df.loc[mask]

    result = df[["stom"]].dropna(subset=["stom"])
    if result.empty:
        logger.warning("[stom] 计算结果为空")
        return pd.DataFrame()

    logger.info("[stom] 计算完成: rows=%d", len(result))
    return result


async def _compute_stoq(
    start_date: date,
    end_date: date,
    symbols: list[str],
) -> pd.DataFrame:
    """季换手率因子 — 从 stom 派生 63 日滚动均值。

    Barra CNE6 流动性因子 STOQ：3 个月（63 日）STOM 均值。
    数据流：先计算 stom 面板（需预热），再按 symbol 做 63 日滚动均值。

    注：stom 已是 log(Σ(21日, V_t/S_t))，stoq = mean(63日, stom)。
    """
    # stoq 需要 63 日滚动窗口，预热天数 = stom 预热(60) + 63 日 = 123 日
    warmup_start = start_date - timedelta(days=180)

    # 先计算 stom 面板（含预热数据）
    stom_panel = await _compute_stom(warmup_start, end_date, symbols)
    if stom_panel.empty or "stom" not in stom_panel.columns:
        logger.warning("[stoq] stom 面板为空，无法派生 stoq")
        return pd.DataFrame()

    df = stom_panel.copy()
    # 按 symbol 做 63 日滚动均值
    df["stoq"] = df.groupby(level="symbol")["stom"].transform(
        lambda s: s.rolling(window=63, min_periods=21).mean()
    )

    # 截断到 [start_date, end_date]（统一转 Timestamp 比较）
    td_idx = pd.to_datetime(df.index.get_level_values("trade_date"))
    mask = (td_idx >= pd.Timestamp(start_date)) & (
        td_idx <= pd.Timestamp(end_date)
    )
    df = df.loc[mask]

    result = df[["stoq"]].dropna(subset=["stoq"])
    if result.empty:
        logger.warning("[stoq] 计算结果为空")
        return pd.DataFrame()

    logger.info("[stoq] 计算完成: rows=%d", len(result))
    return result
