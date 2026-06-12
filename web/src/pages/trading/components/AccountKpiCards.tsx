import { useMemo } from 'react';
import { Briefcase, BarChart3, TrendingUp, ArrowUpRight } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { KPI_DATA } from '../data/mock-trading';
import { formatMoney } from '../utils/trading';

interface KpiCard {
  label: string;
  value: string;
  delta: string | null;
  deltaType: 'rise' | 'fall' | null;
  icon: LucideIcon;
}

export function AccountKpiCards() {
  const kpiCards = useMemo<KpiCard[]>(() => [
    { label: '总资产', value: formatMoney(KPI_DATA.totalAsset), delta: null, deltaType: null, icon: Briefcase },
    { label: '可用资金', value: formatMoney(KPI_DATA.availableCash), delta: null, deltaType: null, icon: BarChart3 },
    { label: '持仓市值', value: formatMoney(KPI_DATA.marketValue), delta: null, deltaType: null, icon: TrendingUp },
    { label: '当日收益', value: `+${formatMoney(KPI_DATA.todayPnl)}`, delta: `+${(KPI_DATA.todayPnlPct * 100).toFixed(2)}%`, deltaType: 'rise', icon: ArrowUpRight },
  ], []);

  return (
    <div className="trading-kpi-grid" data-component="KPI Cards">
      {kpiCards.map(card => {
        const Icon = card.icon;
        return (
          <div className="trading-kpi-card" key={card.label}>
            <div className="trading-kpi-card__icon"><Icon size={14} /></div>
            <div className="trading-kpi-card__label">{card.label}</div>
            <div className={`trading-kpi-card__value ${card.deltaType === 'rise' ? 'trading-kpi-card__value--rise' : card.deltaType === 'fall' ? 'trading-kpi-card__value--fall' : ''}`}>
              {card.value}
            </div>
            {card.delta && (
              <div className={`trading-kpi-card__delta ${card.deltaType === 'rise' ? 'trading-kpi-card__delta--rise' : 'trading-kpi-card__delta--fall'}`}>
                <Icon size={12} />{card.delta}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
