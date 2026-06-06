import type { ReactNode } from 'react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import enUS from 'antd/locale/en_US'
import { getAntdTheme } from '@/config/antdTheme'
import type { AppLocale } from '@/config/locale'
import { useThemeStore } from '@/stores/themeStore'
import { useLocaleStore } from '@/stores/localeStore'

const ANT_LOCALE_MAP = {
  'zh-CN': zhCN,
  'en-US': enUS,
} as const satisfies Record<AppLocale, typeof zhCN>

interface AppProvidersProps {
  children: ReactNode
}

export function AppProviders({ children }: AppProvidersProps) {
  const themeMode = useThemeStore((s) => s.mode)
  const locale = useLocaleStore((s) => s.locale)

  return (
    <ConfigProvider
      locale={ANT_LOCALE_MAP[locale]}
      theme={getAntdTheme(themeMode)}
      componentSize="small"
    >
      {children}
    </ConfigProvider>
  )
}
