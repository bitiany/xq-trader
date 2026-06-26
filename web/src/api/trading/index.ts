import { request } from '@/api/client'
import type { Strategy } from '@/api/strategy'
import type { OrderStatus } from '@/pages/trading/types'

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

export interface PositionSnapshot {
  id: number
  account_id: number
  instance_id: number | null
  symbol: string
  snapshot_date: string
  qty: number
  available_qty: number
  cost_price: string | number | null
  market_price: string | number | null
  market_value: string | number | null
  weight: string | number | null
  target_weight: string | number | null
  weight_deviation: string | number | null
  unrealized_pnl: string | number | null
  daily_pnl: string | number | null
  snapshot_time: string | null
  extra: Record<string, unknown> | null
}

export interface TradingOrder {
  id: number
  account_id: number | null
  instance_id: number
  pre_order_id: number | null
  symbol: string
  side: 'buy' | 'sell'
  order_type: 'limit' | 'market'
  order_price: string | number | null
  order_qty: number
  filled_price: string | number | null
  filled_qty: number
  status: OrderStatus
  broker_order_id: string | null
  reject_reason: string | null
  signal_date: string | null
  execution_date: string | null
  workflow_run_id: string | null
  created_at: string
  updated_at: string
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
  config: Record<string, unknown> & { watchlist_strategies?: WatchlistStrategyBinding[] }
  position_sizing: Record<string, unknown>
  risk_overrides: Record<string, unknown>
  universe_pool: string
  started_at: string | null
  stopped_at: string | null
  description: string
  created_at: string
  updated_at: string
}

export interface WatchlistStrategyBinding {
  strategy_id: string
  name: string
  symbols: string[]
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
  signal_strategy?: Strategy | null
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

export async function fetchAccountSnapshots(accountId: number, params?: {
  page?: number
  page_size?: number
}): Promise<PaginatedResponse<AccountSnapshot>> {
  return request.get(`/trading/accounts/${accountId}/snapshots`, { params })
}

export interface KillSwitchCancelResult {
  order_id: number
  broker_order_id: string
  cancel_result?: number
  status: 'cancel_succeeded' | 'cancel_failed'
  error?: string
}

export interface KillSwitchCloseOrderResult {
  order_id: number
  status: 'submitted' | 'submit_failed'
  result?: PreOrderExecutionResult
  error?: string
}

export interface KillSwitchResult {
  account_id: number
  reduce_only: boolean
  cancelled_orders: KillSwitchCancelResult[]
  close_orders: KillSwitchCloseOrderResult[]
}

export async function enableAccountKillSwitch(
  accountId: number,
  data: { operator: string; reason?: string },
): Promise<KillSwitchResult> {
  return request.post(`/trading/accounts/${accountId}/kill-switch`, data)
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

export async function fetchAccountDecisionWorkflowInstance(accountId: number): Promise<StrategyInstance> {
  return request.get(`/trading/accounts/${accountId}/decision-workflow/instance`)
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

export async function fetchPositions(accountId: number, params?: {
  snapshot_date?: string
}): Promise<{ items: PositionSnapshot[] }> {
  return request.get('/trading/positions', { params: { account_id: accountId, ...params } })
}

export async function fetchOrders(params: {
  account_id: number
  status?: string
  page?: number
  page_size?: number
}): Promise<PaginatedResponse<TradingOrder>> {
  return request.get('/trading/orders', { params })
}

export interface PreOrderExecutionResult {
  run: {
    run_id: string
    flow_id: string
    workspace_id: string
    status: 'running' | 'succeeded' | 'failed' | 'paused' | 'stopped'
    outputs: Record<string, unknown>
    elapsed_time: number
  }
  order: TradingOrder
  submitter: 'simulated' | 'qmt' | null
  broker_order_id: string | null
}

export interface BatchPreOrderExecutionResult {
  submitted: number
  failed: number
  items: PreOrderExecutionResult[]
  failures: { pre_order_id: number; message: string }[]
}

export async function submitPreOrder(preOrderId: number, data: { operator?: string }): Promise<PreOrderExecutionResult> {
  return request.post(`/trading/pre-orders/${preOrderId}/submit`, data)
}

export async function batchSubmitPreOrders(data: {
  pre_order_ids: number[]
  operator?: string
}): Promise<BatchPreOrderExecutionResult> {
  return request.post('/trading/pre-orders/submit/batch', data)
}

export interface RiskEventDisplay {
  level_label: string
  event_type_label: string
  reason_labels: string[]
  action_label: string | null
  summary: string
  scope: string
  reasons_text?: string
  relation_hint: string
}

export interface RiskEvent {
  id: number
  rule_id: number | null
  account_id: number | null
  instance_id: number | null
  event_type: 'blocked' | 'warning' | 'circuit_breaker' | 'kill_switch'
  level: 'info' | 'warn' | 'critical' | 'fatal'
  detail: Record<string, unknown> | null
  action_taken: string | null
  resolved: boolean
  resolved_by: string | null
  resolved_at: string | null
  created_at: string
  display?: RiskEventDisplay
}

export async function fetchRiskEvents(params?: {
  account_id?: number
  instance_id?: number
  resolved?: boolean
  level?: string
  event_type?: string
  page?: number
  page_size?: number
}): Promise<PaginatedResponse<RiskEvent>> {
  return request.get('/trading/risk-events', { params })
}

export async function resolveRiskEvent(eventId: number, data: { resolved_by?: string }): Promise<RiskEvent> {
  return request.put(`/trading/risk-events/${eventId}/resolve`, data)
}

// ---- 预订单 ----

export interface SignalDetail {
  direction: string
  confidence: number | null
  strength: number | null
  score: number | null
  reason: string | null
  strategy_id: string | null
  fused_score: number | null
  factor_values: Record<string, unknown> | null
  market_data: Record<string, unknown> | null
  entry_price_detail: Record<string, unknown> | null
}

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
  signal_detail: SignalDetail | null
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
  account_id?: number
  instance_id?: number
  status?: string
  approval_status?: string
  signal_date?: string
  page?: number
  page_size?: number
}): Promise<PaginatedResponse<PreOrder>> {
  return request.get('/trading/pre-orders', { params })
}

export interface ManualDecisionWorkflowResult {
  run: {
    run_id: string
    flow_id: string
    workspace_id: string
    status: 'running' | 'succeeded' | 'failed' | 'paused' | 'stopped'
    outputs: Record<string, unknown>
    elapsed_time: number
  }
  account_id: number
  instance_id: number
  signal_date: string
  execution_date: string
  signals_count: number
  fusion_count: number
  sizing_count: number
  pre_orders_count: number
  pre_orders: PreOrder[]
}

export async function runAccountDecisionWorkflow(accountId: number): Promise<ManualDecisionWorkflowResult> {
  return request.post(`/trading/accounts/${accountId}/decision-workflow/run`, {})
}

export async function updatePreOrder(preOrderId: number, data: {
  target_weight?: number | null
  target_qty?: number | null
  order_type?: string
  limit_price?: string | null
  approval_execution?: Record<string, unknown>
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
