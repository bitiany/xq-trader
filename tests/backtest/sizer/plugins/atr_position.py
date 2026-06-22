"""ATR 仓位插件 — 基于平均真实波幅(ATR)计算仓位

核心思路: 固定风险比例，通过 ATR 确定止损距离，反推仓位大小

  仓位 = (组合价值 × 风险比例) / (ATR × ATR倍数)

  - 风险比例: 每笔交易愿意承担的最大亏损占组合价值的比例
  - ATR倍数: 止损距离 = ATR × 倍数（如 2 倍 ATR 作为止损距离）

参数:
  - risk_pct: 单笔风险比例，默认 2%
  - atr_multiplier: ATR 倍数，默认 2.0
  - max_pct: 最大仓位占可用资金比例上限

依赖因子:
  - atr: ATR 指标值
"""

from ..plugin import PositionPlugin
from ..context import PositionContext, PositionResult


class ATRPositionPlugin(PositionPlugin):
    """ATR 仓位管理插件"""

    position_id: str = "atr"
    name: str = "ATR仓位管理"
    factor_ids: list[str] = ["atr"]

    def __init__(self, params: dict | None = None):
        p = params or {}
        self.risk_pct = p.get("risk_pct", 0.02)
        self.atr_multiplier = p.get("atr_multiplier", 2.0)
        self.max_pct = p.get("max_pct", 0.95)

    def calculate_size(self, context: PositionContext) -> PositionResult:
        price = context.current_price
        portfolio_value = context.portfolio_value
        cash = context.available_cash
        atr = context.factor_values.get("atr")

        if atr is None or atr <= 0:
            # ATR 数据不可用，回退到固定比例
            size = int(cash * 0.2 / price / 100) * 100
            return PositionResult(
                size=size,
                reason=f"ATR仓位(回退): ATR数据不可用, 使用默认20%比例, 仓位={size}股",
            )

        # 止损距离 = ATR × 倍数
        stop_distance = atr * self.atr_multiplier

        # 风险金额 = 组合价值 × 风险比例
        risk_amount = portfolio_value * self.risk_pct

        # 仓位 = 风险金额 / 止损距离
        raw_size = risk_amount / stop_distance

        # 不超过可用资金的最大仓位
        max_size_by_cash = cash * self.max_pct / price
        raw_size = min(raw_size, max_size_by_cash)

        # 按手数取整
        size = int(raw_size / 100) * 100

        return PositionResult(
            size=size,
            reason=f"ATR仓位: ATR={atr:.4f}, 止损距离={stop_distance:.4f}"
                   f"(×{self.atr_multiplier}), 风险金额={risk_amount:.0f}"
                   f"({self.risk_pct:.0%}), 仓位={size}股",
        )
