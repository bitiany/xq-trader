import { useEffect, useState } from 'react'
import {
  BarChart3,
  Check,
  ChevronRight,
  Circle,
  DollarSign,
  FileText,
  FolderOpen,
  Globe,
  Loader2,
  Pencil,
  Search,
  Terminal,
  TrendingUp,
  X,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { AgentActivity } from '@/stores/agentStore'
import { formatToolTitle, shouldHideTool } from '@/utils/agentTrace'
import './AgentTrace.css'

interface AgentTraceProps {
  activities: AgentActivity[]
  isRunning: boolean
}

function toolIcon(name: string) {
  switch (name) {
    case 'write_file':
    case 'edit_file':
    case 'notebook_edit':
      return Pencil
    case 'read_file':
      return FileText
    case 'list_dir':
      return FolderOpen
    case 'grep':
      return Search
    case 'web_search':
    case 'web_fetch':
      return Globe
    case 'get_stock_overview':
      return BarChart3
    case 'get_stock_financials':
      return FileText
    case 'get_stock_technicals':
      return TrendingUp
    case 'get_stock_position':
      return DollarSign
    case 'get_stock_fund_flow':
      return TrendingUp
    default:
      return Terminal
  }
}

export function AgentTrace({ activities, isRunning }: AgentTraceProps) {
  const { t } = useTranslation()
  const visible = activities.filter((a) => a.kind === 'tool' && a.toolName && !shouldHideTool(a.toolName))

  const [expanded, setExpanded] = useState(isRunning)

  useEffect(() => {
    queueMicrotask(() => {
      if (isRunning) {
        setExpanded(true)
      } else if (visible.length > 0) {
        setExpanded(false)
      }
    })
  }, [isRunning, visible.length])

  if (visible.length === 0 && !isRunning) {
    return null
  }

  const doneCount = visible.filter((a) => a.status === 'done').length
  const errorCount = visible.filter((a) => a.status === 'error').length
  const runningCount = visible.filter((a) => a.status === 'running').length

  const summary = isRunning
    ? t('agent.trace.running', { count: visible.length })
    : errorCount > 0
      ? t('agent.trace.doneWithErrors', { done: doneCount, errors: errorCount })
      : t('agent.trace.done', { count: doneCount || visible.length })

  return (
    <div
      className={`agent-trace ${isRunning ? 'agent-trace--running' : 'agent-trace--done'}`}
    >
      <button
        type="button"
        className="agent-trace__header"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className="agent-trace__chevron">
          <ChevronRight size={14} className={expanded ? 'agent-trace__chevron-open' : ''} />
        </span>
        <span className="agent-trace__status-dot">
          {isRunning ? (
            <Loader2 size={12} className="agent-trace__spin" />
          ) : errorCount > 0 ? (
            <X size={12} />
          ) : (
            <Check size={12} />
          )}
        </span>
        <span className="agent-trace__summary">{summary}</span>
        {!expanded && runningCount > 0 ? (
          <span className="agent-trace__badge">{runningCount}</span>
        ) : null}
      </button>

      {expanded ? (
        <ul className="agent-trace__list">
          {visible.map((act) => {
            const Icon = toolIcon(act.toolName ?? '')
            return (
              <li
                key={act.id}
                className={`agent-trace__item agent-trace__item--${act.status}`}
              >
                <span className="agent-trace__item-icon">
                  {act.status === 'running' ? (
                    <Loader2 size={12} className="agent-trace__spin" />
                  ) : act.status === 'error' ? (
                    <X size={12} />
                  ) : (
                    <Icon size={12} />
                  )}
                </span>
                <span className="agent-trace__item-label">
                  {formatToolTitle(act.toolName ?? 'tool', act.summary)}
                </span>
                {act.status === 'done' ? (
                  <Check size={11} className="agent-trace__item-check" />
                ) : act.status === 'running' ? (
                  <Circle size={6} className="agent-trace__item-pulse" />
                ) : null}
              </li>
            )
          })}
          {isRunning && visible.length === 0 ? (
            <li className="agent-trace__item agent-trace__item--running">
              <Loader2 size={12} className="agent-trace__spin" />
              <span className="agent-trace__item-label">{t('agent.trace.preparing')}</span>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  )
}
