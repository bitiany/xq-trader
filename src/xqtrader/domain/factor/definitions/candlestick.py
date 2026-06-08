"""F类: K线形态聚合因子定义。"""

from xqtrader.domain.factor.definitions.factor_def import FactorDefinition as F

CANDLESTICK_FACTORS: list[F] = [
    F(factor_id="cdl_bull_freq_20", display_name="20日看涨形态频次", category="candlestick",
      group_id="cdl_agg", direction="DESC", data_origin="computed",
      compute_engine="plugin", update_freq="daily", min_periods=20,
      dependencies="open,high,low,close", description="20日内看涨形态出现次数"),
    F(factor_id="cdl_bear_freq_20", display_name="20日看跌形态频次", category="candlestick",
      group_id="cdl_agg", direction="ASC", data_origin="computed",
      compute_engine="plugin", update_freq="daily", min_periods=20,
      dependencies="open,high,low,close", description="20日内看跌形态出现次数"),
    F(factor_id="cdl_net_score_20", display_name="20日形态净得分", category="candlestick",
      group_id="cdl_agg", direction="DESC", data_origin="computed",
      compute_engine="plugin", update_freq="daily", min_periods=20,
      dependencies="open,high,low,close", description="(看涨次数-看跌次数)/总次数"),
    F(factor_id="cdl_upper_shadow_ratio", display_name="上影线占比均值", category="candlestick",
      group_id="cdl_agg", direction="ASC", data_origin="computed",
      compute_engine="plugin", update_freq="daily", min_periods=20,
      dependencies="high,open,close,low", description="MA(20,(H-max(O,C))/(H-L))"),
    F(factor_id="cdl_lower_shadow_ratio", display_name="下影线占比均值", category="candlestick",
      group_id="cdl_agg", direction="DESC", data_origin="computed",
      compute_engine="plugin", update_freq="daily", min_periods=20,
      dependencies="low,open,close,high", description="MA(20,(min(O,C)-L)/(H-L))"),
    F(factor_id="cdl_body_ratio", display_name="实体占比均值", category="candlestick",
      group_id="cdl_agg", direction="DESC", data_origin="computed",
      compute_engine="plugin", update_freq="daily", min_periods=20,
      dependencies="close,open,high,low", description="MA(20,abs(C-O)/(H-L+0.001))"),
]
