import { Languages } from 'lucide-react'
import { Dropdown, Tooltip } from 'antd'
import type { MenuProps } from 'antd'
import { useTranslation } from 'react-i18next'
import { LOCALE_OPTIONS, type AppLocale } from '@/config/locale'
import { useLocaleStore } from '@/stores/localeStore'

export function LocaleSwitch() {
  const { t } = useTranslation()
  const locale = useLocaleStore((s) => s.locale)
  const setLocale = useLocaleStore((s) => s.setLocale)

  const items: MenuProps['items'] = LOCALE_OPTIONS.map((opt) => ({
    key: opt.value,
    label: t(opt.labelKey),
  }))

  return (
    <Dropdown
      menu={{
        items,
        selectable: true,
        selectedKeys: [locale],
        onClick: ({ key }) => setLocale(key as AppLocale),
      }}
      trigger={['click']}
      classNames={{ root: 'topbar__pref-dropdown' }}
    >
      <Tooltip title={t('topbar.language')}>
        <button type="button" className="topbar__icon-btn" aria-label={t('topbar.language')}>
          <Languages size={15} />
        </button>
      </Tooltip>
    </Dropdown>
  )
}
