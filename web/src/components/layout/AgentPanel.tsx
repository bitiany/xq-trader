import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GripVertical, Send, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Select } from 'antd'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useAgentStore } from '@/stores/agentStore'
import { useLayoutStore } from '@/stores/layoutStore'
import { useLocaleStore } from '@/stores/localeStore'
import { aiModelApi, normalizeModelList, type AiModelItem } from '@/api/ai/models'
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
  const setSelectedModel = useAgentStore((s) => s.setSelectedModel)
  const sendMessage = useAgentStore((s) => s.sendMessage)
  const loadHistory = useAgentStore((s) => s.loadHistory)
  const sessionKey = useAgentStore((s) => s.sessionKey)
  const agentPanelWidth = useLayoutStore((s) => s.agentPanelWidth)
  const setAgentPanelWidth = useLayoutStore((s) => s.setAgentPanelWidth)

  const [input, setInput] = useState('')
  const [modelOptions, setModelOptions] = useState<{ label: string; value: string }[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  // 加载可用模型列表
  useEffect(() => {
    aiModelApi
      .list({ page: 1, page_size: 100 })
      .then((res) => {
        const items = normalizeModelList(res as never)
        const options = items
          .filter((m: AiModelItem) => m.status !== false)
          .map((m: AiModelItem) => ({
            label: m.name || String(m.id || ''),
            value: m.name || String(m.id || ''),
          }))
        if (options.length > 0) {
          setModelOptions(options)
        }
      })
      .catch(() => {
        // API 不可用时静默回退到默认模型
      })
  }, [])

  // 根据 session scope 动态选择快捷指令：股票页显示标的相关指令，其他页面显示全局指令
  const quickPrompts = useMemo(() => {
    if (sessionKey?.startsWith('stock:')) {
      return [
        t('agent.quickStock.full'),
        t('agent.quickStock.technical'),
        t('agent.quickStock.fund'),
        t('agent.quickStock.basic'),
      ]
    }
    return [
      t('agent.quick.market'),
      t('agent.quick.screening'),
      t('agent.quick.strategy'),
      t('agent.quick.risk'),
    ]
  }, [sessionKey, t])

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
        <Select
          size="small"
          variant="borderless"
          value={selectedModel}
          options={modelOptions}
          onChange={(val) => setSelectedModel(val)}
          className="agent-panel__model-select"
          popupMatchSelectWidth={false}
          showSearch
        />
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
