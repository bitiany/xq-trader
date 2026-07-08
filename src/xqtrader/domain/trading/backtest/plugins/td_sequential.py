"""神奇九转 TD Sequential 规则插件 — SPI 机制

TD Sequential 是 Tom DeMark 的经典反转指标:
  TD Setup (9根确认):
    买入信号: 连续9个交易日收盘价 < 4日前收盘价（下跌动能衰竭）
    卖出信号: 连续9个交易日收盘价 > 4日前收盘价（上涨动能衰竭）

  信号特点:
    - 反转信号，非趋势信号
    - 9根确认后产生信号，等待动能衰竭后的反转
    - 适合震荡市或趋势末期，不适合强势趋势中段

  与其他指标配合:
    - 与趋势指标（均线/ADX）配合可避免逆势
    - 与 RSI 背离组合增强反转判断

依赖内置因子: td_seq_buy, td_seq_sell, td_seq_count
（由 service.py._calc_td_sequential 实时计算）
"""
from ..core import RuleContext, RulePlugin, RuleResult


class TDSequentialPlugin(RulePlugin):
    """神奇九转 TD Sequential 规则插件

    买入条件: td_seq_buy == 1（连续9日下跌后反转）
    卖出条件: td_seq_sell == 1（连续9日上涨后反转）
    """

    rule_id: str = "ts_td_sequential"
    name: str = "神奇九转 TD Sequential"
    factor_ids: list[str] = ["td_seq_buy", "td_seq_sell", "td_seq_count"]
    prev_factor_ids: list[str] = []

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        buy_sig = fv.get("td_seq_buy")
        sell_sig = fv.get("td_seq_sell")
        td_count = fv.get("td_seq_count")

        if buy_sig is None and sell_sig is None:
            return RuleResult(
                rule_id=self.rule_id,
                direction="neutral",
                reason="TD Sequential 数据不充分",
            )

        buy_val = buy_sig or 0.0
        sell_val = sell_sig or 0.0
        count_val = td_count or 0

        # 买入信号: 连续9日下跌后反转
        if buy_val > 0:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="buy",
                confidence=0.85,
                reason=(
                    f"神奇九转买入: 连续9日 close < close.shift(4)，下跌动能衰竭 "
                    f"(td_seq_buy={buy_val}, count={count_val})"
                ),
                detail={
                    "td_seq_buy": buy_val, "td_seq_sell": sell_val,
                    "td_seq_count": count_val,
                    "signal": "td_buy_setup_9",
                },
            )

        # 卖出信号: 连续9日上涨后反转
        if sell_val > 0:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="sell",
                confidence=0.85,
                reason=(
                    f"神奇九转卖出: 连续9日 close > close.shift(4)，上涨动能衰竭 "
                    f"(td_seq_sell={sell_val}, count={count_val})"
                ),
                detail={
                    "td_seq_buy": buy_val, "td_seq_sell": sell_val,
                    "td_seq_count": count_val,
                    "signal": "td_sell_setup_9",
                },
            )

        # 计数预警提示（不直接触发交易）
        if count_val != 0:
            if count_val > 0:
                return RuleResult(
                    rule_id=self.rule_id,
                    direction="neutral",
                    reason=(
                        f"神奇九转卖出预警: 上涨计数={count_val}/9 "
                        f"(连续 close > close.shift(4))"
                    ),
                    detail={
                        "td_seq_buy": buy_val, "td_seq_sell": sell_val,
                        "td_seq_count": count_val,
                    },
                )
            return RuleResult(
                rule_id=self.rule_id,
                direction="neutral",
                reason=(
                    f"神奇九转买入预警: 下跌计数={-count_val}/9 "
                    f"(连续 close < close.shift(4))"
                ),
                detail={
                    "td_seq_buy": buy_val, "td_seq_sell": sell_val,
                    "td_seq_count": count_val,
                },
            )

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason="神奇九转无信号: 计数未启动",
            detail={
                "td_seq_buy": buy_val, "td_seq_sell": sell_val,
                "td_seq_count": count_val,
            },
        )
