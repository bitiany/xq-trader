"""因子相关去冗余 — 组内保留 ICIR 最高者。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr  # type: ignore[import-untyped]

from framework.commons.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_CORR_THRESHOLD = 0.9


def average_cross_section_correlation(
    factor_panel: pd.DataFrame,
    min_periods: int = 20,
) -> pd.DataFrame:
    """计算因子间截面 Spearman 相关矩阵的时间均值。"""
    factor_ids = factor_panel.columns.tolist()
    if len(factor_ids) < 2:
        return pd.DataFrame(index=factor_ids, columns=factor_ids, dtype=float)

    dates = factor_panel.index.get_level_values("trade_date").unique()
    corr_sum = np.zeros((len(factor_ids), len(factor_ids)), dtype=float)
    corr_count = np.zeros((len(factor_ids), len(factor_ids)), dtype=float)

    for dt in dates:
        try:
            cross = factor_panel.xs(dt, level="trade_date").dropna(how="all")
        except KeyError:
            continue
        if len(cross) < min_periods:
            continue

        values = cross[factor_ids].values.astype(float)
        valid_rows = np.all(np.isfinite(values), axis=1)
        if valid_rows.sum() < min_periods:
            continue

        mat = values[valid_rows]
        corr_mat_raw, _ = spearmanr(mat, axis=0)
        if isinstance(corr_mat_raw, float):
            if len(factor_ids) != 2:
                continue
            c = float(corr_mat_raw)
            corr_mat = np.array([[1.0, c], [c, 1.0]])
        else:
            corr_mat = np.asarray(corr_mat_raw)
        if not np.isfinite(corr_mat).all():
            continue

        if corr_mat.ndim == 1:
            if len(factor_ids) == 1:
                corr_mat = corr_mat.reshape(1, 1)
            elif len(factor_ids) == 2:
                c = float(corr_mat[0, 1]) if corr_mat.shape == (2, 2) else float(corr_mat[0])
                corr_mat = np.array([[1.0, c], [c, 1.0]])
            else:
                continue

        corr_sum += np.abs(corr_mat)
        corr_count += 1

    with np.errstate(divide="ignore", invalid="ignore"):
        avg_corr = np.where(corr_count > 0, corr_sum / corr_count, np.nan)

    return pd.DataFrame(avg_corr, index=factor_ids, columns=factor_ids)


def dedup_by_correlation(
    factor_ids: list[str],
    factor_panel: pd.DataFrame,
    icir_rank: dict[str, float],
    threshold: float = _DEFAULT_CORR_THRESHOLD,
    min_periods: int = 20,
) -> list[str]:
    """按 ICIR 降序贪心去冗余：与已选因子平均相关 > threshold 则剔除。"""
    available = [fid for fid in factor_ids if fid in factor_panel.columns]
    if len(available) <= 1:
        return available

    corr_df = average_cross_section_correlation(
        factor_panel[available],
        min_periods=min_periods,
    )
    ranked = sorted(
        available,
        key=lambda fid: abs(icir_rank.get(fid, 0.0)),
        reverse=True,
    )

    selected: list[str] = []
    for fid in ranked:
        if not selected:
            selected.append(fid)
            continue
        corrs: list[float] = []
        for kept in selected:
            if kept not in corr_df.index or fid not in corr_df.index:
                continue
            raw = corr_df.at[fid, kept]
            if isinstance(raw, (float, int, np.floating)) and np.isfinite(float(raw)):
                corrs.append(float(raw))
        max_corr = max(corrs) if corrs else 0.0
        if max_corr <= threshold:
            selected.append(fid)
        else:
            logger.debug(
                "因子去冗余剔除: %s max_corr=%.3f threshold=%.2f",
                fid, max_corr, threshold,
            )

    return selected
