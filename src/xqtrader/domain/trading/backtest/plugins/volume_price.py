"""量价突破规则插件 — SPI 机制

量价配合是业界主流的交易信号:
  放量上涨买入: 价格突破前高 + 成交量放大（>1.5倍均量）
  缩量下跌卖出: 价格跌破前低 + 成交量萎缩（<0.5倍均量）或放量下跌

量价突破需要时序数据（前高/前低/均量），表达式无法实现，必须用 SPI 机制。

依赖内置因子: close, volume, vol_ma_20, close_prev
前值因子: close_prev, vol_ma_20_prev（用于判断突破）
"""
from ..core import RuleContext, RulePlugin, RuleResult


class VolumePricePlugin(RulePlugin):
    """量价突破规则插件

    买入条件: close > close_prev（上涨）且 volume > 1.5 * vol_ma_20（放量）
    卖出条件: close < close_prev（下跌）且 volume > 1.5 * vol_ma_20（放量下跌）
              或 close < close_prev 且 volume < 0.5 * vol_ma_20（缩量下跌，动能衰竭）
    """

    rule_id: str = "ts_volume_price"
    name: str = "量价突破"
    factor_ids: list[str] = ["close", "volume", "vol_ma_20"]
    prev_factor_ids: list[str] = ["close"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        close = fv.get("close")
        volume = fv.get("volume")
        vol_ma = fv.get("vol_ma_20")
        close_prev = fv.get("close_prev")

        if close is None or volume is None or vol_ma is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="量价数据不充分")
        if close_prev is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="前值数据不充分")
        if vol_ma <= 0:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="均量为0")

        vol_ratio = volume / vol_ma
        is_up = close > close_prev
        is_down = close < close_prev
        is_volume_surge = vol_ratio > 1.5  # 放量
        is_volume_shrink = vol_ratio < 0.5  # 缩量

        # 买入信号: 放量上涨
        if is_up and is_volume_surge:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=min(1.0, 0.7 + (vol_ratio - 1.5) * 0.2),
                direction="buy",
                confidence=0.8,
                reason=(
                    f"放量上涨买入: close={close:.4f} > 前close={close_prev:.4f}, "
                    f"volume={volume:.0f}, vol_ma={vol_ma:.0f}, vol_ratio={vol_ratio:.2f}"
                ),
                detail={
                    "close": close, "volume": volume, "vol_ma_20": vol_ma,
                    "close_prev": close_prev, "vol_ratio": vol_ratio,
                    "signal": "volume_surge_up",
                },
            )

        # 卖出信号: 放量下跌
        if is_down and is_volume_surge:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=min(1.0, 0.7 + (vol_ratio - 1.5) * 0.2),
                direction="sell",
                confidence=0.8,
                reason=(
                    f"放量下跌卖出: close={close:.4f} < 前close={close_prev:.4f}, "
                    f"volume={volume:.0f}, vol_ma={vol_ma:.0f}, vol_ratio={vol_ratio:.2f}"
                ),
                detail={
                    "close": close, "volume": volume, "vol_ma_20": vol_ma,
                    "close_prev": close_prev, "vol_ratio": vol_ratio,
                    "signal": "volume_surge_down",
                },
            )

        # 卖出信号: 缩量下跌（动能衰竭，趋势可能反转）
        if is_down and is_volume_shrink:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=0.7,
                direction="sell",
                confidence=0.7,
                reason=(
                    f"缩量下跌卖出: close={close:.4f} < 前close={close_prev:.4f}, "
                    f"volume={volume:.0f}, vol_ma={vol_ma:.0f}, vol_ratio={vol_ratio:.2f}"
                ),
                detail={
                    "close": close, "volume": volume, "vol_ma_20": vol_ma,
                    "close_prev": close_prev, "vol_ratio": vol_ratio,
                    "signal": "volume_shrink_down",
                },
            )

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=(
                f"量价无信号: close={close:.4f}, volume={volume:.0f}, "
                f"vol_ma={vol_ma:.0f}, vol_ratio={vol_ratio:.2f}"
            ),
            detail={
                "close": close, "volume": volume, "vol_ma_20": vol_ma,
                "vol_ratio": vol_ratio,
            },
        )
