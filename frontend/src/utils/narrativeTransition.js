// A boundary belongs to the incoming shot; both neighbours read that same plan.
import { roleHandoffPlan } from './continuityHandoff.js'
import { environmentInstruction } from './environmentContinuity.js'
export const TRANSITION_OPTIONS = [
  { value: 'sound', label: '声音引出 → 视线反应 → 切镜' },
  { value: 'gaze', label: '视线或运镜引出下一场' },
  { value: 'match', label: '动作或构图呼应切镜' },
  { value: 'establish', label: '环境交代 / 时间跳转' },
  { value: 'none', label: '直接切镜' },
]
const BLOCK_START = '【自动转场安排·开始】'
const BLOCK_END = '【自动转场安排·结束】'
export function stripTransitionBlock(prompt) {
  return String(prompt || '').replace(/【自动转场安排·开始】[\s\S]*?【自动转场安排·结束】\s*/g, '').trim()
}
// The overlay is direction, not request policy: the editor shows it, and the
// generation prompt keeps it once the 【转场边界】 meta line is removed.
export function transitionBlockOf(prompt) {
  const match = String(prompt || '').match(/【自动转场安排·开始】[\s\S]*?【自动转场安排·结束】/)
  return match ? match[0] : ''
}
const textOf = shot => `${shot?.title || ''} ${stripTransitionBlock(shot?.prompt)}`
const sceneOf = shot => String(shot?.sceneId || shot?.scene_id || shot?.references?.find(a => a.category === 'scene')?.id || '')
export function changesScene(previous, current) {
  if (!previous || !current) return false
  const a = sceneOf(previous), b = sceneOf(current)
  if (a && b) return a !== b
  if (/场景转场|空间切换|换场景|场景切换|转场切镜/.test(textOf(current))) return true
  const p = String(previous.title || '').match(/镜\s*(\d+)[-－]/)
  const c = String(current.title || '').match(/镜\s*(\d+)[-－]/)
  return Boolean(p && c && p[1] !== c[1])
}
export function defaultTransition(previous, current) {
  if (roleHandoffPlan([previous, current], current)) return null
  if (!changesScene(previous, current) && current?.inheritPrevTail !== false) return null
  const text = textOf(current)
  const sceneName = current?.references?.find(a => a.category === 'scene')?.name || '下一场景'
  const previousText = textOf(previous)
  const distant = /次日|翌日|数日后|多年后|回忆|梦境|与此同时|另一座|另一处|远在/.test(text)
  const adjacent = !distant && ((/屋内|屋里|室内|破屋内/.test(previousText) && /屋外|门外|村道|街道|室外/.test(text)) || (/屋外|门外|村道|街道/.test(previousText) && /屋内|室内|破屋内/.test(text)))
  const chase = /追赶|追兵|追逐|奔跑|抓住|逃跑|奔逃/.test(text)
  if (adjacent && chase) return { version: 1, strategy: 'sound', enabled: true, source: 'auto',
    outgoing: '末尾约1秒，画外传来远处急促脚步与追赶动静；镜中人物短暂侧耳，视线转向声音方向，镜头小幅顺视线偏移，不离开本场景。',
    incoming: `开场延续急促脚步的节奏，切到${sceneName}交代追逐者与被追者的位置，保持逃跑方向和目光关系清楚，随后执行本镜动作。`,
    cue: '远处追赶脚步声；不新增对白，不重复下一镜整句台词' }
  return { version: 1, strategy: distant ? 'establish' : 'match', enabled: true, source: 'auto',
    outgoing: distant ? '末尾收住当前动作，保留短暂环境余韵，为时间或空间变化留出剪辑点。' : '末尾收住一个明确动作或视线方向，保留稳定构图作为剪辑点；不提前进入下一场景。',
    incoming: distant ? `开场短暂交代${sceneName}的环境和人物位置，清楚表示时空变化，再进入本镜动作。` : `从${sceneName}开始，以运动方向、构图重心或景别呼应上一镜剪辑点，再展开本镜内容；不复制上一场景。`,
    cue: '使用各自场景已有环境音衔接；不假定异地人物能听见彼此，不新增对白' }
}
export function ensureTransitions(shots) {
  shots.forEach((shot, i) => {
    if (!i) return
    if (roleHandoffPlan(shots, shot)) { shot.narrativeTransition = null; return }
    if (shot.narrativeTransition?.source === 'auto' && shot.narrativeTransition.previousShotId && shot.narrativeTransition.previousShotId !== shots[i - 1].id) shot.narrativeTransition = null
    if (!shot.narrativeTransition) {
      const plan = defaultTransition(shots[i - 1], shot)
      if (plan) {
        shot.narrativeTransition = { ...plan, previousShotId: shots[i - 1].id }
        shot.inheritPrevTail = false
      }
    }
  })
  syncTransitionPrompts(shots)
  return shots
}
export function selectTransitionStrategy(previous, current, strategy) {
  const plan = defaultTransition(previous, current) || { version: 1 }
  const descriptions = {
    sound: ['末尾以故事中已有环境声做声音引子，人物只有确实能听到声源时才侧耳转头；异地音桥仅作剪辑连接。', '开头承接声音节奏，先交代声源所在环境与人物位置，再执行本镜动作。', '使用现有环境声音，不额外编造对白或跨时空听觉'],
    gaze: ['末尾让镜中人物的视线落到画面外明确方向，镜头顺视线小幅摇移，停在剪辑点，不提前进入下一场景。', '以建立镜头或对应视线的角度交代本场景，明确人物左右位置，接住上一镜的注视方向。', '保持原有环境音，不新增对白'],
    match: ['末尾以清晰的动作方向或构图重心收住本场景，留下稳定剪辑点。', '开头用相同运动方向或相近构图重心呼应上一镜，明确交代本场景，不复制上一镜环境。', '使用已有环境音连接，不新增对白'],
    establish: ['收住当前动作，保留环境余韵，明确结束本场景。', '开场以环境建立镜头交代本场时空与人物，再进入动作；不暗示人物可听到异地声音。', '使用本场景自身环境音，时间跳跃时可短暂留白'],
    none: ['', '', ''],
  }
  const [outgoing, incoming, cue] = descriptions[strategy] || descriptions.match
  return { ...plan, strategy, outgoing, incoming, cue, enabled: true, source: 'manual', previousShotId: previous?.id }
}
// A cut has no tail frame, so the incoming shot only stays honest if the previous
// shot's last beat is named in its prompt; otherwise it opens the new scene cold.
const ENDING_BEAT = /视线|目光|眼神|看向|望向|转头|回头|侧耳|抬头|低头|停住|结束|反应/
const META_BEAT = /仅作|仅|不要|不得|避免|不再|时才|末尾|开头|剪辑点|构图重心|本场景|稳定/
const META_LINE = /^\s*(运镜|对白|音频|接线单|提示词|一致性引用|【)/
const endingBeatOf = plan => {
  if (!plan?.outgoing || plan.source === 'auto') return ''
  const sentences = String(plan.outgoing)
    .split(/(?<=[。！？；])/)
    .map(s => s.trim())
    .filter(s => s && !META_BEAT.test(s))
  const beat = [...sentences].reverse().find(s => ENDING_BEAT.test(s))
  return beat || sentences[sentences.length - 1] || ''
}
const lastVisualBeat = shot => {
  const lines = stripTransitionBlock(shot?.prompt).split('\n')
  const visual = lines.find(l => /^\s*画面[：:]/.test(l))
  const source = (visual || lines.filter(l => l.trim() && !META_LINE.test(l)).join(' ')).replace(/^\s*画面[：:]\s*/, '')
  const sentences = String(source).split(/(?<=[。！？；])/).map(s => s.trim()).filter(Boolean)
  return sentences[sentences.length - 1] || String(source).trim()
}
export function incomingHandoff(shots, shot) {
  const i = shots.findIndex(s => s.id === shot.id)
  if (i <= 0 || shot.inheritPrevTail !== false) return ''
  const plan = shot.narrativeTransition
  const valid = plan?.enabled !== false && plan?.strategy !== 'none' && (!plan?.previousShotId || plan.previousShotId === shots[i - 1]?.id)
  return (valid && endingBeatOf(plan)) || lastVisualBeat(shots[i - 1])
}
// A gaze that ends on a boundary (door/window/outside) is the one cut a text prompt
// cannot carry: the incoming shot must start from the previous shot's own last frame.
export function gazeHandoffBeat(shots, shot) {
  // A planned cut connects viewpoints; it must not also force a camera push
  // from the old room and discard the incoming scene/character references.
  if (shot?.narrativeTransition?.handoffMode === 'cut') return ''
  const beat = incomingHandoff(shots, shot)
  if (!beat) return ''
  const boundary = /门口|门外|窗外|屋外|远处/
  const gaze = /视线|目光|看向|望向|看到/
  return boundary.test(beat) && gaze.test(beat) ? beat : ''
}
export function transitionPrompt(shots, shot) {
  const i = shots.findIndex(s => s.id === shot.id)
  if (i < 0) return ''
  const parts = []
  const incoming = shot.narrativeTransition
  const outgoing = shots[i + 1]?.narrativeTransition
  const line = value => String(value || '').replace(/\s*\n\s*/g, ' ').trim()
  const valid = (plan, previous) => plan?.enabled !== false && plan?.strategy !== 'none' && (!plan?.previousShotId || plan.previousShotId === previous?.id)
  if (i > 0 && incoming && shot.inheritPrevTail === false && valid(incoming, shots[i - 1])) {
    const beat = line(incomingHandoff(shots, shot))
    const handoff = beat ? `接镜点：上一镜以「${beat}」结束；本镜开场必须与该结尾建立清楚的剪辑关系（视线、动作方向、声源方位至少承接一项），不重放上一镜画面。\n` : ''
    parts.push(`【跨场景入镜·${i}→${i + 1}】${handoff}${line(incoming.incoming)}\n声音线索：${line(incoming.cue)}`)
  }
  if (outgoing && shots[i + 1].inheritPrevTail === false && valid(outgoing, shot)) parts.push(`【跨场景出镜·${i + 1}→${i + 2}】${line(outgoing.outgoing)}\n声音线索：${line(outgoing.cue)}`)
  return parts.length ? `${parts.join('\n')}\n【转场边界】转场安排在本镜既定时长内；先完成正文动作，再按本段安排结束画面。仅生成当前这一镜，不拼接前后视频，不额外生成第二场景。保持原有台词，不把转场说明念出来。` : ''
}

// The editor, persisted project and provider request must show the same plan.
export function promptWithTransition(shots, shot) {
  let body = stripTransitionBlock(shot.prompt)
  const plan = transitionPrompt(shots, shot)
  if (plan.includes('【跨场景出镜·')) {
    body = body.replace(/本镜末尾\s*【留动作】[：:]/g, '本镜后段【动作铺垫】：')
  } else {
    body = body.replace(/本镜后段【动作铺垫】：/g, '本镜末尾【留动作】：')
  }
  const instructions=[environmentInstruction(shots, shot),plan].filter(Boolean).join('\n')
  return instructions ? `${BLOCK_START}\n${instructions}\n${BLOCK_END}\n\n${body}` : body
}

export function syncTransitionPrompts(shots) {
  for (const shot of shots) {
    const prompt = promptWithTransition(shots, shot)
    if (prompt !== String(shot.prompt || '')) shot.prompt = prompt
  }
}
