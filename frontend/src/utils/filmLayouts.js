export const FILM_LAYOUTS = [
  { value: 'ink-press', label: 'Ink Press · 纸墨整片模板' },
  { value: 'auto', label: '通用图解 · 默认方案' },
  { value: 'botanical', label: '自然科普 · 插图与图解' },
  { value: 'editorial', label: '清晰图解 · 彩色信息卡' },
  { value: 'technology', label: '深色科技 · 图解排版' },
  { value: 'paper', label: '纸墨字卡 · 图解排版' },
]

export function filmLayoutValue(brief = {}) {
  if (FILM_LAYOUTS.some(item => item.value === brief.filmLayout)) return brief.filmLayout
  if (brief.templateId === 'ink-press' || brief.mode === 'template') return 'ink-press'
  return FILM_LAYOUTS.some(item => item.value === brief.filmTheme) ? brief.filmTheme : 'auto'
}

export function filmLayoutFields(value) {
  if (!FILM_LAYOUTS.some(item => item.value === value)) throw new Error('请选择已有模板或画面方案')
  return { filmLayout: value, filmTheme: value === 'ink-press' ? 'paper' : value === 'auto' ? 'editorial' : value,
    production: 'motion', mode: value === 'ink-press' ? 'template' : 'autonomous',
    templateId: value === 'ink-press' ? value : '' }
}
