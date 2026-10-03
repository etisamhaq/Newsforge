import { useCallback, useEffect, useState } from 'react'

type Theme = 'light' | 'dark'
const STORAGE = 'newsforge.theme'

export function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem(STORAGE)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* ignore */
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(STORAGE, next)
      } catch {
        /* ignore */
      }
      return next
    })
  }, [])
  return { theme, toggle }
}
