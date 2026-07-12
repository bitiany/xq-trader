import { useEffect } from 'react'
import { useMonitorStore, type MonitorCellConfig } from '../stores/monitorStore'

const STORAGE_KEY = 'monitor:layout'

interface StoredLayout {
  cells: MonitorCellConfig[]
}

export function loadLayout(): MonitorCellConfig[] | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredLayout
    if (!Array.isArray(parsed.cells)) return null
    return parsed.cells
  } catch {
    return null
  }
}

export function saveLayout(cells: MonitorCellConfig[]): void {
  try {
    const data: StoredLayout = { cells }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    // localStorage 满或不可用时静默
  }
}

export function useMonitorLayout(): void {
  const cells = useMonitorStore((s) => s.cells)

  // 初始加载
  useEffect(() => {
    const stored = loadLayout()
    if (stored && stored.length > 0) {
      useMonitorStore.getState().setCells(stored)
    }
  }, [])

  // 变更时持久化
  useEffect(() => {
    saveLayout(cells)
  }, [cells])
}
