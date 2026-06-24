// ── Topic 常量（与后端 WsTopic 对齐） ──
export const TOPIC_BROKER_STATUS = 'ws.broker.status'
export const TOPIC_TRADING_PNL = 'ws.trading.pnl'
export const TOPIC_MARKET_WATCHLIST_QUOTES = 'ws.market.watchlist_quotes'

// ── WS 数据类型 ──
export interface BrokerStatusData {
  market_status: 'connected' | 'disconnected'
  trading_status: 'connected' | 'disconnected'
  timestamp: number
}

export interface TradingPnlItem {
  account_id?: number
  broker_type?: string
  cash: number
  frozen_cash: number
  market_value: number
  total_asset: number
  today_pnl: number
  today_pnl_pct: number
}

export interface TradingPnlData {
  items?: TradingPnlItem[]
  account_id?: number
  cash?: number
  frozen_cash?: number
  market_value?: number
  total_asset?: number
  today_pnl?: number
  today_pnl_pct?: number
  reason?: string
  timestamp: number
}

export interface WatchlistQuoteItem {
  symbol: string
  last_price: number | null
  change_pct: number | null
  account_id?: number
  timestamp: number
}

export interface WatchlistQuotesData {
  items: WatchlistQuoteItem[]
  timestamp: number
  reason?: string
}

// ── WS 连接 ──
export function getWebSocketUrl(): string {
  if (import.meta.env.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws`
}

// ── Ticket 认证 ──
export async function fetchTicket(signal?: AbortSignal): Promise<string> {
  const resp = await fetch('/api/v1/ws/ticket', { method: 'POST', signal })
  if (!resp.ok) {
    throw new Error(`Failed to fetch WS ticket: ${resp.status}`)
  }
  const json = await resp.json()
  const ticket = json.data?.ticket ?? json.ticket
  if (typeof ticket !== 'string' || !ticket) {
    throw new Error('Invalid ticket response')
  }
  return ticket
}

// ── 消息协议 ──
export type WsServerMessageType = 'SNAPSHOT' | 'UPDATE' | 'ACK' | 'PING' | 'PONG' | 'ERROR' | 'RESULT'

export interface WsServerMessage<T = unknown> {
  type: WsServerMessageType
  channel?: string
  data?: T
  id?: number | string
  code?: string
  message?: string
}

export interface WsClientMessage {
  method: 'SUBSCRIBE' | 'UNSUBSCRIBE' | 'PING' | 'LIST_SUBSCRIPTIONS'
  params?: string[]
  id?: number
}
