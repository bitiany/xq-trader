import type { ConnectionStatus, SignalItem, StrategyInstanceItem } from '@/api/trading'

// ── Topic 常量 ──
export const TOPIC_MARKET_INDEX_MAJOR = 'market.index.major'
export const TOPIC_TRADING_ACCOUNT_SUMMARY = 'trading.account.summary'
export const TOPIC_TRADING_POSITIONS = 'trading.positions'
export const TOPIC_TRADING_CONNECTION = 'trading.connection'
export const TOPIC_TRADING_SIGNALS = 'trading.signals'
export const TOPIC_TRADING_STRATEGY_INSTANCES = 'trading.strategy.instances'
export const TOPIC_STOCK_QUOTE_PREFIX = 'market.stock.'

// ── WS 数据类型（与 API 类型对齐） ──
export type ConnectionStatusData = ConnectionStatus
export type SignalData = SignalItem
export type StrategyInstanceData = StrategyInstanceItem

// ── WS 连接 ──
export function getWebSocketUrl(): string {
  if (import.meta.env.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws`
}

// ── 消息协议 ──
export type WsServerMessageType = 'SNAPSHOT' | 'UPDATE' | 'ACK' | 'ERROR' | 'PONG' | 'RESULT'

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
