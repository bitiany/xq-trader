import i18n from '@/i18n'

export type ToolName =
  | 'write_file'
  | 'edit_file'
  | 'read_file'
  | 'list_dir'
  | 'grep'
  | 'notebook_edit'
  | 'complete_goal'
  | 'spawn'
  | 'message'
  | string

/** 工具展示用友好标题（Cursor 风格短标签） */
export function formatToolTitle(name: ToolName, summary?: string): string {
  const key = `agent.trace.tools.${name}`
  const hasKey = i18n.exists(key)
  const base = hasKey ? i18n.t(key) : i18n.t('agent.trace.tools.default', { name })
  if (summary && name !== 'complete_goal') {
    return `${base} · ${shortenDisplay(summary)}`
  }
  return base
}

export function shortenDisplay(text: string, max = 48): string {
  const t = text.replace(/\\/g, '/').trim()
  if (t.length <= max) {
    return t
  }
  const parts = t.split('/')
  const tail = parts[parts.length - 1]
  if (tail.length <= max) {
    return tail
  }
  return `${tail.slice(0, max - 1)}…`
}

export function shouldHideTool(name: string): boolean {
  return name === 'complete_goal'
}

export function parseToolArgs(raw: unknown): Record<string, unknown> {
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return raw as Record<string, unknown>
  }
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw) as unknown
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      /* ignore */
    }
  }
  return {}
}
