import { useCallback, useEffect, useRef, useState } from 'react'
import { Responsive, WidthProvider } from 'react-grid-layout/legacy'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { useMonitorStore, type MonitorCellConfig } from '../stores/monitorStore'
import { MonitorCell } from './MonitorCell'
import '@/pages/monitor/styles/monitor.css'

const ResponsiveGridLayout = WidthProvider(Responsive)

/** 每行 3 列（cols=6, w=2），每个 cell 高度占 3 个 rowHeight 单位 */
const COLS_PER_ROW = 3
const CELL_H = 3
const WRAPPER_PADDING = 8

export function MonitorGrid() {
  const cells = useMonitorStore((s) => s.cells)
  const cols = useMonitorStore((s) => s.cols)
  const maximizedCellId = useMonitorStore((s) => s.maximizedCellId)
  const selectedCellId = useMonitorStore((s) => s.selectedCellId)
  const updateCellLayout = useMonitorStore((s) => s.updateCellLayout)

  const wrapperRef = useRef<HTMLDivElement>(null)
  const [dynamicRowHeight, setDynamicRowHeight] = useState(100)

  // 动态计算 rowHeight，使网格撑满容器高度
  useEffect(() => {
    if (!wrapperRef.current) return
    const el = wrapperRef.current
    const calc = () => {
      const containerHeight = el.clientHeight - WRAPPER_PADDING
      const numRows = Math.max(1, Math.ceil(cells.length / COLS_PER_ROW))
      // 总高度 = 3*numRows*RH + 12*numRows - 4（RGL 布局公式）
      // 解出 RH = (containerHeight - 12*numRows + 4) / (3*numRows)
      let rh = Math.floor((containerHeight - 12 * numRows + 4) / (CELL_H * numRows))
      // 限制最小高度，避免 cell 过小
      rh = Math.max(rh, 60)
      setDynamicRowHeight(rh)
    }
    calc()
    const ro = new ResizeObserver(calc)
    ro.observe(el)
    return () => ro.disconnect()
  }, [cells.length])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const raw = e.dataTransfer.getData('text/plain')
      if (!raw) return
      try {
        const { symbol, name } = JSON.parse(raw) as { symbol: string; name: string }
        useMonitorStore.getState().addCell(symbol, name)
      } catch {
        // 忽略非法拖拽数据
      }
    },
    [],
  )

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const handleLayoutChange = useCallback(
    (newLayout: ReactGridLayout.Layout[]) => {
      for (const item of newLayout) {
        const cell = cells.find((c) => c.id === item.i)
        if (cell) {
          updateCellLayout(cell.id, {
            x: item.x,
            y: item.y,
            w: item.w,
            h: item.h,
          })
        }
      }
    },
    [cells, updateCellLayout],
  )

  // 放大态：只显示放大的 cell，占满全部
  if (maximizedCellId) {
    const maxCell = cells.find((c) => c.id === maximizedCellId)
    if (maxCell) {
      return (
        <div className="monitor-grid-wrapper" onDrop={handleDrop} onDragOver={handleDragOver}>
          <div
            className="monitor-grid"
            style={{ height: '100%', display: 'flex' }}
          >
            <div
              className="react-grid-item react-grid-item--maximized"
              style={{
                position: 'relative',
                width: '100%',
                height: '100%',
                margin: 0,
              }}
            >
              <MonitorCell cell={maxCell} isMaximized={true} />
            </div>
          </div>
        </div>
      )
    }
  }

  const layout: ReactGridLayout.Layout[] = cells.map((c) => ({
    i: c.id,
    x: c.layout.x,
    y: c.layout.y,
    w: c.layout.w,
    h: c.layout.h,
  }))

  if (cells.length === 0) {
    return (
      <div
        className="monitor-grid-wrapper"
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        style={{ display: 'flex' }}
      >
        <div className="monitor-grid__empty">
          <p>从左侧拖拽标的到此处</p>
          <p style={{ fontSize: 12 }}>或双击侧栏标的快速添加</p>
        </div>
      </div>
    )
  }

  return (
    <div className="monitor-grid-wrapper" ref={wrapperRef} onDrop={handleDrop} onDragOver={handleDragOver}>
      <ResponsiveGridLayout
        className="monitor-grid layout"
        layouts={{ lg: layout, md: layout, sm: layout }}
        cols={{ lg: cols, md: cols, sm: cols, xs: 2, xxs: 1 }}
        rowHeight={dynamicRowHeight}
        margin={[4, 4]}
        containerPadding={[0, 0]}
        onLayoutChange={handleLayoutChange}
        isDraggable
        isResizable
        draggableHandle=".monitor-cell__header"
        compactType="vertical"
      >
        {cells.map((cell: MonitorCellConfig) => (
          <div
            key={cell.id}
            className={selectedCellId === cell.id ? 'react-grid-item-selected' : ''}
          >
            <MonitorCell cell={cell} isMaximized={false} />
          </div>
        ))}
      </ResponsiveGridLayout>
    </div>
  )
}
