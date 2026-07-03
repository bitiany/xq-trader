import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronDown, GripVertical, Send, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useAgentStore } from '@/stores/agentStore'
import { useLayoutStore } from '@/stores/layoutStore'
import { useLocaleStore } from '@/stores/localeStore'
import { ActivityList } from './AgentTrace'
import './AgentPanel.css'

function formatTime(ts: number): string {
  const d = new Date(ts)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

export function AgentPanel() {
  const { t } = useTranslation()
  const locale = useLocaleStore((s) => s.locale)
  const messages = useAgentStore((s) => s.messages)
  const isTyping = useAgentStore((s) => s.isTyping)
  const traceRunning = useAgentStore((s) => s.traceRunning)
  const selectedModel = useAgentStore((s) => s.selectedModel)
  const sendMessage = useAgentStore((s) => s.sendMessage)
  const loadHistory = useAgentStore((s) => s.loadHistory)
  const sessionKey = useAgentStore((s) => s.sessionKey)
  const agentPanelWidth = useLayoutStore((s) => s.agentPanelWidth)
  const setAgentPanelWidth = useLayoutStore((s) => s.setAgentPanelWidth)

  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const quickPrompts = [
    t('agent.quick.momentum'),
    t('agent.quick.backtest'),
    t('agent.quick.risk'),
    t('agent.quick.brief'),
  ]

  // session_key 变化（含挂载、页面切换）或切换语言时，按当前 key 回载历史对话
  useEffect(() => {
    void loadHistory()
  }, [sessionKey, locale, loadHistory])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping, traceRunning])

  const handleSend = () => {
    if (!input.trim() || isTyping) {
      return
    }
    void sendMessage(input)
    setInput('')
  }

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      dragging.current = true
      const startX = e.clientX
      const startWidth = agentPanelWidth

      const onMove = (ev: MouseEvent) => {
        if (!dragging.current) {
          return
        }
        const delta = startX - ev.clientX
        setAgentPanelWidth(startWidth + delta)
      }

      const onUp = () => {
        dragging.current = false
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
      }

      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [agentPanelWidth, setAgentPanelWidth],
  )

  // 判断是否显示打字指示器（assistant 消息为空、无 activities、正在运行）
  const showTypingDots =
    isTyping &&
    messages.length > 0 &&
    messages[messages.length - 1]?.role === 'assistant' &&
    !messages[messages.length - 1]?.content &&
    (messages[messages.length - 1]?.activities ?? []).length === 0

  return (
    <aside className="agent-panel" style={{ width: agentPanelWidth }}>
      <div
        className="agent-panel__resize-handle"
        onMouseDown={handleResizeStart}
        role="separator"
        aria-orientation="vertical"
        aria-label={t('agent.resize')}
      >
        <GripVertical size={12} />
      </div>

      <header className="agent-panel__header">
        <div className="agent-panel__title">
          <Sparkles size={14} className="agent-panel__title-icon" />
          <span>{t('agent.title')}</span>
        </div>
        <button type="button" className="agent-panel__model-btn" disabled>
          <span>{selectedModel}</span>
          <ChevronDown size={12} />
        </button>
      </header>

      <div className="agent-panel__messages">
        {messages.map((msg) => (
          <div key={msg.id} className="agent-panel__turn">
            {msg.role === 'user' ? (
              <div className="agent-panel__message agent-panel__message--user">
                <div className="agent-panel__bubble">{msg.content}</div>
              </div>
            ) : null}
            {msg.role === 'user' ? (
              <div className="agent-panel__msg-time">{formatTime(msg.timestamp)}</div>
            ) : null}

            {msg.role === 'assistant' && msg.activities && msg.activities.length > 0 ? (
              <ActivityList activities={msg.activities} />
            ) : null}

            {msg.role === 'assistant' && msg.content ? (
              <div className="agent-panel__message agent-panel__message--assistant">
                <div className="agent-panel__avatar">
                  <Sparkles size={12} />
                </div>
                <div className="agent-panel__md">
                  <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
                  {msg.streaming ? (
                    <span className="agent-panel__cursor">▍</span>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        ))}
        {showTypingDots ? (
          <div className="agent-panel__message agent-panel__message--assistant">
            <div className="agent-panel__avatar">
              <Sparkles size={12} />
            </div>
            <div className="agent-panel__typing">
              <span />
              <span />
              <span />
            </div>
          </div>
        ) : null}
        <div ref={messagesEndRef} />
      </div>

      <div className="agent-panel__quick">
        {quickPrompts.map((prompt) => (
          <button
            key={prompt}
            type="button"
            className="agent-panel__quick-btn"
            disabled={isTyping}
            onClick={() => {
              void sendMessage(prompt)
            }}
          >
            {prompt}
          </button>
        ))}
      </div>

      <footer className="agent-panel__input-area">
        <textarea
          className="agent-panel__input"
          placeholder={t('agent.placeholder')}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          rows={3}
          disabled={isTyping}
        />
        <button
          type="button"
          className="agent-panel__send"
          onClick={handleSend}
          disabled={!input.trim() || isTyping}
          aria-label={t('agent.send')}
        >
          <Send size={14} />
        </button>
      </footer>
    </aside>
  )
}
