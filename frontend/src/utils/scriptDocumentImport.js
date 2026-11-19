// Universal local document parsing. Accepts common screenplay/storyboard formats,
// extracts shots, durations, camera/visual descriptions, dialogues, BGM, and prompts.
export const IMPORT_VERSION = 1
export const MAX_IMPORT_BYTES = 2 * 1024 * 1024

export function cleanLatexMath(s) {
  if (!s) return ''
  return String(s)
    .replace(/\r\n/g, '\n')
    .replace(/\r(?=ightarrow)/gi, 'r')
    .replace(/\$\s*\\+(?:rightarrow|to|longrightarrow)\s*\$/gi, '→')
    .replace(/\\+(?:rightarrow|to|longrightarrow)\b/gi, '→')
    .replace(/\$\s*\\+(?:leftarrow|gets|longleftarrow)\s*\$/gi, '←')
    .replace(/\\+(?:leftarrow|gets|longleftarrow)\b/gi, '←')
    .replace(/\$\s*\\+(?:leftrightarrow)\s*\$/gi, '↔')
    .replace(/\\+(?:leftrightarrow)\b/gi, '↔')
    .replace(/\$\s*\\+(?:Rightarrow|Longrightarrow)\s*\$/gi, '⇒')
    .replace(/\\+(?:Rightarrow|Longrightarrow)\b/gi, '⇒')
    .replace(/([^\w\\]|^)ightarrow\$/gi, '$1→')
    .replace(/\$\s*([^$\n]+?)\s*\$/g, '$1')
    .replace(/\$/g, '')
}

const num = value => {
  if (!value) return 0
  if (/^\d+$/.test(value)) return Number(value)
  const digits = '零一二三四五六七八九'; let result = 0, digit = 0
  for (const c of String(value).replace(/两/g, '二')) {
    if (digits.includes(c)) digit = digits.indexOf(c)
    else if (c === '十') { result += (digit || 1) * 10; digit = 0 }
    else if (c === '百') { result += (digit || 1) * 100; digit = 0 }
  }
  return result + digit
}

const cleanEnglishAnnotations = str => String(str || '')
  .replace(/[（(]\s*[A-Za-z\s,/'-]+\s*[）)]/g, '')
  .replace(/ {2,}/g, ' ')
  .trim()

const plain = line => cleanLatexMath(String(line || ''))
  .trim()
  .replace(/^#{1,6}\s*/, '')
  .replace(/^[-*+]\s+|^>\s?/g, '')
  .replace(/[*_`]/g, '')
  .trim()

const text = lines => (lines || [])
  .map(l => cleanLatexMath(String(l || '')).trim().replace(/^[-*+]\s+|^>\s?/g, '').replace(/[*_`]/g, '').trim())
  .filter(l => l && !/^[-*_]{3,}$/.test(l) && !/^```|^~~~/.test(l))
  .join('\n')
  .trim()

const clock = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`

function parseDurationSeconds(str) {
  if (!str) return null
  const s = String(str)
  let m = s.match(/(\d+(?:\.\d+)?)\s*(?:秒|s\b|sec\b)/i)
  if (m) return Math.round(Number(m[1]))
  m = s.match(/(?:(\d{1,2}):(\d{2}))\s*[-—–~到至]\s*(?:(\d{1,2}):(\d{2}))/)
  if (m) {
    const startSec = Number(m[1]) * 60 + Number(m[2])
    const endSec = Number(m[3]) * 60 + Number(m[4])
    if (endSec > startSec) return endSec - startSec
  }
  m = s.match(/^\s*(\d+)\s*$/)
  if (m) return Number(m[1])
  return null
}

const fieldType = label => {
  const l = String(label || '').toLowerCase().trim()
  if (/画面描述|画面动作|核心分镜|分镜内容|镜头内容|核心动作|视觉描述|视觉|起始画面|首帧|末帧|结束画面|动作|画面/.test(l)) return 'core'
  if (/景别与运镜|运镜与景别|景别|运镜|镜头运动|机位|机位与景别|镜头设计/.test(l)) return 'core'
  if (/时间轴|时长|时间|duration|timecode/.test(l)) return 'duration'
  if (/环境音|环境声|音效|音效\s*[/／]\s*bgm|bgm|背景音乐|音乐|现场声音|现场音|sound|sfx|audio/.test(l)) return 'sound'
  if (/场景|地点|时地|环境|时空|时间与天气|天气|场地/.test(l)) return 'scene'
  if (/角色与资产|出场角色|角色|登场人物|人物|资产/.test(l)) return 'role'
  if (/现场人物对白|人物对白|现场对白|对白|台词|台词\s*[/／]\s*对白|dialogue|lines/.test(l)) return 'dialogue'
  if (/旁白|画外音|内心独白|解说词|解说|narration|voiceover|\bvo\b/.test(l)) return 'narration'
  if (/ai\s*视频生成\s*prompt|prompt\s*建议|视频\s*prompt|prompt|提示词|ai\s*提示词|英文\s*prompt/.test(l)) return 'prompt'
  if (/接点|衔接|交接|转场|剪辑交接/.test(l)) return 'join'
  if (/红线|警示|禁止|本镜约束|拍摄约束|注意事项|约束/.test(l)) return 'constraints'
  return 'archive'
}

function parseShotLine(line) {
  const s = plain(line)
  // 1. #### 镜头 01 / ### 镜头01 / 镜头 01 / 镜头 1:
  let m = s.match(/^(?:镜头|分镜|分镜头|镜)\s*(\d+|[一二两三四五六七八九十]+)(?:[-—–](\d+|[一二两三四五六七八九十]+))?(?:\s*[:：|｜\s-]\s*(.*))?$/i)
  if (m) {
    const n = num(m[1])
    const sub = m[2] ? num(m[2]) : null
    return { number: sub || n, rawNum: sub ? `${n}-${sub}` : `${n}`, title: m[3] || '' }
  }
  // 2. 【镜1-1】 / [镜1-1] / 【镜头 01】 / [Shot 1] / 【分镜 1】
  m = s.match(/^[【\[](?:镜头|分镜|镜|shot|cut)?\s*(\d+|[一二两三四五六七八九十]+)(?:[-—–](\d+|[一二两三四五六七八九十]+))?[】\]]\s*(.*)$/i)
  if (m) {
    const n = num(m[1])
    const sub = m[2] ? num(m[2]) : null
    return { number: sub || n, rawNum: sub ? `${n}-${sub}` : `${n}`, title: m[3] || '' }
  }
  // 3. 第01段 / 第 1 段
  m = s.match(/^第\s*(\d+|[一二两三四五六七八九十]+)\s*段(?:[｜|、:：\s]+(.*))?$/i)
  if (m) {
    const n = num(m[1])
    return { number: n, rawNum: `${n}`, title: m[2] || '' }
  }
  // 4. Shot 01 / Cut 01 / Scene 01
  m = s.match(/^(?:shot|cut|scene)\s*(\d+)(?:\s*[:：|｜\s-]\s*(.*))?$/i)
  if (m) {
    const n = num(m[1])
    return { number: n, rawNum: `${n}`, title: m[2] || '' }
  }
  return null
}

export function autoAdaptScriptText(rawText, name = '分镜文档') {
  const clean = cleanLatexMath(rawText || '').trim()
  if (!clean) return clean
  const lines = clean.split('\n')
  const blocks = []
  let cur = []
  for (const l of lines) {
    const t = l.trim()
    if (!t) {
      if (cur.length) { blocks.push(cur); cur = [] }
      continue
    }
    if (/^(?:[#* ]+)?(?:序[·. ]|第[一二两三四五六七八九十0-9]+[节场幕集]|[0-9一二两三四五六七八九十]+[、. ])/.test(t)) {
      if (cur.length) { blocks.push(cur); cur = [] }
      blocks.push([l])
      continue
    }
    cur.push(l)
  }
  if (cur.length) blocks.push(cur)

  const shots = []
  let shotIndex = 1
  let currentSection = '正片'
  let currentScene = '场景'

  for (const block of blocks) {
    const first = block[0].trim()
    const secM = first.match(/^(?:[#* ]+)?(序[·. ].*|第[一二两三四五六七八九十0-9]+[节场幕集].*|[0-9一二两三四五六七八九十]+[、. ].*)$/)
    if (secM && block.length === 1) {
      currentSection = secM[1].replace(/^[#* ]+/, '').trim()
      continue
    }

    const blockText = block.join('\n')
    let duration = 8
    const durM = blockText.match(/(\d+)\s*(?:秒|s\b)/i)
    if (durM) duration = Math.min(60, Math.max(2, parseInt(durM[1])))

    let camera = ''
    const camM = blockText.match(/(特写|大远景|远景|全景|中景|近景|俯瞰|仰拍|仰视|前推|推近|拉远|摇镜|跟拍|升空|俯冲)/)
    if (camM) camera = camM[1]

    const dialogues = []
    const narrations = []
    const sounds = []
    const cores = []
    const joins = []

    for (const line of block) {
      const l = line.trim()
      const diagM = l.match(/^(?:对白|台词)?\s*([^\s:：]{1,10})\s*[:：]\s*["“](.*?)["”]?$/)
      if (diagM && !/^(?:画面|运镜|场景|时间|时长|音效|环境|转场)/.test(diagM[1])) {
        dialogues.push(`${diagM[1]}："${diagM[2]}"`)
        continue
      }
      const narrM = l.match(/^(?:旁白|画外音|解说词)\s*[:：]\s*(.*)$/)
      if (narrM) { narrations.push(narrM[1]); continue }
      const soundM = l.match(/^(?:环境音|音效|声音|bgm)\s*[:：]\s*(.*)$/i)
      if (soundM) { sounds.push(soundM[1]); continue }
      const joinM = l.match(/^(?:转场|衔接)\s*[:：]\s*(.*)$/)
      if (joinM) { joins.push(joinM[1]); continue }
      const sceneM = l.match(/^(?:场景|时地|地点)\s*[:：]\s*(.*)$/)
      if (sceneM) { currentScene = sceneM[1]; continue }
      cores.push(l)
    }

    const title = `${camera ? camera + '·' : ''}${currentSection}·镜头${String(shotIndex).padStart(2, '0')}`
    const sBlock = [
      `### 镜头 ${String(shotIndex).padStart(2, '0')}：${title}`,
      `【时长】: ${duration}秒`,
      `【场景】: ${currentScene}`,
      `【画面描述】: ${cores.join(' ') || '画面动作演进'}`,
      camera && `【景别与运镜】: ${camera}`,
      dialogues.length && `【对白】: ${dialogues.join(' ')}`,
      narrations.length && `【旁白】: ${narrations.join(' ')}`,
      sounds.length && `【环境音】: ${sounds.join(' ')}`,
      joins.length && `【转场】: ${joins.join(' ')}`
    ].filter(Boolean).join('\n')

    shots.push(sBlock)
    shotIndex++
  }

  const cleanName = (name || '分镜文档').replace(/\.[^.]+$/, '')
  return [
    `# 第1集：${cleanName}（智能适配分镜）`,
    '',
    shots.join('\n\n')
  ].join('\n')
}

export function parseScriptDocument(rawText, name = '分镜文档') {
  const raw = cleanLatexMath(String(rawText || '').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n'))
  if (new TextEncoder().encode(raw).length > MAX_IMPORT_BYTES) throw Error('文档超过 2MB，请按作品拆分后导入')
  if (!raw.trim() || /\u0000/.test(raw)) throw Error('文件为空或不是可读取的文本')

  const preamble = [], tail = [], episodes = [], warnings = [], errors = []
  let episode = null, shot = null, section = null, fenced = false, afterScript = false
  let currentScene = ''

  const addEpisode = (number, title) => {
    episode = { key: `episode-${number}`, number, title: title || `第${number}集`, shots: [] }
    episodes.push(episode)
    shot = null
    section = null
    afterScript = false
  }

  const lines = raw.split('\n')

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    if (/^\s*(?:```|~~~)/.test(line)) {
      fenced = !fenced
      if (shot && section) section.lines.push(line)
      else (afterScript ? tail : preamble).push(line)
      continue
    }
    if (fenced) {
      if (shot && section) section.lines.push(line)
      else (afterScript ? tail : preamble).push(line)
      continue
    }

    // Episode / Chapter detection
    const epMatch = line.match(/^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:第\s*([\d一二两三四五六七八九十百]+)\s*(?:集|幕|篇章|场|章)|(?:episode|act|chapter)\s*(\d+))\s*[:：\s]*(.*?)(?:\*\*)?\s*$/i)
    if (epMatch && !shot) {
      const epNum = num(epMatch[1] || epMatch[2])
      const epTitle = plain(epMatch[3]) || `第${epNum}集`
      if (!episode || (episode.shots.length === 0 && episode.number === 1)) {
        if (!episode) addEpisode(epNum, epTitle)
        else { episode.number = epNum; episode.key = `episode-${epNum}`; episode.title = epTitle }
      }
      continue
    }

    const sceneHeading = line.match(/^\s*(?:#{1,6}\s*)?【场\s*\d+\s+([^】]+)】/)
    if (sceneHeading) {
      currentScene = sceneHeading[1]
      continue
    }

    // Shot detection
    const parsedShot = parseShotLine(line)
    if (parsedShot) {
      if (!episode) {
        addEpisode(1, plain(lines[0]) || name || '第1集')
      }
      const number = episode.shots.length + 1
      const title = parsedShot.title || `镜头${parsedShot.rawNum}`
      const durationFromTitle = parseDurationSeconds(parsedShot.title)

      shot = {
        number,
        rawNum: parsedShot.rawNum,
        key: `${episode.number}-${number}`,
        title,
        scene: currentScene,
        duration: durationFromTitle,
        sections: [],
        rawLines: [line]
      }
      episode.shots.push(shot)
      section = { label: '分镜正文', type: 'core', lines: [] }
      shot.sections.push(section)
      afterScript = false
      continue
    }

    if (/^\s*(?:#{1,6}\s*)?(?:[一二三四五六七八九十]+[、. ]|[0-9]+[、. ])?(?:建议|总结|附录|说明|参考|注意事项|结语|版权|时长预算|预算|AI制作路径|古今用词|文旅赛)/i.test(line) && shot && episode && episode.shots.length > 0) {
      shot = null
      section = null
      afterScript = true
    }

    if (!shot) {
      (afterScript ? tail : preamble).push(line)
      continue
    }

    shot.rawLines.push(line)

    const fieldMatch = line.match(/^\s*(?:[-*+]\s+)?(?:\*\*)?[【\[]?([^】\]\n:*：]+)[】\]]?(?:\*\*)?\s*[:：]\s*(.*)$/)
    if (fieldMatch) {
      const rawLabel = plain(fieldMatch[1])
      const value = fieldMatch[2]
      const type = fieldType(rawLabel)

      if (type === 'duration') {
        const d = parseDurationSeconds(value)
        if (d && !shot.duration) shot.duration = d
      }

      section = {
        label: rawLabel,
        type: type === 'core' ? 'core' : type,
        lines: value ? [value] : []
      }
      shot.sections.push(section)
    } else if (section) {
      section.lines.push(line)
    }
  }

  const shotCount = episodes.reduce((sum, e) => sum + e.shots.length, 0)
  if (!shotCount) {
    try {
      const adapted = autoAdaptScriptText(raw, name)
      if (adapted && adapted !== raw) {
        const adaptedResult = parseScriptDocument(adapted, name)
        if (adaptedResult.shotCount > 0) {
          adaptedResult.warnings.push('✨ 已自动启用智能剧本适配：检测到当前文档为非标准结构或纯文学叙事，系统已自动按场景与动作切分并规范化为分镜')
          return adaptedResult
        }
      }
    } catch (_) {}
    errors.push('未识别到明确分镜。支持“镜头 01”、“【镜1-1】”、“第01段 | 10秒”等格式')
    return { parserVersion: IMPORT_VERSION, name, rawText: raw, episodes: [], rules: [], models: [], archive: { preamble: preamble.join('\n'), tail: tail.join('\n') }, shotCount: 0, duration: 0, warnings: [], errors }
  }

  for (const ep of episodes) {
    const scripts = []
    ep.archive = []

    for (const s of ep.shots) {
      const read = t => s.sections
        .filter(v => v.type === t)
        .map(v => text(v.lines))
        .filter(Boolean)
        .join('\n')

      s.core = cleanEnglishAnnotations(read('core'))
      s.scene = cleanEnglishAnnotations(read('scene')) || s.scene || currentScene
      s.dialogue = read('dialogue')
      s.narration = read('narration')
      s.sound = read('sound')
      s.prompt = read('prompt')
      s.join = read('join')
      s.constraints = read('constraints')

      if (!s.core) {
        const allText = s.sections
          .filter(v => v.type !== 'sound' && v.type !== 'dialogue' && v.type !== 'narration')
          .flatMap(v => v.lines)
          .join('\n')
        s.core = cleanEnglishAnnotations(text([allText])) || s.title || `分镜${s.number}画面动作`
      }

      if (!s.duration || !Number.isInteger(s.duration) || s.duration < 1 || s.duration > 600) {
        s.duration = 8
        warnings.push(`镜头${s.number}未标明确时长，默认设为8秒`)
      }

      if (s.dialogue && /^[（(]?无(?:对白|台词)[^）)]*[）)]?$/i.test(s.dialogue.trim())) {
        s.dialogue = ''
      }

      const scriptBlock = [
        `【镜${s.key}】${s.title || `镜头${s.number}`}`,
        `【00:00-${clock(s.duration)}】`,
        s.scene && `【时地背景】${s.scene}`,
        s.constraints && `【拍摄约束】${s.constraints}`,
        s.core,
        s.dialogue && `对白：${s.dialogue}`,
        s.narration && `旁白：${s.narration}`,
        s.sound && `环境音：${s.sound}`,
        s.join && `【剪辑交接参考，不提前演下一镜】${s.join}`
      ].filter(Boolean).join('\n')

      scripts.push(scriptBlock)

      ep.archive.push({
        shot: s.number,
        title: s.title,
        fields: [
          ...s.sections
            .filter(v => v.type === 'archive' && text(v.lines))
            .map(v => ({ label: v.label, text: text(v.lines) })),
          ...(s.prompt ? [{ label: '原稿 AI 英文提示词', text: s.prompt }] : [])
        ]
      })

      delete s.sections
      delete s.rawLines
    }

    ep.script = scripts.join('\n\n')
    ep.duration = ep.shots.reduce((sum, s) => sum + s.duration, 0)
  }

  const totalDuration = episodes.reduce((sum, e) => sum + e.duration, 0)

  return {
    parserVersion: IMPORT_VERSION,
    name,
    rawText: raw,
    episodes,
    rules: [],
    models: [],
    archive: { preamble: preamble.join('\n'), tail: tail.join('\n') },
    shotCount,
    duration: totalDuration,
    warnings: [...new Set(warnings)],
    errors: [...new Set(errors)]
  }
}

export function decodeScriptFile(bytes) {
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  if (data.byteLength > MAX_IMPORT_BYTES) throw Error('文档超过 2MB')
  let encoding = 'utf-8'
  if (data[0] === 255 && data[1] === 254) encoding = 'utf-16le'
  else if (data[0] === 254 && data[1] === 255) encoding = 'utf-16be'
  try { return new TextDecoder(encoding, { fatal: true }).decode(data) }
  catch { try { return new TextDecoder('gb18030', { fatal: true }).decode(data) } catch { throw Error('文件编码无法识别，请另存为 UTF-8 文本后导入') } }
}

export function lockImportedShots(document, script, importInfo, parseShots) {
  if (!importInfo || importInfo.originalScript !== script) return document
  const expected = parseShots(script, document.consistency || document.assets || {})
  if (expected.length !== importInfo.shotCount) throw Error('导入分镜的完整性校验未通过，请检查正文')
  const byKey = new Map(expected.map(s => [s.sourceShotKey, s]))
  return { ...document, shots: document.shots.map(s => {
    const source = byKey.get(s.sourceShotKey)
    return source ? { ...s, duration_s: source.duration_s, visual: source.visual, video_prompt: source.video_prompt, dialogue: source.dialogue, audio_prompt: source.audio_prompt } : s
  }) }
}
