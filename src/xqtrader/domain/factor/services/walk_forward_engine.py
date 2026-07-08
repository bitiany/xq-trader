"""Forward-Walk 训练循环引擎 — 三方案共享的时间窗口切分核心。

设计原则（参考 AQR / Two Sigma 业界实践）：
  - 无前瞻偏差：训练只用过去数据，Gap 防标签泄漏
  - 滚动重训：月频重训模型，适应市场环境变化
  - 样本外验证：训练/验证/测试三段切分
  - Gap 防泄漏：与标签 fwd_ret_horizon 对齐，避免标签跨越 train/test 边界

时间窗口划分：
  时间轴 ──────────────────────────────────────────────────────────▶
              ←── Train ──→←Gap→←Val──→←Gap→←Test──→
              train_window    gap  val_window  gap  test_window
                                              ↑
                                           当前日 T

  每月滚动：T 每月前进 `step` 个交易日，重训模型
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from framework.commons.logger import get_logger

logger = get_logger("factor.walk_forward")


@dataclass(frozen=True)
class WalkForwardWindow:
    """单个 walk-forward 窗口。

    每个窗口包含四段：train / validate / test / predict
    - train: 训练集（252d 默认，约 1 年）
    - validate: 验证集（42d 默认，约 2 月），用于早停
    - test: 测试集（42d 默认，约 2 月），样本外评估
    - predict: 预测段（test_end 之后），实盘推理

    各段之间通过 gap 隔离，防止标签泄漏（fwd_ret_5d 跨越边界）。
    """

    fold: int                      # 折叠序号（从 1 开始）
    train_start: date
    train_end: date
    validate_start: date           # = train_end + gap
    validate_end: date
    test_start: date               # = validate_end + gap
    test_end: date
    predict_start: date            # = test_end + 1 交易日
    predict_end: date              # = predict_start + step - 1 交易日

    def describe(self) -> str:
        """窗口描述字符串（用于日志输出）。"""
        return (
            f"fold={self.fold} "
            f"train={self.train_start}~{self.train_end} "
            f"val={self.validate_start}~{self.validate_end} "
            f"test={self.test_start}~{self.test_end} "
            f"predict={self.predict_start}~{self.predict_end}"
        )


@dataclass
class WalkForwardConfig:
    """Forward-Walk 配置参数。

    默认值依据 AQR/Two Sigma 业界经验：
      - train_window=252（1年）：国内 A 股 1 年最优，平衡样本量与市场环境稳定性
      - val_window=42（2月）：用于早停和超参调优
      - test_window=42（2月）：样本外评估，不参与训练
      - gap=5：与 fwd_ret_5d 标签 horizon 对齐，防泄漏
      - step=21（1月）：AQR 月频重训，平衡计算成本与新鲜度
    """

    train_window: int = 252       # 训练窗（交易日）
    val_window: int = 42          # 验证窗
    test_window: int = 42         # 测试窗
    gap: int = 5                  # Gap（防泄漏，与标签 horizon 对齐）
    step: int = 21                # 滚动步长（月频重训）


class WalkForwardEngine:
    """Forward-Walk 训练循环引擎。

    职责单一：仅负责时间窗口切分，不涉及数据加载或模型训练。
    数据加载由 FeatureMatrixBuilder 负责，模型训练由 MLCombiner 负责。

    使用方式：
        engine = WalkForwardEngine(WalkForwardConfig())
        windows = engine.generate_windows(start, end, trading_days)
        for window in windows:
            X_train, y_train = await builder.build_train_dataset(window)
            model = combiner.train(X_train, y_train, ...)
    """

    def __init__(self, config: WalkForwardConfig | None = None) -> None:
        self.config = config or WalkForwardConfig()

    def generate_windows(
        self,
        start: date,
        end: date,
        trading_days: list[date],
    ) -> list[WalkForwardWindow]:
        """生成所有 walk-forward 窗口。

        窗口从最早期开始生成，每次向前滚动 `step` 个交易日，
        直到 test_end 超过 end 为止。

        Args:
            start: 数据可用起始日（实际 train_start 由 trading_days 长度决定）
            end: 数据可用结束日（test_end 不得超过此日期）
            trading_days: 交易日历（已排序）

        Returns:
            窗口列表，按时间顺序排列

        Raises:
            ValueError: 交易日历不足以构成一个完整窗口
        """
        cfg = self.config
        total_needed = cfg.train_window + cfg.gap + cfg.val_window + cfg.gap + cfg.test_window
        if len(trading_days) < total_needed:
            raise ValueError(
                f"交易日历不足：需要至少 {total_needed} 个交易日"
                f"（train={cfg.train_window} + gap={cfg.gap} + val={cfg.val_window}"
                f" + gap={cfg.gap} + test={cfg.test_window}），"
                f"实际 {len(trading_days)} 个"
            )

        # 过滤出 [start, end] 范围内的交易日
        valid_days = [d for d in trading_days if start <= d <= end]
        if len(valid_days) < total_needed:
            raise ValueError(
                f"[{start}~{end}] 范围内交易日不足：需要 {total_needed}，实际 {len(valid_days)}"
            )

        windows: list[WalkForwardWindow] = []
        fold = 0

        # 第一个窗口的 train_start 索引
        train_start_idx = 0
        # test_end 索引不得超过最后一个交易日
        max_test_end_idx = len(valid_days) - 1

        while True:
            train_end_idx = train_start_idx + cfg.train_window - 1
            val_start_idx = train_end_idx + cfg.gap + 1
            val_end_idx = val_start_idx + cfg.val_window - 1
            test_start_idx = val_end_idx + cfg.gap + 1
            test_end_idx = test_start_idx + cfg.test_window - 1

            if test_end_idx > max_test_end_idx:
                break

            # predict 段：test_end 之后的 step 个交易日（最后一个窗口可能不足 step）
            predict_start_idx = test_end_idx + 1
            predict_end_idx = min(predict_start_idx + cfg.step - 1, max_test_end_idx)
            if predict_start_idx > max_test_end_idx:
                # test 段已是最后一段，无 predict 段（用 test_end 占位）
                predict_start = valid_days[test_end_idx]
                predict_end = valid_days[test_end_idx]
            else:
                predict_start = valid_days[predict_start_idx]
                predict_end = valid_days[predict_end_idx]

            fold += 1
            window = WalkForwardWindow(
                fold=fold,
                train_start=valid_days[train_start_idx],
                train_end=valid_days[train_end_idx],
                validate_start=valid_days[val_start_idx],
                validate_end=valid_days[val_end_idx],
                test_start=valid_days[test_start_idx],
                test_end=valid_days[test_end_idx],
                predict_start=predict_start,
                predict_end=predict_end,
            )
            windows.append(window)

            logger.info(
                "[walk_forward] 生成窗口 %s", window.describe(),
            )

            # 滚动到下一个窗口
            train_start_idx += cfg.step

        logger.info(
            "[walk_forward] 共生成 %d 个窗口 (step=%d, train=%d, val=%d, test=%d, gap=%d)",
            len(windows), cfg.step, cfg.train_window, cfg.val_window, cfg.test_window, cfg.gap,
        )
        return windows
