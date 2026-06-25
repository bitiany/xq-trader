import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { Card, Table, Tag, Button, Space, message, Modal, Form, Input, InputNumber, Select } from 'antd';
import { Star, Search, Plus, Trash2, Cpu, Settings, X, Edit2 } from 'lucide-react';
import { INSTANCE_STATUS_COLOR, INSTANCE_STATUS_LABEL, RUN_MODE_LABEL } from '../utils/trading';
import { PositionSizingConfigDrawer } from './PositionSizingConfigDrawer';
import {
  fetchAccount,
  fetchInstances,
  fetchWatchlist,
  addWatchlistItem,
  deleteWatchlistItem,
  updateWatchlistItem,
  startInstance,
  type StrategyInstance,
  type TradingAccount,
  type WatchlistItem as ApiWatchlistItem,
} from '@/api/trading';
import { searchStocks, type StockSearchItem } from '@/api/stock';
import { fetchStrategies, type Strategy } from '@/api/strategy';
import { extractPageItems } from '@/api/types';
import { usePageWebSocket } from '@/ws/usePageWebSocket';
import { TOPIC_MARKET_WATCHLIST_QUOTES, type WatchlistQuotesData } from '@/ws/protocol';

interface WatchlistStrategyTabProps {
  accountId: number | null;
}

export function WatchlistStrategyTab({ accountId }: WatchlistStrategyTabProps) {
  const [watchlistItems, setWatchlistItems] = useState<ApiWatchlistItem[]>([]);
  const [instances, setInstances] = useState<StrategyInstance[]>([]);
  const [account, setAccount] = useState<TradingAccount | null>(null);
  const [timingStrategies, setTimingStrategies] = useState<Strategy[]>([]);
  const [searchText, setSearchText] = useState('');
  const [searchResults, setSearchResults] = useState<StockSearchItem[]>([]);
  const [sizingDrawerOpen, setSizingDrawerOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<ApiWatchlistItem | null>(null);
  const [editForm] = Form.useForm();
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setAccount(null);
        return undefined;
      }
      return fetchAccount(accountId).then((res) => {
        if (!cancelled) setAccount(res);
      }).catch(() => {
        if (!cancelled) setAccount(null);
      });
    });
    return () => { cancelled = true; };
  }, [accountId]);

  const loadInstances = useCallback(async () => {
    if (accountId === null) {
      setInstances([]);
      return;
    }
    try {
      const res = await fetchInstances({ account_id: accountId, page_size: 200 });
      setInstances(res.items);
    } catch {
      setInstances([]);
    }
  }, [accountId]);

  // 加载当前账户下的策略实例
  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(async () => {
      if (cancelled) return;
      await loadInstances();
    });
    return () => { cancelled = true; };
  }, [loadInstances]);

  // 加载可用于实盘监控的时序交易信号策略
  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      return fetchStrategies({ status: 'active', strategy_type: 'timing', page_size: 500 }).then((res) => {
        if (!cancelled) {
          setTimingStrategies(extractPageItems<Strategy>(res));
        }
      }).catch(() => {
        if (!cancelled) {
          setTimingStrategies([]);
        }
      });
    });
    return () => { cancelled = true; };
  }, []);

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

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (accountId === null) {
        setWatchlistItems([]);
        return undefined;
      }
      return fetchWatchlist(accountId).then((res) => {
        if (!cancelled) setWatchlistItems(res.items ?? []);
      }).catch(() => {
        if (!cancelled) message.error('自选池加载失败');
      });
    });
    return () => { cancelled = true; };
  }, [accountId]);

  const handleQuotesUpdate = useCallback((_channel: string, data: WatchlistQuotesData) => {
    if (!data?.items?.length || accountId === null) return;
    // 只处理当前账户的行情数据
    const quoteMap = new Map(
      data.items
        .filter(item => item.account_id === accountId)
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
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!searchText.trim()) {
        setSearchResults([]);
        return undefined;
      }
      if (searchTimer.current) clearTimeout(searchTimer.current);
      searchTimer.current = setTimeout(async () => {
        try {
          const results = await searchStocks(searchText.trim(), 10);
          if (!cancelled) setSearchResults(results.filter(s => !existingSymbols.has(s.symbol)));
        } catch {
          if (!cancelled) message.error('标的搜索失败');
        }
      }, 300);
      return undefined;
    });
    return () => {
      cancelled = true;
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
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
      await loadInstances();
      message.success(`已添加 ${stock.name}`);
    } catch {
      message.error('添加失败');
    }
  }, [accountId, loadInstances, loadWatchlist]);

  const handleRemoveFromWatchlist = useCallback(async (itemId: number, symbol: string) => {
    try {
      await deleteWatchlistItem(itemId);
      setWatchlistItems(prev => prev.filter(w => w.id !== itemId));
      await loadInstances();
    } catch {
      message.error(`删除 ${symbol} 失败`);
    }
  }, [loadInstances]);

  const handleEditWatchlistItem = useCallback((item: ApiWatchlistItem) => {
    setEditingItem(item);
    editForm.setFieldsValue({
      symbol: item.symbol,
      target_weight: item.target_weight === null ? null : Number(item.target_weight),
      strategy_id: typeof item.signal_config?.strategy_id === 'string' ? item.signal_config.strategy_id : undefined,
      note: item.note ?? '',
    });
  }, [editForm]);

  const handleSaveWatchlistItem = useCallback(async () => {
    if (!editingItem) return;
    const values = await editForm.validateFields();
    const signalConfig = {
      ...(editingItem.signal_config ?? {}),
      strategy_id: values.strategy_id,
    };
    const updated = await updateWatchlistItem(editingItem.id, {
      symbol: values.symbol.trim().toUpperCase(),
      target_weight: values.target_weight ?? null,
      signal_config: signalConfig,
      note: values.note ?? '',
    });
    setWatchlistItems(prev => prev.map(item => item.id === updated.id ? { ...item, ...updated } : item));
    await loadWatchlist();
    await loadInstances();
    setEditingItem(null);
    message.success('自选股配置已保存');
  }, [editForm, editingItem, loadInstances, loadWatchlist]);

  const handleInstanceAction = useCallback(async (instanceId: number, action: 'start') => {
    try {
      const updated = await startInstance(instanceId);
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

  const getSignalStrategyLabel = (item: ApiWatchlistItem) => {
    if (item.signal_strategy?.name) return item.signal_strategy.name;
    const strategyId = item.signal_config?.strategy_id;
    if (typeof strategyId !== 'string') return '未绑定';
    const found = timingStrategies.find(s => s.strategy_id === strategyId);
    return found?.name ?? strategyId;
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
      title: '信号策略', dataIndex: 'signal_config', width: 120,
      render: (_: Record<string, unknown>, row: ApiWatchlistItem) => <span style={{ fontSize: 11 }}>{getSignalStrategyLabel(row)}</span>,
    },
    {
      title: '', width: 70,
      render: (_: unknown, row: ApiWatchlistItem) => (
        <Space size={4}>
          <Button size="small" type="link" style={{ padding: 0 }} onClick={() => handleEditWatchlistItem(row)}>
            <Edit2 size={11} style={{ verticalAlign: 'middle' }} />
          </Button>
          <Button size="small" type="link" style={{ padding: 0, color: 'var(--color-fall)' }} onClick={() => handleRemoveFromWatchlist(row.id, row.symbol)}>
            <Trash2 size={11} style={{ verticalAlign: 'middle' }} />
          </Button>
        </Space>
      ),
    },
  ];

  // 传给 PositionSizingConfigDrawer 的简化数据
  const drawerWatchlist = useMemo(
    () => watchlistItems.map(w => ({ symbol: w.symbol, name: w.name || w.symbol })),
    [watchlistItems],
  );

  const visibleInstances = useMemo(
    () => instances.filter(inst => {
      if (inst.account_id !== accountId) return false;
      if (account?.account_type === 'paper') return inst.run_mode === 'paper';
      if (account?.account_type === 'live') return inst.run_mode === 'live_manual' || inst.run_mode === 'live_auto';
      return false;
    }),
    [account?.account_type, accountId, instances],
  );

  // 每个实例关联的自选股中已配置的策略清单
  const configuredStrategiesMap = useMemo(() => {
    const map = new Map<number, { name: string; symbols: string[] }[]>();
    for (const inst of visibleInstances) {
      const configured = inst.config?.watchlist_strategies;
      if (Array.isArray(configured)) {
        map.set(inst.id, configured.map(item => ({ name: item.name, symbols: item.symbols })));
        continue;
      }
      const strategyIds = new Set<string>();
      for (const item of watchlistItems) {
        const sid = item.signal_config?.strategy_id;
        if (typeof sid === 'string') {
          strategyIds.add(sid);
        }
      }
      const names: { name: string; symbols: string[] }[] = [];
      for (const sid of strategyIds) {
        const found = timingStrategies.find(s => s.strategy_id === sid);
        names.push({
          name: found?.name ?? sid,
          symbols: watchlistItems
            .filter(item => item.signal_config?.strategy_id === sid)
            .map(item => item.symbol),
        });
      }
      map.set(inst.id, names);
    }
    return map;
  }, [visibleInstances, watchlistItems, timingStrategies]);

  // 当前用于仓位配置的实例（优先取 running 状态的第一个）
  const activeInstance = useMemo(
    () => visibleInstances.find(i => i.status === 'running') ?? visibleInstances[0] ?? null,
    [visibleInstances],
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
            {visibleInstances.map(inst => (
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
                <div className="strategy-card__strategies">
                  <span className="strategy-card__strategies-label">已配置策略</span>
                  {configuredStrategiesMap.get(inst.id)?.length ? (
                    <div className="strategy-card__strategies-tags">
                      {configuredStrategiesMap.get(inst.id)!.map(strategy => (
                        <Tag key={strategy.name}>{strategy.name}({strategy.symbols.length})</Tag>
                      ))}
                    </div>
                  ) : (
                    <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>未配置策略</span>
                  )}
                </div>
                <div className="strategy-card__actions">
                  {(inst.status === 'draft' || inst.status === 'stopped') && (
                    <Button size="small" onClick={() => handleInstanceAction(inst.id, 'start')}>启动</Button>
                  )}
                </div>
              </Card>
            ))}
            {visibleInstances.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 20, fontSize: 12 }}>
                暂无策略实例
              </div>
            )}
          </div>
        </div>
      </div>
      <PositionSizingConfigDrawer
        open={sizingDrawerOpen}
        onClose={() => setSizingDrawerOpen(false)}
        onSaved={loadInstances}
        watchlist={drawerWatchlist}
        instanceId={activeInstance?.id ?? null}
        positionSizing={activeInstance?.position_sizing ?? {}}
      />
      <Modal
        title="编辑自选股配置"
        open={editingItem !== null}
        onCancel={() => setEditingItem(null)}
        onOk={handleSaveWatchlistItem}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="symbol" label="标的代码" rules={[{ required: true, message: '请输入标的代码' }]}>
            <Input placeholder="例如 600522.SH" />
          </Form.Item>
          <Form.Item name="target_weight" label="目标权重(%)">
            <InputNumber min={0} max={100} precision={2} style={{ width: '100%' }} placeholder="例如 10" />
          </Form.Item>
          <Form.Item name="strategy_id" label="时序交易信号策略" rules={[{ required: true, message: '请选择时序交易信号策略' }]}>
            <Select
              placeholder="选择用于监控该标的并产生交易信号的策略"
              options={timingStrategies.map(strategy => ({ value: strategy.strategy_id, label: strategy.name }))}
            />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} maxLength={256} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
