import type {
  Account, KpiData, PreOrder, RiskStatus, StrategyInstance,
  StockItem, WatchlistItem, Position, Order, WorkflowStep,
  RiskRule, SignalHistoryItem,
} from '../types';

export const ACCOUNTS: Account[] = [
  { value: 'live-001', label: '实盘-001 (QMT)', broker: 'QMT' },
  { value: 'live-002', label: '实盘-002 (QMT)', broker: 'QMT' },
];

export const KPI_DATA: KpiData = {
  totalAsset: 1234567.89,
  availableCash: 456789.12,
  marketValue: 778778.77,
  todayPnl: 14823.45,
  todayPnlPct: 0.0120,
  cumulativePnl: 83456.78,
  cumulativePnlPct: 0.083,
  maxDrawdownPct: -0.021,
};

export const PRE_ORDERS: PreOrder[] = [
  { id: 'po-001', symbol: '600519.SH', name: '贵州茅台', side: 'open', suggestedQty: 100, suggestedPrice: 1680, priceType: 'limit', targetWeight: 12, currentWeight: 0, sizingStrategy: 'ATR风险(14)', availableCash: 500000, reason: 'Alpha信号 Top1', signalDate: '2026-06-09', executionDate: '2026-06-10' },
  { id: 'po-002', symbol: '000858.SZ', name: '五粮液', side: 'reduce', suggestedQty: 200, suggestedPrice: 0, priceType: 'market', targetWeight: 5, currentWeight: 8, sizingStrategy: '等权降级', availableCash: 0, reason: 'Alpha衰减 Top3', signalDate: '2026-06-09', executionDate: '2026-06-10' },
  { id: 'po-003', symbol: '601318.SH', name: '中国平安', side: 'close', suggestedQty: 500, suggestedPrice: 0, priceType: 'market', targetWeight: 0, currentWeight: 6.5, sizingStrategy: '等权', availableCash: 0, reason: '止损触发', signalDate: '2026-06-09', executionDate: '2026-06-10' },
];

export const RISK_STATUS: RiskStatus = {
  circuitBreakerTriggered: false,
  todayBlocked: 0,
  activeAlerts: 1,
  activeRules: 12,
  dailyLossPct: -0.8,
  maxDrawdownPct: -2.1,
  deviationAlerts: [{ symbol: '000858.SZ', name: '五粮液', targetWeight: 5, currentWeight: 8, deviation: 3 }],
};

export const STRATEGY_INSTANCES: StrategyInstance[] = [
  { id: 'inst-001', code: 'Alpha-Rebalance-01', name: 'Alpha动态调仓', runMode: 'live', status: 'running', positionSizing: 'ATR风险(14)', cumulativePnl: 8.3, maxDrawdown: -2.1, totalCycles: 45, lastRunAt: '2026-06-09 18:00', nextRunAt: '2026-06-10 18:00', stockPool: 5, pendingApprovals: 1 },
  { id: 'inst-002', code: 'ATR-Risk-02', name: 'ATR风险定仓', runMode: 'live', status: 'running', positionSizing: '等权', cumulativePnl: 3.2, maxDrawdown: -1.5, totalCycles: 30, lastRunAt: '2026-06-09 18:00', nextRunAt: '2026-06-10 18:00', stockPool: 3, pendingApprovals: 0 },
];

export const ALL_STOCKS_POOL: StockItem[] = [
  { symbol: '600519.SH', name: '贵州茅台', lastPrice: 1756.80, changePct: 1.2, industry: '白酒', marketValue: '2.1T' },
  { symbol: '000858.SZ', name: '五粮液', lastPrice: 148.50, changePct: -5.01, industry: '白酒', marketValue: '580B' },
  { symbol: '601318.SH', name: '中国平安', lastPrice: 50.85, changePct: 2.69, industry: '保险', marketValue: '920B' },
  { symbol: '300750.SZ', name: '宁德时代', lastPrice: 215.30, changePct: 2.10, industry: '新能源', marketValue: '1.0T' },
  { symbol: '000001.SZ', name: '平安银行', lastPrice: 11.95, changePct: -6.64, industry: '银行', marketValue: '230B' },
  { symbol: '002475.SZ', name: '立讯精密', lastPrice: 38.20, changePct: 0.85, industry: '电子', marketValue: '540B' },
  { symbol: '600036.SH', name: '招商银行', lastPrice: 35.80, changePct: 1.45, industry: '银行', marketValue: '890B' },
  { symbol: '000333.SZ', name: '美的集团', lastPrice: 62.50, changePct: 0.32, industry: '家电', marketValue: '420B' },
  { symbol: '600900.SH', name: '长江电力', lastPrice: 28.30, changePct: 0.78, industry: '电力', marketValue: '690B' },
  { symbol: '002352.SZ', name: '顺丰控股', lastPrice: 42.10, changePct: -1.23, industry: '物流', marketValue: '200B' },
  { symbol: '601012.SH', name: '隆基绿能', lastPrice: 22.80, changePct: -3.15, industry: '光伏', marketValue: '170B' },
  { symbol: '000568.SZ', name: '泸州老窖', lastPrice: 168.20, changePct: 2.30, industry: '白酒', marketValue: '260B' },
];

export const INITIAL_WATCHLIST: WatchlistItem[] = [
  { symbol: '600519.SH', name: '贵州茅台', lastPrice: 1756.80, changePct: 1.2, tags: ['核心持仓', 'Alpha信号'], industry: '白酒', marketValue: '2.1T' },
  { symbol: '000858.SZ', name: '五粮液', lastPrice: 148.50, changePct: -5.01, tags: ['减仓信号'], industry: '白酒', marketValue: '580B' },
  { symbol: '601318.SH', name: '中国平安', lastPrice: 50.85, changePct: 2.69, tags: ['平仓信号'], industry: '保险', marketValue: '920B' },
  { symbol: '300750.SZ', name: '宁德时代', lastPrice: 215.30, changePct: 2.10, tags: ['持仓'], industry: '新能源', marketValue: '1.0T' },
  { symbol: '000001.SZ', name: '平安银行', lastPrice: 11.95, changePct: -6.64, tags: ['止损'], industry: '银行', marketValue: '230B' },
  { symbol: '002475.SZ', name: '立讯精密', lastPrice: 38.20, changePct: 0.85, tags: ['观察'], industry: '电子', marketValue: '540B' },
];

export const POSITIONS: Position[] = [
  { symbol: '600519.SH', name: '贵州茅台', targetWeight: 12.0, actualWeight: 11.8, deviation: -0.2, costPrice: 1680.00, lastPrice: 1756.80, pnl: 7680.00, pnlPct: 4.57, todayPnl: 1260.00 },
  { symbol: '000858.SZ', name: '五粮液', targetWeight: 5.0, actualWeight: 8.0, deviation: 3.0, costPrice: 156.30, lastPrice: 148.50, pnl: -2340.00, pnlPct: -5.01, todayPnl: -780.00 },
  { symbol: '601318.SH', name: '中国平安', targetWeight: 6.5, actualWeight: 6.5, deviation: 0.0, costPrice: 48.20, lastPrice: 50.85, pnl: 1325.00, pnlPct: 2.69, todayPnl: 325.00 },
  { symbol: '300750.SZ', name: '宁德时代', targetWeight: 5.5, actualWeight: 5.5, deviation: 0.0, costPrice: 198.50, lastPrice: 215.30, pnl: 4172.50, pnlPct: 2.10, todayPnl: 892.50 },
  { symbol: '000001.SZ', name: '平安银行', targetWeight: 3.0, actualWeight: 3.0, deviation: 0.0, costPrice: 12.80, lastPrice: 11.95, pnl: -850.00, pnlPct: -6.64, todayPnl: -340.00 },
];

export const ORDERS: Order[] = [
  { id: '20260610-001', time: '09:30:15', symbol: '600519.SH', name: '贵州茅台', side: 'buy', qty: 100, price: 1756.80, status: 'filled', strategy: 'Alpha-Rebalance-01' },
  { id: '20260610-002', time: '09:31:02', symbol: '000858.SZ', name: '五粮液', side: 'sell', qty: 200, price: 148.50, status: 'filled', strategy: 'Alpha-Rebalance-01' },
  { id: '20260610-003', time: '09:45:30', symbol: '601318.SH', name: '中国平安', side: 'buy', qty: 500, price: 50.85, status: 'partial_filled', strategy: 'ATR-Risk-02' },
];

export const DECISION_STEPS: WorkflowStep[] = [
  { title: '数据加载', status: 'finish' },
  { title: '选股', status: 'finish' },
  { title: '信号生成', status: 'finish' },
  { title: '信号融合', status: 'finish' },
  { title: '仓位管理', status: 'finish' },
  { title: '预订单', status: 'finish' },
  { title: '风控预检', status: 'finish' },
];

export const EXECUTION_STEPS: WorkflowStep[] = [
  { title: '加载审批', status: 'wait' },
  { title: '盘前风控', status: 'wait' },
  { title: '提交下单', status: 'wait' },
  { title: '成交确认', status: 'wait' },
];

export const RISK_RULES: RiskRule[] = [
  { code: 'daily_loss', name: '日亏损熔断', category: 'circuit_breaker', level: 'critical', enabled: true, params: '-2%' },
  { code: 'max_position', name: '单票仓位上限', category: 'position', level: 'warn', enabled: true, params: '10%' },
  { code: 'max_positions', name: '持仓数量上限', category: 'position', level: 'warn', enabled: true, params: '10' },
  { code: 'max_order_amount', name: '单笔金额上限', category: 'capital', level: 'warn', enabled: true, params: '50万' },
  { code: 'trading_session', name: '交易时段', category: 'timing', level: 'info', enabled: true, params: '09:30-15:00' },
  { code: 't_plus_1_sell', name: 'T+1卖出限制', category: 'capital', level: 'critical', enabled: true, params: 'available_qty' },
  { code: 'cash_sufficient', name: '现金充足检查', category: 'capital', level: 'critical', enabled: true, params: 'cash≥buy_amount' },
  { code: 'signal_ttl', name: '信号有效期', category: 'timing', level: 'warn', enabled: true, params: '5min' },
];

export const SIGNAL_HISTORY: SignalHistoryItem[] = [
  { signalDate: '2026-06-08', symbol: '600519.SH', name: '贵州茅台', direction: 'open', status: 'filled', approvedBy: '张三', result: '+2.4%' },
  { signalDate: '2026-06-07', symbol: '000858.SZ', name: '五粮液', direction: 'add', status: 'filled', approvedBy: '张三', result: '-1.4%' },
  { signalDate: '2026-06-06', symbol: '601318.SH', name: '中国平安', direction: 'open', status: 'rejected', approvedBy: '张三', result: '—' },
];

export const generateCalendarData = (): Record<number, number> => {
  const data: Record<number, number> = {};
  const pnlValues = [0.8, -0.3, 1.2, 0.5, -0.1, 0.0, 0.3, -0.5, 1.5, 0.7, -0.8, 0.2];
  for (let d = 1; d <= 12; d++) data[d] = pnlValues[d - 1];
  return data;
};
