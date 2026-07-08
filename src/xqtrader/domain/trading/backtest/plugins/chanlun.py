"""缠论买卖点规则插件 — SPI 机制

基于 chanlun_signal.py 实时计算的 chan_buy_point / chan_sell_point / chan_bi_direction 信号。
缠论买卖点本身就是时序信号（笔/中枢/背驰确认后产生），适合 SPI 机制。

信号:
  一买买入: chan_buy_point == 1（底背驰）
  二买买入: chan_buy_point == 2（回调不破前低）
  三买买入: chan_buy_point == 3（突破中枢回踩不破）
  一卖卖出: chan_sell_point == 1（顶背驰）
  二卖卖出: chan_sell_point == 2（反弹不破前高）
  三卖卖出: chan_sell_point == 3（跌破中枢反弹不破）

依赖内置因子: chan_buy_point, chan_sell_point, chan_bi_direction
（由 chanlun_signal.compute_chanlun_signals 实时计算，不依赖 DB 因子库）
"""
from ..core import RuleContext, RulePlugin, RuleResult


class ChanlunPlugin(RulePlugin):
    """缠论买卖点规则插件

    买入条件: chan_buy_point > 0（一买/二买/三买任一触发）
    卖出条件: chan_sell_point > 0（一卖/二卖/三卖任一触发）
    """

    rule_id: str = "ts_chanlun_signal"
    name: str = "缠论买卖点"
    factor_ids: list[str] = ["chan_buy_point", "chan_sell_point", "chan_bi_direction"]
    prev_factor_ids: list[str] = []

    # 买卖点名称映射
    _BUY_NAMES = {1: "一买（底背驰）", 2: "二买（回调不破）", 3: "三买（突破回踩）"}
    _SELL_NAMES = {1: "一卖（顶背驰）", 2: "二卖（反弹不破）", 3: "三卖（跌破反弹）"}

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        buy_point = fv.get("chan_buy_point")
        sell_point = fv.get("chan_sell_point")
        bi_dir = fv.get("chan_bi_direction")

        # 缠论信号为 0.0 表示无信号，None 表示数据不足
        if buy_point is None and sell_point is None:
            return RuleResult(
                rule_id=self.rule_id,
                direction="neutral",
                reason="缠论信号数据不充分",
            )

        buy_val = buy_point or 0.0
        sell_val = sell_point or 0.0
        bi_val = bi_dir or 0

        # 买入信号
        if buy_val > 0:
            bp_type = int(buy_val)
            bp_name = self._BUY_NAMES.get(bp_type, f"买点{bp_type}")
            bi_hint = "（向上笔确认）" if bi_val == 1 else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0 if bp_type == 1 else 0.85,  # 一买信号最强
                direction="buy",
                confidence=0.9 if bp_type == 1 else 0.75,
                reason=f"缠论{bp_name}买入: chan_buy_point={buy_val}{bi_hint}",
                detail={
                    "chan_buy_point": buy_val,
                    "chan_sell_point": sell_val,
                    "chan_bi_direction": bi_val,
                    "signal": f"buy_point_{bp_type}",
                },
            )

        # 卖出信号
        if sell_val > 0:
            sp_type = int(sell_val)
            sp_name = self._SELL_NAMES.get(sp_type, f"卖点{sp_type}")
            bi_hint = "（向下笔确认）" if bi_val == -1 else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0 if sp_type == 1 else 0.85,  # 一卖信号最强
                direction="sell",
                confidence=0.9 if sp_type == 1 else 0.75,
                reason=f"缠论{sp_name}卖出: chan_sell_point={sell_val}{bi_hint}",
                detail={
                    "chan_buy_point": buy_val,
                    "chan_sell_point": sell_val,
                    "chan_bi_direction": bi_val,
                    "signal": f"sell_point_{sp_type}",
                },
            )

        # 无信号
        bi_hint = ""
        if bi_val == 1:
            bi_hint = "，向上笔中"
        elif bi_val == -1:
            bi_hint = "，向下笔中"

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=f"缠论无信号: chan_buy_point={buy_val}, chan_sell_point={sell_val}{bi_hint}",
            detail={
                "chan_buy_point": buy_val,
                "chan_sell_point": sell_val,
                "chan_bi_direction": bi_val,
            },
        )
