// Light / Dark / System (PR-SET-01), a per-device presentation preference; never financial state.
export type Theme = 'light' | 'dark' | 'system'
const KEY = 'duit-theme'

export function savedTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY)
    return value === 'light' || value === 'dark' ? value : 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme: Theme) {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.dataset.theme = theme
  try {
    if (theme === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, theme)
  } catch { /* storage blocked: the choice lasts for this page only */ }
}
