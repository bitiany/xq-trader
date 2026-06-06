import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, ChevronDown, GripVertical, Send, Sparkles, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useAgentStore } from '@/stores/agentStore'
import { useLayoutStore } from '@/stores/layoutStore'
import { useLocaleStore } from '@/stores/localeStore'
import { AgentTrace } from './AgentTrace'
import './AgentPanel.css'

export function AgentPanel() {
  const { t } = useTranslation()
  const locale = useLocaleStore((s) => s.locale)
  const messages = useAgentStore((s) => s.messages)
  const activities = useAgentStore((s) => s.activities)
  const isTyping = useAgentStore((s) => s.isTyping)
  const traceRunning = useAgentStore((s) => s.traceRunning)
  const selectedModel = useAgentStore((s) => s.selectedModel)
  const sendMessage = useAgentStore((s) => s.sendMessage)
  const resetWelcome = useAgentStore((s) => s.resetWelcome)
  const pageContext = useAgentStore((s) => s.pageContext)
  const setPageContext = useAgentStore((s) => s.setPageContext)
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

  useEffect(() => {
    resetWelcome()
  }, [locale, resetWelcome])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, activities, isTyping, traceRunning])

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

  const lastUserIdx = messages.map((m) => m.role).lastIndexOf('user')
  const showTrace =
    (traceRunning || activities.length > 0) && lastUserIdx >= 0

  const showTypingDots =
    isTyping &&
    messages.length > 0 &&
    messages[messages.length - 1]?.role === 'assistant' &&
    !messages[messages.length - 1]?.content &&
    activities.length === 0

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
          <Bot size={12} />
          <span>{selectedModel}</span>
          <ChevronDown size={12} />
        </button>
      </header>

      {pageContext?.stock_symbol ? (
        <div className="agent-panel__context-tag">
          <Sparkles size={10} />
          <span>{pageContext.stock_symbol}</span>
          <button
            type="button"
            className="agent-panel__context-tag-close"
            onClick={() => setPageContext(null)}
            aria-label="清除上下文"
          >
            <X size={10} />
          </button>
        </div>
      ) : null}

      <div className="agent-panel__messages">
        {messages.map((msg, index) => (
          <div key={msg.id} className="agent-panel__turn">
            {msg.role === 'user' ? (
              <div className="agent-panel__message agent-panel__message--user">
                <div className="agent-panel__bubble">{msg.content}</div>
              </div>
            ) : null}

            {msg.role === 'user' && index === lastUserIdx && showTrace ? (
              <AgentTrace activities={activities} isRunning={traceRunning} />
            ) : null}

            {msg.role === 'assistant' ? (
              <div className="agent-panel__message agent-panel__message--assistant">
                <div className="agent-panel__avatar">
                  <Sparkles size={12} />
                </div>
                <div className="agent-panel__bubble">
                  {msg.content}
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
            <div className="agent-panel__bubble agent-panel__typing">
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
