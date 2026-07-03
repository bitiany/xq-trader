import { API_BASE_URL } from '@/api/config'
import { request } from '@/api/client'

export interface AgentSession {
  session_id: string
  session_key?: string | null
  title?: string | null
  model?: string | null
  created_at: string
}

export interface SubmitMessageResult {
  run_id: string
  session_id: string
  status: string
}

export interface ToolCallFunction {
  name: string
  arguments: string
}

export interface ToolCallInfo {
  id: string
  type: string
  function: ToolCallFunction
}

export interface HistoryMessage {
  role: 'user' | 'assistant' | 'tool'
  content: string
  timestamp: string
  tool_calls?: ToolCallInfo[]
  tool_call_id?: string
  name?: string
}

export interface SessionHistory {
  session_key: string
  messages: HistoryMessage[]
}

export interface AgentMessageContext {
  stock_symbol?: string
  page_source?: string
  [key: string]: unknown
}

export interface AgentStreamEvent {
  v: number
  type: string
  run_id: string
  session_id: string
  timestamp: string
  payload: Record<string, unknown>
}

export const agentChatApi = {
  createSession(payload?: { session_key?: string; title?: string; model?: string }) {
    return request.post<AgentSession>('/agent/sessions', payload ?? {})
  },

  fetchHistory(sessionKey: string) {
    return request.get<SessionHistory>('/agent/history', {
      params: { session_key: sessionKey },
    })
  },

  submitMessage(
    sessionId: string,
    content: string,
    model?: string,
    context?: AgentMessageContext,
  ) {
    return request.post<SubmitMessageResult>(
      `/agent/sessions/${sessionId}/messages`,
      { content, model, context },
      { validateStatus: (s) => s === 202 || (s >= 200 && s < 300) },
    )
  },
}

/** 订阅 Run SSE；返回关闭函数。 */
export function subscribeAgentRun(
  runId: string,
  handlers: {
    onEvent: (event: AgentStreamEvent) => void
    onError?: (err: Event) => void
    onDone?: () => void
  },
): () => void {
  const token = localStorage.getItem('xqtrader-token')
  const url = new URL(`${API_BASE_URL}/agent/runs/${runId}/stream`, window.location.origin)
  if (token) {
    url.searchParams.set('access_token', token)
  }

  const source = new EventSource(url.toString())

  const handleMessage = (ev: MessageEvent<string>) => {
    try {
      const data = JSON.parse(ev.data) as AgentStreamEvent
      handlers.onEvent(data)
      if (data.type === 'done' || data.type === 'error') {
        handlers.onDone?.()
        source.close()
      }
    } catch {
      /* ignore malformed */
    }
  }

  const eventTypes = [
    'run_start',
    'thinking',
    'token',
    'tool_start',
    'tool_end',
    'subagent_start',
    'subagent_tool',
    'subagent_end',
    'message',
    'error',
    'done',
  ] as const

  for (const name of eventTypes) {
    source.addEventListener(name, handleMessage as EventListener)
  }
  // 勿使用 source.onmessage：与 event: message 重复触发导致回复输出两遍
  source.onerror = (e) => {
    handlers.onError?.(e)
    source.close()
  }

  return () => source.close()
}
