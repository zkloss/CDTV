// Authored shot headings are the source of truth; a nonempty model array can still be incomplete.
const heading = /^(?:#{1,6}\s*|[-*+]\s+)?(?:\*\*)?[【\[]?\s*(?:第\s*(\d+)\s*镜|(?:镜头|分镜|镜)\s*(\d+(?:\s*[-—–－]\s*\d+)?))[】\]]?(?:\*\*)?/
const cleanKey = value => String(value || '').replace(/\s/g, '').replace(/[—–－]/g, '-').split('-').map(Number).join('-')
function tag(value) { const m = String(value || '').trim().match(heading); return m ? { key: cleanKey(m[1] || m[2]), text: m[0] } : null }

export function parseScriptShots(script, consistency = {}, stylePrefix = '') {
  const scenes = Array.isArray(consistency.scenes) ? consistency.scenes : []
  let scene = scenes[0], sceneName = '', block
  const blocks = []
  for (const raw of String(script || '').split(/\r?\n/)) {
    const line = raw.trim()
    const sceneMatch = line.match(/^(?:#{1,6}\s*)?【场\s*\d+\s*([^】]+)】/)
    if (sceneMatch) {
      sceneName = sceneMatch[1].split(/\s*[/／]\s*/)[0].trim()
      scene = scenes.find(s => s.name && (sceneName.includes(s.name) || s.name.includes(sceneName)))
      continue
    }
    const match = tag(line)
    if (match) { block = { key: match.key, title: line.slice(match.text.length).trim(), lines: [], scene, sceneName }; blocks.push(block) }
    else if (block && line && !/^["'}\s]+$/.test(line)) block.lines.push(line)
  }
  return blocks.map((b, index) => {
    const camera = b.title.replace(/^[（(]|[）)]$/g, '').trim() || '固定机位'
    const dialogue = [], visual = [], audio = []
    let duration = 10
    for (const line of b.lines) {
      const environment = line.match(/^(?:【(?:环境音|环境声|音效|现场声音|现场音)】|(?:环境音|环境声|音效|现场声音|现场音))[：:]\s*(.*)$/)
      if (environment) { if (environment[1].trim()) audio.push(environment[1].trim()); continue }
      const t = line.match(/^[【\[]?(\d{1,2}):(\d{2}(?:\.\d+)?)\s*[-—–~～]\s*(\d{1,2}):(\d{2}(?:\.\d+)?)[】\]]?$/)
      if (t) { const span = Number(t[3]) * 60 + Number(t[4]) - Number(t[1]) * 60 - Number(t[2]); if (span > 0) duration = span; continue }
      const spoken = line.replace(/^对白[：:]\s*/, '')
      const speech = spoken.match(/^([^：:。！？]{1,30})[：:]\s*[“"「]/)
      if (speech && !/画面|界面|文字|环境|音效|显示|生成|出现/.test(speech[1])) { dialogue.push(spoken); continue }
      const parts = line.split(/(?:环境音|环境声|音效)[：:]/)
      if (parts[0].trim()) visual.push(parts[0].trim())
      if (parts.length > 1) audio.push(parts.slice(1).join('；').trim())
    }
    const text = `${b.title} ${b.lines.join(' ')} ${b.sceneName}`
    const references = [], wirelist = []
    const add = (a, type) => { if (!a?.id || references.includes(a.id)) return; references.push(a.id); wirelist.push({ slot: `图${wirelist.length + 1}`, asset_id: a.id, name: a.name, type, action: type === 'scene' ? '环境底图' : '主体锚定' }) }
    add(b.scene, 'scene')
    for (const [group, type] of [['characters', 'character'], ['props', 'prop']]) {
      for (const a of Array.isArray(consistency[group]) ? consistency[group] : []) {
        if (a.name && a.name.toLowerCase().trim().split(/\s+/).every(word => text.toLowerCase().includes(word))) add(a, type)
      }
    }
    const picture = visual.join('\n') || b.title
    return { id: `shot_${String(index + 1).padStart(2, '0')}`, sourceShotKey: b.key, title: `【镜${b.key}】${camera}`, duration_s: duration,
      scene_id: b.scene?.id || '', references, wirelist, visual: picture, camera, dialogue,
      audio_prompt: audio.join('；'), video_prompt: [stylePrefix, picture, `运镜：${camera}`].filter(Boolean).join('。') }
  })
}

export function ensureScriptShotCoverage(document, script, stylePrefix = '') {
  if (!document || typeof document !== 'object') return document
  const root = document.consistency || document.assets || document
  const expected = parseScriptShots(script, root, stylePrefix)
  if (!expected.length) return document
  const keys = new Set(expected.map(s => s.sourceShotKey))
  if (keys.size !== expected.length) throw new Error('剧本中有重复的分镜编号，请先改为唯一编号再推送')
  const original = Array.isArray(document.shots) ? document.shots : Array.isArray(root.shots) ? root.shots : []
  const matched = new Map(), unmatched = []
  for (const shot of original) {
    if (!shot || typeof shot !== 'object') continue
    const explicit = shot.sourceShotKey || tag(shot.title)?.key || tag(shot.name)?.key
    const ordinal = String(shot.id || '').match(/^(?:json-shot-)?shot[_-]0*(\d+)$/i)
    const key = explicit ? cleanKey(explicit) : ordinal ? expected[Number(ordinal[1]) - 1]?.sourceShotKey : ''
    if (keys.has(key) && !matched.has(key)) matched.set(key, shot)
    else unmatched.push(shot)
  }
  const ids = new Set(), recovered = []
  const shots = expected.map(fallback => {
    const source = matched.get(fallback.sourceShotKey)
    if (!source) recovered.push(fallback.sourceShotKey)
    const shot = { ...fallback, ...source, sourceShotKey: fallback.sourceShotKey }
    let id = String(shot.id || fallback.id)
    if (ids.has(id)) id = `${fallback.id}_script_${fallback.sourceShotKey}`
    ids.add(id); shot.id = id
    return shot
  })
  return { ...document, shots, shotCoverage: { expected: expected.length, received: original.length, recovered, keys: [...keys] },
    ...(unmatched.length ? { unmappedShots: [...(document.unmappedShots || []), ...unmatched] } : {}) }
}

// Chapter repushes add missing shots without discarding existing video/voice work or local edits.
export function mergePushedItems(existing = [], imported = [], idKey = 'id') {
  if (!Array.isArray(existing) || !existing.length) return Array.isArray(imported) ? [...imported] : []
  if (!Array.isArray(imported) || !imported.length) return [...existing]

  const byId = new Map()
  const byName = new Map()
  existing.forEach(item => {
    if (!item) return
    const id = String(item[idKey] || item.id || '').trim().toLowerCase()
    if (id) byId.set(id, item)
    const name = String(item.name || '').trim().toLowerCase()
    if (name) byName.set(name, item)
  })

  const matchedExisting = new Set()

  const mergedImported = imported.map(incoming => {
    if (!incoming) return incoming
    const id = String(incoming[idKey] || incoming.id || '').trim().toLowerCase()
    const name = String(incoming.name || '').trim().toLowerCase()
    const existingItem = (id ? byId.get(id) : null) || (name ? byName.get(name) : null)
    if (!existingItem) return incoming

    matchedExisting.add(existingItem)
    return {
      ...incoming,
      fileId: existingItem.fileId || incoming.fileId || '',
      coverId: existingItem.coverId || incoming.coverId || '',
      cover: existingItem.cover || incoming.cover || '',
      taskId: existingItem.taskId || incoming.taskId || '',
      resultUrl: existingItem.resultUrl || incoming.resultUrl || '',
      resultFileId: existingItem.resultFileId || incoming.resultFileId || '',
      resultPath: existingItem.resultPath || incoming.resultPath || '',
      generatedPrompt: existingItem.generatedPrompt || incoming.generatedPrompt || '',
      status: existingItem.status || incoming.status || '',
      statusText: existingItem.statusText || incoming.statusText || '',
      progress: existingItem.progress !== undefined ? existingItem.progress : incoming.progress,
    }
  })

  const retainedExisting = existing.filter(item => !matchedExisting.has(item))
  return [...mergedImported, ...retainedExisting]
}
