import type { SignalItem } from '../stores/monitorStore'

// 信号类型中文标签（中性，具体方向由 buildSignalDesc 描述）
export const SIGNAL_TYPE_LABELS: Record<string, string> = {
  vwap_breakthrough: 'VWAP突破',
  twap_deviation: 'TWAP偏离',
  macd_cross: 'MACD交叉',
  rsi_extreme: 'RSI极值',
  volume_price_divergence: '量价背离',
  resonance: '共振信号',
}

// 方向中文标签
export const DIRECTION_LABELS: Record<string, string> = {
  long: '▲ 看多',
  short: '▼ 看空',
  neutral: '-',
}

/**
 * 构建专业信号说明（带数据+方向+阈值）
 *
 * 面向量化交易员的专业描述，每个信号必须包含：
 * - 具体类型（如顶背离/底背离、金叉/死叉、超买/超卖）
 * - 关键数据（价格、指标值、阈值）
 * - 方向性判断
 */
export function buildSignalDesc(signal: SignalItem): string {
  const rv = signal.raw_values ?? {}
  switch (signal.signal_type) {
    case 'vwap_breakthrough': {
      const isUp = rv.cross === 'up'
      const cross = isUp ? '上穿' : '下穿'
      const dev = rv.deviation_pct as number | undefined
      const close = rv.close as number | undefined
      const vwap = rv.vwap as number | undefined
      const dir = isUp ? '转强' : '转弱'
      return `VWAP${cross}${dir} 偏离${dev != null ? (dev > 0 ? '+' : '') + dev.toFixed(2) : '-'}% 价${fmtPrice(close)} vs VWAP${fmtPrice(vwap)}`
    }
    case 'twap_deviation': {
      const dev = rv.deviation_pct as number | undefined
      const close = rv.close as number | undefined
      const twap = rv.twap as number | undefined
      const isAbove = (dev ?? 0) > 0
      const dir = isAbove ? '高于' : '低于'
      const zone = isAbove ? '超买区' : '超卖区'
      return `TWAP偏离${dir}TWAP ${Math.abs(dev ?? 0).toFixed(2)}% ${zone} 价${fmtPrice(close)} vs TWAP${fmtPrice(twap)}`
    }
    case 'macd_cross': {
      const isGolden = rv.cross === 'golden'
      const cross = isGolden ? '金叉' : '死叉'
      const dif = rv.dif as number | undefined
      const dea = rv.dea as number | undefined
      const hist = rv.macd_hist as number | undefined
      const dir = isGolden ? '看多' : '看空'
      return `MACD${cross}${dir} DIF=${fmt4(dif)} DEA=${fmt4(dea)} 柱=${fmt4(hist)}`
    }
    case 'rsi_extreme': {
      const rsi = rv.rsi as number | undefined
      // 基于 signal.direction 精确判断超买/超卖：
      // direction=short -> 超买（RSI > 70，可能回落）
      // direction=long  -> 超卖（RSI < 30，可能反弹）
      const isOverbought = signal.direction === 'short'
      const label = isOverbought ? '超买' : '超卖'
      const threshold = isOverbought ? rv.threshold_overbought : rv.threshold_oversold
      const action = isOverbought ? '可能回落' : '可能反弹'
      return `RSI(14)${label}${action} RSI=${fmtVal(rsi, 1)} 阈值${threshold}`
    }
    case 'volume_price_divergence': {
      const isTop = rv.divergence === 'top'
      const currVol = rv.curr_volume as number | undefined
      if (isTop) {
        const currHigh = rv.curr_high as number | undefined
        const maxPrevHigh = rv.max_prev_high as number | undefined
        const maxPrevVol = rv.max_prev_volume as number | undefined
        const pricePct = maxPrevHigh && currHigh != null
          ? ((currHigh - maxPrevHigh) / maxPrevHigh * 100)
          : null
        const volPct = maxPrevVol && currVol != null
          ? ((maxPrevVol - currVol) / maxPrevVol * 100)
          : null
        return `量价顶背离 价创30根新高${pricePct != null ? '+' + pricePct.toFixed(2) + '%' : '-'} 量能萎缩${volPct != null ? volPct.toFixed(1) + '%' : '-'}(当前${fmtVol(currVol)} vs 前期最大${fmtVol(maxPrevVol)})`
      } else {
        const currLow = rv.curr_low as number | undefined
        const minPrevLow = rv.min_prev_low as number | undefined
        const minPrevVol = rv.min_prev_volume as number | undefined
        const pricePct = minPrevLow && currLow != null
          ? ((minPrevLow - currLow) / minPrevLow * 100)
          : null
        const volPct = minPrevVol && currVol != null
          ? ((currVol - minPrevVol) / minPrevVol * 100)
          : null
        return `量价底背离 价创30根新低${pricePct != null ? '-' + pricePct.toFixed(2) + '%' : '-'} 量能放大${volPct != null ? volPct.toFixed(1) + '%' : '-'}(当前${fmtVol(currVol)} vs 前期最小${fmtVol(minPrevVol)})`
      }
    }
    case 'resonance': {
      // 优先使用后端 contributing 字段（含每个信号的方向和关键数据），精确展示
      const contributing = rv.contributing as Array<{
        type: string; direction: string; metric: string
      }> | undefined
      const count = rv.count as number | undefined
      const isLong = signal.direction === 'long'
      const dirLabel = isLong ? '看多' : '看空'
      if (contributing && contributing.length > 0) {
        // 展示每项的具体方向和数据，如「RSI超买 RSI=73.2」「TWAP偏离+2.07% 超买区」
        const parts = contributing.map((c) => c.metric)
        return `共振${dirLabel}(${count ?? contributing.length}项): ${parts.join(' + ')}`
      }
      // 兜底：仅有 contributing_types（旧数据），用标签展示
      const types = rv.contributing_types as string[] | undefined
      const labels = (types ?? []).map(
        (t) => SIGNAL_TYPE_LABELS[t] ?? t,
      )
      return `共振${dirLabel}(${count ?? 0}项): ${labels.join(' + ')}`
    }
    default:
      return signal.signal_type ?? signal.signal_source
  }
}

/**
 * 将 UTC 时间转为上海时区显示
 */
export function toShanghaiTime(utcTime: string): string {
  try {
    const date = new Date(utcTime)
    return date.toLocaleTimeString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  } catch {
    return utcTime.substring(11, 19)
  }
}

// ──────────────── 格式化辅助 ────────────────

function fmtPrice(v: number | undefined): string {
  if (v == null || Number.isNaN(v)) return '-'
  return v.toFixed(2)
}

function fmt4(v: number | undefined): string {
  if (v == null || Number.isNaN(v)) return '-'
  return v.toFixed(4)
}

function fmtVal(v: number | undefined, digits: number): string {
  if (v == null || Number.isNaN(v)) return '-'
  return v.toFixed(digits)
}

function fmtVol(v: number | undefined): string {
  if (v == null || Number.isNaN(v)) return '-'
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万手`
  return `${v.toFixed(0)}手`
}
