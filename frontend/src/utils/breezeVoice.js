export const LEGACY_GENERIC_VOICE = '自然中音，干净清晰，普通话，清晰自然，语速适中'
export const STRONG_MALE_VOICE = '壮年男性，约35岁，低沉浑厚的男低音，胸腔共鸣充足，低频厚实有重量，粗犷微沙哑带颗粒感，气息结实，咬字有力，普通话，自然正常语速。声音成熟有威慑力，不使用轻柔青年音、气声或刻意压喉的假低音。保持音色稳定，具体情绪按本句表演。'

const FEMALE_CUES = /女性|女人|少女|女孩|姑娘|妇人|老太|老妪|女士|妈妈|母亲|姐姐|妹妹|阿姨|嫂子|婆婆|奶奶|外婆|女/
const MALE_CUES = /男性|男人|少年|青年|老者|大爷|先生|汉子|师父|师傅|父亲|爸爸|叔叔|伯伯|哥哥|弟弟|爷爷|外公|老头|小伙|儿子|少爷|公子/
const ELDERLY_CUES = /老年|老者|老人|老汉|老太|花甲|古稀|六旬|七旬|银发|白发|灰白|皱纹|沧桑/
const TIMBRE_CUES = /低沉|沙哑|浑厚|沧桑|磁性|颗粒|清亮|清脆|温润|共鸣|醇厚|沉稳|通透|明亮|成熟|老年|壮年|中年|青年|少年|少女/

export function prefersStrongMaleVoice(character) {
  const description = [character?.appearance, character?.description, character?.gender_age, character?.prompt].filter(Boolean).join(' ')
  return /壮汉|彪形大汉|魁梧|粗犷|络腮胡/.test(description) && !/女性|女人/.test(description)
}

function characterAge(character, text) {
  const field = String(character?.age ?? '').match(/\d{1,3}/)
  if (field) return Number(field[0])
  const stated = text.match(/(\d{1,3})\s*岁/)
  if (stated) return Number(stated[1])
  if (/十五六|十五|十六|少年|少女/.test(text)) return 16
  if (/三十|四十|壮年/.test(text)) return 35
  if (/五十|六十|七十|老年|老者|老爷|老太|老妪/.test(text)) return 65
  return 0
}

function characterGender(character, text) {
  const declared = `${character?.gender || character?.sex || ''} ${character?.gender_age || ''}`
  if (/女/.test(declared)) return '女'
  if (/男/.test(declared)) return '男'
  if (FEMALE_CUES.test(text)) return '女'
  if (MALE_CUES.test(text)) return '男'
  return ''
}

export function automaticVoiceInstruction(character, extra = '') {
  const explicit = character?.voice_instruction || character?.voiceInstruction
  if (explicit) return String(explicit)
  const text = [character?.name, character?.gender_age, character?.age, character?.appearance,
    character?.description, character?.personality, character?.temperament, character?.prompt].filter(Boolean).join(' ')
  const age = characterAge(character, text)
  const gender = characterGender(character, text)
  const elderly = age >= 55 || ELDERLY_CUES.test(text)
  const teen = Boolean((age && age < 20) || /十五六|十五|十六|少年|少女/.test(text))
  if (prefersStrongMaleVoice(character) && gender !== '女') return STRONG_MALE_VOICE

  let identity = ''
  if (gender === '女') {
    identity = elderly ? '老年女性，偏低沉的中低音，略带沙哑与岁月感，气息稳，语速从容；避免清亮少女音'
      : teen ? '少女，明亮清透的中高音，有少年感，避免幼童奶音'
        : '成年女性，饱满清晰的中音，成熟自然，有支撑感'
  } else if (gender === '男') {
    identity = elderly ? '老年男性，低沉浑厚的中低音，略带沙哑与颗粒感，胸腔共鸣充足，气息稳健，语速从容；避免清亮青年音'
      : teen ? '少年男性，清亮有韧性的中音，略带变声期质感，避免成熟大叔低音'
        : age >= 30 ? '成年男性，中低音，胸腔共鸣自然，厚实稳健，咬字有力'
          : '青年男性，自然中音，清晰结实，避免过度气声和柔弱感'
  } else if (elderly) {
    identity = '老年声线，偏低沉浑厚的中低音，略带沙哑与岁月感，胸腔共鸣，气息稳健，语速从容；避免年轻化、清亮青年音和少女音'
  } else if (teen) {
    identity = '少年声线，清亮有韧性的中音，避免成熟低音'
  } else if (age) {
    identity = '成年声线，自然中音，清晰稳定，避免刻意年轻化或过度苍老'
  }
  const custom = [character?.voice_tone, character?.voice_pitch || character?.pitch,
    character?.voice_texture || character?.texture].filter(Boolean).join('，')
  if (!identity && !custom && !extra) return LEGACY_GENERIC_VOICE
  const temperament = /冷峻|冷酷|威严|严厉/.test(text) ? '音色冷峻有力度'
    : /温柔|温润|文雅/.test(text) ? '音色温润自然' : '保持角色身份的辨识度'
  return [identity, custom, extra, temperament, '普通话，自然正常语速，保持音色稳定；情绪与音量按本句表演，不拖长字音']
    .filter(Boolean).join('，')
}

// Older auto-generated bindings often say only "62岁，自然中音，干净清晰…",
// which Breeze renders as a young voice. Refresh those, but keep manual edits.
export function isLegacyVoiceInstruction(value) {
  const text = String(value || '').trim()
  if (!text || text === LEGACY_GENERIC_VOICE) return true
  if (TIMBRE_CUES.test(text)) return false
  return /^(?:\d{1,3}\s*岁|[男女][，,]?\s*\d{1,3}\s*岁|成年|青年|老年|少年|少女|壮年|中年)[，,]/.test(text)
}

export function voiceSignature(contract, bindings) {
  return JSON.stringify([...new Set((contract?.roles || []).map(role => role || '未标注角色'))].sort().map(role => [
    role, String(bindings?.[role]?.voiceId || ''), String(bindings?.[role]?.instruction || '').trim(),
  ]))
}
