import { request } from '@/api/client'

// ── 类型 ──

export interface BrokerAsset {
  account_id: string
  cash: number
  frozen_cash: number
  market_value: number
  total_asset: number
  fetch_balance: number
}

export interface BrokerPosition {
  account_id: string
  stock_code: string
  volume: number
  can_use_volume: number
  open_price: number
  market_value: number
  frozen_volume: number
  on_road_volume: number
  yesterday_volume: number
  avg_price: number
  direction: number
}

export interface BrokerOrder {
  account_id: string
  order_id: number
  stock_code: string
  order_type: number
  order_volume: number
  price_type: number
  price: number
  order_status: number
  order_remark: string
  strategy_name: string
  order_time: number
}

export interface BrokerTrade {
  account_id: string
  order_id: number
  stock_code: string
  order_type: number
  traded_volume: number
  traded_price: number
  traded_time: number
  order_remark: string
  strategy_name: string
}

export interface BrokerAccountInfo {
  account_id: string
  account_type: string
}

export interface BrokerConnectResult {
  connected: boolean
  message: string
}

// ── API ──

export const brokerApi = {
  /** 查询资金资产 */
  getAsset: () => request.get<BrokerAsset>('/broker/asset'),

  /** 查询所有持仓 */
  getPositions: () => request.get<{ positions: BrokerPosition[] }>('/broker/positions'),

  /** 查询单只持仓 */
  getPosition: (stockCode: string) => request.get<BrokerPosition>(`/broker/positions/${stockCode}`),

  /** 查询当日委托 */
  getOrders: (cancelableOnly = false) =>
    request.get<{ orders: BrokerOrder[] }>('/broker/orders', { params: { cancelable_only: cancelableOnly } }),

  /** 查询当日成交 */
  getTrades: () => request.get<{ trades: BrokerTrade[] }>('/broker/trades'),

  /** 查询所有资金账号 */
  getAccounts: () => request.get<{ accounts: BrokerAccountInfo[] }>('/broker/accounts'),

  /** 查询连接状态 */
  getStatus: () => request.get<{ connected: boolean }>('/broker/status'),

  /** 连接 QMT 交易服务 */
  connect: () => request.post<BrokerConnectResult>('/broker/connect'),

  /** 断开 QMT 交易服务 */
  disconnect: () => request.post<BrokerConnectResult>('/broker/disconnect'),
}
