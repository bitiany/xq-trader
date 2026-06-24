import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { Card, Table, Tag, Button, Space, message } from 'antd';
import { Star, Search, Plus, Trash2, Cpu, Settings, X } from 'lucide-react';
import { INSTANCE_STATUS_COLOR, INSTANCE_STATUS_LABEL, RUN_MODE_LABEL, POSITION_SIZING_OPTIONS } from '../utils/trading';
import { PositionSizingConfigDrawer } from './PositionSizingConfigDrawer';
import {
  fetchInstances,
  fetchWatchlist,
  addWatchlistItem,
  deleteWatchlistItem,
  startInstance,
  pauseInstance,
  stopInstance,
  type StrategyInstance,
  type WatchlistItem as ApiWatchlistItem,
} from '@/api/trading';
import { searchStocks, type StockSearchItem } from '@/api/stock';
import { usePageWebSocket } from '@/ws/usePageWebSocket';
import { TOPIC_MARKET_WATCHLIST_QUOTES, type WatchlistQuotesData } from '@/ws/protocol';

interface WatchlistStrategyTabProps {
  accountId: number | null;
}

export function WatchlistStrategyTab({ accountId }: WatchlistStrategyTabProps) {
  const [watchlistItems, setWatchlistItems] = useState<ApiWatchlistItem[]>([]);
  const [instances, setInstances] = useState<StrategyInstance[]>([]);
  const [searchText, setSearchText] = useState('');
  const [searchResults, setSearchResults] = useState<StockSearchItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [sizingDrawerOpen, setSizingDrawerOpen] = useState(false);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 加载当前账户下的策略实例
  useEffect(() => {
    if (accountId === null) {
      setInstances([]);
      return;
    }
    let cancelled = false;
    fetchInstances({ account_id: accountId, page_size: 200 }).then((res) => {
      if (!cancelled) {
        setInstances(res.items);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [accountId]);

  // 加载当前账户的自选池
  const loadWatchlist = useCallback(async () => {
    if (accountId === null) return;
    try {
      const res = await fetchWatchlist(accountId);
      setWatchlistItems(res.items ?? []);
    } catch {
      setWatchlistItems([]);
    }
  }, [accountId]);

  useEffect(() => { loadWatchlist(); }, [loadWatchlist]);

  const handleQuotesUpdate = useCallback((_channel: string, data: WatchlistQuotesData) => {
    if (!data?.items?.length || accountId === null) return;
    // 只处理当前账户的行情数据
    const quoteMap = new Map(
      data.items
        .filter(item => item.account_id === accountId || item.account_id === undefined)
        .map(item => [item.symbol, item]),
    );
    if (quoteMap.size === 0) return;
    setWatchlistItems(prev => prev.map(item => {
      const quote = quoteMap.get(item.symbol);
      if (!quote) return item;
      return {
        ...item,
        last_price: quote.last_price ?? item.last_price,
        change_pct: quote.change_pct ?? item.change_pct,
      };
    }));
  }, [accountId]);

  usePageWebSocket<WatchlistQuotesData>({
    topics: [TOPIC_MARKET_WATCHLIST_QUOTES],
    enabled: accountId !== null,
    onSnapshot: handleQuotesUpdate,
    onUpdate: handleQuotesUpdate,
  });

  // 已在自选池中的 symbol 集合
  const existingSymbols = useMemo(
    () => new Set(watchlistItems.map(w => w.symbol)),
    [watchlistItems],
  );

  // 搜索标的 — 防抖调用后端 API
  useEffect(() => {
    if (!searchText.trim()) {
      setSearchResults([]);
      return;
    }
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await searchStocks(searchText.trim(), 10);
        setSearchResults(results.filter(s => !existingSymbols.has(s.symbol)));
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [searchText, existingSymbols]);

  const handleAddToWatchlist = useCallback(async (stock: StockSearchItem) => {
    if (accountId === null) {
      message.warning('请先选择账户');
      return;
    }
    try {
      await addWatchlistItem(accountId, { symbol: stock.symbol });
      setSearchText('');
      setSearchResults([]);
      await loadWatchlist();
      message.success(`已添加 ${stock.name}`);
    } catch {
      message.error('添加失败');
    }
  }, [accountId, loadWatchlist]);

  const handleRemoveFromWatchlist = useCallback(async (itemId: number, symbol: string) => {
    try {
      await deleteWatchlistItem(itemId);
      setWatchlistItems(prev => prev.filter(w => w.id !== itemId));
    } catch {
      message.error(`删除 ${symbol} 失败`);
    }
  }, []);

  const handleInstanceAction = useCallback(async (instanceId: number, action: 'start' | 'pause' | 'stop') => {
    try {
      const fn = action === 'start' ? startInstance : action === 'pause' ? pauseInstance : stopInstance;
      const updated = await fn(instanceId);
      setInstances(prev => prev.map(inst => inst.id === instanceId ? updated : inst));
    } catch {
      message.error(`${action} 失败`);
    }
  }, []);

  const formatPrice = (v: number | null) => {
    if (v === null || v === undefined) return '—';
    return v.toFixed(2);
  };

  const formatChangePct = (v: number | null) => {
    if (v === null || v === undefined) return '—';
    const sign = v > 0 ? '+' : '';
    return `${sign}${v.toFixed(2)}%`;
  };

  const getChangeColor = (v: number | null) => {
    if (v === null || v === undefined) return 'var(--text-secondary)';
    return v > 0 ? 'var(--color-rise)' : v < 0 ? 'var(--color-fall)' : 'var(--text-secondary)';
  };

  const getSizingLabel = (config: Record<string, unknown>) => {
    const strategy = config?.strategy as string | undefined;
    if (!strategy) return '—';
    const found = POSITION_SIZING_OPTIONS.find(o => o.value === strategy);
    return found ? found.label : strategy;
  };

  const wlColumns = [
    {
      title: '代码', dataIndex: 'symbol', width: 90,
      render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v}</span>,
    },
    {
      title: '名称', dataIndex: 'name', width: 80,
      render: (v: string) => <span>{v || '—'}</span>,
    },
    {
      title: '最新价', dataIndex: 'last_price', width: 70,
      render: (v: number | null) => <span style={{ fontFamily: 'var(--font-mono)' }}>{formatPrice(v)}</span>,
    },
    {
      title: '涨跌幅', dataIndex: 'change_pct', width: 70,
      render: (v: number | null) => (
        <span style={{ fontFamily: 'var(--font-mono)', color: getChangeColor(v) }}>{formatChangePct(v)}</span>
      ),
    },
    {
      title: '权重', dataIndex: 'target_weight', width: 55,
      render: (v: string | null) => <span style={{ fontFamily: 'var(--font-mono)' }}>{v ? `${v}%` : '—'}</span>,
    },
    {
      title: '策略', dataIndex: 'sizing_config', width: 70,
      render: (v: Record<string, unknown>) => <span style={{ fontSize: 11 }}>{getSizingLabel(v)}</span>,
    },
    {
      title: '', width: 40,
      render: (_: unknown, row: ApiWatchlistItem) => (
        <Button size="small" type="link" style={{ padding: 0, color: 'var(--color-fall)' }} onClick={() => handleRemoveFromWatchlist(row.id, row.symbol)}>
          <Trash2 size={11} style={{ verticalAlign: 'middle' }} />
        </Button>
      ),
    },
  ];

  // 传给 PositionSizingConfigDrawer 的简化数据
  const drawerWatchlist = useMemo(
    () => watchlistItems.map(w => ({ symbol: w.symbol, name: w.name || w.symbol })),
    [watchlistItems],
  );

  return (
    <div className="ws-tab" data-component="Watchlist & Strategy Tab">
      <div className="ws-tab__panels">
        <div className="ws-tab__panel ws-tab__panel--left">
          <div className="ws-tab__panel-header">
            <div className="ws-tab__panel-title">
              <Star size={14} style={{ color: 'var(--accent-primary)' }} />
              <span>自选股池</span>
              <span className="ws-tab__panel-count">{watchlistItems.length}只</span>
            </div>
            <div className="ws-tab__panel-search">
              <div className="watchlist-search-inline">
                <div className="watchlist-search-inline__input-wrap">
                  <Search size={12} className="watchlist-search-inline__icon" />
                  <input
                    className="watchlist-search-inline__input"
                    placeholder={accountId ? '搜索代码/名称/拼音添加...' : '请先选择账户'}
                    value={searchText}
                    onChange={e => setSearchText(e.target.value)}
                    disabled={accountId === null}
                  />
                  {searchText && (
                    <button className="watchlist-search-inline__clear" onClick={() => { setSearchText(''); setSearchResults([]); }}>
                      <X size={12} />
                    </button>
                  )}
                </div>
                {searchResults.length > 0 && (
                  <div className="watchlist-search-results">
                    {searchResults.map(s => (
                      <div key={s.symbol} className="watchlist-search-result-item" onClick={() => handleAddToWatchlist(s)}>
                        <span className="watchlist-search-result-item__symbol">{s.symbol}</span>
                        <span className="watchlist-search-result-item__name">{s.name}</span>
                        <span className="watchlist-search-result-item__industry">{s.industry}</span>
                        <Plus size={14} style={{ color: 'var(--accent-primary)', marginLeft: 'auto' }} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
          <Table dataSource={watchlistItems} columns={wlColumns} rowKey="id" size="small" pagination={false} scroll={{ y: 260 }} />
        </div>

        <div className="ws-tab__panel ws-tab__panel--right">
          <div className="ws-tab__panel-header">
            <div className="ws-tab__panel-title">
              <Cpu size={14} style={{ color: 'var(--accent-primary)' }} />
              <span>策略实例</span>
            </div>
            <Button size="small" icon={<Settings size={12} />} onClick={() => setSizingDrawerOpen(true)}>仓位配置</Button>
          </div>
          <div className="strategy-instance-cards">
            {instances.map(inst => (
              <Card key={inst.id} size="small" className="strategy-card" data-component="Strategy Instance Card">
                <div className="strategy-card__header">
                  <div className="strategy-card__identity">
                    <span className="strategy-card__code">{inst.instance_name}</span>
                  </div>
                  <Space size={4}>
                    <Tag color={INSTANCE_STATUS_COLOR[inst.status]}>{INSTANCE_STATUS_LABEL[inst.status]}</Tag>
                    <Tag color="blue">{RUN_MODE_LABEL[inst.run_mode]}</Tag>
                  </Space>
                </div>
                <div className="strategy-card__metrics">
                  <div className="strategy-card__metric"><span>股票池</span><span>{inst.universe_pool || '—'}</span></div>
                </div>
                <div className="strategy-card__actions">
                  {inst.status === 'draft' || inst.status === 'stopped' ? (
                    <Button size="small" onClick={() => handleInstanceAction(inst.id, 'start')}>启动</Button>
                  ) : inst.status === 'running' ? (
                    <>
                      <Button size="small" onClick={() => handleInstanceAction(inst.id, 'pause')}>暂停</Button>
                      <Button size="small" onClick={() => handleInstanceAction(inst.id, 'stop')}>停止</Button>
                    </>
                  ) : inst.status === 'paused' ? (
                    <>
                      <Button size="small" onClick={() => handleInstanceAction(inst.id, 'start')}>恢复</Button>
                      <Button size="small" onClick={() => handleInstanceAction(inst.id, 'stop')}>停止</Button>
                    </>
                  ) : null}
                </div>
              </Card>
            ))}
            {instances.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 20, fontSize: 12 }}>
                暂无策略实例
              </div>
            )}
          </div>
        </div>
      </div>
      <PositionSizingConfigDrawer open={sizingDrawerOpen} onClose={() => setSizingDrawerOpen(false)} watchlist={drawerWatchlist} />
    </div>
  );
}
