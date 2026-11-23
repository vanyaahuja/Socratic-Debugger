import { useEffect, useRef, useState } from 'react'

export default function useTheme() {
  const [theme, setTheme] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  const touched = useRef(false)
  useEffect(() => {
    let live = true
    Promise.resolve(globalThis.chrome?.storage?.local?.get(['theme'])).then((stored) => {
      if (live && !touched.current && ['dark', 'light'].includes(stored?.theme)) setTheme(stored.theme)
    }).catch(() => {})
    return () => { live = false }
  }, [])
  const toggle = () => {
    touched.current = true
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    Promise.resolve(globalThis.chrome?.storage?.local?.set({ theme: next })).catch(() => {})
  }
  return [theme, toggle]
}
