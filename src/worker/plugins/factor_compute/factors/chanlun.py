"""E1 缠论连续值因子 — 分型强度 / 笔属性 / 中枢属性 / 背驰强度 / MACD面积。

参照 factor-catalog v7.0：
  - chan_fractal_strength: 分型强度（极值与两侧差之和 / close）
  - chan_bi_length: 笔长度（abs(顶H-底L) / close）
  - chan_bi_kcount: 笔内K线数
  - chan_bi_slope: 笔斜率（(终点价-起点价) / K线数 / close）
  - chan_bi_amplitude: 笔振幅（笔内最大回撤 / 笔长度）
  - chan_bi_strength: 笔强度（笔长度 / 笔内K线数）
  - chan_zs_height_ratio: 中枢高度比（(ZG-ZD) / close）
  - chan_zs_range: 中枢区间（ZG-ZD 绝对宽度）
  - chan_divergence_ratio: 背驰强度（A_curr / A_prev 面积比）
  - chan_macd_area: MACD面积（笔内|MACD柱|之和 / close）

设计原则：
  - 价格相关值均除以 close，确保截面可比
  - 离散买卖点信号归信号引擎，此处仅输出连续值因子
  - 使用 chanpy 缠论引擎计算分型/笔/中枢/背驰
  - 组合因子模式：一次 chanpy 计算，输出 10 个子因子
"""

from __future__ import annotations

import logging
from uuid import uuid4

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin

logger = logging.getLogger(__name__)

# 所有缠论子因子 ID
_CHAN_FACTOR_IDS: list[str] = [
    "chan_fractal_strength",
    "chan_bi_length",
    "chan_bi_kcount",
    "chan_bi_slope",
    "chan_bi_amplitude",
    "chan_bi_strength",
    "chan_zs_height_ratio",
    "chan_zs_range",
    "chan_divergence_ratio",
    "chan_macd_area",
]


def _compute_chan_elements(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """调用 chanpy 计算缠论元素，返回各因子值的 numpy 数组。

    使用 DfApi 数据源将 DataFrame 传入 chanpy，一次性计算所有缠论元素，
    然后将结果映射回每日因子值。
    """
    # chanpy 内部使用裸模块导入，此处也使用裸导入以保持枚举对象一致性
    import chanpy  # noqa: F401, I001 — 顶级模块导入，触发 __init__.py 将包目录加入 sys.path
    from Chan import CChan  # type: ignore[import-not-found]  # noqa: I001
    from ChanConfig import CChanConfig  # type: ignore[import-not-found]  # noqa: I001
    from Common.CEnum import AUTYPE, FX_TYPE, KL_TYPE, MACD_ALGO  # type: ignore[import-not-found]  # noqa: I001
    from DataAPI.DfApi import _DF_CACHE  # type: ignore[import-not-found]  # noqa: I001

    n = len(df)
    nan_arr = np.full(n, np.nan)

    if n < 5:
        return {fid: nan_arr.copy() for fid in _CHAN_FACTOR_IDS}

    # 准备 DataFrame 给 DfApi
    # chanpy 严格要求 OHLC 约束：high >= max(O,H,L,C), low <= min(O,H,L,C)
    # 真实行情数据可能存在微小偏差（如复权价），需预处理确保约束
    open_arr = df["open"].values.astype(float)
    high_arr = df["high"].values.astype(float)
    low_arr = df["low"].values.astype(float)
    close_arr = df["close"].values.astype(float)
    ohlc_max = np.maximum.reduce([open_arr, high_arr, low_arr, close_arr])  # type: ignore[arg-type]
    ohlc_min = np.minimum.reduce([open_arr, high_arr, low_arr, close_arr])  # type: ignore[arg-type]
    high_arr = np.maximum(high_arr, ohlc_max)  # type: ignore[arg-type]
    low_arr = np.minimum(low_arr, ohlc_min)  # type: ignore[arg-type]

    # DfApi 用 df.index[i] 取日期，需设为 DatetimeIndex
    if "trade_date" in df.columns:
        date_index = pd.DatetimeIndex(pd.to_datetime(df["trade_date"]))
    else:
        date_index = pd.DatetimeIndex(pd.to_datetime(df.index))

    chan_df = pd.DataFrame(
        {
            "open": open_arr,
            "high": high_arr,
            "low": low_arr,
            "close": close_arr,
            "volume": df["volume"].values.astype(float)
            if "volume" in df.columns
            else np.zeros(n),
        },
        index=date_index,
    )

    cache_key = f"_chan_factor_{uuid4().hex}"
    _DF_CACHE[cache_key] = chan_df

    try:
        config = CChanConfig(
            {
                "bi_strict": True,
                "bi_fx_check": "strict",
                "zs_combine": True,
                "zs_algo": "normal",
                "seg_algo": "chan",
                "trigger_step": False,
                "kl_data_check": False,
            }
        )
        try:
            chan = CChan(
                code=cache_key,
                data_src="custom:DfApi.DfApi",
                lv_list=[KL_TYPE.K_DAY],
                autype=AUTYPE.NONE,
                config=config,
            )
        except Exception as e:
            # chanpy 初始化失败（数据校验等），返回全 NaN
            logger.warning("[chanlun] CChan init failed: %s", e, exc_info=True)
            return {fid: nan_arr.copy() for fid in _CHAN_FACTOR_IDS}

        kl_list = chan[0]

        # ── 1. 分型强度 ──
        fractal_strength = nan_arr.copy()
        for klc in kl_list.lst:
            if klc.fx == FX_TYPE.UNKNOWN:
                continue
            pre_klc = klc.pre
            nxt_klc = klc.next
            if pre_klc is None or nxt_klc is None:
                continue

            if klc.fx == FX_TYPE.TOP:
                strength = (klc.high - pre_klc.low) + (klc.high - nxt_klc.low)
            else:  # BOTTOM
                strength = (pre_klc.high - klc.low) + (nxt_klc.high - klc.low)

            for klu in klc.lst:
                if 0 <= klu.idx < n:
                    ref_price = close_arr[klu.idx]
                    if ref_price > 0:
                        fractal_strength[klu.idx] = strength / ref_price

        # ── 2-6. 笔属性 ──
        bi_length = nan_arr.copy()
        bi_kcount = nan_arr.copy()
        bi_slope = nan_arr.copy()
        bi_amplitude = nan_arr.copy()
        bi_strength = nan_arr.copy()

        for bi in kl_list.bi_list:
            if not bi.is_sure:
                continue

            end_klu = bi.get_end_klu()
            end_idx = end_klu.idx
            if end_idx < 0 or end_idx >= n:
                continue

            ref_price = close_arr[end_idx]
            if ref_price <= 0:
                continue

            # 笔长度 = abs(顶H - 底L) / close
            length = bi.amp() / ref_price
            bi_length[end_idx] = length

            # 笔内K线数
            kcount = float(bi.get_klu_cnt())
            bi_kcount[end_idx] = kcount

            # 笔斜率 = (终点价 - 起点价) / K线数 / close
            begin_val = bi.get_begin_val()
            end_val = bi.get_end_val()
            if kcount > 0:
                bi_slope[end_idx] = (end_val - begin_val) / kcount / ref_price

            # 笔振幅 = 笔内最大回撤 / 笔长度
            if length > 0:
                if bi.is_up():
                    max_drawdown = 0.0
                    running_high = bi.begin_klc.high
                    for klc in bi.klc_lst:
                        running_high = max(running_high, klc.high)
                        drawdown = (running_high - klc.low) / running_high if running_high > 0 else 0
                        max_drawdown = max(max_drawdown, drawdown)
                else:
                    max_drawdown = 0.0
                    running_low = bi.begin_klc.low
                    for klc in bi.klc_lst:
                        running_low = min(running_low, klc.low)
                        drawdown = (klc.high - running_low) / running_low if running_low > 0 else 0
                        max_drawdown = max(max_drawdown, drawdown)
                bi_amplitude[end_idx] = max_drawdown / length

            # 笔强度 = 笔长度 / 笔内K线数
            if kcount > 0:
                bi_strength[end_idx] = length / kcount

        # ── 7-8. 中枢属性 ──
        zs_height_ratio = nan_arr.copy()
        zs_range = nan_arr.copy()

        for zs in kl_list.zs_list:
            end_klu = zs.end
            end_idx = end_klu.idx
            if end_idx < 0 or end_idx >= n:
                continue

            ref_price = close_arr[end_idx]
            if ref_price <= 0:
                continue

            height_ratio = (zs.high - zs.low) / ref_price
            zs_height_ratio[end_idx] = height_ratio
            zs_range[end_idx] = zs.high - zs.low

        # ── 9. 背驰强度 ──
        divergence_ratio = nan_arr.copy()

        for zs in kl_list.zs_list:
            if zs.bi_in is None or zs.bi_out is None:
                continue
            end_klu = zs.end
            end_idx = end_klu.idx
            if end_idx < 0 or end_idx >= n:
                continue

            try:
                in_metric = zs.get_bi_in().cal_macd_metric(
                    MACD_ALGO.AREA, is_reverse=False,
                )
                out_metric = zs.get_bi_out().cal_macd_metric(
                    MACD_ALGO.AREA, is_reverse=True,
                )
                if in_metric > 0:
                    divergence_ratio[end_idx] = out_metric / in_metric
            except Exception:
                pass

        # ── 10. MACD面积 ──
        macd_area = nan_arr.copy()

        for bi in kl_list.bi_list:
            if not bi.is_sure:
                continue
            end_klu = bi.get_end_klu()
            end_idx = end_klu.idx
            if end_idx < 0 or end_idx >= n:
                continue

            ref_price = close_arr[end_idx]
            if ref_price <= 0:
                continue

            try:
                area = bi.Cal_MACD_area()
                macd_area[end_idx] = area / ref_price
            except Exception:
                pass

        return {
            "chan_fractal_strength": fractal_strength,
            "chan_bi_length": bi_length,
            "chan_bi_kcount": bi_kcount,
            "chan_bi_slope": bi_slope,
            "chan_bi_amplitude": bi_amplitude,
            "chan_bi_strength": bi_strength,
            "chan_zs_height_ratio": zs_height_ratio,
            "chan_zs_range": zs_range,
            "chan_divergence_ratio": divergence_ratio,
            "chan_macd_area": macd_area,
        }

    finally:
        _DF_CACHE.pop(cache_key, None)


class ChanlunFactor(FactorPlugin):
    """缠论组合因子 — 一次 chanpy 计算，输出 10 个子因子。

    组合因子模式避免重复调用 chanpy（缠论计算开销大），
    一次计算输出所有缠论连续值因子。
    """

    factor_id: str = "chanlun"
    display_name: str = "缠论组合"
    category: str = "chanlun"
    group_id: str = "chanlun"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["open", "high", "low", "close"]
    min_periods: int = 5
    requires_full_history: bool = True
    is_composite: bool = True
    composite_factor_ids: list[str] = _CHAN_FACTOR_IDS
    child_display_names: dict[str, str] = {
        "chan_fractal_strength": "缠论分型强度",
        "chan_bi_length": "缠论笔长度",
        "chan_bi_kcount": "缠论笔内K线数",
        "chan_bi_slope": "缠论笔斜率",
        "chan_bi_amplitude": "缠论笔振幅",
        "chan_bi_strength": "缠论笔强度",
        "chan_zs_height_ratio": "缠论中枢高度比",
        "chan_zs_range": "缠论中枢区间",
        "chan_divergence_ratio": "缠论背驰强度",
        "chan_macd_area": "缠论MACD面积",
    }
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        result = _compute_chan_elements(df)
        return pd.DataFrame(result, index=df.index)
