import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { applyTheme, type ThemeMode, THEME_STORAGE_KEY } from '@/config/theme'

interface ThemeState {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  toggleMode: () => void
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: 'dark',
      setMode: (mode) => {
        applyTheme(mode)
        set({ mode })
      },
      toggleMode: () => {
        const next = get().mode === 'dark' ? 'light' : 'dark'
        applyTheme(next)
        set({ mode: next })
      },
    }),
    {
      name: THEME_STORAGE_KEY,
      onRehydrateStorage: () => (state) => {
        if (state?.mode) {
          applyTheme(state.mode)
        }
      },
    },
  ),
)

applyTheme(useThemeStore.getState().mode)
