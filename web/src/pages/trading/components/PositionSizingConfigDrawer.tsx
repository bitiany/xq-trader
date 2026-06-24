import { useState } from 'react';
import { Drawer, Select, InputNumber, Button } from 'antd';
import { Settings, Cpu, Star } from 'lucide-react';
import { POSITION_SIZING_OPTIONS } from '../utils/trading';

interface DrawerWatchlistItem {
  symbol: string
  name: string
}

interface PositionSizingConfigDrawerProps {
  open: boolean;
  onClose: () => void;
  watchlist: DrawerWatchlistItem[];
}

interface SizingParams {
  atrPeriod: number;
  riskBudgetPct: number;
  maxSingleWeight: number;
  fallbackStrategy: string;
  kellyFraction: number;
  kellyWindow: number;
  signalMinWeight: number;
  volTarget: number;
  volWindow: number;
  fixedPct: number;
}

export function PositionSizingConfigDrawer({ open, onClose, watchlist }: PositionSizingConfigDrawerProps) {
  const [selectedSizing, setSelectedSizing] = useState<string>('atr_risk');
  const [sizingParams, setSizingParams] = useState<SizingParams>({
    atrPeriod: 14, riskBudgetPct: 2, maxSingleWeight: 10, fallbackStrategy: 'equal_weight',
    kellyFraction: 0.25, kellyWindow: 60, signalMinWeight: 2, volTarget: 15, volWindow: 20, fixedPct: 10,
  });

  const update = (k: keyof SizingParams, v: number | string) => setSizingParams(p => ({ ...p, [k]: v }));

  return (
    <Drawer
      title={<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Settings size={14} />自选股仓位配置</div>}
      placement="right" size="default" open={open} onClose={onClose}
    >
      <div className="strategy-config__form" data-component="Position Sizing Config">
        <div className="strategy-config__section">
          <div className="strategy-config__section-title"><Cpu size={14} />配仓策略</div>
          <Select value={selectedSizing} onChange={setSelectedSizing} options={POSITION_SIZING_OPTIONS} style={{ width: '100%' }} size="small" />
        </div>

        {selectedSizing === 'atr_risk' && (
          <div className="strategy-config__params">
            <div className="strategy-config__param"><span>ATR 周期</span><InputNumber value={sizingParams.atrPeriod} onChange={v => update('atrPeriod', v ?? 0)} size="small" min={1} max={100} style={{ width: 80 }} /></div>
            <div className="strategy-config__param"><span>风险预算 (%)</span><InputNumber value={sizingParams.riskBudgetPct} onChange={v => update('riskBudgetPct', v ?? 0)} size="small" min={0.1} max={10} step={0.1} style={{ width: 80 }} /></div>
            <div className="strategy-config__param"><span>单票上限 (%)</span><InputNumber value={sizingParams.maxSingleWeight} onChange={v => update('maxSingleWeight', v ?? 0)} size="small" min={1} max={50} style={{ width: 80 }} /></div>
            <div className="strategy-config__param"><span>降级策略</span><Select value={sizingParams.fallbackStrategy} onChange={v => update('fallbackStrategy', v)} options={POSITION_SIZING_OPTIONS.filter(o => o.value !== selectedSizing)} size="small" style={{ width: '100%' }} /></div>
            <div className="strategy-config__param-hint">主策略缺数据时使用，必填</div>
          </div>
        )}

        {selectedSizing === 'kelly' && (
          <div className="strategy-config__params">
            <div className="strategy-config__param"><span>Kelly 分数</span><InputNumber value={sizingParams.kellyFraction} onChange={v => update('kellyFraction', v ?? 0)} size="small" min={0.01} max={1} step={0.05} style={{ width: 80 }} /></div>
            <div className="strategy-config__param"><span>统计窗口</span><InputNumber value={sizingParams.kellyWindow} onChange={v => update('kellyWindow', v ?? 0)} size="small" min={10} max={500} style={{ width: 80 }} /></div>
          </div>
        )}

        {selectedSizing === 'signal_weighted' && (
          <div className="strategy-config__params">
            <div className="strategy-config__param"><span>最小权重阈值 (%)</span><InputNumber value={sizingParams.signalMinWeight} onChange={v => update('signalMinWeight', v ?? 0)} size="small" min={0.5} max={20} step={0.5} style={{ width: 80 }} /></div>
          </div>
        )}

        {selectedSizing === 'vol_target' && (
          <div className="strategy-config__params">
            <div className="strategy-config__param"><span>目标波动率 (%)</span><InputNumber value={sizingParams.volTarget} onChange={v => update('volTarget', v ?? 0)} size="small" min={5} max={50} style={{ width: 80 }} /></div>
            <div className="strategy-config__param"><span>估计窗口</span><InputNumber value={sizingParams.volWindow} onChange={v => update('volWindow', v ?? 0)} size="small" min={5} max={100} style={{ width: 80 }} /></div>
          </div>
        )}

        {selectedSizing === 'inverse_volatility' && (
          <div className="strategy-config__params">
            <div className="strategy-config__param"><span>估计窗口</span><InputNumber value={20} size="small" min={5} max={100} style={{ width: 80 }} /></div>
            <div className="strategy-config__param"><span>最小波动率</span><InputNumber value={0.01} size="small" min={0.001} max={1} step={0.001} style={{ width: 80 }} /></div>
          </div>
        )}

        {selectedSizing === 'fixed_pct' && (
          <div className="strategy-config__params">
            <div className="strategy-config__param"><span>固定比例 (%)</span><InputNumber value={sizingParams.fixedPct} onChange={v => update('fixedPct', v ?? 0)} size="small" min={1} max={50} style={{ width: 80 }} /></div>
          </div>
        )}

        <div className="strategy-config__stock-pool">
          <div className="strategy-config__section-title"><Star size={14} />自选股池 ({watchlist.length}只)</div>
          <div className="strategy-config__stock-list">
            {watchlist.map(s => (
              <div key={s.symbol} className="strategy-config__stock-item">
                <span className="strategy-config__stock-symbol">{s.symbol}</span>
                <span className="strategy-config__stock-name">{s.name}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="strategy-config__footer">
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={onClose}>保存配置</Button>
        </div>
      </div>
    </Drawer>
  );
}
