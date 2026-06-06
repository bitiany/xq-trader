import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import i18n from '@/i18n'
import { DEFAULT_LOCALE, LOCALE_STORAGE_KEY, type AppLocale } from '@/config/locale'

interface LocaleState {
  locale: AppLocale
  setLocale: (locale: AppLocale) => void
}

export const useLocaleStore = create<LocaleState>()(
  persist(
    (set) => ({
      locale: DEFAULT_LOCALE,
      setLocale: (locale) => {
        void i18n.changeLanguage(locale)
        set({ locale })
      },
    }),
    {
      name: LOCALE_STORAGE_KEY,
      onRehydrateStorage: () => (state) => {
        if (state?.locale) {
          void i18n.changeLanguage(state.locale)
        }
      },
    },
  ),
)
