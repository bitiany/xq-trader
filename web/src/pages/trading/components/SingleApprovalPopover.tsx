import { useState } from 'react';
import { Popover, InputNumber, Select, Button, Tag } from 'antd';
import { Edit3 } from 'lucide-react';
import type { ReactNode } from 'react';
import type { PreOrder } from '../types';
import { SIGNAL_SIDE_LABEL, SIGNAL_SIDE_COLOR } from '../utils/trading';

interface SingleApprovalPopoverProps {
  po: PreOrder;
  children: ReactNode;
}

export function SingleApprovalPopover({ po, children }: SingleApprovalPopoverProps) {
  const [editQty, setEditQty] = useState<number>(po.suggestedQty);
  const [editPriceType, setEditPriceType] = useState<'limit' | 'market'>(po.priceType);
  const [editPrice, setEditPrice] = useState<number>(po.priceType === 'market' ? 0 : po.suggestedPrice);

  const content = (
    <div className="single-approval-popover" data-component="Single Approval Popover">
      <div className="single-approval-popover__header">
        <span className="single-approval-popover__symbol">{po.symbol}</span>
        <span className="single-approval-popover__name">{po.name}</span>
        <Tag color={SIGNAL_SIDE_COLOR[po.side]} style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>
          {SIGNAL_SIDE_LABEL[po.side]}
        </Tag>
      </div>
      <div className="single-approval-popover__signal-info">
        <span>信号依据: {po.reason} | 配仓: {po.sizingStrategy}</span>
      </div>
      <div className="single-approval-popover__edit-section">
        <div className="single-approval-popover__edit-title">
          <Edit3 size={13} style={{ color: 'var(--accent-primary)' }} />
          调整下单参数
        </div>
        <div className="single-approval-popover__edit-row">
          <span className="single-approval-popover__edit-label">委托数量</span>
          <InputNumber value={editQty} onChange={v => setEditQty(v ?? 0)} size="middle" min={100} step={100} style={{ width: 130 }} addonAfter="股" />
        </div>
        <div className="single-approval-popover__edit-row">
          <span className="single-approval-popover__edit-label">委托类型</span>
          <Select value={editPriceType} onChange={setEditPriceType} size="middle" style={{ width: 130 }}
            options={[{ value: 'limit', label: '限价单' }, { value: 'market', label: '市价单' }]} />
        </div>
        {editPriceType === 'limit' && (
          <div className="single-approval-popover__edit-row">
            <span className="single-approval-popover__edit-label">委托价格</span>
            <InputNumber value={editPrice} onChange={v => setEditPrice(v ?? 0)} size="middle" min={0.01} step={0.01} style={{ width: 130 }} addonAfter="元" />
          </div>
        )}
        <div className="single-approval-popover__edit-row">
          <span className="single-approval-popover__edit-label">目标权重</span>
          <span className="single-approval-popover__edit-value">{po.targetWeight}% <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>当前 {po.currentWeight}%</span></span>
        </div>
      </div>
      <div className="single-approval-popover__footer">
        <Button size="middle" danger>拒绝</Button>
        <Button size="middle" type="primary">确认下单</Button>
      </div>
    </div>
  );

  return (
    <Popover content={content} trigger="click" placement="bottom" overlayClassName="single-approval-overlay">
      {children}
    </Popover>
  );
}
