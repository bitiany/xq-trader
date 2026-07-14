import { useState } from 'react';
import { App, Drawer, Select, InputNumber, Button } from 'antd';
import { Settings, Cpu, Star } from 'lucide-react';
import { POSITION_SIZING_OPTIONS } from '../utils/trading';
import { updateInstance } from '@/api/trading';
import type { PositionSizingStrategy } from '../types';

interface DrawerWatchlistItem {
  symbol: string
  name: string
}

interface PositionSizingConfigDrawerProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
  watchlist: DrawerWatchlistItem[];
  instanceId: number | null;
  positionSizing: Record<string, unknown>;
}

interface SizingParams {
  maxTotalWeight: number;
  maxSingleWeight: number;
}

const DEFAULT_MODE: PositionSizingStrategy = 'watchlist_target_weight';
const DEFAULT_PARAMS: SizingParams = { maxTotalWeight: 100, maxSingleWeight: 20 };

function resolveSizingMode(value: unknown): PositionSizingStrategy {
  return POSITION_SIZING_OPTIONS.some(option => option.value === value) ? value as PositionSizingStrategy : DEFAULT_MODE;
}

function percentFromFraction(value: unknown, fallback: number): number {
  if (typeof value !== 'number') return fallback;
  return value <= 1 ? value * 100 : value;
}

function extractParamsFromPositionSizing(ps: Record<string, unknown>): SizingParams {
  return {
    maxTotalWeight: percentFromFraction(ps.max_total_weight, DEFAULT_PARAMS.maxTotalWeight),
    maxSingleWeight: percentFromFraction(ps.max_single_weight, DEFAULT_PARAMS.maxSingleWeight),
  };
}

export function PositionSizingConfigDrawer({ open, onClose, onSaved, watchlist, instanceId, positionSizing }: PositionSizingConfigDrawerProps) {
  const { message } = App.useApp();
  const [selectedSizing, setSelectedSizing] = useState<PositionSizingStrategy>(
    resolveSizingMode(positionSizing.mode),
  );
  const [sizingParams, setSizingParams] = useState<SizingParams>(
    extractParamsFromPositionSizing(positionSizing),
  );
  const [saving, setSaving] = useState(false);

  const update = (k: keyof SizingParams, v: number | null) => setSizingParams(p => ({ ...p, [k]: v ?? 0 }));

  const handleSave = async () => {
    if (instanceId === null) {
      message.warning('无可用策略实例');
      return;
    }
    setSaving(true);
    try {
      await updateInstance(instanceId, {
        position_sizing: {
          mode: selectedSizing,
          max_total_weight: sizingParams.maxTotalWeight / 100,
          max_single_weight: sizingParams.maxSingleWeight / 100,
        },
      });
      message.success('仓位配置已保存');
      await onSaved();
      onClose();
    } catch {
      message.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

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

        <div className="strategy-config__params">
          <div className="strategy-config__param">
            <span>组合总仓位上限 (%)</span>
            <InputNumber value={sizingParams.maxTotalWeight} onChange={v => update('maxTotalWeight', v)} size="small" min={1} max={100} precision={2} style={{ width: 100 }} />
          </div>
          <div className="strategy-config__param">
            <span>单票仓位上限 (%)</span>
            <InputNumber value={sizingParams.maxSingleWeight} onChange={v => update('maxSingleWeight', v)} size="small" min={1} max={100} precision={2} style={{ width: 100 }} />
          </div>
        </div>

        {selectedSizing === 'watchlist_target_weight' && (
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            使用自选股表格中的目标权重；若合计超过组合总仓位上限，会按比例缩放。
          </div>
        )}
        {selectedSizing === 'confidence_weighted' && (
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            按入选信号置信度分配组合总仓位，并受单票仓位上限约束。
          </div>
        )}
        {selectedSizing === 'equal_weight' && (
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
            对入选信号等权分配组合总仓位，并受单票仓位上限约束。
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
          <Button type="primary" loading={saving} onClick={handleSave}>保存配置</Button>
        </div>
      </div>
    </Drawer>
  );
}
