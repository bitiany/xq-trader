"""量比突破规则插件 — SPI 机制

量比 = 当日成交量 / N日平均成交量

量比反映成交活跃度:
  量比 < 0.5: 明显缩量
  量比 0.5~1.5: 正常成交量
  量比 1.5~2.5: 温和放量
  量比 2.5~5: 明显放量
  量比 > 5: 剧烈放量

量价配合的经典信号:
  放量上涨买入: 量比 > 1.5 且 close > close_prev
  放量下跌卖出: 量比 > 1.5 且 close < close_prev
  缩量下跌卖出: 量比 < 0.5 且 close < close_prev（动能衰竭）

与 volume_price.py 区别:
  - volume_price 用 vol_ma_20（20日均量）
  - vol_ratio 用 vol_ratio（5日均量计算的量比），更敏感
  - 本插件增加突破前高的判断

依赖内置因子: close, volume, vol_ratio
前值因子: close（用于判断上涨/下跌）
"""
from ..core import RuleContext, RulePlugin, RuleResult


class VolRatioPlugin(RulePlugin):
    """量比突破规则插件

    买入条件: 量比 > 1.5（放量）且 close 上涨
    卖出条件: 量比 > 1.5（放量下跌）或 量比 < 0.5（缩量下跌）
    """

    rule_id: str = "ts_vol_ratio"
    name: str = "量比突破"
    factor_ids: list[str] = ["close", "volume", "vol_ratio"]
    prev_factor_ids: list[str] = ["close"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        close = fv.get("close")
        volume = fv.get("volume")
        vol_ratio = fv.get("vol_ratio")
        close_prev = fv.get("close_prev")

        if close is None or volume is None or vol_ratio is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="量比数据不充分")
        if close_prev is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="前值数据不充分")

        is_up = close > close_prev
        is_down = close < close_prev
        is_volume_surge = vol_ratio > 1.5  # 放量
        is_volume_shrink = vol_ratio < 0.5  # 缩量

        # 买入信号: 放量上涨
        if is_up and is_volume_surge:
            # 量比越大，信号越强（上限 5.0）
            score = min(1.0, 0.7 + (vol_ratio - 1.5) * 0.15)
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=score,
                direction="buy",
                confidence=0.85,
                reason=(
                    f"量比放量上涨买入: close={close:.4f} > 前close={close_prev:.4f}, "
                    f"volume={volume:.0f}, vol_ratio={vol_ratio:.2f}"
                ),
                detail={
                    "close": close, "volume": volume, "vol_ratio": vol_ratio,
                    "close_prev": close_prev,
                    "signal": "vol_surge_up",
                },
            )

        # 卖出信号: 放量下跌
        if is_down and is_volume_surge:
            score = min(1.0, 0.7 + (vol_ratio - 1.5) * 0.15)
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=score,
                direction="sell",
                confidence=0.85,
                reason=(
                    f"量比放量下跌卖出: close={close:.4f} < 前close={close_prev:.4f}, "
                    f"volume={volume:.0f}, vol_ratio={vol_ratio:.2f}"
                ),
                detail={
                    "close": close, "volume": volume, "vol_ratio": vol_ratio,
                    "close_prev": close_prev,
                    "signal": "vol_surge_down",
                },
            )

        # 卖出信号: 缩量下跌（动能衰竭）
        if is_down and is_volume_shrink:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=0.75,
                direction="sell",
                confidence=0.75,
                reason=(
                    f"量比缩量下跌卖出: close={close:.4f} < 前close={close_prev:.4f}, "
                    f"volume={volume:.0f}, vol_ratio={vol_ratio:.2f}"
                ),
                detail={
                    "close": close, "volume": volume, "vol_ratio": vol_ratio,
                    "close_prev": close_prev,
                    "signal": "vol_shrink_down",
                },
            )

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=(
                f"量比无信号: close={close:.4f}, volume={volume:.0f}, vol_ratio={vol_ratio:.2f}"
            ),
            detail={
                "close": close, "volume": volume, "vol_ratio": vol_ratio,
                "close_prev": close_prev,
            },
        )
