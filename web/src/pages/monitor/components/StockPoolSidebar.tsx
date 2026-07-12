import { useState, useMemo } from 'react'
import { useMonitorStore } from '../stores/monitorStore'
import type { WatchlistItem } from '@/api/trading'
import '@/pages/monitor/styles/monitor.css'

interface StockPoolSidebarProps {
  watchlistItems: WatchlistItem[]
  positionSymbols: { symbol: string; name?: string }[]
}

export function StockPoolSidebar({ watchlistItems, positionSymbols }: StockPoolSidebarProps) {
  const [keyword, setKeyword] = useState('')
  const addCell = useMonitorStore((s) => s.addCell)

  const filteredWatchlist = useMemo(() => {
    if (!keyword) return watchlistItems
    const kw = keyword.toLowerCase()
    return watchlistItems.filter(
      (item) =>
        item.symbol.toLowerCase().includes(kw) ||
        (item.name ?? '').toLowerCase().includes(kw),
    )
  }, [watchlistItems, keyword])

  const filteredPositions = useMemo(() => {
    if (!keyword) return positionSymbols
    const kw = keyword.toLowerCase()
    return positionSymbols.filter(
      (p) => p.symbol.toLowerCase().includes(kw) || (p.name ?? '').toLowerCase().includes(kw),
    )
  }, [positionSymbols, keyword])

  const handleDragStart = (e: React.DragEvent, symbol: string, name: string) => {
    e.dataTransfer.setData('text/plain', JSON.stringify({ symbol, name }))
    e.dataTransfer.effectAllowed = 'copy'
  }

  const handleDoubleClick = (symbol: string, name: string) => {
    addCell(symbol, name)
  }

  return (
    <div className="monitor-sidebar">
      <div className="monitor-sidebar__search">
        <input
          type="text"
          placeholder="搜索代码/名称..."
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>
      <div className="monitor-sidebar__section">
        <div className="monitor-sidebar__section-title">自选池 ({filteredWatchlist.length})</div>
        {filteredWatchlist.map((item) => (
          <div
            key={item.id}
            className="monitor-sidebar__item"
            draggable
            onDragStart={(e) => handleDragStart(e, item.symbol, item.name ?? item.symbol)}
            onDoubleClick={() => handleDoubleClick(item.symbol, item.name ?? item.symbol)}
            title="拖拽到网格区或双击添加"
          >
            <span className="monitor-sidebar__item-symbol">{item.symbol}</span>
            <span className="monitor-sidebar__item-name">{item.name}</span>
          </div>
        ))}

        <div className="monitor-sidebar__section-title" style={{ marginTop: 8 }}>
          持仓 ({filteredPositions.length})
        </div>
        {filteredPositions.map((p) => (
          <div
            key={p.symbol}
            className="monitor-sidebar__item"
            draggable
            onDragStart={(e) => handleDragStart(e, p.symbol, p.name ?? p.symbol)}
            onDoubleClick={() => handleDoubleClick(p.symbol, p.name ?? p.symbol)}
            title="拖拽到网格区或双击添加"
          >
            <span className="monitor-sidebar__item-symbol">{p.symbol}</span>
            <span className="monitor-sidebar__item-name">{p.name ?? p.symbol}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
