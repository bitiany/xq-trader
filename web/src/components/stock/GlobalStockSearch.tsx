import { AutoComplete } from 'antd'
import { Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { searchStocks, type StockSearchItem } from '@/api/stock'

function debounce<T extends (...args: [string]) => void>(fn: T, wait: number) {
  let timer: ReturnType<typeof setTimeout> | null = null
  return (value: string) => {
    if (timer) {
      clearTimeout(timer)
    }
    timer = setTimeout(() => fn(value), wait)
  }
}

export function GlobalStockSearch() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [options, setOptions] = useState<Array<{ value: string; label: string }>>([])
  const [loading, setLoading] = useState(false)

  const navigateToStock = useCallback(
    (symbol: string) => {
      navigate(`/stock/${encodeURIComponent(symbol)}`)
      setQuery('')
      setOptions([])
    },
    [navigate],
  )

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        const input = document.querySelector<HTMLInputElement>('.topbar__search-input')
        input?.focus()
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [])

  const runSearch = useMemo(
    () =>
      debounce(async (value: string) => {
        const keyword = value.trim()
        if (!keyword) {
          setOptions([])
          return
        }
        setLoading(true)
        try {
          const items: StockSearchItem[] = await searchStocks(keyword, 12)
          setOptions(items.map((item) => ({ value: item.symbol, label: `${item.name} (${item.symbol})` })))
        } finally {
          setLoading(false)
        }
      }, 250),
    [],
  )

  return (
    <div className="topbar__search topbar__search-wrap">
      <Search size={13} className="topbar__search-icon" />
      <AutoComplete
        value={query}
        options={options}
        style={{ width: '100%' }}
        onSearch={(value) => {
          setQuery(value)
          void runSearch(value)
        }}
        onSelect={(value) => navigateToStock(String(value))}
        notFoundContent={loading ? t('common.loading') : query ? t('stock.search.empty') : null}
      >
        <input
          type="text"
          placeholder={t('topbar.searchPlaceholder')}
          className="topbar__search-input"
          aria-label={t('topbar.globalSearch')}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            void runSearch(event.target.value)
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && options[0]) {
              navigateToStock(options[0].value)
            }
          }}
        />
      </AutoComplete>
      <kbd className="topbar__kbd">⌘K</kbd>
    </div>
  )
}
