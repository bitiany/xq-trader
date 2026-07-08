"""月频 ML 因子组合训练任务 — Walk-Forward LightGBM 训练。

训练流程：
  1. 加载交易日历，生成 walk-forward 窗口
  2. 逐折叠：构建训练/验证/测试数据集 → 训练 LightGBM → OOS 评估
  3. 最终模型用最近窗口训练并保存为版本
  4. 注册 ML 因子到 FacFactorRegistry

设计要点：
  - 防泄漏：Walk-Forward + Gap(5d) + PIT 成分过滤
  - 月频重训：step=21（每月滚动一次）
  - OOS 评估：测试集 Rank IC + 多空收益
  - 模型版本化：storage/models/ml_combiner/{date}/
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from framework.commons.logger import get_logger
from framework.config.settings import settings
from framework.scheduler.base_task import BaseTask
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.services.feature_matrix_builder import FeatureMatrixBuilder
from xqtrader.domain.factor.services.ml_combiner import (
    LGBHyperParams,
    MLCombiner,
)
from xqtrader.domain.factor.services.walk_forward_engine import (
    WalkForwardConfig,
    WalkForwardEngine,
)
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger("ml.train")

# 默认训练起始日：资金流因子数据起始日（2023-09-11）
# 确保所有活跃因子（含 fund_flow 类别）在训练窗口内均有完整数据覆盖
_DEFAULT_START_DATE = date(2023, 9, 11)
_DEFAULT_POOL_IDS: list[str] = ["idx_300"]
_DEFAULT_FACTOR_ID = "ml_alpha_v1"
_MODEL_SUBDIR = "ml_combiner"


class MLTrainTask(BaseTask):
    """月频 ML 因子组合训练任务。"""

    task_name = "ml.train_monthly"
    description = "Walk-Forward ML 因子组合模型训练"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        task_start = time.monotonic()

        # 1. 解析参数
        pool_ids = parse_list_param(kwargs.get("pool_ids")) or _DEFAULT_POOL_IDS
        train_window = int(kwargs.get("train_window", 252))
        val_window = int(kwargs.get("val_window", 42))
        test_window = int(kwargs.get("test_window", 42))
        gap = int(kwargs.get("gap", 5))
        step = int(kwargs.get("step", 21))
        horizon = int(kwargs.get("horizon", 5))
        factor_id = str(kwargs.get("factor_id", _DEFAULT_FACTOR_ID))
        start_date_str = str(kwargs.get("start_date", ""))
        end_date_str = str(kwargs.get("end_date", ""))
        max_folds = int(kwargs.get("max_folds", 0))  # >0 时只取最后 N 折（快速验证）

        logger.info(
            "[ml.train] === 任务启动 === pools=%s train=%d val=%d test=%d gap=%d step=%d "
            "horizon=%d factor_id=%s max_folds=%d",
            pool_ids, train_window, val_window, test_window, gap, step,
            horizon, factor_id, max_folds,
        )

        # 2. 确定训练日期范围
        latest_trade_date = await TradeCalendar.get_latest_trade_date()
        if latest_trade_date is None:
            return {"status": "FAILED", "message": "交易日历查询失败"}
        end_date = date.fromisoformat(end_date_str) if end_date_str else latest_trade_date
        if start_date_str:
            start_date = date.fromisoformat(start_date_str)
        else:
            # 默认起始日 = 资金流因子数据起始日，确保所有因子有完整数据覆盖
            start_date = _DEFAULT_START_DATE

        # 3. 加载交易日历
        trading_days = await self._load_trading_days(start_date, end_date)
        if not trading_days:
            return {"status": "FAILED", "message": "交易日历为空"}

        # 4. 初始化组件
        wf_config = WalkForwardConfig(
            train_window=train_window,
            val_window=val_window,
            test_window=test_window,
            gap=gap,
            step=step,
        )
        engine = WalkForwardEngine(wf_config)
        builder = FeatureMatrixBuilder()
        combiner = MLCombiner(LGBHyperParams())

        # 4.5 数据完整性预检查：任一因子数据缺失则直接终止训练
        factor_ids = await builder.load_active_factor_ids()
        try:
            await builder.verify_data_completeness(start_date, end_date, factor_ids)
        except ValueError as e:
            logger.error("[ml.train] %s", e, exc_info=True)
            return {"status": "FAILED", "message": str(e)}

        # 5. 生成 walk-forward 窗口
        try:
            windows = engine.generate_windows(start_date, end_date, trading_days)
        except ValueError as e:
            return {"status": "FAILED", "message": f"窗口生成失败: {e}"}

        if not windows:
            return {"status": "FAILED", "message": "无有效 walk-forward 窗口"}

        # max_folds > 0 时只取最后 N 折（快速验证用）
        if max_folds > 0 and len(windows) > max_folds:
            original_count = len(windows)
            windows = windows[-max_folds:]
            logger.info(
                "[ml.train] max_folds=%d 截取最后 %d/%d 折",
                max_folds, len(windows), original_count,
            )

        # 6. 逐池训练
        all_results: list[dict[str, Any]] = []
        for pool_id in pool_ids:
            logger.info("[ml.train] >>> 开始训练 pool=%s", pool_id)
            pool_result = await self._train_pool(
                pool_id=pool_id,
                windows=windows,
                builder=builder,
                combiner=combiner,
                horizon=horizon,
                factor_id=factor_id,
            )
            all_results.append(pool_result)

        elapsed = time.monotonic() - task_start
        logger.info(
            "[ml.train] === 任务完成 === pools=%d 耗时=%.1fs",
            len(pool_ids), elapsed,
        )

        return {
            "status": "SUCCESS",
            "pools": all_results,
            "elapsed_seconds": elapsed,
        }

    async def _train_pool(
        self,
        pool_id: str,
        windows: list,
        builder: FeatureMatrixBuilder,
        combiner: MLCombiner,
        horizon: int,
        factor_id: str,
    ) -> dict[str, Any]:
        """单个样本池的 walk-forward 训练。

        流程：
          1. 全量预加载
          2. Optuna 超参搜索（用第一个 fold 的 train/val 数据）
          3. 用最优参数 walk-forward 训练
        """
        pool_start = time.monotonic()
        fold_results: list[dict[str, Any]] = []
        latest_result = None

        # === 训练前全量预加载 ===
        global_start = windows[0].train_start
        global_end = windows[-1].test_end
        logger.info(
            "[ml.train] pool=%s === 全量预加载 === range=%s~%s",
            pool_id, global_start, global_end,
        )
        cache = await builder.preload_all_data(
            start_date=global_start,
            end_date=global_end,
            pool_id=pool_id,
            horizon=horizon,
        )
        if not cache:
            logger.error("[ml.train] pool=%s 全量预加载失败，终止训练", pool_id)
            return {
                "pool_id": pool_id,
                "factor_id": factor_id,
                "folds": [],
                "avg_oos_auc": float("nan"),
                "successful_folds": 0,
                "total_folds": len(windows),
                "elapsed_seconds": time.monotonic() - pool_start,
            }
        preload_elapsed = time.monotonic() - pool_start
        logger.info(
            "[ml.train] pool=%s 全量预加载耗时=%.1fs，开始 Optuna 超参搜索",
            pool_id, preload_elapsed,
        )

        # === Optuna 超参搜索（用第一个 fold 的 train/val 数据）===
        first_window = windows[0]
        x_train_search, y_train_search, feature_names = builder.build_dataset_from_cache(
            cache, first_window, segment="train",
        )
        x_val_search, y_val_search, _ = builder.build_dataset_from_cache(
            cache, first_window, segment="validate",
        )

        best_params = combiner.search_hyperparams(
            x_train_search, y_train_search,
            x_val_search, y_val_search,
            feature_names,
            n_trials=20,
        )
        # 用最优参数创建新的 combiner
        combiner = MLCombiner(best_params)
        search_elapsed = time.monotonic() - pool_start
        logger.info(
            "[ml.train] pool=%s Optuna 搜索完成，开始 walk-forward 训练 耗时=%.1fs",
            pool_id, search_elapsed,
        )

        # === Walk-Forward 训练 ===
        for window in windows:
            logger.info(
                "[ml.train] pool=%s >>> 折叠 %d/%d %s",
                pool_id, window.fold, len(windows), window.describe(),
            )

            fold_result = await self._train_fold(
                pool_id=pool_id,
                window=window,
                builder=builder,
                combiner=combiner,
                cache=cache,
                horizon=horizon,
            )
            fold_results.append(fold_result)

            if fold_result.get("status") == "SUCCESS":
                latest_result = fold_result

            # 累计统计
            valid_aucs_so_far = [
                fr["oos_auc"] for fr in fold_results
                if fr.get("status") == "SUCCESS"
                and np.isfinite(fr.get("oos_auc", float("nan")))
            ]
            avg_auc_so_far = float(np.mean(valid_aucs_so_far)) if valid_aucs_so_far else float("nan")
            logger.info(
                "[ml.train] pool=%s <<< 折叠 %d 完成 AUC=%.4f Acc=%.4f F1=%.4f "
                "IC=%.4f 多空=%.4f 累计平均AUC=%.4f 成功折叠=%d/%d 累计耗时=%.1fs",
                pool_id, window.fold,
                fold_result.get("oos_auc", float("nan")),
                fold_result.get("oos_accuracy", float("nan")),
                fold_result.get("oos_f1", float("nan")),
                fold_result.get("oos_rank_ic", float("nan")),
                fold_result.get("oos_long_short_ret", float("nan")),
                avg_auc_so_far,
                len(valid_aucs_so_far), len(fold_results),
                time.monotonic() - pool_start,
            )

        # 保存最终模型
        if latest_result is not None:
            version = date.today().isoformat()
            model_dir = Path(settings.APP.STORAGE_DIR) / "models" / _MODEL_SUBDIR
            saved_dir = combiner.save_model(
                latest_result["_train_result"], model_dir, version,
            )
            await self._register_ml_factor(
                pool_id=pool_id,
                factor_id=factor_id,
                version=version,
                fold_results=fold_results,
                model_dir=str(saved_dir),
            )

        # 汇总指标
        valid_aucs = [
            fr["oos_auc"] for fr in fold_results
            if fr.get("status") == "SUCCESS" and np.isfinite(fr.get("oos_auc", float("nan")))
        ]
        avg_auc = float(np.mean(valid_aucs)) if valid_aucs else float("nan")

        # 清理 _train_result（不可 JSON 序列化）
        serializable_folds = [
            {k: v for k, v in fr.items() if k != "_train_result"}
            for fr in fold_results
        ]

        return {
            "pool_id": pool_id,
            "factor_id": factor_id,
            "folds": serializable_folds,
            "avg_oos_auc": avg_auc,
            "successful_folds": len(valid_aucs),
            "total_folds": len(windows),
            "elapsed_seconds": time.monotonic() - pool_start,
        }

    async def _train_fold(
        self,
        pool_id: str,
        window: Any,
        builder: FeatureMatrixBuilder,
        combiner: MLCombiner,
        cache: dict[str, Any],
        horizon: int,
    ) -> dict[str, Any]:
        """单次 walk-forward 折叠训练 + 评估（从预加载缓存切片）。"""
        try:
            # 从预加载缓存切片构建数据集（无 DB 查询）
            x_train, y_train, feature_names = builder.build_dataset_from_cache(
                cache, window, segment="train",
            )
            x_val, y_val, _ = builder.build_dataset_from_cache(
                cache, window, segment="validate",
            )
            x_test, y_test, _ = builder.build_dataset_from_cache(
                cache, window, segment="test",
            )

            if x_train.empty or x_val.empty or x_test.empty:
                return {
                    "fold": window.fold,
                    "status": "SKIPPED",
                    "message": "数据集为空",
                    "oos_auc": float("nan"),
                    "oos_accuracy": float("nan"),
                    "oos_f1": float("nan"),
                    "oos_rank_ic": float("nan"),
                    "oos_long_short_ret": float("nan"),
                }

            # 对齐特征列
            if feature_names:
                x_val = x_val.reindex(columns=feature_names)
                x_test = x_test.reindex(columns=feature_names)

            # 训练
            train_result = combiner.train(
                x_train, y_train, x_val, y_val, feature_names,
            )

            # OOS 评估（传入 returns_panel 用于计算 IC 和多空收益）
            y_pred = combiner.predict(train_result.model, x_test)
            returns_panel = cache.get("returns_panel")
            metrics = combiner.evaluate(
                y_test, y_pred, fold=window.fold,
                returns_panel=returns_panel, horizon=horizon,
            )

            # 保留 train() 阶段填充的 train_samples/feature_count
            metrics.train_samples = train_result.fold_metrics.train_samples
            metrics.feature_count = train_result.fold_metrics.feature_count
            train_result.fold_metrics = metrics

            logger.info(
                "[ml.train] pool=%s fold=%d 训练+评估完成: "
                "best_iter=%d train_samples=%d test_samples=%d features=%d "
                "AUC=%.4f Acc=%.4f F1=%.4f IC=%.4f 多空=%.4f",
                pool_id, window.fold,
                train_result.model.best_iteration,
                metrics.train_samples, metrics.test_samples, metrics.feature_count,
                metrics.oos_auc, metrics.oos_accuracy, metrics.oos_f1,
                metrics.oos_rank_ic, metrics.oos_long_short_ret,
            )

            return {
                "fold": window.fold,
                "status": "SUCCESS",
                "oos_auc": metrics.oos_auc,
                "oos_accuracy": metrics.oos_accuracy,
                "oos_precision": metrics.oos_precision,
                "oos_recall": metrics.oos_recall,
                "oos_f1": metrics.oos_f1,
                "oos_rank_ic": metrics.oos_rank_ic,
                "oos_ic_win_rate": metrics.oos_ic_win_rate,
                "oos_long_short_ret": metrics.oos_long_short_ret,
                "train_samples": metrics.train_samples,
                "test_samples": metrics.test_samples,
                "feature_count": metrics.feature_count,
                "_train_result": train_result,
                "window": {
                    "train_start": window.train_start.isoformat(),
                    "train_end": window.train_end.isoformat(),
                    "test_start": window.test_start.isoformat(),
                    "test_end": window.test_end.isoformat(),
                },
            }

        except Exception as e:
            logger.error(
                "[ml.train] pool=%s fold=%d 训练失败: %s",
                pool_id, window.fold, e, exc_info=True,
            )
            return {
                "fold": window.fold,
                "status": "FAILED",
                "message": str(e),
                "oos_auc": float("nan"),
                "oos_accuracy": float("nan"),
                "oos_f1": float("nan"),
                "oos_rank_ic": float("nan"),
                "oos_long_short_ret": float("nan"),
            }

    async def _load_trading_days(
        self, start: date, end: date,
    ) -> list[date]:
        """加载 [start, end] 范围内的交易日列表（已排序）。"""
        rows = await TradeCalendar.filter(
            exchange="SSE",
            is_open=True,
            cal_date__gte=start,
            cal_date__lte=end,
            order_by="cal_date",
        )
        return [r.cal_date for r in rows]

    async def _register_ml_factor(
        self,
        pool_id: str,
        factor_id: str,
        version: str,
        fold_results: list[dict[str, Any]],
        model_dir: str,
    ) -> None:
        """注册或更新 ML 因子到 FacFactorRegistry。

        使用 composite_method='ml' 标识 ML 合成因子，
        data_origin='ml_combiner' 标识数据来源。
        """
        # 计算平均 OOS AUC 用于等级评定
        valid_aucs = [
            fr["oos_auc"] for fr in fold_results
            if fr.get("status") == "SUCCESS" and np.isfinite(fr.get("oos_auc", float("nan")))
        ]
        avg_auc = float(np.mean(valid_aucs)) if valid_aucs else 0.0

        # 等级评定（基于 AUC，0.5 为随机基准）：
        # A(AUC>0.55) / B(AUC>0.53) / C(AUC>0.51) / D(其他)
        if avg_auc > 0.55:
            grade = "A"
        elif avg_auc > 0.53:
            grade = "B"
        elif avg_auc > 0.51:
            grade = "C"
        else:
            grade = "D"

        # upsert：已存在则更新，不存在则创建
        update_fields = {
            "category": "composite_ml",
            "data_origin": "ml_combiner",
            "composite_method": "ml",
            "update_freq": "daily",
            "status": "active" if grade in ("A", "B") else "deprecated",
            "factor_grade": grade,
            "data_start_date": date.today(),
        }
        existing = await FacFactorRegistry.get_or_none(factor_id=factor_id)
        if existing is not None:
            await FacFactorRegistry.update_by(update_fields, factor_id=factor_id)
        else:
            await FacFactorRegistry.create(
                factor_id=factor_id,
                display_name=factor_id,
                **update_fields,
            )
        logger.info(
            "[ml.train] ML 因子已注册: factor_id=%s grade=%s avg_oos_auc=%.4f model_dir=%s",
            factor_id, grade, avg_auc, model_dir,
        )
