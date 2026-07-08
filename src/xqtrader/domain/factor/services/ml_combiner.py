"""LightGBM 截面因子组合训练器（二分类任务）。

职责单一：仅负责模型训练、推理、评估、持久化、超参搜索。
不做数据加载（由 FeatureMatrixBuilder 负责），不做时间窗口切分（由 WalkForwardEngine 负责）。

设计依据（示例代码 CASE-机器学习因子挖掘 + 华泰金工）：
  - 任务类型：二分类（5日前向收益 > 0 = 1，否则 = 0）
  - 目标函数：binary（logloss）
  - 评估指标：AUC + Accuracy + F1
  - 早停：验证集 AUC 100 轮无提升则停止
  - 超参搜索：Optuna 贝叶斯优化
  - 特征重要性：持久化用于因子筛选
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger

logger = get_logger("factor.ml_combiner")

# LightGBM 延迟导入：避免未安装时影响其他因子服务
try:
    import lightgbm as lgb  # type: ignore[import-untyped]
    _LGB_AVAILABLE = True
except ImportError:
    _LGB_AVAILABLE = False
    lgb = None  # type: ignore[assignment]


@dataclass
class LGBHyperParams:
    """LightGBM 超参数配置（二分类任务）。

    默认值依据示例代码 CASE-机器学习因子挖掘：
      - objective=binary：二分类任务（5日收益 > 0 = 1）
      - metric=auc：AUC 评估指标
      - learning_rate=0.05：适度学习率
      - num_leaves=31：适度复杂度
      - max_depth=5：适度深度
      - min_child_samples=20：叶子节点最小样本数
      - feature_fraction=0.8：特征采样比例
      - bagging_fraction=0.8：样本采样比例
      - lambda_l1=0.1, lambda_l2=1.0：L1/L2 正则化
      - early_stopping_rounds=100：放宽早停阈值
    """

    objective: str = "binary"
    metric: str = "auc"
    learning_rate: float = 0.05
    num_leaves: int = 31
    max_depth: int = 5
    min_child_samples: int = 20
    feature_fraction: float = 0.8
    bagging_fraction: float = 0.8
    bagging_freq: int = 5
    lambda_l1: float = 0.1
    lambda_l2: float = 1.0
    num_boost_round: int = 500
    early_stopping_rounds: int = 100
    verbose: int = -1
    n_jobs: int = -1
    seed: int = 42

    def to_lightgbm_params(self) -> dict[str, Any]:
        """转换为 LightGBM 原生参数字典。"""
        return {
            "objective": self.objective,
            "metric": self.metric,
            "learning_rate": self.learning_rate,
            "num_leaves": self.num_leaves,
            "max_depth": self.max_depth,
            "min_child_samples": self.min_child_samples,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": self.bagging_freq,
            "lambda_l1": self.lambda_l1,
            "lambda_l2": self.lambda_l2,
            "verbose": self.verbose,
            "n_jobs": self.n_jobs,
            "seed": self.seed,
        }


@dataclass
class FoldMetrics:
    """单折评估指标（二分类）。"""

    fold: int
    oos_auc: float
    oos_accuracy: float
    oos_precision: float
    oos_recall: float
    oos_f1: float
    oos_rank_ic: float  # 概率值与收益的 Spearman IC
    oos_ic_win_rate: float
    oos_long_short_ret: float
    train_samples: int
    test_samples: int
    feature_count: int


@dataclass
class TrainResult:
    """训练结果。"""

    model: lgb.Booster  # type: ignore[name-defined]
    feature_names: list[str]
    feature_importance: dict[str, float]
    fold_metrics: FoldMetrics
    hyperparams: LGBHyperParams
    trained_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_metadata(self) -> dict:
        """转换为可序列化的元数据字典。"""
        return {
            "trained_at": self.trained_at,
            "feature_names": self.feature_names,
            "feature_importance": self.feature_importance,
            "fold_metrics": asdict(self.fold_metrics),
            "hyperparams": asdict(self.hyperparams),
        }


class MLCombiner:
    """LightGBM 截面因子组合训练器（二分类）。

    使用方式：
        combiner = MLCombiner()
        result = combiner.train(X_train, y_train, X_val, y_val, feature_names)
        pred = combiner.predict(result.model, X_test)
        metrics = combiner.evaluate(y_test, pred, fold=1)
    """

    def __init__(self, hyperparams: LGBHyperParams | None = None) -> None:
        if not _LGB_AVAILABLE:
            raise ImportError("lightgbm 未安装，请运行: pip install lightgbm")
        self.hyperparams = hyperparams or LGBHyperParams()

    def train(
        self,
        x_train: pd.DataFrame,
        y_train: pd.Series,
        x_val: pd.DataFrame,
        y_val: pd.Series,
        feature_names: list[str],
    ) -> TrainResult:
        """训练 LightGBM 二分类模型。

        Args:
            x_train: 训练集特征矩阵
            y_train: 训练集标签（0/1 二分类）
            x_val: 验证集特征矩阵
            y_val: 验证集标签
            feature_names: 特征名列表

        Returns:
            TrainResult 包含模型、特征重要性、训练元数据
        """
        if x_train.empty or y_train.empty:
            raise ValueError("训练数据为空")
        if x_val.empty or y_val.empty:
            raise ValueError("验证数据为空")

        logger.info(
            "[ml_combiner] 开始训练: train=%s val=%s features=%d",
            x_train.shape, x_val.shape, len(feature_names),
        )

        # 对齐训练集 X 和 y
        train_common = x_train.index.intersection(y_train.index)
        x_train_aligned = x_train.loc[train_common]
        y_train_aligned = y_train.loc[train_common]

        val_common = x_val.index.intersection(y_val.index)
        x_val_aligned = x_val.loc[val_common]
        y_val_aligned = y_val.loc[val_common]

        if x_train_aligned.empty or x_val_aligned.empty:
            raise ValueError("训练/验证数据对齐后为空")

        # 确保标签为 0/1 整数
        y_train_aligned = y_train_aligned.astype(int)
        y_val_aligned = y_val_aligned.astype(int)

        logger.info(
            "[ml_combiner] 数据对齐完成: train_aligned=%d val_aligned=%d "
            "pos_rate_train=%.4f pos_rate_val=%.4f",
            len(x_train_aligned), len(x_val_aligned),
            float(y_train_aligned.mean()), float(y_val_aligned.mean()),
        )

        # 构建 LightGBM 数据集
        params = self.hyperparams.to_lightgbm_params()

        train_data = lgb.Dataset(
            x_train_aligned.values,
            label=y_train_aligned.values,
            feature_name=feature_names,
        )
        val_data = lgb.Dataset(
            x_val_aligned.values,
            label=y_val_aligned.values,
            feature_name=feature_names,
            reference=train_data,
        )

        # 训练
        model = lgb.train(
            params,
            train_data,
            num_boost_round=self.hyperparams.num_boost_round,
            valid_sets=[val_data],
            callbacks=[
                lgb.early_stopping(self.hyperparams.early_stopping_rounds, verbose=False),
                lgb.log_evaluation(period=100),
            ],
        )

        # 特征重要性（gain 加权）
        importance = dict(zip(
            feature_names,
            model.feature_importance(importance_type="gain").tolist(),
        ))
        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

        val_auc = float(model.best_score["valid_0"]["auc"]) if "valid_0" in model.best_score else float("nan")
        logger.info(
            "[ml_combiner] 训练完成: best_iteration=%d total_rounds=%d "
            "val_auc=%.6f top5_features=%s",
            model.best_iteration,
            model.current_iteration(),
            val_auc,
            list(importance.items())[:5],
        )

        return TrainResult(
            model=model,
            feature_names=feature_names,
            feature_importance=importance,
            fold_metrics=FoldMetrics(
                fold=0,
                oos_auc=0.0,
                oos_accuracy=0.0,
                oos_precision=0.0,
                oos_recall=0.0,
                oos_f1=0.0,
                oos_rank_ic=0.0,
                oos_ic_win_rate=0.0,
                oos_long_short_ret=0.0,
                train_samples=len(x_train_aligned),
                test_samples=0,
                feature_count=len(feature_names),
            ),
            hyperparams=self.hyperparams,
        )

    def predict(self, model: lgb.Booster, x: pd.DataFrame) -> pd.Series:  # type: ignore[name-defined]
        """模型推理（返回正类概率）。

        Args:
            model: lgb.Booster 模型
            x: 特征矩阵

        Returns:
            Series, 与 x 同索引，值为正类概率（0~1）
        """
        if x.empty:
            return pd.Series(dtype=float)

        pred = model.predict(x.values)
        return pd.Series(pred, index=x.index, name="prediction")

    def evaluate(
        self,
        y_true: pd.Series,
        y_pred: pd.Series,
        fold: int,
        returns_panel: pd.DataFrame | None = None,
        horizon: int = 5,
    ) -> FoldMetrics:
        """OOS 评估（二分类 + 概率因子评估）。

        计算指标：
          - oos_auc：AUC（要求 y_true 为 0/1）
          - oos_accuracy：准确率（阈值 0.5）
          - oos_precision/Recall/F1：精确率/召回率/F1
          - oos_rank_ic：概率值与实际收益的截面 Spearman IC 均值
          - oos_ic_win_rate：IC > 0 的比例
          - oos_long_short_ret：top 10% - bottom 10% 多空收益

        Args:
            y_true: 真实标签（0/1）
            y_pred: 模型预测概率（0~1）
            fold: 折叠序号
            returns_panel: 前向收益面板（用于计算 IC 和多空收益）
            horizon: 前向收益周期

        Returns:
            FoldMetrics
        """
        from sklearn.metrics import (
            accuracy_score,
            f1_score,
            precision_score,
            recall_score,
            roc_auc_score,
        )

        from xqtrader.domain.factor.services.feature_matrix_builder import daily_rank_ic

        if y_true.empty or y_pred.empty:
            return FoldMetrics(
                fold=fold, oos_auc=float("nan"), oos_accuracy=float("nan"),
                oos_precision=float("nan"), oos_recall=float("nan"), oos_f1=float("nan"),
                oos_rank_ic=float("nan"), oos_ic_win_rate=float("nan"),
                oos_long_short_ret=float("nan"),
                train_samples=0, test_samples=0, feature_count=0,
            )

        # 对齐索引
        common = y_true.index.intersection(y_pred.index)
        if len(common) == 0:
            return FoldMetrics(
                fold=fold, oos_auc=float("nan"), oos_accuracy=float("nan"),
                oos_precision=float("nan"), oos_recall=float("nan"), oos_f1=float("nan"),
                oos_rank_ic=float("nan"), oos_ic_win_rate=float("nan"),
                oos_long_short_ret=float("nan"),
                train_samples=0, test_samples=len(y_pred), feature_count=0,
            )

        y_true_aligned = y_true.loc[common].astype(int)
        y_pred_aligned = y_pred.loc[common]

        # 二分类指标（要求至少有两个类别）
        unique_labels = y_true_aligned.nunique()
        if unique_labels < 2:
            auc = float("nan")
        else:
            try:
                auc = float(roc_auc_score(y_true_aligned.values, y_pred_aligned.values))
            except (ValueError, IndexError):
                auc = float("nan")

        y_pred_binary = (y_pred_aligned >= 0.5).astype(int)
        accuracy = float(accuracy_score(y_true_aligned.values, y_pred_binary.values))
        precision = float(precision_score(y_true_aligned.values, y_pred_binary.values, zero_division=0))
        recall = float(recall_score(y_true_aligned.values, y_pred_binary.values, zero_division=0))
        f1 = float(f1_score(y_true_aligned.values, y_pred_binary.values, zero_division=0))

        # 概率因子 IC 评估（需要前向收益面板）
        rank_ic = float("nan")
        ic_win_rate = float("nan")
        long_short_ret = float("nan")

        if returns_panel is not None and not returns_panel.empty:
            ret_col = f"fwd_ret_{horizon}d"
            if ret_col in returns_panel.columns:
                # 对齐收益面板
                ret_common = returns_panel.index.intersection(y_pred_aligned.index)
                if len(ret_common) > 0:
                    ret_series = returns_panel.loc[ret_common, ret_col]
                    pred_aligned = y_pred_aligned.loc[ret_common]

                    # 截面 Spearman IC
                    daily_ic = daily_rank_ic(ret_series, pred_aligned)
                    if not daily_ic.empty:
                        rank_ic = float(daily_ic.mean())
                        ic_win_rate = float((daily_ic > 0).sum() / len(daily_ic))

                    # 多空收益：每日 top 10% - bottom 10%（按预测概率分组）
                    combined_ls = pd.DataFrame({"ret": ret_series, "pred": pred_aligned})
                    daily_ls_rets: list[float] = []
                    for td, group in combined_ls.groupby(level="trade_date"):
                        if len(group) < 20:
                            continue
                        pred_td = group["pred"]
                        ret_td = group["ret"]
                        n = len(pred_td)
                        threshold = max(n // 10, 1)
                        sorted_idx = pred_td.sort_values(ascending=False).index
                        top_idx = sorted_idx[:threshold]
                        bottom_idx = sorted_idx[-threshold:]
                        top_ret = float(ret_td.loc[top_idx].mean())
                        bottom_ret = float(ret_td.loc[bottom_idx].mean())
                        daily_ls_rets.append(top_ret - bottom_ret)

                    if daily_ls_rets:
                        long_short_ret = float(np.mean(daily_ls_rets))

        return FoldMetrics(
            fold=fold,
            oos_auc=auc,
            oos_accuracy=accuracy,
            oos_precision=precision,
            oos_recall=recall,
            oos_f1=f1,
            oos_rank_ic=rank_ic,
            oos_ic_win_rate=ic_win_rate,
            oos_long_short_ret=long_short_ret,
            train_samples=0,
            test_samples=len(y_pred_aligned),
            feature_count=0,
        )

    def search_hyperparams(
        self,
        x_train: pd.DataFrame,
        y_train: pd.Series,
        x_val: pd.DataFrame,
        y_val: pd.Series,
        feature_names: list[str],
        n_trials: int = 20,
    ) -> LGBHyperParams:
        """Optuna 贝叶斯超参搜索。

        参考示例代码 4-LightGBM对比与调参.py，目标：最大化验证集 AUC。

        Args:
            x_train: 训练集特征矩阵
            y_train: 训练集标签（0/1）
            x_val: 验证集特征矩阵
            y_val: 验证集标签
            feature_names: 特征名列表
            n_trials: 搜索次数（默认 20，平衡时间与效果）

        Returns:
            最优 LGBHyperParams
        """
        try:
            import optuna
        except ImportError:
            logger.warning("[ml_combiner] optuna 未安装，使用默认超参数")
            return self.hyperparams

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        # 对齐数据
        train_common = x_train.index.intersection(y_train.index)
        x_tr = x_train.loc[train_common]
        y_tr = y_train.loc[train_common].astype(int)

        val_common = x_val.index.intersection(y_val.index)
        x_va = x_val.loc[val_common]
        y_va = y_val.loc[val_common].astype(int)

        if x_tr.empty or x_va.empty:
            logger.warning("[ml_combiner] 超参搜索数据为空，使用默认参数")
            return self.hyperparams

        def objective(trial: optuna.Trial) -> float:
            params = LGBHyperParams(
                objective="binary",
                metric="auc",
                learning_rate=trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
                num_leaves=trial.suggest_int("num_leaves", 15, 63),
                max_depth=trial.suggest_int("max_depth", 3, 8),
                min_child_samples=trial.suggest_int("min_child_samples", 10, 50),
                feature_fraction=trial.suggest_float("feature_fraction", 0.6, 1.0),
                bagging_fraction=trial.suggest_float("bagging_fraction", 0.6, 1.0),
                bagging_freq=5,
                lambda_l1=trial.suggest_float("lambda_l1", 0.0, 1.0),
                lambda_l2=trial.suggest_float("lambda_l2", 0.0, 1.0),
                num_boost_round=200,
                early_stopping_rounds=50,
                verbose=-1,
                n_jobs=-1,
                seed=42,
            )

            try:
                train_data = lgb.Dataset(x_tr.values, label=y_tr.values, feature_name=feature_names)
                val_data = lgb.Dataset(x_va.values, label=y_va.values, feature_name=feature_names, reference=train_data)
                model = lgb.train(
                    params.to_lightgbm_params(),
                    train_data,
                    num_boost_round=params.num_boost_round,
                    valid_sets=[val_data],
                    callbacks=[
                        lgb.early_stopping(params.early_stopping_rounds, verbose=False),
                    ],
                )
                return float(model.best_score["valid_0"]["auc"])
            except Exception:
                return 0.5

        logger.info(
            "[ml_combiner] Optuna 超参搜索开始: n_trials=%d train=%d val=%d",
            n_trials, len(x_tr), len(x_va),
        )

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

        best = study.best_params
        best_auc = study.best_value
        logger.info(
            "[ml_combiner] Optuna 搜索完成: best_auc=%.4f best_params=%s",
            best_auc, best,
        )

        return LGBHyperParams(
            objective="binary",
            metric="auc",
            learning_rate=best["learning_rate"],
            num_leaves=best["num_leaves"],
            max_depth=best["max_depth"],
            min_child_samples=best["min_child_samples"],
            feature_fraction=best["feature_fraction"],
            bagging_fraction=best["bagging_fraction"],
            bagging_freq=5,
            lambda_l1=best["lambda_l1"],
            lambda_l2=best["lambda_l2"],
            num_boost_round=500,
            early_stopping_rounds=100,
            verbose=-1,
            n_jobs=-1,
            seed=42,
        )

    def save_model(
        self,
        result: TrainResult,
        model_dir: Path,
        version: str,
    ) -> Path:
        """持久化模型工件。

        目录结构：
            model_dir/
              {version}/
                model.lgb              — LightGBM 模型
                metadata.json          — 训练元数据
                feature_importance.json — 特征重要性
                oos_metrics.json       — OOS 评估指标

        Args:
            result: 训练结果
            model_dir: 模型根目录
            version: 版本号（如 "2026-07-07"）

        Returns:
            版本目录路径
        """
        version_dir = model_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)

        # 保存 LightGBM 模型
        model_path = version_dir / "model.lgb"
        result.model.save_model(str(model_path))  # type: ignore[attr-defined]

        # 保存元数据
        metadata_path = version_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(result.to_metadata(), f, ensure_ascii=False, indent=2)

        # 保存特征重要性
        importance_path = version_dir / "feature_importance.json"
        with open(importance_path, "w", encoding="utf-8") as f:
            json.dump(result.feature_importance, f, ensure_ascii=False, indent=2)

        # 保存 OOS 指标
        metrics_path = version_dir / "oos_metrics.json"
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(asdict(result.fold_metrics), f, ensure_ascii=False, indent=2)

        logger.info(
            "[ml_combiner] 模型工件已保存: %s (model=%s)",
            version_dir, model_path,
        )
        return version_dir

    @staticmethod
    def load_model(model_path: Path) -> lgb.Booster:  # type: ignore[name-defined]
        """加载 LightGBM 模型。"""
        if not _LGB_AVAILABLE:
            raise ImportError("lightgbm 未安装")
        return lgb.Booster(model_file=str(model_path))  # type: ignore[no-any-return]

    @staticmethod
    def load_metadata(version_dir: Path) -> dict:
        """加载模型元数据。"""
        metadata_path = version_dir / "metadata.json"
        if not metadata_path.exists():
            return {}
        with open(metadata_path, encoding="utf-8") as f:
            data: dict = json.load(f)
        return data

    @staticmethod
    def get_latest_version(model_dir: Path) -> Path | None:
        """获取最新版本目录。"""
        if not model_dir.exists():
            return None

        latest_link = model_dir / "latest"
        if latest_link.exists():
            return latest_link.resolve() if latest_link.is_symlink() else latest_link

        version_dirs = [
            d for d in model_dir.iterdir()
            if d.is_dir() and d.name != "latest"
        ]
        if not version_dirs:
            return None

        def _parse_date(name: str) -> date | None:
            try:
                return date.fromisoformat(name)
            except ValueError:
                return None

        dated: list[tuple[Path, date]] = []
        for d in version_dirs:
            dt = _parse_date(d.name)
            if dt is not None:
                dated.append((d, dt))
        if dated:
            latest = max(dated, key=lambda x: x[1])[0]
        else:
            latest = max(version_dirs, key=lambda d: d.name)

        return latest
