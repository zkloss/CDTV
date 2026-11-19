import layout from '../../../SKILL/ksr-character-reference-art/assets/role-layout.json'

export const ROLE_REFERENCE_LAYOUT_PROMPT = layout.prompt
export const ROLE_REFERENCE_VERSION = layout.version
export const LEGACY_ROLE_IMAGE_PROMPT = '16:9 横版角色设定图构图。画面左侧为超大高清半身面部特写，突出人物脸部、发型、发饰与上半身服装细节；画面中部为角色全身三视图，从左到右依次展示正面、侧面、背面，三视图严格对齐，比例一致，人物保持完全统一；'

// Remove only the app's own previous boilerplate, never an authored layout.
export function rolePromptWithoutDefaultLayout(value) {
  return String(value || '').replaceAll(LEGACY_ROLE_IMAGE_PROMPT, '').trim()
}

export function hasCustomRoleLayout(value) {
  const prompt = rolePromptWithoutDefaultLayout(value).replaceAll(ROLE_REFERENCE_LAYOUT_PROMPT, '')
  const affirmative = prompt.replace(/(?:禁止|不要|不使用|不用|不画|无须)[^。；\n]*?(?:三视图|四宫格|四格|2\s*[x×]\s*2|character\s*sheet)/gi, '')
  return /三视图|四宫格|四格|九宫格|2\s*[x×]\s*2|character\s*sheet|单张(?:全身|半身|肖像)|只(?:画|要)(?:一张|单张)/i.test(affirmative)
}

export function roleLayoutPrompt(stylePrefix = '') {
  return [String(stylePrefix || '').trim(), '这是角色身份设定板，不是剧情视频；视频中的第一人称不露脸约束不用于设定板上排的两个脸部特写格。', ROLE_REFERENCE_LAYOUT_PROMPT].filter(Boolean).join('。')
}

export function buildRoleReferencePrompt(value, stylePrefix = '', enabled = true) {
  const prompt = rolePromptWithoutDefaultLayout(value)
  if (!enabled || hasCustomRoleLayout(prompt)) return prompt
  // Idempotent if a previously generated prompt is supplied again.
  if (prompt.includes(ROLE_REFERENCE_LAYOUT_PROMPT)) return prompt
  return [prompt, roleLayoutPrompt(stylePrefix)].filter(Boolean).join('\n')
}
