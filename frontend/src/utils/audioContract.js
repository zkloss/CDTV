// Stable voice descriptions are distinct from the performance of one line.
export function stableVoicePrompt(value) {
  return String(value || '').replace(/清晰紧张质地/g, '清晰自然质地')
    .split(/[+，；;]/).map(s => s.trim())
    .filter(s => s && !/喘息|气喘|粗重呼吸|带颤音|急促|嘶吼|哭腔|低微呼吸|苍老低微/.test(s))
    .join('，')
}

export function cleanAudioPrompt(value) {
  const seen = new Set()
  return String(value || '').split(/[；;]/).map(s => {
    s = s.trim()
    return /^【统一音色[·・]/.test(s) ? stableVoicePrompt(s) : s
  }).filter(s => s && !seen.has(s) && seen.add(s)).join('；')
}

export function cleanShotAudioPrompt(value) {
  return String(value || '').split('\n').map(line => {
    const m = line.match(/^(\s*(?:音频提示词|音频|声音)[：:])(.*)$/)
    return m ? m[1] + cleanAudioPrompt(m[2]) : line
  }).join('\n')
}

export function collectAudioPrompts(audios, refIds, text) {
  const characters = refIds.filter(id => String(id).startsWith('char_'))
  const prompts = new Set()
  for (const aud of audios) {
    const id = String(aud.id || '')
    const voice = aud.category === 'voice' || id.startsWith('aud_vo_')
    const matched = voice ? characters.some(cid => id === `aud_vo_${cid.slice(5)}`)
      : (/door/.test(id) && /撞开|木门|门板/.test(text))
        || (/footstep/.test(id) && /狂奔|脚步|冲刺/.test(text))
        || (/breath/.test(id) && /喘息|气喘/.test(text))
        || (/kowtow/.test(id) && /磕头|双膝跪地/.test(text))
    if (!matched) continue
    if (!refIds.includes(id)) refIds.push(id)
    const prompt = voice ? stableVoicePrompt(aud.prompt) : String(aud.prompt || '').trim()
    if (prompt) prompts.add(prompt)
  }
  return [...prompts]
}

const NON_DIALOGUE_PREFIXES = [
  '一致性引用', '接线单', '画面', '运镜', '景别', '提示词', '音频提示词', '音频', '声音',
  '环境音', '环境声', '音效', 'bgm', '背景音乐', '动作', '时间', '天气', '场景', '时空',
  '转场', '剪辑', '拍摄约束', '约束', '红线', '【时空与天气连续性】', '【自动转场安排',
  '【剪辑交接', '【00:', '【本镜动作】', '【时地背景】'
]

const EXPLICIT_DIALOGUE_LABEL = /^\s*(?:【\s*(对白|台词|画外音|旁白|内心独白|独白|解说|解说词|vo|os)\s*】|(对白|台词|画外音|旁白|内心独白|独白|解说|解说词|vo|os))\s*[：:]\s*(.*)$/i
const NONE_RE = /^(?:无|无对白|无台词|无旁白|无画外音|无内心独白|none|silence)(?=$|[。.!！\s，,；;])/i
const CHAR_SPEECH = /^\s*([^\s（(：:【】“"「『]{1,15})\s*(?:[（(]([^）)]+)[）)])?\s*[：:]\s*([“"「『‘\'].+[”"」』’\'])\s*$/

export function dialogueContract(prompt) {
  const lines = [], roles = [], deliveries = [], errors = []
  const seenBlocks = new Set()
  let explicitNone = false

  for (const raw of String(prompt || '').split('\n')) {
    const line = raw.trim()
    if (!line) continue

    // Absolute blacklist: metadata and scene instructions are never dialogue
    if (NON_DIALOGUE_PREFIXES.some(p => line.startsWith(p))) continue

    let defaultRole = ''
    let body = ''
    let isDialogueLine = false

    const labelM = line.match(EXPLICIT_DIALOGUE_LABEL)
    if (labelM) {
      isDialogueLine = true
      const lbl = (labelM[1] || labelM[2] || '').toLowerCase()
      if (['旁白', '画外音', '内心独白', '独白', '解说', '解说词', 'vo', 'os'].includes(lbl)) {
        defaultRole = ['旁白', 'vo', 'os', '画外音', '解说', '解说词'].includes(lbl) ? '旁白' : '内心独白'
      }
      body = labelM[3].trim()
      if (NONE_RE.test(body)) {
        explicitNone = true
        continue
      }
    } else {
      const charM = line.match(CHAR_SPEECH)
      if (charM) {
        isDialogueLine = true
        const candRole = charM[1].trim()
        defaultRole = ['旁白', '画外音', '独白', '解说'].includes(candRole) ? '旁白' : candRole
        body = line
      }
    }

    if (!isDialogueLine) continue

    // Find quoted strings
    const quoteMatches = [...body.matchAll(/[“"]([^”"]+)[”"]|[「]([^」]+)[」]|[『]([^』]+)[』]/g)]
    const block = []

    if (quoteMatches.length > 0) {
      let prevEnd = 0
      for (const q of quoteMatches) {
        const text = q[1] || q[2] || q[3] || ''
        const prefix = body.slice(prevEnd, q.index).trim().replace(/^[；;，, ：:【】〖〗\t]+|[；;，, ：:【】〖〗\t]+$/g, '')
        let role = prefix.replace(/[（(][^）)]*[）)]/g, '').replace(/^[ ：:]+|[ ：:]+$/g, '')
        if (!role || role === '对白' || role === '台词') {
          role = defaultRole || '旁白'
        }
        const deliveryMatches = [...prefix.matchAll(/[（(]([^）)]+)[）)]/g)]
        const delivery = deliveryMatches.map(dm => dm[1].trim()).filter(Boolean).join('，')
        block.push({
          role,
          text: text.trim(),
          delivery,
        })
        prevEnd = q.index + q[0].length
      }
    } else {
      // Unquoted dialogue line ONLY when explicit label is present
      const colonM = body.match(/^(?:([^：:（(\s]{1,15})\s*(?:[（(]([^）)]+)[）)])?\s*[：:])?\s*(.+)$/)
      if (colonM && colonM[3]?.trim()) {
        let extractedRole = colonM[1]?.trim() || defaultRole || '旁白'
        if (extractedRole === '对白' || extractedRole === '台词') extractedRole = defaultRole || '旁白'
        const extractedDelivery = (colonM[2] || '').trim()
        let extractedText = colonM[3].trim().replace(/^[“"「『‘\']|[”"」』’\']$/g, '').trim()
        if (extractedText && !NONE_RE.test(extractedText)) {
          block.push({
            role: extractedRole,
            text: extractedText,
            delivery: extractedDelivery,
          })
        }
      }
    }

    const signature = JSON.stringify(block.map(item => [item.role, item.text]))
    if (seenBlocks.has(signature)) continue
    seenBlocks.add(signature)

    for (const item of block) {
      roles.push(item.role)
      deliveries.push(item.delivery)
      lines.push(item.text)
    }
  }

  if (explicitNone && lines.length) errors.push('无对白与有台词要求冲突，请保留一种')
  return { version: 1, lines, roles, deliveries, text: lines.join('\n'), explicit: lines.length > 0 || explicitNone, errors }
}

export const STANDARD_VOICE_PRESETS = [
  { id: 'narrator_epic', label: '🎙️ 雄浑厚重旁白', text: '成熟男性，男低音，声音雄浑厚重，低沉磁性，胸腔共鸣充沛，语气庄重沉稳、富有史诗叙事感，语速舒缓从容，字字千钧，吐字清晰有力，普通话标准。' },
  { id: 'narrator_weathered', label: '📜 沧桑史诗旁白', text: '成熟男性，男低音，声音雄浑厚重，低沉磁性带岁月沧桑颗粒感，胸腔共鸣扎实，声线沉稳大气，富有史诗叙事厚重感，吐字清晰沉着，语速舒缓从容，普通话标准。' },
  { id: 'narrator_powerful', label: '👑 霸气掷地有声', text: '壮年男性，男中低音，声音雄浑厚重、刚劲有力，胸腔共鸣充沛，声线霸气威严、掷地有声，中气十足，字字铿锵，富有号召力与穿透力，普通话标准。' },
  { id: 'narrator_solemn', label: '⚖️ 庄严肃穆旁白', text: '成熟男性，男低音，声音雄浑厚重，庄严肃穆，胸腔共鸣稳固，声线冷峻深沉，语速从容沉着，字字千钧，吐字清晰有力，普通话标准。' },
  { id: 'male_hero', label: '⚔️ 坚毅热血男主', text: '青年男性，约20岁，清亮有韧性的青年正音，音质清澈坚毅，低频微带磁性，声线刚强不屈、热血坚定，咬字干脆利落，气息稳定，普通话标准。' },
  { id: 'male_villain', label: '🦹 傲慢轻蔑反派', text: '青年男性，反派男音，声线轻慢刺耳带嘲弄不屑感，语调居高临下扬高，带有冷笑质感，咬字尖锐，普通话标准。' },
  { id: 'male_elder', label: '👴 沉稳沧桑老者', text: '资深老者，老年男性，低沉浑厚略带沙哑苍老，胸腔共鸣温厚，语气从容深邃，充满岁月阅历感，语速舒缓沉稳，普通话标准。' },
  { id: 'female_gentle', label: '🌸 温婉清澈女主', text: '年轻女性，声音温柔甜美治愈，声线清澈温润，呼吸自然轻盈，语气亲切舒缓，富有感染力，普通话标准。' },
  { id: 'weak_character', label: '🍂 虚弱重伤少年', text: '少年男性，声音虚弱微颤，略带沙哑气音，语气无助微弱，呼吸声微促，轻声细语，普通话标准。' },
]

export function extractRoleVoiceInstruction(prompt, role, delivery = '', character = null) {
  const promptStr = String(prompt || '')
  const delivStr = String(delivery || '')

  // 1. Check for narrator / voiceover
  if (['旁白', '画外音', '解说', '解说词'].includes(role)) {
    const combined = `${promptStr} ${delivStr}`
    if (/掷地有声|霸气|强力|震撼|爆发/.test(combined)) {
      return STANDARD_VOICE_PRESETS.find(p => p.id === 'narrator_powerful').text
    }
    if (/肃穆|庄重|冷峻|压迫/.test(combined)) {
      return STANDARD_VOICE_PRESETS.find(p => p.id === 'narrator_solemn').text
    }
    if (/沧桑|沙哑|岁月|远古|三千年|悲壮/.test(combined)) {
      return STANDARD_VOICE_PRESETS.find(p => p.id === 'narrator_weathered').text
    }
    return STANDARD_VOICE_PRESETS.find(p => p.id === 'narrator_epic').text
  }

  // 2. Character-specific standard detection
  const charDesc = character?.description || character?.prompt || ''
  const combinedInfo = `${role} ${delivStr} ${promptStr} ${charDesc}`
  if (/老人|老者|老头|师尊|师父|掌门|爷爷|六十|七十|陈守一/.test(combinedInfo)) {
    return STANDARD_VOICE_PRESETS.find(p => p.id === 'male_elder').text
  }
  if (/弟子|反派|恶徒|狗腿|嘲讽|嫌恶|不屑|傲慢|冷笑/.test(combinedInfo)) {
    return STANDARD_VOICE_PRESETS.find(p => p.id === 'male_villain').text
  }
  if (/乞丐|虚弱|重伤|濒死|微弱|有毒|颤抖|求救/.test(combinedInfo)) {
    return STANDARD_VOICE_PRESETS.find(p => p.id === 'weak_character').text
  }
  if (/女|少女|师妹|师姐|仙子|苏兰|小妹|姑娘/.test(combinedInfo)) {
    return STANDARD_VOICE_PRESETS.find(p => p.id === 'female_gentle').text
  }
  if (/林北|林枫|男主|少侠|少年|青年/.test(combinedInfo)) {
    return STANDARD_VOICE_PRESETS.find(p => p.id === 'male_hero').text
  }

  return STANDARD_VOICE_PRESETS.find(p => p.id === 'narrator_epic').text
}

export function sameDialogue(a, b) {
  const norm = v => String(v).normalize('NFKC').replace(/[\p{P}\p{Z}\s]/gu, '').toLowerCase()
  return Boolean(a?.explicit && b?.explicit)
    && JSON.stringify(a.lines.map(norm)) === JSON.stringify(b.lines.map(norm))
    && (a.roles === undefined || JSON.stringify(a.roles) === JSON.stringify(b.roles))
}
