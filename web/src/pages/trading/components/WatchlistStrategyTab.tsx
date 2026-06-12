import { useState, useCallback, useMemo } from 'react';
import { Card, Table, Tag, Select, Button, InputNumber, Space, Popover } from 'antd';
import { Star, Search, Plus, Trash2, Edit3, Cpu, Settings, X } from 'lucide-react';
import type { StockItem, WatchlistItem } from '../types';
import { INITIAL_WATCHLIST, ALL_STOCKS_POOL, STRATEGY_INSTANCES } from '../data/mock-trading';
import { POSITION_SIZING_OPTIONS, INSTANCE_STATUS_COLOR, INSTANCE_STATUS_LABEL, RUN_MODE_LABEL } from '../utils/trading';
import { PositionSizingConfigDrawer } from './PositionSizingConfigDrawer';

function StockConfigPopover({ stock, children }: { stock: StockItem; children: React.ReactNode }) {
  const [targetWeight, setTargetWeight] = useState<number>(10);
  const [sizingStrategy, setSizingStrategy] = useState<string>('atr_risk');
  const content = (
    <div className="stock-config-popover" data-component="Stock Config Popover">
      <div className="stock-config-popover__header">
        <span className="stock-config-popover__symbol">{stock.symbol}</span>
        <span className="stock-config-popover__name">{stock.name}</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>{stock.industry}</span>
      </div>
      <div className="stock-config-popover__params">
        <div className="stock-config-popover__param">
          <span>目标权重 (%)</span>
          <InputNumber value={targetWeight} onChange={v => setTargetWeight(v ?? 0)} size="middle" min={0} max={50} step={0.5} style={{ width: 100 }} />
        </div>
        <div className="stock-config-popover__param">
          <span>配仓策略</span>
          <Select value={sizingStrategy} onChange={setSizingStrategy} size="middle" style={{ width: 140 }} options={POSITION_SIZING_OPTIONS} />
        </div>
      </div>
      <div className="stock-config-popover__actions">
        <Button size="middle">取消</Button>
        <Button size="middle" type="primary">保存</Button>
      </div>
    </div>
  );
  return (
    <Popover content={content} trigger="click" placement="bottom" overlayClassName="stock-config-overlay">
      {children}
    </Popover>
  );
}

export function WatchlistStrategyTab() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>(INITIAL_WATCHLIST);
  const [searchText, setSearchText] = useState('');
  const [sizingDrawerOpen, setSizingDrawerOpen] = useState(false);

  const searchResults = useMemo(() => {
    if (!searchText.trim()) return [];
    const q = searchText.trim().toLowerCase();
    return ALL_STOCKS_POOL.filter(s =>
      !watchlist.some(w => w.symbol === s.symbol) &&
      (s.symbol.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
    ).slice(0, 5);
  }, [searchText, watchlist]);

  const addToWatchlist = useCallback((stock: StockItem) => {
    setWatchlist(prev => [...prev, { ...stock, tags: ['观察'] }]);
    setSearchText('');
  }, []);

  const removeFromWatchlist = useCallback((symbol: string) => {
    setWatchlist(prev => prev.filter(s => s.symbol !== symbol));
  }, []);

  const wlColumns = [
    { title: '代码', dataIndex: 'symbol', width: 90, render: (v: string) => <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v}</span> },
    { title: '名称', dataIndex: 'name', width: 70 },
    { title: '最新价', dataIndex: 'lastPrice', width: 70, render: (v: number) => <span style={{ fontFamily: 'var(--font-mono)' }}>{v.toFixed(2)}</span> },
    {
      title: '涨跌幅', dataIndex: 'changePct', width: 75,
      render: (v: number) => {
        const color = v > 0 ? 'var(--color-rise)' : v < 0 ? 'var(--color-fall)' : 'var(--text-secondary)';
        return <span style={{ color, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span>;
      },
    },
    { title: '标签', dataIndex: 'tags', width: 110, render: (tags: string[]) => <Space size={2} wrap>{tags.map(t => <Tag key={t} style={{ fontSize: 10, padding: '0 4px', margin: 0, borderRadius: 3 }} color={t.includes('信号') || t.includes('止损') ? 'warning' : t.includes('持仓') ? 'blue' : 'default'}>{t}</Tag>)}</Space> },
    {
      title: '', width: 70,
      render: (_: unknown, row: WatchlistItem) => (
        <Space size={2}>
          <StockConfigPopover stock={row}>
            <Button size="small" type="link" style={{ padding: 0, fontSize: 11, color: 'var(--accent-primary)' }}>
              <Edit3 size={11} style={{ verticalAlign: 'middle', marginRight: 2 }} />仓位
            </Button>
          </StockConfigPopover>
          <Button size="small" type="link" style={{ padding: 0, color: 'var(--color-fall)' }} onClick={() => removeFromWatchlist(row.symbol)}>
            <Trash2 size={11} style={{ verticalAlign: 'middle' }} />
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="ws-tab" data-component="Watchlist & Strategy Tab">
      <div className="ws-tab__panels">
        <div className="ws-tab__panel ws-tab__panel--left">
          <div className="ws-tab__panel-header">
            <div className="ws-tab__panel-title">
              <Star size={14} style={{ color: 'var(--accent-primary)' }} />
              <span>自选股池</span>
              <span className="ws-tab__panel-count">{watchlist.length}只</span>
            </div>
            <div className="ws-tab__panel-search">
              <div className="watchlist-search-inline">
                <div className="watchlist-search-inline__input-wrap">
                  <Search size={12} className="watchlist-search-inline__icon" />
                  <input
                    className="watchlist-search-inline__input"
                    placeholder="搜索代码/名称添加..."
                    value={searchText}
                    onChange={e => setSearchText(e.target.value)}
                  />
                  {searchText && (
                    <button className="watchlist-search-inline__clear" onClick={() => setSearchText('')}>
                      <X size={12} />
                    </button>
                  )}
                </div>
                {searchResults.length > 0 && (
                  <div className="watchlist-search-results">
                    {searchResults.map(s => (
                      <div key={s.symbol} className="watchlist-search-result-item" onClick={() => addToWatchlist(s)}>
                        <span className="watchlist-search-result-item__symbol">{s.symbol}</span>
                        <span className="watchlist-search-result-item__name">{s.name}</span>
                        <span className="watchlist-search-result-item__industry">{s.industry}</span>
                        <span className="watchlist-search-result-item__change" style={{ color: s.changePct > 0 ? 'var(--color-rise)' : 'var(--color-fall)' }}>
                          {s.changePct > 0 ? '+' : ''}{s.changePct.toFixed(2)}%
                        </span>
                        <Plus size={14} style={{ color: 'var(--accent-primary)', marginLeft: 4 }} />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
          <Table dataSource={watchlist} columns={wlColumns} rowKey="symbol" size="small" pagination={false} scroll={{ y: 260 }} />
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
            {STRATEGY_INSTANCES.map(inst => (
              <Card key={inst.id} size="small" className="strategy-card" data-component="Strategy Instance Card">
                <div className="strategy-card__header">
                  <div className="strategy-card__identity">
                    <span className="strategy-card__code">{inst.code}</span>
                    <span className="strategy-card__name">{inst.name}</span>
                  </div>
                  <Space size={4}>
                    <Tag color={INSTANCE_STATUS_COLOR[inst.status]}>{INSTANCE_STATUS_LABEL[inst.status]}</Tag>
                    <Tag color="blue">{RUN_MODE_LABEL[inst.runMode]}</Tag>
                  </Space>
                </div>
                <div className="strategy-card__metrics">
                  <div className="strategy-card__metric"><span>配仓</span><span>{inst.positionSizing}</span></div>
                  <div className="strategy-card__metric"><span>累计收益</span><span style={{ color: inst.cumulativePnl > 0 ? 'var(--color-rise)' : 'var(--color-fall)' }}>+{inst.cumulativePnl}%</span></div>
                  <div className="strategy-card__metric"><span>最大回撤</span><span style={{ color: 'var(--color-fall)' }}>{inst.maxDrawdown}%</span></div>
                  <div className="strategy-card__metric"><span>股票池</span><span>{inst.stockPool}只</span></div>
                </div>
                <div className="strategy-card__actions">
                  <Button size="small" icon={<Edit3 size={11} />}>查看信号</Button>
                  <Button size="small">暂停</Button>
                  <Button size="small">停止</Button>
                </div>
              </Card>
            ))}
          </div>
        </div>
      </div>
      <PositionSizingConfigDrawer open={sizingDrawerOpen} onClose={() => setSizingDrawerOpen(false)} watchlist={watchlist} />
    </div>
  );
}
