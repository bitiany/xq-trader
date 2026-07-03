import { useState } from 'react'
import {
  BarChart3,
  Bot,
  Check,
  ChevronRight,
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

function toolIcon(name: string, size = 12) {
  switch (name) {
    case 'write_file':
    case 'edit_file':
    case 'notebook_edit':
      return <Pencil size={size} />
    case 'read_file':
      return <FileText size={size} />
    case 'list_dir':
      return <FolderOpen size={size} />
    case 'grep':
      return <Search size={size} />
    case 'web_search':
    case 'web_fetch':
      return <Globe size={size} />
    case 'get_stock_overview':
      return <BarChart3 size={size} />
    case 'get_stock_financials':
      return <FileText size={size} />
    case 'get_stock_technicals':
    case 'get_stock_technical':
      return <TrendingUp size={size} />
    case 'get_stock_position':
      return <DollarSign size={size} />
    case 'get_stock_fund_flow':
      return <TrendingUp size={size} />
    default:
      return <Terminal size={size} />
  }
}

function StatusIcon({ status }: { status: AgentActivity['status'] }) {
  if (status === 'running') {
    return <Loader2 size={12} className="tool-bubble__spin" />
  }
  if (status === 'error') {
    return <X size={12} />
  }
  return <Check size={12} />
}

/** 工具调用气泡 — trae 风格独立卡片，上方说明，内部结果默认一行可展开。 */
export function ToolBubble({ act }: { act: AgentActivity }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  const hasDetail = Boolean(act.detail)
  const hasArgs = act.args && Object.keys(act.args).length > 0
  const expandable = hasDetail || hasArgs

  return (
    <div className={`tool-bubble tool-bubble--${act.status}`}>
      <button
        type="button"
        className="tool-bubble__header"
        onClick={() => expandable && setExpanded((v) => !v)}
        aria-expanded={expanded}
        disabled={!expandable}
      >
        <span className="tool-bubble__icon">
          {act.status === 'running' ? (
            <Loader2 size={12} className="tool-bubble__spin" />
          ) : (
            toolIcon(act.toolName)
          )}
        </span>
        <span className="tool-bubble__title">
          {formatToolTitle(act.toolName ?? 'tool', act.summary)}
        </span>
        <span className="tool-bubble__status">
          <StatusIcon status={act.status} />
        </span>
        {expandable ? (
          <ChevronRight
            size={11}
            className={`tool-bubble__caret ${expanded ? 'tool-bubble__caret--open' : ''}`}
          />
        ) : null}
      </button>
      {hasDetail && !expanded ? (
        <div className="tool-bubble__preview">{act.detail}</div>
      ) : null}
      {expanded ? (
        <div className="tool-bubble__body">
          {hasArgs ? (
            <pre className="tool-bubble__args">
              {JSON.stringify(act.args, null, 2)}
            </pre>
          ) : null}
          {hasDetail ? (
            <pre className="tool-bubble__result">{act.detail}</pre>
          ) : null}
        </div>
      ) : null}
      {act.status === 'running' && !hasDetail ? (
        <div className="tool-bubble__running">{t('agent.trace.preparing')}</div>
      ) : null}
    </div>
  )
}

/** 子 Agent 气泡 — Bot 图标 + 标签 + 可展开结果。 */
export function SubagentBubble({ act }: { act: AgentActivity }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const hasDetail = Boolean(act.detail)

  return (
    <div className={`tool-bubble tool-bubble--subagent tool-bubble--${act.status}`}>
      <div className="tool-bubble__subagent-bar" />
      <button
        type="button"
        className="tool-bubble__header"
        onClick={() => hasDetail && setExpanded((v) => !v)}
        aria-expanded={expanded}
        disabled={!hasDetail}
      >
        <span className="tool-bubble__icon">
          {act.status === 'running' ? (
            <Loader2 size={13} className="tool-bubble__spin" />
          ) : (
            <Bot size={13} />
          )}
        </span>
        <span className="tool-bubble__title">
          {t('agent.trace.subagent', { label: act.label ?? '' })}
        </span>
        <span className="tool-bubble__status">
          <StatusIcon status={act.status} />
        </span>
      </button>
      {expanded && hasDetail ? (
        <div className="tool-bubble__body">
          <pre className="tool-bubble__result">{act.detail}</pre>
        </div>
      ) : null}
    </div>
  )
}

/** 渲染一组 activity（工具 + 子 Agent），每项独立气泡。 */
export function ActivityList({ activities }: { activities: AgentActivity[] }) {
  const visible = activities.filter(
    (a) => a.kind === 'subagent' || (a.toolName && !shouldHideTool(a.toolName)),
  )
  if (visible.length === 0) {
    return null
  }
  return (
    <div className="activity-list">
      {visible.map((act) =>
        act.kind === 'subagent' ? (
          <SubagentBubble key={act.id} act={act} />
        ) : (
          <ToolBubble key={act.id} act={act} />
        ),
      )}
    </div>
  )
}
