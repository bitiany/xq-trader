import { create } from 'zustand'
import i18n from '@/i18n'
import { agentChatApi, subscribeAgentRun, type AgentMessageContext, type AgentStreamEvent, type HistoryMessage } from '@/api/agent'
import { parseToolArgs, shouldHideTool } from '@/utils/agentTrace'

export type AgentActivityStatus = 'running' | 'done' | 'error'
export type AgentActivityKind = 'tool' | 'subagent'

export interface AgentActivity {
  id: string
  kind: AgentActivityKind
  toolName: string
  label?: string
  summary?: string
  detail?: string
  args?: Record<string, unknown>
  status: AgentActivityStatus
  timestamp: number
}

export interface AgentMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  streaming?: boolean
  activities?: AgentActivity[]
}

interface AgentState {
  sessionId: string | null
  sessionKey: string
  sessionScope: string | null
  messages: AgentMessage[]
  isTyping: boolean
  traceRunning: boolean
  selectedModel: string
  sendMessage: (content: string, context?: AgentMessageContext) => Promise<void>
  setSessionScope: (scope?: string | null) => void
  loadHistory: () => Promise<void>
  setSelectedModel: (model: string) => void
}

const SESSION_KEY_STORAGE = 'xqtrader-agent-session-key'
const MODEL_STORAGE = 'xqtrader-agent-model'

function getOrCreateBaseKey(): string {
  try {
    const existing = localStorage.getItem(SESSION_KEY_STORAGE)
    if (existing) {
      return existing
    }
    const uuid =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    const key = `web:${uuid}`
    localStorage.setItem(SESSION_KEY_STORAGE, key)
    return key
  } catch {
    return `web:${Date.now()}`
  }
}

/** 浏览器级稳定基础 key（存 localStorage，跨刷新延续）。 */
const baseSessionKey = getOrCreateBaseKey()

/**
 * 计算 session_key：业务侧页面通过 scope（如 `stock:600519.SH`）直接指定完整 key，
 * 未指定时回退到浏览器级全局 key。Agent 层只当作不透明字符串。
 */
function composeSessionKey(scope?: string | null): string {
  return scope || baseSessionKey
}

let closeStream: (() => void) | null = null
let streamBuffer = ''
let historyLoadingKey: string | null = null

function createWelcomeMessage(): AgentMessage {
  return {
    id: 'welcome',
    role: 'assistant',
    content: i18n.t('agent.welcome'),
    timestamp: Date.now(),
  }
}

function summaryFromArgs(toolName: string, args: Record<string, unknown>): string | undefined {
  const path = args.path ?? args.notebook_path ?? args.directory
  if (typeof path === 'string' && path) {
    return path.split(/[/\\]/).pop() ?? path
  }
  if (toolName === 'grep' && typeof args.pattern === 'string') {
    return args.pattern.slice(0, 48)
  }
  return undefined
}

/**
 * 将后端历史消息（含 tool 角色和 assistant.tool_calls）重建为带嵌入式 activities 的 AgentMessage 列表。
 * 算法：遍历扁平消息流，assistant 的 tool_calls 转为 activity，匹配后续 tool 消息作为结果，
 * 累积到下一条有文本内容的 assistant 消息上。
 */
function historyToMessages(history: HistoryMessage[]): AgentMessage[] {
  const result: AgentMessage[] = []
  let pendingActivities: AgentActivity[] = []

  // 构建 tool_call_id → tool 结果的快速查找表
  const toolResults = new Map<string, HistoryMessage>()
  for (const m of history) {
    if (m.role === 'tool' && m.tool_call_id) {
      toolResults.set(m.tool_call_id, m)
    }
  }

  for (let i = 0; i < history.length; i++) {
    const m = history[i]
    const ts = m.timestamp ? Date.parse(m.timestamp) || Date.now() : Date.now()

    if (m.role === 'user') {
      result.push({
        id: `history-${i}`,
        role: 'user',
        content: m.content,
        timestamp: ts,
      })
    } else if (m.role === 'assistant') {
      if (m.tool_calls) {
        for (const tc of m.tool_calls) {
          if (shouldHideTool(tc.function.name)) continue
          const args = parseToolArgs(tc.function.arguments)
          const toolResult = tc.id ? toolResults.get(tc.id) : undefined
          const isError = toolResult
            ? /error|异常|失败/i.test(toolResult.content)
            : false
          pendingActivities.push({
            id: tc.id || `tool-${i}`,
            kind: 'tool',
            toolName: tc.function.name,
            summary: summaryFromArgs(tc.function.name, args),
            args: Object.keys(args).length > 0 ? args : undefined,
            detail: toolResult?.content,
            status: toolResult ? (isError ? 'error' : 'done') : 'done',
            timestamp: ts,
          })
        }
      }
      if (m.content) {
        result.push({
          id: `history-${i}`,
          role: 'assistant',
          content: m.content,
          timestamp: ts,
          activities: pendingActivities.length > 0 ? pendingActivities : undefined,
        })
        pendingActivities = []
      }
    }
  }

  return result
}

/** 更新最后一条 assistant 消息的 content/streaming 状态。 */
function patchLastAssistant(
  messages: AgentMessage[],
  content: string,
  streaming: boolean,
): AgentMessage[] {
  const last = messages[messages.length - 1]
  if (last?.role === 'assistant' && (last.streaming || streaming)) {
    return [...messages.slice(0, -1), { ...last, content, streaming }]
  }
  if (last?.role === 'assistant' && !streaming && last.content === content) {
    return [...messages.slice(0, -1), { ...last, streaming: false }]
  }
  return [
    ...messages,
    {
      id: `assistant-${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: Date.now(),
      streaming,
    },
  ]
}

/** 对最后一条 assistant 消息的 activities 数组执行变换。 */
function patchLastAssistantActivities(
  messages: AgentMessage[],
  fn: (activities: AgentActivity[]) => AgentActivity[],
): AgentMessage[] {
  const last = messages[messages.length - 1]
  if (!last || last.role !== 'assistant') {
    return messages
  }
  return [
    ...messages.slice(0, -1),
    { ...last, activities: fn(last.activities ?? []) },
  ]
}

function finishRunningActivities(activities: AgentActivity[]): AgentActivity[] {
  return activities.map((a) =>
    a.status === 'running' ? { ...a, status: 'done' as const } : a,
  )
}

function upsertToolActivity(
  activities: AgentActivity[],
  patch: { callId?: string; toolName: string; status: AgentActivityStatus; summary?: string; detail?: string },
): AgentActivity[] {
  const { callId, toolName, status, summary, detail } = patch
  let idx = -1
  if (callId) {
    idx = activities.findIndex((a) => a.id === callId && a.status === 'running')
  }
  if (idx < 0) {
    idx = activities.findIndex((a) => a.toolName === toolName && a.status === 'running')
  }
  if (idx < 0) {
    return activities
  }
  const next = [...activities]
  next[idx] = {
    ...next[idx],
    status,
    summary: summary ?? next[idx].summary,
    detail: detail ?? next[idx].detail,
  }
  return next
}

function upsertSubagent(
  activities: AgentActivity[],
  patch: { taskId: string; label?: string; status: AgentActivityStatus; detail?: string },
): AgentActivity[] {
  const { taskId, label, status, detail } = patch
  const idx = activities.findIndex(
    (a) => a.kind === 'subagent' && a.id === taskId && a.status === 'running',
  )
  if (idx < 0) {
    return activities
  }
  const next = [...activities]
  next[idx] = {
    ...next[idx],
    status,
    label: label ?? next[idx].label,
    detail: detail ?? next[idx].detail,
  }
  return next
}

export const useAgentStore = create<AgentState>((set, get) => ({
  sessionId: null,
  sessionKey: baseSessionKey,
  sessionScope: null,
  messages: [createWelcomeMessage()],
  isTyping: false,
  traceRunning: false,
  selectedModel: localStorage.getItem(MODEL_STORAGE) || 'deepseek-ai/DeepSeek-V3',
  setSelectedModel: (model) => {
    localStorage.setItem(MODEL_STORAGE, model)
    set({ selectedModel: model })
  },

  setSessionScope: (scope) => {
    const nextScope = scope ?? null
    if (nextScope === get().sessionScope) {
      return
    }
    closeStream?.()
    closeStream = null
    streamBuffer = ''
    set({
      sessionScope: nextScope,
      sessionKey: composeSessionKey(nextScope),
      sessionId: null,
      messages: [createWelcomeMessage()],
      isTyping: false,
      traceRunning: false,
    })
  },

  loadHistory: async () => {
    const key = get().sessionKey
    // 去重：同一 key 的并发请求只执行一次
    if (historyLoadingKey === key) {
      return
    }
    historyLoadingKey = key
    try {
      const history = await agentChatApi.fetchHistory(key)
      if (get().sessionKey !== key || get().isTyping) {
        return
      }
      const msgs = historyToMessages(history.messages)
      set({ messages: msgs.length > 0 ? msgs : [createWelcomeMessage()] })
    } catch {
      /* 历史加载失败时保留欢迎语，不阻断对话 */
    } finally {
      historyLoadingKey = null
    }
  },

  sendMessage: async (content, context) => {
    const trimmed = content.trim()
    if (!trimmed || get().isTyping) {
      return
    }

    closeStream?.()
    closeStream = null
    streamBuffer = ''

    let messageFinalized = false

    const settleTrace = () => {
      set((s) => ({
        messages: patchLastAssistantActivities(s.messages, finishRunningActivities),
        traceRunning: false,
        isTyping: false,
      }))
    }

    const userMsg: AgentMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: trimmed,
      timestamp: Date.now(),
    }

    set((s) => ({
      messages: [
        ...s.messages.filter((m) => m.id !== 'welcome'),
        userMsg,
        {
          id: `assistant-pending-${Date.now()}`,
          role: 'assistant',
          content: '',
          timestamp: Date.now(),
          streaming: true,
          activities: [],
        },
      ],
      isTyping: true,
      traceRunning: true,
    }))

    const ensureSession = async (): Promise<string> => {
      const existing = get().sessionId
      if (existing) {
        return existing
      }
      const session = await agentChatApi.createSession({
        session_key: get().sessionKey,
        title: i18n.t('agent.sessionTitle'),
      })
      set({ sessionId: session.session_id })
      return session.session_id
    }

    const finalizeAssistant = (text: string) => {
      if (messageFinalized) {
        return
      }
      messageFinalized = true
      streamBuffer = ''
      set((s) => ({
        messages: patchLastAssistantActivities(
          patchLastAssistant(s.messages, text, false),
          finishRunningActivities,
        ),
        traceRunning: false,
        isTyping: false,
      }))
    }

    const handleStreamEvent = (event: AgentStreamEvent) => {
      switch (event.type) {
        case 'run_start':
          set({ traceRunning: true })
          break
        case 'thinking':
          break
        case 'tool_start': {
          const name = String(event.payload.name ?? 'tool')
          if (shouldHideTool(name)) {
            break
          }
          const callId = String(event.payload.call_id ?? '')
          const args = parseToolArgs(event.payload.arguments)
          const summary =
            String(event.payload.summary ?? '') || summaryFromArgs(name, args)
          set((s) => ({
            traceRunning: true,
            messages: patchLastAssistantActivities(s.messages, (acts) => [
              ...acts,
              {
                id: callId || `tool-${name}-${Date.now()}`,
                kind: 'tool',
                toolName: name,
                summary: summary || undefined,
                args: Object.keys(args).length > 0 ? args : undefined,
                status: 'running',
                timestamp: Date.now(),
              },
            ]),
          }))
          break
        }
        case 'tool_end': {
          const name = String(event.payload.name ?? 'tool')
          if (shouldHideTool(name)) {
            break
          }
          const status = String(event.payload.status ?? 'ok')
          const summary = String(event.payload.summary ?? '')
          const detail = String(event.payload.detail ?? '')
          set((s) => ({
            messages: patchLastAssistantActivities(s.messages, (acts) =>
              upsertToolActivity(acts, {
                callId: String(event.payload.call_id ?? ''),
                toolName: name,
                status: status === 'error' ? 'error' : 'done',
                summary: summary || undefined,
                detail: detail || undefined,
              }),
            ),
          }))
          break
        }
        case 'subagent_start': {
          const taskId = String(event.payload.task_id ?? '')
          const label = String(event.payload.label ?? '子任务')
          set((s) => ({
            traceRunning: true,
            messages: patchLastAssistantActivities(s.messages, (acts) => [
              ...acts,
              {
                id: taskId || `subagent-${Date.now()}`,
                kind: 'subagent',
                toolName: 'spawn',
                label,
                summary: String(event.payload.task ?? '') || undefined,
                status: 'running',
                timestamp: Date.now(),
              },
            ]),
          }))
          break
        }
        case 'subagent_end': {
          const taskId = String(event.payload.task_id ?? '')
          const status = String(event.payload.status ?? 'ok')
          set((s) => ({
            messages: patchLastAssistantActivities(s.messages, (acts) =>
              upsertSubagent(acts, {
                taskId,
                label: String(event.payload.label ?? '') || undefined,
                status: status === 'error' ? 'error' : 'done',
                detail: String(event.payload.result_summary ?? '') || undefined,
              }),
            ),
          }))
          break
        }
        case 'subagent_tool':
          break
        case 'token': {
          const delta = String(event.payload.delta ?? '')
          if (!delta || messageFinalized) {
            return
          }
          streamBuffer += delta
          const buf = streamBuffer
          set((s) => ({
            messages: patchLastAssistant(s.messages, buf, true),
          }))
          break
        }
        case 'message': {
          const text = String(event.payload.content ?? streamBuffer)
          finalizeAssistant(text)
          break
        }
        case 'error':
          finalizeAssistant(
            i18n.t('agent.error', {
              msg: String(event.payload.message ?? 'unknown'),
            }),
          )
          break
        case 'done':
          settleTrace()
          break
        default:
          break
      }
    }

    try {
      const sessionId = await ensureSession()
      const result = await agentChatApi.submitMessage(sessionId, trimmed, get().selectedModel, context)
      closeStream = subscribeAgentRun(result.run_id, {
        onEvent: handleStreamEvent,
        onError: () => {
          finalizeAssistant(i18n.t('agent.streamError'))
        },
        onDone: () => {
          settleTrace()
        },
      })
    } catch {
      finalizeAssistant(i18n.t('agent.requestError'))
    }
  },
}))
