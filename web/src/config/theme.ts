export type ThemeMode = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'xqtrader-theme'

export function applyTheme(mode: ThemeMode) {
  document.documentElement.setAttribute('data-theme', mode)
  document.documentElement.style.colorScheme = mode
}
