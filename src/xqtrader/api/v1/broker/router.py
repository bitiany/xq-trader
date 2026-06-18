"""QMT 券商代理服务 API 路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from framework.commons.exceptions import BusinessException
from xqtrader.broker.services.qmt_callback_handler import QmtCallbackHandler
from xqtrader.broker.services.qmt_connection import QmtConnection
from xqtrader.broker.services.qmt_data_collector import QmtDataCollector
from xqtrader.broker.services.qmt_trader import QmtTrader

router = APIRouter(prefix="/broker", tags=["券商代理"])

_connection = QmtConnection.get_instance()
_data_collector = QmtDataCollector()
_trader = QmtTrader()
_callback_handler = QmtCallbackHandler()


# ── 连接管理 ──────────────────────────────────────────────


@router.post("/connect", summary="连接 QMT 交易服务")
async def connect_trader() -> dict:
    """连接 MiniQMT 交易服务，注册回调并订阅账号。"""
    result = await _connection.connect_async()
    if result != 0:
        raise BusinessException(f"QMT 交易连接失败: result={result}")

    _connection.trader.register_callback(_callback_handler)
    await _trader.subscribe_account()

    return {"connected": True, "message": "QMT 交易连接成功"}


@router.post("/disconnect", summary="断开 QMT 交易服务")
async def disconnect_trader() -> dict:
    """断开 MiniQMT 交易服务。"""
    await _connection.disconnect_async()
    return {"connected": False, "message": "QMT 交易连接已断开"}


@router.post("/reconnect", summary="重连 QMT 交易服务")
async def reconnect_trader() -> dict:
    """重新连接 MiniQMT 交易服务。"""
    result = await _connection.reconnect_async()
    if result != 0:
        raise BusinessException(f"QMT 交易重连失败: result={result}")

    _connection.trader.register_callback(_callback_handler)
    await _trader.subscribe_account()

    return {"connected": True, "message": "QMT 交易重连成功"}


@router.get("/status", summary="查询连接状态")
async def get_connection_status() -> dict:
    """查询 QMT 交易连接状态。"""
    return {"connected": _connection.is_connected}


# ── 数据采集 ──────────────────────────────────────────────


@router.post("/data/connect", summary="连接行情服务")
async def connect_data() -> dict:
    """连接 MiniQMT 行情服务。"""
    await _data_collector.connect()
    return {"message": "行情服务连接完成"}


@router.post("/data/disconnect", summary="断开行情服务")
async def disconnect_data() -> dict:
    """断开行情服务。"""
    await _data_collector.disconnect()
    return {"message": "行情服务已断开"}


@router.get("/data/daily-kline", summary="获取日线行情")
async def fetch_daily_kline(
    stock_list: str = Query(..., description="证券代码，逗号分隔，如 600000.SH 或 600000.SH,000001.SZ"),
    start_time: str = Query(default="", description="起始日期 YYYYMMDD"),
    end_time: str = Query(default="", description="结束日期 YYYYMMDD"),
    dividend_type: str = Query(default="front", description="复权: none/front/back/front_ratio/back_ratio"),
) -> dict:
    """获取日线行情数据（先下载补缓存，再获取）。

    支持单支和批量，stock_list 传逗号分隔的证券代码。
    返回 {stock_code: {count, columns, data}} 格式，每只股票包含
    trade_date/open/close/high/low/volume/amount/change/pre_close/pct_chg 列。
    """
    codes = [s.strip() for s in stock_list.split(",") if s.strip()]
    if not codes:
        raise BusinessException("stock_list 不能为空")

    raw = await _data_collector.fetch_kline_daily(
        stock_list=codes,
        start_time=start_time,
        end_time=end_time,
        dividend_type=dividend_type,
    )

    result: dict[str, Any] = {}
    for code, df in raw.items():
        if df.empty:
            result[code] = {"count": 0, "columns": [], "data": []}
        else:
            result[code] = {
                "count": len(df),
                "columns": list(df.columns),
                "data": df.values.tolist(),
            }

    return {"stock_list": codes, "data": result}


@router.get("/data/tick", summary="获取全推Tick数据")
async def get_full_tick(
    code_list: str = Query(..., description="证券代码，逗号分隔"),
) -> dict:
    """获取全推 Tick 数据（最新分笔）。"""
    codes = [s.strip() for s in code_list.split(",") if s.strip()]
    if not codes:
        raise BusinessException("code_list 不能为空")

    data = await _data_collector.get_full_tick(codes)
    return {"data": {code: str(val) for code, val in data.items()}}


@router.get("/data/financial", summary="获取财务数据")
async def fetch_financial_data(
    stock_list: str = Query(..., description="证券代码，逗号分隔"),
    table_list: str = Query(default="", description="报表名，逗号分隔，如 Balance,Income,CashFlow"),
    start_time: str = Query(default="", description="起始时间"),
    end_time: str = Query(default="", description="结束时间"),
) -> dict:
    """获取财务数据。

    返回格式: {stock_code: {table_name: {count, columns, data}}}
    """
    codes = [s.strip() for s in stock_list.split(",") if s.strip()]
    tables = [s.strip() for s in table_list.split(",") if s.strip()] or None
    if not codes:
        raise BusinessException("stock_list 不能为空")

    raw = await _data_collector.fetch_financial_data(
        stock_list=codes,
        table_list=tables,
        start_time=start_time,
        end_time=end_time,
    )

    result: dict[str, Any] = {}
    for code, tables_data in raw.items():
        if not tables_data:
            result[code] = {}
            continue
        tables_result: dict[str, Any] = {}
        for tbl_name, df in tables_data.items():
            tables_result[tbl_name] = {
                "count": len(df),
                "columns": list(df.columns),
                "data": df.values.tolist(),
            }
        result[code] = tables_result

    return {"data": result}


@router.get("/data/instrument", summary="获取合约信息")
async def get_instrument_detail(
    stock_code: str = Query(..., description="证券代码"),
) -> dict:
    """获取合约基础信息。"""
    data = await _data_collector.get_instrument_detail(stock_code)
    if data is None:
        raise BusinessException(f"合约信息不存在: {stock_code}")
    return {"data": data}


@router.get("/data/trading-dates", summary="获取交易日列表")
async def get_trading_dates(
    market: str = Query(default="SH", description="市场: SH/SZ"),
    start_time: str = Query(default="", description="起始时间"),
    end_time: str = Query(default="", description="结束时间"),
) -> dict:
    """获取交易日列表。"""
    dates = await _data_collector.get_trading_dates(market, start_time, end_time)
    return {"market": market, "dates": dates}


@router.get("/data/sectors", summary="获取板块列表")
async def get_sector_list() -> dict:
    """获取板块列表。"""
    sectors = await _data_collector.get_sector_list()
    return {"sectors": sectors}


@router.get("/data/sector-stocks", summary="获取板块成分股")
async def get_sector_stocks(
    sector_name: str = Query(..., description="板块名称"),
) -> dict:
    """获取板块成分股。"""
    stocks = await _data_collector.get_stock_list_in_sector(sector_name)
    return {"sector_name": sector_name, "stocks": stocks}


# ── 交易操作 ──────────────────────────────────────────────


@router.post("/order", summary="下单")
async def order_stock(
    stock_code: str = Query(..., description="证券代码，如 600000.SH"),
    order_type: int = Query(..., description="委托类型: 23=买入, 24=卖出"),
    order_volume: int = Query(..., description="委托数量"),
    price_type: int = Query(default=11, description="报价类型: 11=限价, 5=最新价"),
    price: float = Query(default=0, description="委托价格，限价时为具体价格"),
    strategy_name: str = Query(default="", description="策略名称"),
    order_remark: str = Query(default="", description="委托备注"),
) -> dict:
    """同步下单。"""
    order_id = await _trader.order_stock(
        stock_code=stock_code,
        order_type=order_type,
        order_volume=order_volume,
        price_type=price_type,
        price=price,
        strategy_name=strategy_name,
        order_remark=order_remark,
    )
    return {"order_id": order_id, "message": "下单成功"}


@router.post("/order/async", summary="异步下单")
async def order_stock_async(
    stock_code: str = Query(..., description="证券代码"),
    order_type: int = Query(..., description="委托类型: 23=买入, 24=卖出"),
    order_volume: int = Query(..., description="委托数量"),
    price_type: int = Query(default=11, description="报价类型: 11=限价, 5=最新价"),
    price: float = Query(default=0, description="委托价格"),
    strategy_name: str = Query(default="", description="策略名称"),
    order_remark: str = Query(default="", description="委托备注"),
) -> dict:
    """异步下单，回报通过回调推送。"""
    seq = await _trader.order_stock_async(
        stock_code=stock_code,
        order_type=order_type,
        order_volume=order_volume,
        price_type=price_type,
        price=price,
        strategy_name=strategy_name,
        order_remark=order_remark,
    )
    return {"seq": seq, "message": "异步下单已提交"}


@router.post("/cancel", summary="撤单")
async def cancel_order(
    order_id: int = Query(..., description="委托编号"),
) -> dict:
    """同步撤单。"""
    result = await _trader.cancel_order(order_id)
    return {"order_id": order_id, "result": result, "message": "撤单成功"}


@router.post("/cancel/async", summary="异步撤单")
async def cancel_order_async(
    order_id: int = Query(..., description="委托编号"),
) -> dict:
    """异步撤单，回报通过回调推送。"""
    seq = await _trader.cancel_order_async(order_id)
    return {"order_id": order_id, "seq": seq, "message": "异步撤单已提交"}


# ── 查询 ──────────────────────────────────────────────────


@router.get("/asset", summary="查询资金资产", operation_id="get_broker_asset")
async def query_asset() -> dict:
    """查询当前账户资金资产。"""
    return await _trader.query_asset()


@router.get("/orders", summary="查询当日委托", operation_id="list_broker_orders")
async def query_orders(
    cancelable_only: bool = Query(default=False, description="是否仅查询可撤委托"),
) -> dict:
    """查询当日委托列表。"""
    orders = await _trader.query_orders(cancelable_only=cancelable_only)
    return {"orders": orders}


@router.get("/orders/{order_id}", summary="查询单笔委托")
async def query_order(order_id: int) -> dict:
    """查询单笔委托详情。"""
    order = await _trader.query_order(order_id)
    if order is None:
        raise BusinessException(f"委托不存在: {order_id}")
    return order


@router.get("/trades", summary="查询当日成交", operation_id="list_broker_trades")
async def query_trades() -> dict:
    """查询当日成交列表。"""
    trades = await _trader.query_trades()
    return {"trades": trades}


@router.get("/positions", summary="查询所有持仓", operation_id="list_broker_positions")
async def query_positions() -> dict:
    """查询所有持仓。"""
    positions = await _trader.query_positions()
    return {"positions": positions}


@router.get("/positions/{stock_code}", summary="查询单只股票持仓", operation_id="get_broker_position")
async def query_position(stock_code: str) -> dict:
    """查询单只股票持仓。"""
    position = await _trader.query_position(stock_code)
    if position is None:
        raise BusinessException(f"持仓不存在: {stock_code}")
    return position


@router.get("/accounts", summary="查询所有资金账号")
async def query_account_infos() -> dict:
    """查询所有资金账号。"""
    accounts = await _trader.query_account_infos()
    return {"accounts": accounts}
