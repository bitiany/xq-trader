"""Topic常量"""


class WsTopic:
    BROKER_STATUS = "ws.broker.status"
    TRADING_PNL = "ws.trading.pnl"
    MARKET_WATCHLIST_QUOTES = "ws.market.watchlist_quotes"
    # 个股实时行情：前缀 + symbol，如 ws.market.stock_quotes.600522.SH
    MARKET_STOCK_QUOTE_PREFIX = "ws.market.stock_quotes."
    # 盘内监控
    INTRADAY_MINUTE_BAR = "ws.intraday.minute_bar"
    INTRADAY_TICK_ANOMALY = "ws.intraday.tick_anomaly"
    INTRADAY_STATUS = "ws.intraday.status"
