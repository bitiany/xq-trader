import { create } from 'zustand'
import i18n from '@/i18n'
import { agentChatApi, subscribeAgentRun, type AgentMessageContext, type AgentStreamEvent } from '@/api/agent'
import { parseToolArgs, shouldHideTool } from '@/utils/agentTrace'

export type AgentActivityStatus = 'running' | 'done' | 'error'

export interface AgentActivity {
  id: string
  kind: 'tool'
  toolName: string
  callId?: string
  summary?: string
  status: AgentActivityStatus
  timestamp: number
}

export interface AgentMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  streaming?: boolean
}

interface AgentState {
  sessionId: string | null
  messages: AgentMessage[]
  activities: AgentActivity[]
  isTyping: boolean
  traceRunning: boolean
  selectedModel: string
  pageContext: AgentMessageContext | null
  sendMessage: (content: string, context?: AgentMessageContext) => Promise<void>
  resetWelcome: () => void
  setSelectedModel: (model: string) => void
  setPageContext: (context: AgentMessageContext | null) => void
}

let closeStream: (() => void) | null = null
let streamBuffer = ''

function createWelcomeMessage(): AgentMessage {
  return {
    id: 'welcome',
    role: 'assistant',
    content: i18n.t('agent.welcome'),
    timestamp: Date.now(),
  }
}

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

function finishRunningActivities(activities: AgentActivity[]): AgentActivity[] {
  return activities.map((a) =>
    a.status === 'running' ? { ...a, status: 'done' as const } : a,
  )
}

function upsertToolActivity(
  activities: AgentActivity[],
  patch: { callId?: string; toolName: string; status: AgentActivityStatus; summary?: string },
): AgentActivity[] {
  const { callId, toolName, status, summary } = patch
  let idx = -1
  if (callId) {
    idx = activities.findIndex((a) => a.callId === callId && a.status === 'running')
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
  }
  return next
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

export const useAgentStore = create<AgentState>((set, get) => ({
  sessionId: null,
  messages: [createWelcomeMessage()],
  activities: [],
  isTyping: false,
  traceRunning: false,
  selectedModel: 'Qwen3-235B',
  pageContext: null,
  setSelectedModel: (model) => set({ selectedModel: model }),
  setPageContext: (context) => set({ pageContext: context }),

  resetWelcome: () => {
    closeStream?.()
    closeStream = null
    streamBuffer = ''
    set({
      sessionId: null,
      messages: [createWelcomeMessage()],
      activities: [],
      isTyping: false,
      traceRunning: false,
    })
  },

  sendMessage: async (content, context) => {
    const trimmed = content.trim()
    if (!trimmed || get().isTyping) {
      return
    }

    const effectiveContext = context ?? get().pageContext

    closeStream?.()
    closeStream = null
    streamBuffer = ''

    let messageFinalized = false

    const settleTrace = () => {
      set((s) => ({
        activities: finishRunningActivities(s.activities),
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
        },
      ],
      activities: [],
      isTyping: true,
      traceRunning: true,
    }))

    const ensureSession = async (): Promise<string> => {
      const existing = get().sessionId
      if (existing) {
        return existing
      }
      const session = await agentChatApi.createSession({
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
        messages: patchLastAssistant(s.messages, text, false),
        activities: finishRunningActivities(s.activities),
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
            activities: [
              ...s.activities,
              {
                id: callId || `tool-${name}-${Date.now()}`,
                kind: 'tool',
                toolName: name,
                callId: callId || undefined,
                summary: summary || undefined,
                status: 'running',
                timestamp: Date.now(),
              },
            ],
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
          set((s) => ({
            activities: upsertToolActivity(s.activities, {
              callId: String(event.payload.call_id ?? ''),
              toolName: name,
              status: status === 'error' ? 'error' : 'done',
              summary: summary || undefined,
            }),
          }))
          break
        }
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
      const result = await agentChatApi.submitMessage(sessionId, trimmed, undefined, effectiveContext ?? undefined)
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
