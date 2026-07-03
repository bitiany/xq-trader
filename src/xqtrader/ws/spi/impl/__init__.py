"""SPI实现模块 — 导入所有SPI以触发注册"""

from .broker_status import BrokerStatusSpi  # noqa: F401
from .pnl import PnlSpi  # noqa: F401
from .stock_quote import StockQuoteSpi  # noqa: F401
from .watchlist_quotes import WatchlistQuotesSpi  # noqa: F401
