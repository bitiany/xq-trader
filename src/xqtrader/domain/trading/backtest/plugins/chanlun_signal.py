"""缠论买卖点信号计算 — 基于 OHLCV 数据实时计算笔/中枢/背驰，生成买卖点信号

买卖点定义（缠论经典）:
  一买: 底背驰后笔向上反转（中枢离开笔 MACD 面积 < 进入笔的 80%）
  二买: 回调不破前低（向上笔的底高于前一个底分型）
  三买: 突破中枢上沿后回踩不破中枢上沿
  一卖: 顶背驰后笔向下反转（中枢离开笔 MACD 面积 > 进入笔的 120%）
  二卖: 反弹不破前高（向下笔的顶低于前一个顶分型）
  三卖: 跌破中枢下沿后反弹不破中枢下沿

输出信号:
  chan_buy_point: 1.0=一买, 2.0=二买, 3.0=三买, 0.0=无
  chan_sell_point: 1.0=一卖, 2.0=二卖, 3.0=三卖, 0.0=无
  chan_bi_direction: 1=向上笔, -1=向下笔, 0=无笔
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_chanlun_signals(df: pd.DataFrame) -> pd.DataFrame:
    """计算缠论买卖点信号

    Args:
        df: OHLCV DataFrame, 必须包含 open/high/low/close/volume 列

    Returns:
        DataFrame with columns: chan_buy_point, chan_sell_point, chan_bi_direction
    """
    n = len(df)
    buy_point = np.zeros(n)
    sell_point = np.zeros(n)
    bi_direction = np.zeros(n)

    if n < 10:
        return pd.DataFrame({
            "chan_buy_point": buy_point,
            "chan_sell_point": sell_point,
            "chan_bi_direction": bi_direction,
        }, index=df.index)

    try:
        import chanpy  # noqa: F401, I001 — 顶级模块导入，触发 __init__.py 将包目录加入 sys.path
        from Chan import CChan  # type: ignore[import-not-found]  # noqa: I001
        from ChanConfig import CChanConfig  # type: ignore[import-not-found]  # noqa: I001
        from Common.CEnum import AUTYPE, KL_TYPE  # type: ignore[import-not-found]  # noqa: I001
        from DataAPI.DfApi import _DF_CACHE  # type: ignore[import-not-found]  # noqa: I001
    except ImportError:
        logger.warning("[chanlun_signal] chanpy 未安装，跳过缠论信号计算")
        return pd.DataFrame({
            "chan_buy_point": buy_point,
            "chan_sell_point": sell_point,
            "chan_bi_direction": bi_direction,
        }, index=df.index)

    # 准备数据
    open_arr = df["open"].values.astype(float)
    high_arr = df["high"].values.astype(float)
    low_arr = df["low"].values.astype(float)
    close_arr = df["close"].values.astype(float)

    # OHLC 约束: high >= max(O,L,C), low <= min(O,H,C)
    ohlc_max = np.maximum.reduce([open_arr, high_arr, low_arr, close_arr])  # type: ignore[arg-type]
    ohlc_min = np.minimum.reduce([open_arr, high_arr, low_arr, close_arr])  # type: ignore[arg-type]
    high_arr = np.maximum(high_arr, ohlc_max)  # type: ignore[arg-type]
    low_arr = np.minimum(low_arr, ohlc_min)  # type: ignore[arg-type]

    if "trade_date" in df.columns:
        date_index = pd.DatetimeIndex(pd.to_datetime(df["trade_date"]))
    else:
        date_index = pd.DatetimeIndex(pd.to_datetime(df.index))

    from uuid import uuid4
    cache_key = f"_chan_signal_{uuid4().hex}"
    _DF_CACHE[cache_key] = pd.DataFrame(
        {
            "open": open_arr,
            "high": high_arr,
            "low": low_arr,
            "close": close_arr,
            "volume": df["volume"].values.astype(float) if "volume" in df.columns else np.zeros(n),
        },
        index=date_index,
    )

    try:
        config = CChanConfig({
            "bi_strict": True,
            "bi_fx_check": "strict",
            "zs_combine": True,
            "zs_algo": "normal",
            "seg_algo": "chan",
            "trigger_step": False,
            "kl_data_check": False,
        })
        chan = CChan(
            code=cache_key,
            data_src="custom:DfApi.DfApi",
            lv_list=[KL_TYPE.K_DAY],
            autype=AUTYPE.NONE,
            config=config,
        )
        kl_list = chan[0]
    except Exception as e:
        logger.warning("[chanlun_signal] CChan 计算失败: %s", e, exc_info=True)
        return pd.DataFrame({
            "chan_buy_point": buy_point,
            "chan_sell_point": sell_point,
            "chan_bi_direction": bi_direction,
        }, index=df.index)
    finally:
        _DF_CACHE.pop(cache_key, None)

    # ── 提取笔列表 ──
    bi_list = [bi for bi in kl_list.bi_list if bi.is_sure]
    if len(bi_list) < 2:
        return pd.DataFrame({
            "chan_buy_point": buy_point,
            "chan_sell_point": sell_point,
            "chan_bi_direction": bi_direction,
        }, index=df.index)

    # ── 笔方向信号 ──
    for bi in bi_list:
        end_idx = bi.get_end_klu().idx
        if 0 <= end_idx < n:
            bi_direction[end_idx] = 1 if bi.is_up() else -1

    # ── 提取中枢列表 ──
    zs_list = list(kl_list.zs_list)

    # ── 买卖点判断 ──
    _detect_buy_points(bi_list, zs_list, buy_point, n)
    _detect_sell_points(bi_list, zs_list, sell_point, n)

    return pd.DataFrame({
        "chan_buy_point": buy_point,
        "chan_sell_point": sell_point,
        "chan_bi_direction": bi_direction,
    }, index=df.index)


def _detect_buy_points(
    bi_list: list, zs_list: list, buy_point: np.ndarray, n: int,
) -> None:
    """检测买入点（一买/二买/三买）

    买入点在向下笔结束时（底分型确认）产生，此时是阶段性底部。
    """
    for i in range(1, len(bi_list)):
        curr_bi = bi_list[i]
        # 买入点只在向下笔的终点（底分型确认 = 阶段性底部）
        if curr_bi.is_up():
            continue

        end_idx = curr_bi.get_end_klu().idx
        if end_idx < 0 or end_idx >= n:
            continue

        # 一买: 底背驰 — 当前向下笔的 MACD 面积 < 前一个向下笔的 80%
        if i >= 2:
            prev_down_bi = None
            for j in range(i - 1, -1, -1):
                if not bi_list[j].is_up():
                    prev_down_bi = bi_list[j]
                    break

            if prev_down_bi is not None and prev_down_bi is not curr_bi:
                try:
                    curr_area = abs(curr_bi.Cal_MACD_area())
                    prev_area = abs(prev_down_bi.Cal_MACD_area())
                    if prev_area > 0 and curr_area < prev_area * 0.8:
                        buy_point[end_idx] = 1.0  # 一买
                        continue
                except Exception:
                    pass

        # 二买: 回调不破前低 — 当前向下笔的底部高于前一个向下笔的底部
        if i >= 2:
            prev_down_bi = None
            for j in range(i - 1, -1, -1):
                if not bi_list[j].is_up():
                    prev_down_bi = bi_list[j]
                    break

            if prev_down_bi is not None and prev_down_bi is not curr_bi:
                curr_low = curr_bi.get_end_val()
                prev_low = prev_down_bi.get_end_val()
                if curr_low > prev_low:
                    if buy_point[end_idx] == 0:
                        buy_point[end_idx] = 2.0  # 二买
                        continue

        # 三买: 突破中枢上沿后回踩不破中枢上沿
        for zs in zs_list:
            zs_end_idx = zs.end.idx
            if zs_end_idx >= end_idx:
                continue
            zs_high = zs.high
            curr_low = curr_bi.get_end_val()
            # 当前向下笔的底部（回调低点）高于中枢上沿
            if curr_low > zs_high:
                if buy_point[end_idx] == 0:
                    buy_point[end_idx] = 3.0  # 三买
                    break


def _detect_sell_points(
    bi_list: list, zs_list: list, sell_point: np.ndarray, n: int,
) -> None:
    """检测卖出点（一卖/二卖/三卖）

    卖出点在向上笔结束时（顶分型确认）产生，此时是阶段性顶部。
    """
    for i in range(1, len(bi_list)):
        curr_bi = bi_list[i]
        # 卖出点只在向上笔的终点（顶分型确认 = 阶段性顶部）
        if not curr_bi.is_up():
            continue

        end_idx = curr_bi.get_end_klu().idx
        if end_idx < 0 or end_idx >= n:
            continue

        # 一卖: 顶背驰 — 当前向上笔的 MACD 面积 < 前一个向上笔的 80%
        if i >= 2:
            prev_up_bi = None
            for j in range(i - 1, -1, -1):
                if bi_list[j].is_up():
                    prev_up_bi = bi_list[j]
                    break

            if prev_up_bi is not None and prev_up_bi is not curr_bi:
                try:
                    curr_area = abs(curr_bi.Cal_MACD_area())
                    prev_area = abs(prev_up_bi.Cal_MACD_area())
                    if prev_area > 0 and curr_area < prev_area * 0.8:
                        sell_point[end_idx] = 1.0  # 一卖
                        continue
                except Exception:
                    pass

        # 二卖: 反弹不破前高 — 当前向上笔的顶部低于前一个向上笔的顶部
        if i >= 2:
            prev_up_bi = None
            for j in range(i - 1, -1, -1):
                if bi_list[j].is_up():
                    prev_up_bi = bi_list[j]
                    break

            if prev_up_bi is not None and prev_up_bi is not curr_bi:
                curr_high = curr_bi.get_end_val()
                prev_high = prev_up_bi.get_end_val()
                if curr_high < prev_high:
                    if sell_point[end_idx] == 0:
                        sell_point[end_idx] = 2.0  # 二卖
                        continue

        # 三卖: 跌破中枢下沿后反弹不破中枢下沿
        for zs in zs_list:
            zs_end_idx = zs.end.idx
            if zs_end_idx >= end_idx:
                continue
            zs_low = zs.low
            curr_high = curr_bi.get_end_val()
            # 当前向上笔的顶部（反弹高点）低于中枢下沿
            if curr_high < zs_low:
                if sell_point[end_idx] == 0:
                    sell_point[end_idx] = 3.0  # 三卖
                    break
