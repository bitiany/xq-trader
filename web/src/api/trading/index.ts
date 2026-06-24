import { request } from '@/api/client'

// ==================== 账户 ====================

export interface TradingAccount {
  id: number
  account_code: string
  account_name: string
  account_type: 'live' | 'paper'
  broker_type: 'qmt' | 'simulated' | 'backtest'
  broker_config: Record<string, unknown>
  initial_capital: string
  available_cash: string
  frozen_cash: string
  reduce_only: boolean
  is_enabled: boolean
  description: string
  created_at: string
  updated_at: string
}

export interface AccountSnapshot {
  id?: number
  account_id: number
  snapshot_date: string | null
  total_assets: string | number
  market_value: string | number
  available_cash: string | number
  frozen_cash: string | number
  daily_pnl: string | number
  cumulative_pnl: string | number
  daily_return: string | number
  position_count: number
  snapshot_time: string | null
}

export interface AccountCreateRequest {
  account_code: string
  account_name: string
  account_type?: 'live' | 'paper'
  broker_type?: 'qmt' | 'simulated' | 'backtest'
  broker_config?: Record<string, unknown>
  initial_capital?: string
  description?: string
}

// ==================== 策略实例 ====================

export interface StrategyInstance {
  id: number
  account_id: number
  strategy_id: number | null
  instance_name: string
  run_mode: 'live_manual' | 'live_auto' | 'paper' | 'backtest'
  status: 'draft' | 'running' | 'paused' | 'stopped'
  config: Record<string, unknown>
  position_sizing: Record<string, unknown>
  risk_overrides: Record<string, unknown>
  universe_pool: string
  started_at: string | null
  stopped_at: string | null
  description: string
  created_at: string
  updated_at: string
}

export interface InstanceCreateRequest {
  account_id: number
  strategy_id?: number | null
  instance_name: string
  run_mode?: 'live_manual' | 'live_auto' | 'paper' | 'backtest'
  config?: Record<string, unknown>
  position_sizing?: Record<string, unknown>
  risk_overrides?: Record<string, unknown>
  universe_pool?: string
  description?: string
}

export interface InstanceUpdateRequest {
  instance_name?: string
  config?: Record<string, unknown>
  position_sizing?: Record<string, unknown>
  risk_overrides?: Record<string, unknown>
  universe_pool?: string
  description?: string
}

// ==================== 自选池 ====================

export interface Watchlist {
  id: number
  account_id: number
  name: string
  description: string
  items: WatchlistItem[]
  created_at: string
  updated_at: string
}

export interface WatchlistItem {
  id: number
  watchlist_id: number
  symbol: string
  name: string
  last_price: number | null
  change_pct: number | null
  sizing_config: Record<string, unknown>
  signal_config: Record<string, unknown>
  target_weight: string | null
  sort_order: number
  is_enabled: number
  note: string
  created_at: string
  updated_at: string
}

export interface WatchlistItemCreateRequest {
  symbol: string
  sizing_config?: Record<string, unknown>
  signal_config?: Record<string, unknown>
  target_weight?: string | null
  note?: string
}

export interface WatchlistItemUpdateRequest {
  symbol?: string
  sizing_config?: Record<string, unknown>
  signal_config?: Record<string, unknown>
  target_weight?: string | number | null
  is_enabled?: number
  note?: string
}

// ==================== 分页 ====================

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ==================== API 函数 ====================

// ---- 账户 ----

export async function fetchAccounts(params?: {
  account_type?: string
  page?: number
  page_size?: number
}): Promise<PaginatedResponse<TradingAccount>> {
  return request.get('/trading/accounts', { params })
}

export async function createAccount(data: AccountCreateRequest): Promise<TradingAccount> {
  return request.post('/trading/accounts', data)
}

export async function fetchAccount(accountId: number): Promise<TradingAccount> {
  return request.get(`/trading/accounts/${accountId}`)
}

export async function fetchAccountSnapshot(accountId: number): Promise<AccountSnapshot | null> {
  return request.get(`/trading/accounts/${accountId}/snapshot`)
}

// ---- 策略实例 ----

export async function fetchInstances(params?: {
  account_id?: number
  status?: string
  run_mode?: string
  page?: number
  page_size?: number
}): Promise<PaginatedResponse<StrategyInstance>> {
  return request.get('/trading/instances', { params })
}

export async function createInstance(data: InstanceCreateRequest): Promise<StrategyInstance> {
  return request.post('/trading/instances', data)
}

export async function fetchInstance(instanceId: number): Promise<StrategyInstance> {
  return request.get(`/trading/instances/${instanceId}`)
}

export async function updateInstance(instanceId: number, data: InstanceUpdateRequest): Promise<StrategyInstance> {
  return request.put(`/trading/instances/${instanceId}`, data)
}

export async function startInstance(instanceId: number): Promise<StrategyInstance> {
  return request.post(`/trading/instances/${instanceId}/start`)
}

export async function pauseInstance(instanceId: number): Promise<StrategyInstance> {
  return request.post(`/trading/instances/${instanceId}/pause`)
}

export async function stopInstance(instanceId: number): Promise<StrategyInstance> {
  return request.post(`/trading/instances/${instanceId}/stop`)
}

// ---- 自选池 ----

export interface WatchlistResponse {
  watchlist: Watchlist | null
  items: WatchlistItem[]
}

export async function fetchWatchlist(accountId: number): Promise<WatchlistResponse> {
  return request.get(`/trading/watchlists/${accountId}`)
}

export async function addWatchlistItem(accountId: number, data: WatchlistItemCreateRequest): Promise<WatchlistItem> {
  return request.post(`/trading/watchlists/${accountId}/items`, data)
}

export async function deleteWatchlistItem(itemId: number): Promise<{ id: number; deleted: boolean }> {
  return request.delete(`/trading/watchlists/items/${itemId}`)
}

export async function updateWatchlistItem(itemId: number, data: WatchlistItemUpdateRequest): Promise<WatchlistItem> {
  return request.put(`/trading/watchlists/items/${itemId}`, data)
}

// ---- 风控规则 ----

export interface RiskRule {
  id: number
  rule_code: string
  name: string
  category: 'circuit_breaker' | 'position' | 'capital' | 'timing'
  level: 'info' | 'warn' | 'critical' | 'fatal'
  is_enabled: boolean
  params: Record<string, unknown>
  scope: string
  scope_id: number | null
  description: string
  created_at: string
  updated_at: string
}

export async function fetchRiskRules(params?: {
  category?: string
  level?: string
}): Promise<{ items: RiskRule[] }> {
  return request.get('/trading/risk-rules', { params })
}

export async function updateRiskRule(ruleId: number, data: { is_enabled: boolean }): Promise<RiskRule> {
  return request.put(`/trading/risk-rules/${ruleId}`, data)
}

// ---- 预订单 ----

export interface PreOrder {
  id: number
  instance_id: number
  workflow_run_id: string | null
  signal_date: string
  execution_date: string
  symbol: string
  side: 'open' | 'add' | 'reduce' | 'close'
  target_weight: number | null
  current_weight: number | null
  target_qty: number | null
  order_type: 'limit' | 'market'
  limit_price: string | null
  sizing_strategy: string | null
  status: string
  risk_check_passed: boolean | null
  risk_check_detail: Record<string, unknown> | null
  approval_status: 'pending' | 'approved' | 'rejected' | 'expired'
  approved_by: string | null
  approved_at: string | null
  approval_comment: string | null
  expired_at: string | null
  idempotency_key: string | null
  node_id: string | null
  created_at: string
  updated_at: string
}

export async function fetchPreOrders(params?: {
  instance_id?: number
  status?: string
  approval_status?: string
  signal_date?: string
  page?: number
  page_size?: number
}): Promise<PaginatedResponse<PreOrder>> {
  return request.get('/trading/pre-orders', { params })
}

export async function fetchPreOrder(preOrderId: number): Promise<PreOrder> {
  return request.get(`/trading/pre-orders/${preOrderId}`)
}

export async function updatePreOrder(preOrderId: number, data: {
  target_weight?: number | null
  target_qty?: number | null
  order_type?: string
  limit_price?: string | null
}): Promise<PreOrder> {
  return request.put(`/trading/pre-orders/${preOrderId}`, data)
}

// ---- 审批 ----

export async function approvePreOrder(preOrderId: number, data: {
  approved: boolean
  approved_by?: string
  comment?: string
}): Promise<PreOrder> {
  return request.post(`/trading/approval/${preOrderId}`, data)
}

export async function batchApprovePreOrders(data: {
  pre_order_ids: number[]
  approved: boolean
  approved_by?: string
  comment?: string
}): Promise<{ approved: number; rejected: number; skipped: number }> {
  return request.post('/trading/approval/batch', data)
}
