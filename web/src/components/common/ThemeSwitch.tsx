import { Moon, Sun } from 'lucide-react'
import { Dropdown, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { useTranslation } from 'react-i18next'
import { useThemeStore } from '@/stores/themeStore'
import type { ThemeMode } from '@/config/theme'

export function ThemeSwitch() {
  const { t } = useTranslation()
  const mode = useThemeStore((s) => s.mode)
  const setMode = useThemeStore((s) => s.setMode)

  const items: MenuProps['items'] = [
    { key: 'dark', icon: <Moon size={13} />, label: t('settings.theme.dark') },
    { key: 'light', icon: <Sun size={13} />, label: t('settings.theme.light') },
  ]

  return (
    <Dropdown
      menu={{
        items,
        selectable: true,
        selectedKeys: [mode],
        onClick: ({ key }) => setMode(key as ThemeMode),
      }}
      trigger={['click']}
      classNames={{ root: 'topbar__pref-dropdown' }}
    >
      <Tooltip title={t('topbar.theme')}>
        <button type="button" className="topbar__icon-btn" aria-label={t('topbar.theme')}>
          {mode === 'dark' ? <Moon size={15} /> : <Sun size={15} />}
        </button>
      </Tooltip>
    </Dropdown>
  )
}
