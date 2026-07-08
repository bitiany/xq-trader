"""日频 ML 因子推理任务 — 加载 latest 模型预测并落表 FacFactorValue。

推理流程：
  1. 加载 latest 模型版本
  2. 加载当日因子面板（复用 factor_data_loader + CrossSectionReader）
  3. 模型推理 → 截面 rank（0-1）
  4. 落表 FacFactorValue

设计要点：
  - 推理不依赖训练任务，仅读取模型工件
  - API 完全无状态，通过 fac_factor_value 表间接消费
  - 推理结果 factor_value 为截面 rank（0-1），1 = 预测收益最高
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.config.settings import settings
from framework.scheduler.base_task import BaseTask
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services.feature_matrix_builder import FeatureMatrixBuilder
from xqtrader.domain.factor.services.ml_combiner import MLCombiner
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger("ml.predict")

_DEFAULT_POOL_IDS: list[str] = ["idx_300"]
_DEFAULT_FACTOR_ID = "ml_alpha_v1"
_MODEL_SUBDIR = "ml_combiner"
_PERSIST_BATCH_SIZE = 5000


class MLPredictTask(BaseTask):
    """日频 ML 因子推理任务。"""

    task_name = "ml.predict_daily"
    description = "日频 ML 因子推理 → 落表 FacFactorValue"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        task_start = time.monotonic()

        # 1. 解析参数
        pool_ids = parse_list_param(kwargs.get("pool_ids")) or _DEFAULT_POOL_IDS
        factor_id = str(kwargs.get("factor_id", _DEFAULT_FACTOR_ID))
        trade_date_str = str(kwargs.get("trade_date", ""))

        # 2. 确定预测日期
        if trade_date_str:
            trade_date = date.fromisoformat(trade_date_str)
        else:
            latest = await TradeCalendar.get_latest_trade_date()
            if latest is None:
                return {"status": "FAILED", "message": "交易日历查询失败"}
            trade_date = latest

        logger.info(
            "[ml.predict] === 任务启动 === pools=%s factor_id=%s date=%s",
            pool_ids, factor_id, trade_date,
        )

        # 3. 加载 latest 模型
        model_dir = Path(settings.APP.STORAGE_DIR) / "models" / _MODEL_SUBDIR
        latest_dir = MLCombiner.get_latest_version(model_dir)
        if latest_dir is None:
            return {
                "status": "FAILED",
                "message": f"无可用模型: {model_dir}（请先执行 ml.train_monthly）",
            }

        model_path = latest_dir / "model.lgb"
        if not model_path.exists():
            return {
                "status": "FAILED",
                "message": f"模型文件不存在: {model_path}",
            }

        logger.info("[ml.predict] 加载模型: %s", latest_dir)
        model = MLCombiner.load_model(model_path)
        # 加载模型训练时的特征列，用于对齐推理特征
        metadata = MLCombiner.load_metadata(latest_dir)
        model_feature_names: list[str] = metadata.get("feature_names", [])

        # 4. 逐池推理
        builder = FeatureMatrixBuilder()
        all_results: list[dict[str, Any]] = []

        for pool_id in pool_ids:
            logger.info("[ml.predict] >>> 推理 pool=%s", pool_id)
            pool_result = await self._predict_pool(
                pool_id=pool_id,
                trade_date=trade_date,
                factor_id=factor_id,
                model=model,
                builder=builder,
                model_feature_names=model_feature_names,
            )
            all_results.append(pool_result)

        elapsed = time.monotonic() - task_start
        total_count = sum(r.get("count", 0) for r in all_results)

        logger.info(
            "[ml.predict] === 任务完成 === pools=%d total_count=%d 耗时=%.1fs",
            len(pool_ids), total_count, elapsed,
        )

        return {
            "status": "SUCCESS",
            "trade_date": trade_date.isoformat(),
            "factor_id": factor_id,
            "pools": all_results,
            "total_count": total_count,
            "elapsed_seconds": elapsed,
        }

    async def _predict_pool(
        self,
        pool_id: str,
        trade_date: date,
        factor_id: str,
        model: Any,
        builder: FeatureMatrixBuilder,
        model_feature_names: list[str],
    ) -> dict[str, Any]:
        """单池推理 + 落表。"""
        pool_start = time.monotonic()

        # 构建预测特征
        x, feature_names = await builder.build_predict_features(trade_date, pool_id)
        if x.empty:
            logger.warning("[ml.predict] pool=%s 特征矩阵为空", pool_id)
            return {
                "pool_id": pool_id,
                "status": "SKIPPED",
                "message": "特征矩阵为空",
                "count": 0,
            }

        # 对齐特征列：以模型训练时的特征为准，缺失列填 NaN，多余列丢弃
        if model_feature_names:
            x = x.reindex(columns=model_feature_names)

        # 推理
        pred = MLCombiner().predict(model, x)
        if pred.empty:
            return {
                "pool_id": pool_id,
                "status": "SKIPPED",
                "message": "推理结果为空",
                "count": 0,
            }

        # 截面 rank（0-1），1 = 预测收益最高
        pred_rank = (
            pred.groupby(level="trade_date")
            .rank(pct=True)
            .rename(factor_id)
        )

        # 落表 FacFactorValue
        count = await self._persist_predictions(
            pool_id=pool_id,
            factor_id=factor_id,
            trade_date=trade_date,
            predictions=pred_rank,
        )

        logger.info(
            "[ml.predict] <<< pool=%s count=%d 耗时=%.1fs",
            pool_id, count, time.monotonic() - pool_start,
        )

        return {
            "pool_id": pool_id,
            "status": "SUCCESS",
            "count": count,
            "feature_count": len(feature_names),
            "elapsed_seconds": time.monotonic() - pool_start,
        }

    async def _persist_predictions(
        self,
        pool_id: str,
        factor_id: str,
        trade_date: date,
        predictions: pd.Series,
    ) -> int:
        """将推理结果落表 FacFactorValue（分片 upsert）。

        Args:
            pool_id: 样本池标识
            factor_id: ML 因子 ID
            trade_date: 预测日期
            predictions: 预测值 Series（MultiIndex: trade_date, symbol）

        Returns:
            落表行数
        """
        if predictions.empty:
            return 0

        # 过滤无效值
        valid_mask = np.isfinite(predictions.values)
        if not valid_mask.any():
            return 0

        valid_pred = predictions.loc[valid_mask]
        n = len(valid_pred)
        total = 0

        # 重置索引便于分片
        reset_df = valid_pred.reset_index()
        vals = reset_df[factor_id].to_numpy(dtype=float)

        for start in range(0, n, _PERSIST_BATCH_SIZE):
            end = min(start + _PERSIST_BATCH_SIZE, n)
            chunk = reset_df.iloc[start:end]
            chunk_vals = vals[start:end]

            rows: list[FacFactorValue] = []
            for idx in range(len(chunk)):
                row = chunk.iloc[idx]
                td = row["trade_date"]
                if hasattr(td, "date"):
                    td = td.date()  # type: ignore[union-attr]
                rows.append(FacFactorValue(
                    symbol=str(row["symbol"]),
                    trade_date=td,
                    factor_id=factor_id,
                    pool_id=pool_id,
                    factor_value=float(chunk_vals[idx]),
                ))

            total += await FacFactorValue.bulk_create_or_update(
                rows,
                on_conflict=["symbol", "trade_date", "factor_id", "pool_id"],
                update_fields=["factor_value"],
            )

            if end == n or end % (_PERSIST_BATCH_SIZE * 5) == 0:
                logger.info(
                    "[ml.predict] pool=%s factor=%s persist progress=%d/%d",
                    pool_id, factor_id, end, n,
                )

        return total
