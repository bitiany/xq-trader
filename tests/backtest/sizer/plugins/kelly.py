"""凯利公式仓位插件 — 基于历史交易胜率和盈亏比动态计算最优仓位

凯利公式: f* = W - (1-W) / R
  - W = 胜率 (winning trades / total trades)
  - R = 盈亏比 (average win / average loss)
  - f* = 最优仓位比例

实际使用中通常采用分数凯利 (fractional Kelly) 以降低波动:
  - 实际仓位 = f* * kelly_fraction * portfolio_value / current_price

参数:
  - kelly_fraction: 凯利分数，默认 0.5（半凯利）
  - min_trades: 最少交易次数，不足时使用 default_pct
  - default_pct: 交易次数不足时的默认仓位比例
  - max_pct: 最大仓位比例上限
"""

from ..plugin import PositionPlugin
from ..context import PositionContext, PositionResult


class KellyPositionPlugin(PositionPlugin):
    """凯利公式仓位管理插件"""

    position_id: str = "kelly"
    name: str = "凯利公式仓位"
    factor_ids: list[str] = []

    def __init__(self, params: dict | None = None):
        p = params or {}
        self.kelly_fraction = p.get("kelly_fraction", 0.5)
        self.min_trades = p.get("min_trades", 5)
        self.default_pct = p.get("default_pct", 0.2)
        self.max_pct = p.get("max_pct", 0.95)

    def calculate_size(self, context: PositionContext) -> PositionResult:
        trades = context.closed_trades
        price = context.current_price
        portfolio_value = context.portfolio_value
        cash = context.available_cash

        # 交易次数不足，使用默认比例
        if len(trades) < self.min_trades:
            pct = self.default_pct
            size = int(cash * pct / price / 100) * 100
            return PositionResult(
                size=size,
                reason=f"凯利仓位(默认): 交易次数{len(trades)}<{self.min_trades}, "
                       f"使用默认比例{self.default_pct:.0%}, 仓位={size}股",
            )

        # 计算胜率和盈亏比
        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) <= 0]
        win_rate = len(wins) / len(trades)

        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t["pnl"] for t in losses) / len(losses)) if losses else 1
        win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

        # 凯利公式: f* = W - (1-W) / R
        kelly_pct = win_rate - (1 - win_rate) / win_loss_ratio if win_loss_ratio > 0 else 0
        kelly_pct = max(0, min(kelly_pct, self.max_pct))  # 限制在 [0, max_pct]

        # 分数凯利
        actual_pct = kelly_pct * self.kelly_fraction
        actual_pct = min(actual_pct, self.max_pct)

        size = int(cash * actual_pct / price / 100) * 100
        return PositionResult(
            size=size,
            reason=f"凯利仓位: 胜率={win_rate:.2%}, 盈亏比={win_loss_ratio:.2f}, "
                   f"凯利比例={kelly_pct:.2%}, 实际比例={actual_pct:.2%}"
                   f"(×{self.kelly_fraction}), 仓位={size}股",
        )
