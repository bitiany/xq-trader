import { useState, useCallback, useEffect } from 'react';
import { Drawer, Tag, Button, Checkbox, Input, InputNumber, Select } from 'antd';
import { Zap, Clock, CheckCircle, XCircle, ArrowRight, Edit3 } from 'lucide-react';
import type { PreOrder } from '../types';

const SIDE_TAG_COLOR: Record<string, string> = {
  open: 'var(--color-rise)',
  add: 'var(--color-rise)',
  reduce: 'var(--color-fall)',
  close: 'var(--color-fall)',
};

const SIDE_LABEL: Record<string, string> = {
  open: '开仓',
  add: '加仓',
  reduce: '减仓',
  close: '平仓',
};

interface EditParams {
  qty: number;
  price: number;
  priceType: 'limit' | 'market';
}

interface PreOrderApprovalDrawerProps {
  open: boolean;
  onClose: () => void;
  preOrders: PreOrder[];
}

export function PreOrderApprovalDrawer({ open, onClose, preOrders }: PreOrderApprovalDrawerProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>(preOrders.map(po => po.id));
  const [countdown, setCountdown] = useState(270);
  const [remark, setRemark] = useState('');
  const [editParams, setEditParams] = useState<Record<string, EditParams>>(() =>
    preOrders.reduce<Record<string, EditParams>>((acc, po) => ({
      ...acc,
      [po.id]: { qty: po.suggestedQty, price: po.suggestedPrice, priceType: po.priceType },
    }), {})
  );

  useEffect(() => {
    if (!open) return;
    const timer = setInterval(() => setCountdown(prev => prev > 0 ? prev - 1 : 0), 1000);
    return () => clearInterval(timer);
  }, [open]);

  const formatCountdown = (seconds: number): string => `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, '0')}`;
  const handleSelectAll = useCallback((checked: boolean) => setSelectedIds(checked ? preOrders.map(po => po.id) : []), [preOrders]);
  const handleSelect = useCallback((id: string, checked: boolean) => setSelectedIds(prev => checked ? [...prev, id] : prev.filter(x => x !== id)), []);
  const isUrgent = countdown <= 60;

  const updateParam = useCallback((id: string, field: keyof EditParams, value: number | string) => {
    setEditParams(prev => ({ ...prev, [id]: { ...prev[id], [field]: value } }));
  }, []);

  return (
    <Drawer
      title={
        <div className="approval-drawer__header" data-component="Approval Drawer Header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Zap size={16} style={{ color: 'var(--accent-primary)' }} />
            <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>预订单审批</span>
            <Tag color="warning" style={{ fontSize: 11 }}>待审批</Tag>
          </div>
          <div className={`approval-drawer__countdown ${isUrgent ? 'approval-drawer__countdown--urgent' : ''}`}>
            <Clock size={12} style={{ marginRight: 4 }} />
            剩余 {formatCountdown(countdown)}
          </div>
        </div>
      }
      open={open}
      onClose={onClose}
      width={720}
      data-component="Pre-Order Approval Drawer"
    >
      <div className="approval-drawer__dates" data-component="Signal Execution Dates">
        <div>
          <div className="approval-drawer__dates-label">信号日 (T)</div>
          <div className="approval-drawer__dates-value">2026-06-09</div>
        </div>
        <div className="approval-drawer__dates-arrow"><ArrowRight size={20} /></div>
        <div>
          <div className="approval-drawer__dates-label">执行日 (T+1)</div>
          <div className="approval-drawer__dates-value">2026-06-10</div>
        </div>
      </div>

      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 12 }}>
        Workflow: trading-cycle-20260609 | 策略: Alpha-Rebalance-01
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <Checkbox checked={selectedIds.length === preOrders.length} onChange={(e) => handleSelectAll(e.target.checked)}>
          <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>全选 ({selectedIds.length}/{preOrders.length})</span>
        </Checkbox>
      </div>

      {preOrders.map(po => {
        const params = editParams[po.id];
        return (
          <div
            key={po.id}
            className="approval-item"
            style={{ borderLeftWidth: 3, borderLeftStyle: 'solid', borderLeftColor: SIDE_TAG_COLOR[po.side] }}
            data-component="Pre-Order Item"
          >
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <Checkbox checked={selectedIds.includes(po.id)} onChange={(e) => handleSelect(po.id, e.target.checked)} />
              <div style={{ flex: 1 }}>
                <div className="approval-item__header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span className="approval-item__symbol">{po.symbol}</span>
                    <span className="approval-item__name">{po.name}</span>
                  </div>
                  <Tag color={SIDE_TAG_COLOR[po.side]} style={{ fontSize: 11, padding: '0 6px', borderRadius: 4, fontWeight: 600 }}>
                    {SIDE_LABEL[po.side]}
                  </Tag>
                </div>

                <div className="approval-item__detail">
                  <div className="approval-item__detail-line">
                    <span className="approval-item__detail-label">目标权重</span>
                    <span className="approval-item__detail-value">{po.targetWeight}%</span>
                    <span className="approval-item__detail-label">当前权重</span>
                    <span className="approval-item__detail-value">{po.currentWeight}%</span>
                  </div>
                  <div className="approval-item__detail-line">
                    <span className="approval-item__detail-label">配仓依据</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{po.sizingStrategy}</span>
                    {po.availableCash > 0 && (
                      <>
                        <span className="approval-item__detail-label">可用现金</span>
                        <span style={{ color: 'var(--accent-primary)', fontFamily: 'var(--font-mono)' }}>¥{po.availableCash.toLocaleString()}</span>
                      </>
                    )}
                  </div>
                  <div className="approval-item__detail-line">
                    <span className="approval-item__detail-label">信号依据</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{po.reason}</span>
                  </div>
                </div>

                <div className="approval-item__edit" data-component="Editable Order Params">
                  <div className="approval-item__edit-title">
                    <Edit3 size={12} style={{ color: 'var(--accent-primary)' }} />
                    <span>调整下单参数</span>
                  </div>
                  <div className="approval-item__edit-fields">
                    <div className="approval-item__edit-field">
                      <span className="approval-item__edit-label">委托数量</span>
                      <InputNumber
                        value={params.qty}
                        onChange={v => updateParam(po.id, 'qty', v ?? 0)}
                        size="small" min={100} step={100}
                        style={{ width: 100 }}
                      />
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>股</span>
                    </div>
                    <div className="approval-item__edit-field">
                      <span className="approval-item__edit-label">委托类型</span>
                      <Select
                        value={params.priceType}
                        onChange={v => updateParam(po.id, 'priceType', v)}
                        size="small"
                        style={{ width: 90 }}
                        options={[{ value: 'limit', label: '限价单' }, { value: 'market', label: '市价单' }]}
                      />
                    </div>
                    {params.priceType === 'limit' && (
                      <div className="approval-item__edit-field">
                        <span className="approval-item__edit-label">委托价格</span>
                        <InputNumber
                          value={params.price}
                          onChange={v => updateParam(po.id, 'price', v ?? 0)}
                          size="small" min={0.01} step={0.01}
                          style={{ width: 90 }}
                        />
                        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>元</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      })}

      <div style={{ marginTop: 16 }}>
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>备注</div>
        <Input.TextArea value={remark} onChange={(e) => setRemark(e.target.value)} placeholder="可选，填写审批备注..." rows={2} />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 20, padding: '16px 0 0', borderTop: '1px solid var(--border-subtle)' }}>
        <Button danger icon={<XCircle size={14} />} size="large">拒绝</Button>
        <Button type="primary" icon={<CheckCircle size={14} />} size="large" disabled={selectedIds.length === 0}>
          确认下单 ({selectedIds.length} 笔)
        </Button>
      </div>
    </Drawer>
  );
}
