export type AppLocale = 'zh-CN' | 'en-US'

export const LOCALE_STORAGE_KEY = 'xqtrader-locale'

export const LOCALE_OPTIONS: { value: AppLocale; labelKey: string }[] = [
  { value: 'zh-CN', labelKey: 'settings.locale.zhCN' },
  { value: 'en-US', labelKey: 'settings.locale.enUS' },
]

export const DEFAULT_LOCALE: AppLocale = 'zh-CN'
