import { theme } from 'antd'
import type { ThemeConfig } from 'antd'
import type { ThemeMode } from '@/config/theme'

const sharedTokens: ThemeConfig['token'] = {
  colorPrimary: '#1677ff',
  colorInfo: '#1677ff',
  colorSuccess: '#389e0d',
  colorError: '#cf1322',
  colorWarning: '#faad14',
  borderRadius: 4,
  fontSize: 12,
  fontFamily:
    "'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
}

export function getAntdTheme(mode: ThemeMode): ThemeConfig {
  const isDark = mode === 'dark'

  return {
    algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      ...sharedTokens,
      ...(isDark
        ? {
            colorBgBase: '#0a0c10',
            colorBgContainer: '#131820',
            colorBgElevated: '#161b24',
            colorBorder: 'rgba(255, 255, 255, 0.08)',
            colorText: '#eef2f8',
            colorTextSecondary: '#9aaabe',
          }
        : {
            colorBgBase: '#eef1f6',
            colorBgContainer: '#ffffff',
            colorBgElevated: '#ffffff',
            colorBorder: '#e2e8f0',
            colorText: '#0f172a',
            colorTextSecondary: '#64748b',
          }),
    },
    components: {
      Button: {
        controlHeight: 26,
        paddingInline: 10,
      },
      Segmented: {
        controlHeight: 26,
      },
      Dropdown: {
        controlHeight: 28,
      },
    },
  }
}
