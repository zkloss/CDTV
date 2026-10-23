<script setup>
import { waitForDesktopApi } from '../utils/desktopApi.js'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import BaseLoadingState from './BaseLoadingState.vue'
import { PROJECT_STYLE_GROUPS, PROJECT_RATIO_OPTIONS, getProjectStyleDescription, getProjectStyleName, getProjectStylePrefix } from './projectFormOptions'

const props = defineProps({
  token: { type: String, required: true },
  initialProjectId: { type: [String, Number], default: '' },
})
const emit = defineEmits(['project-created', 'open-video', 'back'])

const projectId = ref(String(props.initialProjectId || ''))
const project = ref(null)
const chapters = ref([])
const existingProjects = ref([])
const loadingExistingProjects = ref(false)
const models = ref([])
const selectedModel = ref('')
const conversations = ref([])
const activeConversationId = ref('')
const messages = ref([])
const draft = ref('')
const loading = ref(true)
const loadingModels = ref(false)
const loadingConversations = ref(false)
const generating = ref(false)
const extracting = ref(false)
const saving = ref(false)
const error = ref('')
const saveMessage = ref('')
const scrollArea = ref(null)
const draftInput = ref(null)
let persistTimer = null

const projectDraft = ref({ name: '', description: '', style: '3d-xiuxian', ratio: '16:9' })
const chapterDraft = ref({ title: '第1集', sourceText: '', script: '' })
const creationDataDraft = ref(null)
const creationScriptSnapshot = ref('')
const stage = ref('setup')
const activeTab = ref('script')

const projectStyleGroups = PROJECT_STYLE_GROUPS
const projectRatioOptions = PROJECT_RATIO_OPTIONS
const projectStyleDescription = computed(() => getProjectStyleDescription(projectDraft.value.style))
const scopeId = computed(() => projectId.value || '__draft__')
const modelOptions = computed(() => models.value.map(item => ({
  value: String(item.id ?? item.modelName ?? ''),
  label: (item.name || item.modelName || '文本模型') + (item.contextWindow ? ` (${item.contextWindow >= 1000 ? Math.round(item.contextWindow / 1000) + 'k' : item.contextWindow})` : ''),
})))
const canSend = computed(() => !generating.value && !!selectedModel.value && !!draft.value.trim() && stage.value !== 'setup')
const currentConversation = computed(() => conversations.value.find(item => String(item.id) === String(activeConversationId.value)) || null)

// --- 多集与开局旁白状态管理 ---
const selectedChapterId = ref('')
const showAddMenu = ref(false)
const showEpisodeGrid = ref(false)
const gridFilter = ref('all') // 'all' | 'done' | 'draft'
const episodeScrollRef = ref(null)

const currentChapter = computed(() => {
  if (selectedChapterId.value) {
    const found = chapters.value.find(c => String(c.id) === String(selectedChapterId.value))
    if (found) return found
  }
  return chapters.value[0] || null
})

function parseChineseNumber(str) {
  if (!str) return 0
  if (/^\d+$/.test(str)) return parseInt(str, 10)
  const digits = { '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9 }
  const units = { '十': 10, '百': 100, '千': 1000, '万': 10000 }
  let total = 0
  let current = 0
  for (let i = 0; i < str.length; i++) {
    const char = str[i]
    if (digits[char] !== undefined) {
      current = digits[char]
    } else if (units[char] !== undefined) {
      const u = units[char]
      if (u === 10 && current === 0 && (i === 0 || str[i - 1] === '第')) current = 1
      total += current * u
      current = 0
    } else if (/\d/.test(char)) {
      current = current * 10 + parseInt(char, 10)
    }
  }
  total += current
  return total
}

function isPrologueTitle(title) {
  const t = String(title || '').trim().toLowerCase()
  return t.includes('旁白') || t.includes('序') || t.includes('开局') || t.includes('前传') || t.includes('prologue')
}

function normalizeEpisodeTitle(title) {
  const str = String(title || '').trim()
  if (!str) return '第1集'
  if (isPrologueTitle(str)) return '开局旁白 / 序幕'
  const m = str.match(/第\s*([0-9一二两三四五六七八九十百千]+)\s*集/)
  if (m) {
    const n = parseChineseNumber(m[1])
    if (n > 0) return `第${n}集`
  }
  const m2 = str.match(/([0-9]+)/)
  if (m2) return `第${parseInt(m2[1], 10)}集`
  return str
}

function getEpisodeNumber(title) {
  const str = String(title || '').trim()
  if (isPrologueTitle(str)) return 0
  const m = str.match(/第\s*([0-9一二两三四五六七八九十百千]+)\s*集/)
  if (m) {
    const n = parseChineseNumber(m[1])
    if (n > 0) return n
  }
  const m2 = str.match(/([0-9]+)/)
  if (m2) return parseInt(m2[1], 10)
  return 9999
}

function formatShortEpisodeTitle(title) {
  const norm = normalizeEpisodeTitle(title)
  if (isPrologueTitle(norm)) return '序幕'
  const m = norm.match(/第\s*(\d+)\s*集/)
  if (m) return `第 ${m[1]} 集`
  return norm.length > 7 ? norm.slice(0, 6) + '…' : norm
}

const hasPrologue = computed(() => chapters.value.some(c => isPrologueTitle(c.title)))
const hideProloguePill = ref(typeof localStorage !== 'undefined' && localStorage.getItem('cdtv_hide_prologue_pill') === '1')

function dismissProloguePill() {
  hideProloguePill.value = true
  try { localStorage.setItem('cdtv_hide_prologue_pill', '1') } catch {}
  saveMessage.value = '已隐藏开局旁白按钮（如需添加可从右侧 ▾ 菜单添加）'
}

function restoreProloguePill() {
  hideProloguePill.value = false
  try { localStorage.removeItem('cdtv_hide_prologue_pill') } catch {}
}

const nextEpisodeLabel = computed(() => {
  const nums = chapters.value.map(c => getEpisodeNumber(c.title)).filter(n => n > 0 && n < 9000)
  const nextNum = nums.length ? Math.max(...nums) + 1 : chapters.value.filter(c => !isPrologueTitle(c.title)).length + 1
  return `第${nextNum}集`
})

const completedCount = computed(() => chapters.value.filter(c => Boolean(c.script || c.workflow?.script)).length)

const filteredGridChapters = computed(() => {
  if (gridFilter.value === 'done') {
    return chapters.value.filter(c => Boolean(c.script || c.workflow?.script))
  }
  if (gridFilter.value === 'draft') {
    return chapters.value.filter(c => !Boolean(c.script || c.workflow?.script))
  }
  return chapters.value
})

function getChapterStatusTitle(chap) {
  const hasCd = Boolean(chap.workflow?.creationData || chap.creationData)
  const hasSc = Boolean(chap.script || chap.workflow?.script)
  if (hasCd) return '已提取资产与分镜'
  if (hasSc) return '剧本已生成'
  return '待创作剧本'
}

function sortChaptersList() {
  chapters.value.sort((a, b) => {
    const aPro = isPrologueTitle(a.title)
    const bPro = isPrologueTitle(b.title)
    if (aPro && !bPro) return -1
    if (!aPro && bPro) return 1
    if (aPro && bPro) return 0
    return getEpisodeNumber(a.title) - getEpisodeNumber(b.title)
  })
}

function parseChineseOrArabicNumber(str) {
  if (!str) return 1
  const s = String(str).trim()
  const num = parseInt(s, 10)
  if (!Number.isNaN(num)) return num
  const map = { '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10 }
  if (map[s]) return map[s]
  if (s.startsWith('十')) return 10 + (map[s.slice(1)] || 0)
  return 1
}

function extractEpisodesFromDocumentOrText(document, rawText) {
  const list = []
  if (Array.isArray(document?.episodes) && document.episodes.length > 0) {
    document.episodes.forEach((ep, idx) => {
      const num = ep.num || ep.episode || idx + 1
      const rawTitle = ep.title || `第${num}集`
      const summary = ep.summary || ep.description || ep.outline || ''
      list.push({
        num: Number(num) || (idx + 1),
        title: normalizeEpisodeTitle(rawTitle),
        summary: String(summary).trim(),
      })
    })
    return list
  }

  const text = String(rawText || '')
  if (!text) return []

  const lines = text.split('\n')
  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) continue
    const m = line.match(/^(?:[\d\.\-*•—\s]*)(第\s*([0-9一二两三四五六七八九十]+)\s*([集幕话]))\s*(?:[《〈(（]([^》〉)）]+)[》〉)）])?\s*(?:[—–\-:：]{1,2}\s*|\s+)?(.*)$/)
    if (m) {
      const num = parseChineseOrArabicNumber(m[2])
      const unit = m[3]
      const subTitle = (m[4] || '').trim()
      const summary = (m[5] || '').trim()
      const title = subTitle ? `第${num}${unit}《${subTitle}》` : `第${num}${unit}`
      list.push({
        num,
        unit,
        subTitle,
        title: normalizeEpisodeTitle(title),
        summary,
      })
    }
  }
  return list
}

async function syncPlannedEpisodes(parsedEpisodes) {
  if (!projectId.value || !Array.isArray(parsedEpisodes) || parsedEpisodes.length < 2) return
  let createdCount = 0

  const firstEp = parsedEpisodes.find(e => e.num === 1) || parsedEpisodes[0]
  if (firstEp) {
    if (firstEp.title && firstEp.title !== '第1集') {
      chapterDraft.value.title = firstEp.title
      if (currentChapter.value) {
        currentChapter.value.title = firstEp.title
        request('PUT', `/chapter/${encodeURIComponent(currentChapter.value.id)}`, {
          ...currentChapter.value,
          title: firstEp.title,
        }).catch(() => {})
      }
    }
    if (firstEp.summary && (!chapterDraft.value.sourceText || chapterDraft.value.sourceText.length < 10)) {
      chapterDraft.value.sourceText = firstEp.summary
    }
  }

  for (const ep of parsedEpisodes) {
    if (ep.num === 1) continue
    const exists = chapters.value.some(c => getEpisodeNumber(c.title) === ep.num)
    if (!exists) {
      try {
        const created = await request('POST', `/project/${encodeURIComponent(projectId.value)}/chapter`, {
          title: ep.title,
          content: ep.summary || '',
          script: '',
          workflow: {
            workflowStage: 'script',
            agentCreated: true,
            agentUpdatedAt: new Date().toISOString(),
          },
        })
        if (created) {
          created.title = normalizeEpisodeTitle(created.title)
          chapters.value.push(created)
          createdCount++
        }
      } catch (e) {
        console.warn('智能创建集数失败:', ep.title, e)
      }
    }
  }

  if (createdCount > 0) {
    sortChaptersList()
    saveMessage.value = `已智能识别大纲并同步创建全剧 ${chapters.value.length} 集！`
  }
}

async function manualSyncPlannedEpisodes() {
  const text = chapterDraft.value.sourceText || chapterDraft.value.script || ''
  const parsed = extractEpisodesFromDocumentOrText(null, text)
  if (parsed.length >= 2) {
    await syncPlannedEpisodes(parsed)
  } else {
    const lastAssistantMsg = [...messages.value].reverse().find(m => m.role === 'assistant' && m.text)
    if (lastAssistantMsg) {
      const parsedFromMsg = extractEpisodesFromDocumentOrText(null, lastAssistantMsg.text)
      if (parsedFromMsg.length >= 2) {
        await syncPlannedEpisodes(parsedFromMsg)
        return
      }
    }
    saveMessage.value = '未在当前大纲中检测到多集规划（如 第1集... 第2集...）'
  }
}

function isOutlineOnlyText(text) {
  if (!text || typeof text !== 'string') return false
  const t = text.trim()
  if (t.includes('【场1') || t.includes('【第1场') || t.includes('【镜1-1') || t.includes('【镜1】') || /【?镜\s*\d+[-—]\d+】?/.test(t)) {
    return false
  }
  const hasMultipleEpisodes = /(?:第\s*[0-9一二两三四五六七八九十]+\s*[集幕话]).*(?:\n[\s\S]*第\s*[0-9一二两三四五六七八九十]+\s*[集幕话])/i.test(t)
  return hasMultipleEpisodes || t.startsWith('【全片规划') || t.startsWith('全片规划') || t.includes('【分集大纲】') || t.includes('【全片大纲】')
}

function separateOutlineAndScript(rawText) {
  if (!rawText || typeof rawText !== 'string') return { outline: '', script: '' }
  let text = String(rawText).trim()

  const sceneMatch = text.match(/(?:\n|^)\s*(?:【?(?:场\s*[0-9一二两三四五六七八九十]+|第\s*[0-9一二两三四五六七八九十]+\s*场|镜\s*[0-9一二两三四五六七八九十]+[-—][0-9一二两三四五六七八九十]+|镜\s*[0-9]+|剧本正文|分镜剧本正文)】?[:：]?)/i)

  if (sceneMatch && sceneMatch.index !== undefined && sceneMatch.index > 0) {
    const outlinePart = text.slice(0, sceneMatch.index).trim()
    let scriptPart = text.slice(sceneMatch.index).trim()
    scriptPart = scriptPart.replace(/^【?(?:剧本正文|分镜剧本正文|可拍摄剧本)】?[:：]?\s*/i, '').trim()
    return {
      outline: outlinePart,
      script: scriptPart,
    }
  }

  if (isOutlineOnlyText(text)) {
    return {
      outline: text,
      script: '',
    }
  }

  return {
    outline: '',
    script: text,
  }
}

function selectChapter(chapter) {
  if (!chapter) return
  selectedChapterId.value = String(chapter.id)
  const workflow = chapterWorkflow(chapter)
  let rawScript = chapter.script || workflow.script || chapter.chapterDraft?.script || ''
  let rawSource = workflow.novel || chapter.content || chapter.sourceText || ''

  const { outline, script } = separateOutlineAndScript(rawScript)
  if (outline && !rawSource) {
    rawSource = outline
  }
  if (!script && outline) {
    rawScript = ''
  } else if (script) {
    rawScript = script
  }

  chapterDraft.value = {
    title: normalizeEpisodeTitle(chapter.title),
    sourceText: cleanScriptPayload(rawSource),
    script: cleanScriptPayload(rawScript),
  }
  creationDataDraft.value = storedCreationData(chapter) || null
  creationScriptSnapshot.value = creationDataDraft.value ? chapterDraft.value.script : ''
  stage.value = stageFromChapter(chapter)
}

function getPreviousChapter() {
  const currentNum = getEpisodeNumber(chapterDraft.value.title || currentChapter.value?.title)
  const isPro = isPrologueTitle(chapterDraft.value.title || currentChapter.value?.title)
  if (isPro) return null

  if (currentNum === 1) {
    return chapters.value.find(c => isPrologueTitle(c.title)) || null
  }

  const validPrev = chapters.value
    .filter(c => !isPrologueTitle(c.title) && getEpisodeNumber(c.title) < currentNum)
    .sort((a, b) => getEpisodeNumber(b.title) - getEpisodeNumber(a.title))

  if (validPrev.length > 0) return validPrev[0]
  return chapters.value.find(c => isPrologueTitle(c.title)) || null
}

function buildStorylineContext(targetChapter) {
  const currentTitle = normalizeEpisodeTitle(targetChapter?.title || chapterDraft.value.title || '第1集')
  const currentNum = getEpisodeNumber(currentTitle)
  const isPro = isPrologueTitle(currentTitle)

  if (isPro) {
    return {
      currentTitle,
      isPrologue: true,
      contextPrompt: `【当前创作集数】：开局旁白 / 序幕（全剧总起开篇）
【创作目标】：
1. 交代宏大世界观背景、主角身世/开局逆天体质设定、核心世界危机；
2. 用极其震撼、富有画面冲击力与视听意象的语言开篇，留下强烈悬念；
3. 为接下来的《第1集》主角登场与剧情第一波高潮冲突做好充分铺垫。
【严格要求】：只返回合法 JSON，且 chapter.title 必须严格为 "开局旁白 / 序幕"！`
    }
  }

  const prologue = chapters.value.find(c => isPrologueTitle(c.title))
  const numberedPrevChapters = chapters.value
    .filter(c => !isPrologueTitle(c.title) && getEpisodeNumber(c.title) < currentNum)
    .sort((a, b) => getEpisodeNumber(a.title) - getEpisodeNumber(b.title))

  const allChronologicalPrev = []
  if (prologue) allChronologicalPrev.push(prologue)
  allChronologicalPrev.push(...numberedPrevChapters)

  let prevContextLines = []
  let immediatePrevEnding = ''
  let immediatePrevTitle = ''

  for (let i = 0; i < allChronologicalPrev.length; i++) {
    const c = allChronologicalPrev[i]
    const cTitle = normalizeEpisodeTitle(c.title)
    const script = decodeEscapedText(c.script || c.workflow?.script || '')
    const novel = decodeEscapedText(c.content || c.workflow?.novel || c.sourceText || '')

    if (script || novel) {
      let snippet = ''
      if (script) {
        if (script.length <= 350) {
          snippet = script
        } else {
          snippet = `${script.slice(0, 150)} ... \n【该集结尾高潮/断章悬念】：${script.slice(-200)}`
        }
      } else {
        snippet = novel.slice(0, 250)
      }
      prevContextLines.push(`--- 《${cTitle}》核心剧情回顾 ---\n${snippet}`)

      if (i === allChronologicalPrev.length - 1) {
        immediatePrevTitle = cTitle
        immediatePrevEnding = script ? script.slice(-350) : novel.slice(-250)
      }
    }
  }

  let storylineContext = ''
  if (prevContextLines.length > 0) {
    storylineContext = `\n===== 前文剧情连贯上下文（必须严格继承已发生事件、人物关系与世界观）=====\n` + prevContextLines.join('\n\n')
  }

  let connectionInstruction = ''
  if (immediatePrevEnding) {
    connectionInstruction = `\n【上一集《${immediatePrevTitle}》结尾断章悬念】：\n${immediatePrevEnding}\n
【本集《${currentTitle}》核心创作指令】：
1. 【强剧情承接】：本集开头必须立刻紧接《${immediatePrevTitle}》结尾的冲突动作与悬念，不得有任何断层；
2. 【严格集数锁定】：本集集数明确为《${currentTitle}》，严禁写错集数，严禁写成第一集或其他集数！
3. 【推进冲突与结尾断章】：在承接上文的基础上继续推高矛盾，并在本集结尾设计新的强力悬念钩子，为下一集（第${currentNum + 1}集）做铺垫。`
  } else if (currentNum === 1) {
    connectionInstruction = `\n【本集《第1集》核心创作指令】：
1. 迅速切入主角的核心处境与第一波戏剧性高潮冲突，展现逆天反差/爽点；
2. 确立主角性格、关键配角关系与本剧主线目标；
3. 结尾留下强烈的危机或反转断章钩子，吸引观众看《第2集》！`
  } else {
    connectionInstruction = `\n【本集《${currentTitle}》核心创作指令】：
1. 严格作为剧集的《${currentTitle}》展开创作，严禁写成第一集或其他集数！
2. 推进主线情节，深化冲突，并在结尾留下强烈的剧情钩子。`
  }

  return {
    currentTitle,
    isPrologue: false,
    contextPrompt: `${storylineContext}\n${connectionInstruction}\n【严格要求】：只返回合法 JSON，且 chapter.title 必须严格为 "${currentTitle}"！`
  }
}

async function createNewChapter(title = '') {
  if (!projectId.value) {
    error.value = '请先创建项目'
    return
  }
  saving.value = true
  error.value = ''
  try {
    let finalTitle = title.trim()
    if (!finalTitle) {
      const nums = chapters.value.map(c => getEpisodeNumber(c.title)).filter(n => n > 0 && n < 9000)
      const nextNum = nums.length ? Math.max(...nums) + 1 : chapters.value.filter(c => !isPrologueTitle(c.title)).length + 1
      finalTitle = `第${nextNum}集`
    } else {
      finalTitle = normalizeEpisodeTitle(finalTitle)
    }
    const created = await request('POST', `/project/${encodeURIComponent(projectId.value)}/chapter`, {
      title: finalTitle,
      content: '',
      script: '',
      workflow: {
        workflowStage: 'script',
        agentCreated: true,
        agentUpdatedAt: new Date().toISOString(),
      },
    })
    if (created) {
      created.title = normalizeEpisodeTitle(created.title)
      chapters.value.push(created)
      sortChaptersList()
      selectChapter(created)
      saveMessage.value = `已添加「${finalTitle}」`
    }
  } catch (err) {
    error.value = '添加集数失败：' + cleanError(err)
  } finally {
    saving.value = false
  }
}

async function addPrologue() {
  await createNewChapter('开局旁白 / 序幕')
}

async function batchAddEpisodes(count = 3) {
  if (!projectId.value) return
  saving.value = true
  error.value = ''
  try {
    const nums = chapters.value.map(c => getEpisodeNumber(c.title)).filter(n => n > 0 && n < 9000)
    let startNum = nums.length ? Math.max(...nums) + 1 : chapters.value.filter(c => !isPrologueTitle(c.title)).length + 1
    for (let i = 0; i < count; i++) {
      const epTitle = `第${startNum + i}集`
      const created = await request('POST', `/project/${encodeURIComponent(projectId.value)}/chapter`, {
        title: epTitle,
        content: '',
        script: '',
        workflow: {
          workflowStage: 'script',
          agentCreated: true,
          agentUpdatedAt: new Date().toISOString(),
        },
      })
      if (created) {
        created.title = normalizeEpisodeTitle(created.title)
        chapters.value.push(created)
      }
    }
    sortChaptersList()
    saveMessage.value = `已批量创建 ${count} 集！`
  } catch (err) {
    error.value = '批量添加失败：' + cleanError(err)
  } finally {
    saving.value = false
  }
}

async function removeCurrentChapter(chapter) {
  if (!chapter?.id) return
  const delTitle = normalizeEpisodeTitle(chapter.title || '此集')
  if (!confirm(`确定要删除「${delTitle}」吗？删除后不可恢复。`)) return
  saving.value = true
  try {
    await request('DELETE', `/chapter/${encodeURIComponent(chapter.id)}`)
    chapters.value = chapters.value.filter(c => String(c.id) !== String(chapter.id))
    sortChaptersList()
    if (chapters.value.length > 0) {
      selectChapter(chapters.value[0])
    } else {
      chapterDraft.value = { title: '第1集', sourceText: '', script: '' }
      creationDataDraft.value = null
    }
    saveMessage.value = '集数已删除'
  } catch (err) {
    error.value = '删除失败：' + cleanError(err)
  } finally {
    saving.value = false
  }
}

const hasScript = computed(() => Boolean(chapterDraft.value.script.trim()))
const hasCreationData = computed(() => Boolean(creationDataDraft.value && typeof creationDataDraft.value === 'object'))
const stageIndex = computed(() => ({ setup: 0, script: 1, assets: 2, video: 3 }[stage.value] || 0))

const creationCounts = computed(() => {
  const root = creationDataDraft.value?.consistency || creationDataDraft.value?.assets || creationDataDraft.value || {}
  const count = keys => keys.reduce((total, key) => total + (Array.isArray(root[key]) ? root[key].length : 0), 0)
  return {
    assets: count(['characters', 'roles', 'people', 'scenes', 'props', 'items', 'layouts', 'audio', 'audios']),
    shots: Array.isArray(creationDataDraft.value?.shots || root.shots) ? (creationDataDraft.value?.shots || root.shots).length : 0,
  }
})

const assetFilterTab = ref('all')
const copySuccessId = ref('')

const extractedCharacters = computed(() => {
  const root = creationDataDraft.value?.consistency || creationDataDraft.value?.assets || creationDataDraft.value || {}
  return Array.isArray(root.characters) ? root.characters : (Array.isArray(root.roles) ? root.roles : (Array.isArray(root.people) ? root.people : []))
})

const extractedScenes = computed(() => {
  const root = creationDataDraft.value?.consistency || creationDataDraft.value?.assets || creationDataDraft.value || {}
  return Array.isArray(root.scenes) ? root.scenes : []
})

const extractedProps = computed(() => {
  const root = creationDataDraft.value?.consistency || creationDataDraft.value?.assets || creationDataDraft.value || {}
  return Array.isArray(root.props) ? root.props : (Array.isArray(root.items) ? root.items : [])
})

const extractedAudio = computed(() => {
  const root = creationDataDraft.value?.consistency || creationDataDraft.value?.assets || creationDataDraft.value || {}
  return Array.isArray(root.audio) ? root.audio : (Array.isArray(root.audios) ? root.audios : [])
})

function getAudioCategory(aud) {
  if (!aud || typeof aud !== 'object') return 'voice'
  const cat = String(aud.category || aud.kind || aud.type || '').toLowerCase()
  if (['voice', 'dialogue', 'narration', 'system', 'tts'].includes(cat)) return 'voice'
  if (['sfx', 'ambient', 'sound', 'bgm', 'foley'].includes(cat)) return 'sfx'
  const id = String(aud.id || '').toLowerCase()
  const name = String(aud.name || '').toLowerCase()
  const desc = String(aud.description || aud.style || '').toLowerCase()
  if (id.includes('vo_') || id.includes('narrat') || id.includes('dialog') || /旁白|对白|台词|念白|人声|系统音|提示音|神念|自语|独白|配音/.test(name + desc)) return 'voice'
  if (id.includes('sfx') || id.includes('bgm') || id.includes('ambient') || /音效|环境|声|风|雨|雷|刀|剑|脚步|爆炸|打斗|摩擦|推门|倒地|轰鸣|BGM|背景音乐|拟声/.test(name + desc)) return 'sfx'
  return 'voice'
}

const extractedVoice = computed(() => extractedAudio.value.filter(a => getAudioCategory(a) === 'voice'))
const extractedSfx = computed(() => extractedAudio.value.filter(a => getAudioCategory(a) === 'sfx'))

const extractedShots = computed(() => {
  if (Array.isArray(creationDataDraft.value?.shots)) return creationDataDraft.value.shots
  const root = creationDataDraft.value?.consistency || creationDataDraft.value?.assets || creationDataDraft.value || {}
  return Array.isArray(root.shots) ? root.shots : []
})

function getReferenceName(refId) {
  if (!refId) return { type: 'other', icon: '🏷️', name: '', id: '' }
  const char = extractedCharacters.value.find(c => c.id === refId)
  if (char) return { type: 'character', icon: '👤', name: char.name || refId, id: refId }
  const scene = extractedScenes.value.find(s => s.id === refId)
  if (scene) return { type: 'scene', icon: '📍', name: scene.name || refId, id: refId }
  const prop = extractedProps.value.find(p => p.id === refId)
  if (prop) return { type: 'prop', icon: '🗡️', name: prop.name || refId, id: refId }
  const aud = extractedAudio.value.find(a => a.id === refId)
  if (aud) {
    const isVoice = getAudioCategory(aud) === 'voice'
    return { type: 'audio', icon: isVoice ? '🎙️' : '🔊', name: aud.name || refId, id: refId }
  }
  return { type: 'other', icon: '🏷️', name: refId, id: refId }
}

function getSceneName(sceneId) {
  const scene = extractedScenes.value.find(s => s.id === sceneId)
  return scene?.name || sceneId || '默认场景'
}

function copyToClipboard(text, id) {
  if (!text) return
  try {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        copySuccessId.value = id
        setTimeout(() => {
          if (copySuccessId.value === id) copySuccessId.value = ''
        }, 2000)
      }).catch(() => fallbackCopy(text, id))
    } else {
      fallbackCopy(text, id)
    }
  } catch {
    fallbackCopy(text, id)
  }
}

function fallbackCopy(text, id) {
  try {
    const input = document.createElement('textarea')
    input.value = text
    input.style.position = 'fixed'
    input.style.opacity = '0'
    document.body.appendChild(input)
    input.select()
    document.execCommand('copy')
    document.body.removeChild(input)
    copySuccessId.value = id
    setTimeout(() => {
      if (copySuccessId.value === id) copySuccessId.value = ''
    }, 2000)
  } catch {}
}

const suggestions = computed(() => {
  const title = normalizeEpisodeTitle(chapterDraft.value.title)
  const isPro = isPrologueTitle(title)
  if (isPro) {
    return [
      { label: '🎙️ 生成开局旁白', text: `请为《${projectDraft.value.name || '本项目'}》创作一段引人入胜的开局旁白与世界观引入，交代背景与主角逆天体质/身世起源，留下强烈悬念。` },
      { label: '✨ 增强开场史诗感', text: '请优化当前开局旁白，增强画面冲击力与视听节奏感，为第1集的高潮做充分铺垫。' },
      { label: '📖 提炼小说背景为旁白', text: '请根据我提供的小说前序世界观与历史背景，提炼出一分钟以内的开场旁白与分镜镜头引导。' },
    ]
  }
  const epNum = getEpisodeNumber(title)
  if (epNum > 1 && epNum < 9000) {
    const prev = getPreviousChapter()
    const prevTitle = prev ? normalizeEpisodeTitle(prev.title) : `第${epNum - 1}集`
    const hasOutline = Boolean(chapterDraft.value.sourceText && chapterDraft.value.sourceText.length > 10)
    return [
      hasOutline
        ? { label: `🔥 根据大纲创作${title}（推荐·8~10镜）`, text: `请根据《${title}》已规划的大纲（${chapterDraft.value.sourceText.slice(0, 120)}...）并承接${prevTitle}结尾悬念，创作${title}可拍摄分镜头剧本（包含场次、镜号【镜${epNum}-1】等、具体动作与影视标准对白），体量约1.5~2分钟。` }
        : { label: `🔥 承接${prevTitle}创作${title}（推荐·8~10镜）`, text: `请承接${prevTitle}结尾的剧情悬念，紧密连贯地创作${title}剧本，体量约1.5~2分钟（8~10个精细分镜，生成极快极稳），推进核心冲突与情节反转。` },
      { label: `⚡ 创作${title}饱满剧本（约2~3分/12~16镜）`, text: `请承接${prevTitle}，创作${title}长篇饱满剧本，体量约2~3分钟（支撑12~16个精细分镜）。` },
      { label: '⚡ 设计结尾反转与钩子', text: `请为${title}设计一个强烈的剧情反转和结尾断章悬念钩子，吸引观众看下一集。` },
      { label: '📖 导入小说改写本集', text: `请把我提供的小说后续章节文本，改写为${title}的可拍摄连续分镜剧本（约8~12镜）。` },
    ]
  }

  const hasEp1Outline = Boolean(chapterDraft.value.sourceText && chapterDraft.value.sourceText.length > 10 && !chapterDraft.value.script)
  if (hasEp1Outline) {
    return [
      { label: '⚡ 为《第1集》创作8~10镜详细剧本', text: '请根据已规划的大纲，直接为《第1集》创作包含具体场次【场1 ...】、镜号【镜1-1】至【镜1-10】、具体动作与影视对白的可拍摄剧本！' },
      { label: '🎬 重新规划全片5集大纲', text: '请按微短剧工业标准，把全片规划为5集（总长约9分钟，每集约1.5~2分钟/8~10镜）。先构思5集大纲，并直接创作《第1集》可提炼8~10个精细分镜的完整剧本！' },
      { label: '📖 导入小说 / 故事改编', text: '我有一段小说或故事，请先理解人物、世界观和核心冲突，再改编成适合本集制作（约1.5~2分钟/8~10镜）的可拍摄剧本。' },
      { label: '✨ 继续完善本集剧本', text: '请在不改变已经确认的人物、场景、服装、道具和世界观的前提下，继续丰富完善当前剧本的镜头动作与对白。' },
    ]
  }

  return [
    { label: '🎬 规划5集微短剧（总长约9分，每集8-10镜，推荐·极速稳定）', text: '请按微短剧工业标准，把全片规划为5集（总长约9分钟，每集约1.5~2分钟/8~10镜）。请先构思5集大纲，并直接创作《第1集》可提炼8~10个精细分镜的完整剧本！' },
    { label: '🎬 规划3幕短剧（总长约9分，每幕约3分/12-16镜）', text: '请按三幕式结构规划全片（总长约9分钟，每幕约3分钟/12~16镜）。请先构思3幕大纲，并直接创作《第1幕 / 第1集》可拍摄分镜剧本！' },
    { label: '⚡ 创作本集精简剧本（约1.5-2分钟/8-10镜）', text: '请根据项目资料创作当前集剧本，情节体量控制在约1.5~2分钟，节奏明快紧凑，足够支撑提炼8~10个高质量分镜。' },
    { label: '⚡ 创作本集饱满剧本（约3分钟/12-16镜）', text: '请根据项目资料创作当前集剧本，情节体量控制在约2~3分钟，包含丰富场景与密集冲突对白，足够支撑提炼12~16个高质量分镜。' },
    { label: '📖 导入小说 / 故事改编', text: '我有一段小说或故事，请先理解人物、世界观和核心冲突，再改编成适合本集制作（约1.5~2分钟/8~10镜）的可拍摄剧本。' },
    { label: '✨ 继续完善本集剧本', text: '请在不改变已经确认的人物、场景、服装、道具和世界观的前提下，继续丰富完善当前剧本的镜头动作与对白。' },
  ]
})

function cleanError(value) { return String(value?.message || value || '未知错误').replace(/^Error:\s*/, '') }
function listItems(result) {
  if (Array.isArray(result)) return result
  if (Array.isArray(result?.items)) return result.items
  if (Array.isArray(result?.data)) return result.data
  if (Array.isArray(result?.data?.items)) return result.data.items
  return []
}
function projectDate(item) {
  const value = item?.updatedAt || item?.updateTime || item?.createdAt || item?.created_at
  if (!value) return '尚未记录更新时间'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}
function projectStageLabel(item) {
  const stageValue = String(item?.workflowStage || item?.workflow?.workflowStage || '').toLowerCase()
  if (stageValue === 'video') return '已准备制作'
  if (stageValue === 'assets') return '已有资产与分镜'
  if (item?.script || item?.chapterCount) return '已有剧本'
  return '项目资料已保存'
}
function conversationDate(item) {
  const value = item?.updatedAt || item?.updateTime || item?.createdAt || item?.created_at
  if (!value) return '未记录时间'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}
function conversationPreview(item) {
  const message = (Array.isArray(item?.messages) ? item.messages : []).find(entry => String(entry?.text || '').trim())
  return String(message?.text || '还没有内容，继续写下去').replace(/\r?\n/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 46)
}

async function request(method, path, body = null) {
  if (import.meta.env.DEV && !window.pywebview?.api) {
    if (path === '/api/admin/models/public/list?modelType=text') return [{ id: 'demo-text', name: '演示文本模型', modelName: 'demo' }]
    if (method === 'GET' && path === '/project/list') return [{ id: 'demo-project-1', name: '演示项目', description: '这是一个历史项目示例', style: '3d-xiuxian', ratio: '16:9', updatedAt: '2026-10-01T10:00:00.000Z' }]
    if (method === 'GET' && path.includes('/project-agent-conversation/list')) return []
    if (method === 'GET' && path.includes('/chapter/list')) return []
    if (method === 'POST' && path === '/project') return { id: 'demo-project-' + Date.now(), ...body }
    if (method === 'POST' && path.includes('/chapter')) return { id: 'demo-chapter-' + Date.now(), ...body }
    if (method === 'POST' && path === '/project-agent-conversation') return { id: 'demo-conversation-' + Date.now(), ...body }
    if (method === 'PUT') return body || {}
    if (path.startsWith('/project/')) return { id: projectId.value || 'demo-project', ...body }
    return body || {}
  }
  const api = await waitForDesktopApi()
  if (!api?.backend_request) throw new Error('请从桌面客户端启动后使用剧本助手')
  return api.backend_request(method, path, props.token, body)
}

function parseText(result) {
  if (!result) return ''
  if (Array.isArray(result.choices) && result.choices.length) {
    const content = result.choices[0]?.message?.content ?? result.choices[0]?.text
    return Array.isArray(content) ? content.map(item => item?.text || item?.content || '').join('') : String(content || '')
  }
  let content = result.content ?? result.output_text ?? result.text
  if (Array.isArray(content)) content = content.map(item => item?.text || item?.content || '').join('')
  return String(content || '')
}

function parseJson(text) {
  if (text && typeof text === 'object') return text
  let cleaned = String(text || '').replace(/\ufeff/g, '').trim()
  cleaned = cleaned.replace(/<think>[\s\S]*?<\/think>/gi, '').trim()
  const codeMatch = cleaned.match(/```(?:json)?\s*(\{[\s\S]*?\})\s*```/i)
  if (codeMatch) {
    cleaned = codeMatch[1].trim()
  } else {
    const start = cleaned.indexOf('{')
    const end = cleaned.lastIndexOf('}')
    if (start >= 0 && end > start) {
      cleaned = cleaned.slice(start, end + 1)
    }
  }
  cleaned = cleaned.replace(/,\s*([\}\]])/g, '$1')
  try {
    const value = JSON.parse(cleaned)
    return value && typeof value === 'object' ? value : null
  } catch {
    // 容错：尝试提取 "script": "..." 字段
    try {
      const scriptMatch = cleaned.match(/"script"\s*:\s*"([\s\S]*?)"\s*(?:,\s*"|\}\s*$)/)
      if (scriptMatch) {
        return {
          chapter: {
            script: scriptMatch[1]
          }
        }
      }
    } catch {}
    return null
  }
}

function decodeEscapedText(value) {
  return String(value || '')
    .replace(/\\r\\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\"/g, '"')
    .trim()
}

function cleanScriptPayload(raw) {
  if (!raw || typeof raw !== 'string') return ''
  let text = String(raw).trim()
  text = text.replace(/^```(?:json|text|markdown)?\s*/i, '').replace(/\s*```$/i, '').trim()

  // 1. 如果是以 JSON 结构开头或包含 "script":
  if (text.startsWith('{') || text.includes('"script"')) {
    const scriptRegex = /"script"\s*:\s*"([\s\S]*?)"\s*(?:,\s*"|\}\s*$)/
    const match = text.match(scriptRegex)
    if (match && match[1]) {
      text = decodeEscapedText(match[1])
    } else {
      const scriptIdx = text.indexOf('"script"')
      if (scriptIdx >= 0) {
        const colonIdx = text.indexOf(':', scriptIdx)
        if (colonIdx >= 0) {
          let content = text.slice(colonIdx + 1).trim()
          if (content.startsWith('"')) content = content.slice(1)
          if (content.endsWith('}') || content.endsWith('}"')) {
            content = content.replace(/\s*\}[\s"]*$/, '')
          }
          if (content.endsWith('"')) content = content.slice(0, -1)
          text = decodeEscapedText(content)
        }
      }
    }
  }

  // 2. 剥离全片规划/分集大纲杂质（当存在正文场次或镜号时）
  text = text.replace(/【?(?:全片规划|全片大纲|分集大纲|集数规划|全剧大纲)】?[\s\S]*?(?=(?:(?:\n\s*|\A)(?:【?场\s*[0-9一二两三四五六七八九十]+|【?第\s*[0-9一二两三四五六七八九十]+\s*场|【?镜\s*[0-9一二两三四五六七八九十]+[-—][0-9一二两三四五六七八九十]+|【?镜\s*[0-9]+|【剧本正文】|剧本正文[：:]|正文[：:])))/i, '').trim()

  // 3. 过滤体量说明、制作提示等元描述
  text = text.replace(/本集(?:体量|时长)?约[0-9~一二两三四五六七八九十]+(?:分钟|分|秒)?[，,、\s]*可(?:提炼|支撑|生成)[0-9~一二两三四五六七八九十\-—]+个?(?:高精)?分镜[。！\n]*/gi, '')
  text = text.replace(/【?(?:创作说明|编剧说明|制作提示|体量说明|分集规划)】?[:：]?[^\n]*\n?/gi, '')
  text = text.replace(/^【?(?:剧本正文|分镜剧本正文|可拍摄剧本)】?[:：]?\s*/i, '')

  return filterEnglishNoise(decodeEscapedText(text))
}

function filterEnglishNoise(text) {
  if (!text || typeof text !== 'string') return ''
  let cleaned = text.trim()

  // 1. 移除 <think>...</think> 思考链
  cleaned = cleaned.replace(/<think>[\s\S]*?<\/think>/gi, '').trim()

  // 2. 移除英文分析标题及分析段落（如 **My Analysis...**, ### Analysis..., Analysis:, Thought Process: 等）
  cleaned = cleaned.replace(/\*{0,2}(?:My Analysis|Analysis of|Thought Process|Thinking Process|Chain of Thought|Task Breakdown|Analysis)[\s\S]*?(?=(?:(?:\n\s*|\A)(?:第[0-9一二两三四五六七八九十]+[集章回话幕]|开局旁白|序幕|序章|【|#|\*\*【|\*\*第|\[场景|场景[：:]|镜头[：:]|\n\n[\u4e00-\u9fa5]{2,})))/gi, '').trim()

  // 3. 移除 Markdown 代码块包装
  cleaned = cleaned.replace(/^```(?:json|markdown|text)?\s*/i, '').replace(/\s*```$/i, '').trim()

  // 4. 行级过滤开头的英文闲聊/思考自白
  const lines = cleaned.split('\n')
  const keptLines = []
  let reachedChineseContent = false

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i]
    const line = rawLine.trim()
    if (!line) {
      if (reachedChineseContent) keptLines.push('')
      continue
    }

    const hasChinese = /[\u4e00-\u9fa5]/.test(line)
    const englishWords = (line.match(/[a-zA-Z]{2,}/g) || []).length
    const chineseChars = (line.match(/[\u4e00-\u9fa5]/g) || []).length

    if (!reachedChineseContent) {
      // 过滤剧本出现前的纯英文前言（如 "Alright, let's break this down...", "Now let's craft..." 等）
      if (!hasChinese || (englishWords > 3 && chineseChars < 4 && !line.includes('第') && !line.includes('集') && !line.includes('旁白') && !line.includes('序幕'))) {
        continue
      }
      reachedChineseContent = true
      keptLines.push(rawLine)
    } else {
      // 过滤结尾处的英文客套（如 "Hope this helps!", "Let me know..."）
      if (!hasChinese && englishWords > 2 && /^(?:hope this helps|let me know|if you need|feel free|here is|enjoy|best regards)/i.test(line)) {
        continue
      }
      keptLines.push(rawLine)
    }
  }

  const result = keptLines.join('\n').trim()
  return result || cleaned
}

function displayTextFromDocument(document, fallback = '') {
  const script = document?.chapter?.script || document?.chapterDraft?.script || document?.script || document?.content || ''
  return cleanScriptPayload(script || fallback)
}

function cleanAgentText(raw, document = null) {
  if (document) {
    const script = displayTextFromDocument(document)
    if (script) return script
    return 'Agent 已生成纯中文剧本内容。'
  }
  return cleanScriptPayload(raw)
}

function normalizeCreationData(document) {
  const value = document && typeof document === 'object' ? { ...document } : {}
  value.schema_version = String(value.schema_version || '2.6')
  value.title = String(value.title || projectDraft.value.name || '未命名创作')
  value.style = value.style || projectDraft.value.style || '3d-xiuxian'
  value.ratio = value.ratio || projectDraft.value.ratio || '16:9'
  value.project = {
    ...(value.project && typeof value.project === 'object' ? value.project : {}),
    name: projectDraft.value.name,
    description: projectDraft.value.description,
    style: projectDraft.value.style,
    ratio: projectDraft.value.ratio,
  }
  if (!value.consistency && value.assets && typeof value.assets === 'object') value.consistency = value.assets
  if (!value.consistency) value.consistency = {}

  const stylePrefix = getProjectStylePrefix(value.style || projectDraft.value.style)

  // 注入风格前缀到人物设定中，确保生图与成片时牢牢锁定 3D国漫/所选风格
  if (Array.isArray(value.consistency.characters)) {
    value.consistency.characters.forEach(char => {
      if (char && typeof char === 'object') {
        let app = String(char.appearance || '').trim()
        if (app && !app.includes('3D') && !app.includes('国漫') && !app.includes('写实') && !app.includes('二次元') && !app.includes('Q版') && !app.includes('建模')) {
          char.appearance = `${stylePrefix}。${app}`
        }
      }
    })
  }
  // 注入风格前缀到场景设定中
  if (Array.isArray(value.consistency.scenes)) {
    value.consistency.scenes.forEach(scene => {
      if (scene && typeof scene === 'object') {
        let env = String(scene.environment || scene.description || '').trim()
        if (env && !env.includes('3D') && !env.includes('国漫') && !env.includes('写实') && !env.includes('二次元') && !env.includes('Q版') && !env.includes('建模')) {
          scene.environment = `${stylePrefix}。${env}`
        }
      }
    })
  }
  // 音频资产规范化与音色预设注入
  if (Array.isArray(value.consistency.audio)) {
    value.consistency.audio.forEach(aud => {
      if (aud && typeof aud === 'object') {
        const id = String(aud.id || '').toLowerCase()
        const name = String(aud.name || '').toLowerCase()
        const desc = String(aud.description || aud.style || '').toLowerCase()
        if (!aud.category) {
          if (id.includes('vo_') || id.includes('narrat') || id.includes('dialog') || /旁白|对白|台词|念白|人声|系统音|提示音|神念|自语|独白|配音/.test(name + desc)) {
            aud.category = 'voice'
          } else if (id.includes('sfx') || id.includes('bgm') || id.includes('ambient') || /音效|环境|声|风|雨|雷|刀|剑|脚步|爆炸|打斗|摩擦|推门|倒地|轰鸣|BGM|背景音乐|拟声/.test(name + desc)) {
            aud.category = 'sfx'
          } else {
            aud.category = 'voice'
          }
        }
        if (aud.category === 'voice' && !aud.voice) {
          if (/男|大叔|苍凉|雄浑|厚重|天道|开篇|序幕|旁白|老者|老祖|师尊|尊者|帝尊|神明|沉稳/.test(name + desc)) {
            aud.voice = 'longshu_v2'
          } else if (/评书|霸气|说书|热血/.test(name + desc)) {
            aud.voice = 'longfeiyan_v2'
          } else if (/少年|青年|男主|少侠/.test(name + desc)) {
            aud.voice = 'longyuan_v2'
          } else if (/萝莉|可爱|女童|灵宠|灵兽/.test(name + desc)) {
            aud.voice = 'longmiao_v2'
          } else if (/御姐|师姐|女尊|仙子|女帝|知性/.test(name + desc)) {
            aud.voice = 'longyue_v2'
          } else if (/女|女主|甜美/.test(name + desc)) {
            aud.voice = 'longtian_v2'
          } else {
            aud.voice = 'longshu_v2'
          }
        }
      }
    })
  }
  if (!Array.isArray(value.shots) && Array.isArray(value.consistency.shots)) value.shots = value.consistency.shots
  return value
}

function projectBaseDraft() {
  return {
    name: String(project.value?.name || '').trim(),
    description: String(project.value?.description || '').trim(),
    style: project.value?.style || '3d-xiuxian',
    ratio: project.value?.ratio || '16:9',
  }
}

function chapterWorkflow(chapter) {
  return chapter?.workflow && typeof chapter.workflow === 'object' ? chapter.workflow : {}
}

function storedCreationData(chapter) {
  const workflow = chapterWorkflow(chapter)
  const projectWorkflow = project.value?.workflow && typeof project.value.workflow === 'object' ? project.value.workflow : {}
  return workflow.creationData || chapter?.creationData || workflow.assets || workflow.storyboard || projectWorkflow.creationData || project.value?.creationData || null
}

function chapterBaseDraft() {
  const target = currentChapter.value || chapters.value[0]
  const workflow = chapterWorkflow(target)
  return {
    title: normalizeEpisodeTitle(target?.title || '第1集'),
    sourceText: cleanScriptPayload(workflow.novel || target?.content || target?.sourceText || ''),
    script: cleanScriptPayload(target?.script || workflow.script || target?.chapterDraft?.script || ''),
  }
}

function stageFromChapter(chapter) {
  const workflow = chapterWorkflow(chapter)
  const creation = storedCreationData(chapter)
  if (creation) return workflow.workflowStage === 'video' ? 'video' : 'assets'
  return 'script'
}

function hydrateChapterFromStoredProject() {
  const chapter = currentChapter.value || chapters.value[0]
  chapterDraft.value = { ...chapterBaseDraft(), ...chapterDraft.value }

  const { outline, script } = separateOutlineAndScript(chapterDraft.value.script)
  if (outline && !chapterDraft.value.sourceText) {
    chapterDraft.value.sourceText = cleanScriptPayload(outline)
  }
  if (!script && outline) {
    chapterDraft.value.script = ''
  } else if (script) {
    chapterDraft.value.script = cleanScriptPayload(script)
  } else {
    chapterDraft.value.script = cleanScriptPayload(chapterDraft.value.script)
  }

  const outlineSource = outline || chapterDraft.value.sourceText || ''
  if (outlineSource && chapters.value.length === 1 && projectId.value) {
    const parsed = extractEpisodesFromDocumentOrText(null, outlineSource)
    if (parsed.length >= 2) {
      syncPlannedEpisodes(parsed)
    }
  }

  creationDataDraft.value = storedCreationData(chapter) || null
  creationScriptSnapshot.value = creationDataDraft.value ? chapterDraft.value.script : ''
  if (chapter?.title) chapterDraft.value.title = normalizeEpisodeTitle(chapter.title)
}

function resetConversation(conversation = null) {
  activeConversationId.value = conversation?.id ? String(conversation.id) : ''
  messages.value = Array.isArray(conversation?.messages)
    ? conversation.messages.map(item => {
        if (item.role !== 'assistant') return { ...item }
        const structured = item.structured && typeof item.structured === 'object' ? item.structured : parseJson(item.text)
        return { ...item, text: cleanAgentText(item.text, structured), structured: Boolean(structured) }
      })
    : []
  draft.value = ''
  saveMessage.value = ''
  projectDraft.value = { ...projectBaseDraft(), ...(conversation?.projectDraft && typeof conversation.projectDraft === 'object' ? conversation.projectDraft : {}) }
  chapterDraft.value = { ...chapterBaseDraft(), ...(conversation?.chapterDraft && typeof conversation.chapterDraft === 'object' ? conversation.chapterDraft : {}) }
  
  const { outline: convOutline, script: convScript } = separateOutlineAndScript(chapterDraft.value.script)
  if (convOutline && !chapterDraft.value.sourceText) {
    chapterDraft.value.sourceText = cleanScriptPayload(convOutline)
  }
  if (!convScript && convOutline) {
    chapterDraft.value.script = ''
  } else if (convScript) {
    chapterDraft.value.script = cleanScriptPayload(convScript)
  } else {
    chapterDraft.value.script = cleanScriptPayload(chapterDraft.value.script)
  }
  chapterDraft.value.sourceText = cleanScriptPayload(chapterDraft.value.sourceText)

  const stored = (currentChapter.value || chapters.value[0])?.workflow?.creationData
  creationDataDraft.value = conversation?.creationData && typeof conversation.creationData === 'object' ? conversation.creationData : (stored && typeof stored === 'object' ? stored : null)
  creationScriptSnapshot.value = creationDataDraft.value ? chapterDraft.value.script : ''
  if (projectId.value) stage.value = stageFromChapter(currentChapter.value || chapters.value[0])
  scrollToEnd()
}

async function loadExistingProjects() {
  loadingExistingProjects.value = true
  try {
    const result = await request('GET', '/project/list')
    existingProjects.value = listItems(result).filter(item => item && item.id).sort((a, b) => {
      const aTime = new Date(a.updatedAt || a.updateTime || a.createdAt || 0).getTime() || 0
      const bTime = new Date(b.updatedAt || b.updateTime || b.createdAt || 0).getTime() || 0
      return bTime - aTime
    })
  } catch (err) {
    error.value = '读取历史项目失败：' + cleanError(err)
  } finally {
    loadingExistingProjects.value = false
  }
}

async function continueProject(item) {
  if (!item?.id || saving.value) return
  loading.value = true
  error.value = ''; saveMessage.value = ''
  projectId.value = String(item.id)
  try {
    await loadProject()
    await loadConversations()
  } catch (err) {
    error.value = '打开历史项目失败：' + cleanError(err)
    projectId.value = ''
  } finally {
    loading.value = false
  }
}

async function loadModels() {
  loadingModels.value = true
  try {
    const result = await request('GET', '/api/admin/models/public/list?modelType=text')
    models.value = Array.isArray(result) ? result : []
    const currentValid = models.value.some(m => String(m.id ?? m.modelName ?? '') === selectedModel.value)
    if (!currentValid || !selectedModel.value) {
      selectedModel.value = String(models.value[0]?.id ?? models.value[0]?.modelName ?? '')
    }
  } catch (err) {
    error.value = '读取文本模型失败：' + cleanError(err)
  } finally {
    loadingModels.value = false
  }
}

async function loadProject() {
  if (!projectId.value) {
    project.value = null
    chapters.value = []
    selectedChapterId.value = ''
    stage.value = 'setup'
    resetConversation()
    return
  }
  const result = await request('GET', '/project/' + encodeURIComponent(projectId.value))
  const chapterData = await request('GET', '/project/' + encodeURIComponent(projectId.value) + '/chapter/list')
  project.value = result || { id: projectId.value }
  const rawList = Array.isArray(chapterData) ? chapterData : []
  chapters.value = rawList.map(item => {
    const normTitle = normalizeEpisodeTitle(item.title)
    if (normTitle !== item.title && item.id) {
      request('PUT', `/chapter/${encodeURIComponent(item.id)}`, { ...item, title: normTitle }).catch(() => {})
    }
    return {
      ...item,
      title: normTitle,
    }
  })
  sortChaptersList()
  if (chapters.value.length > 0) {
    const target = (selectedChapterId.value && chapters.value.find(c => String(c.id) === String(selectedChapterId.value))) || chapters.value[0]
    selectChapter(target)
  }
  projectDraft.value = { ...projectBaseDraft() }
  resetConversation()
  stage.value = stageFromChapter(currentChapter.value || chapters.value[0])
  hydrateChapterFromStoredProject()
}

async function loadConversations() {
  loadingConversations.value = true
  try {
    const result = await request('GET', '/project-agent-conversation/list?projectId=' + encodeURIComponent(scopeId.value))
    const items = Array.isArray(result) ? result : []
    conversations.value = items.map(item => ({
      ...item,
      title: cleanConversationTitle(item.title || conversationTitle(item.messages || [])),
    }))
    resetConversation(conversations.value[0])
  } catch (err) {
    error.value = '读取项目对话失败：' + cleanError(err)
  } finally {
    loadingConversations.value = false
  }
}

function scrollToEnd() {
  nextTick(() => {
    if (scrollArea.value) scrollArea.value.scrollTop = scrollArea.value.scrollHeight
  })
}

function cleanConversationTitle(title) {
  let text = String(title || '').trim().replace(/\s+/g, ' ')
  if (!text) return '第1集剧本创作'
  text = text
    .replace(/^请根据当前项目资料(?:从零)?创作(?:第[1一]集)?(?:短剧)?[，,：:。\s]*/u, '')
    .replace(/^根据当前项目资料(?:从零)?创作(?:第[1一]集)?(?:短剧)?[，,：:。\s]*/u, '')
    .replace(/^请根据[^\s，,：:。]*[，,：:。\s]*/u, '')
    .replace(/^根据[^\s，,：:。]*[，,：:。\s]*/u, '')
    .trim()
  if (!text || /^请根据/u.test(text) || /^根据/u.test(text) || text.length < 2) {
    return '第1集剧本创作'
  }
  if (text.startsWith('我有一段小说') || text.startsWith('导入小说')) return '小说故事改编'
  if (text.startsWith('请在不改变') || text.startsWith('继续完善')) return '继续完善剧本'
  return text.length > 22 ? text.slice(0, 22) + '…' : text
}

function conversationTitle(items) {
  const first = items.find(item => item.role === 'user' && String(item.text || '').trim())
  if (!first) return '新创作对话'
  const text = String(first.text).trim().replace(/\r?\n/g, ' ').replace(/\s+/g, ' ')
  return cleanConversationTitle(text)
}

async function persistConversation() {
  const conversation = currentConversation.value
  if (!conversation) return
  const payload = {
    projectId: scopeId.value,
    title: conversationTitle(messages.value),
    messages: messages.value.slice(-80),
    projectDraft: projectDraft.value,
    chapterDraft: chapterDraft.value,
    creationData: creationDataDraft.value,
    updatedAt: new Date().toISOString(),
  }
  Object.assign(conversation, payload)
  try {
    await request('PUT', '/project-agent-conversation/' + encodeURIComponent(conversation.id), payload)
  } catch (err) {
    error.value = '对话保存失败：' + cleanError(err)
  }
}

function schedulePersist() {
  if (!activeConversationId.value) return
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(persistConversation, 400)
}

async function ensureConversation() {
  if (activeConversationId.value) return currentConversation.value
  const created = await request('POST', '/project-agent-conversation', {
    projectId: scopeId.value,
    title: '新创作对话',
    messages: [],
    projectDraft: projectDraft.value,
    chapterDraft: chapterDraft.value,
  })
  if (!created?.id) throw new Error('创作对话创建失败')
  conversations.value.unshift(created)
  activeConversationId.value = String(created.id)
  return created
}

async function createProjectAndEnter() {
  if (saving.value) return
  if (!projectDraft.value.name.trim()) {
    error.value = '请先填写项目名称'
    return
  }
  if (!projectDraft.value.description.trim()) {
    error.value = '请先填写项目简介，Agent 会把它作为固定创作上下文'
    return
  }
  const draftConversation = !projectId.value ? currentConversation.value : null
  saving.value = true
  error.value = ''; saveMessage.value = ''
  try {
    const created = await request('POST', '/project', {
      name: projectDraft.value.name.trim(),
      description: projectDraft.value.description.trim(),
      style: projectDraft.value.style,
      styleDesc: projectStyleDescription.value,
      ratio: projectDraft.value.ratio,
      coverId: '',
      workflowStage: 'script',
    })
    if (!created?.id) throw new Error('项目创建失败')
    projectId.value = String(created.id)
    project.value = created
    const initialTitle = normalizeEpisodeTitle(chapterDraft.value.title.trim() || '第1集')
    chapterDraft.value.title = initialTitle
    const chapter = await request('POST', '/project/' + encodeURIComponent(projectId.value) + '/chapter', {
      title: initialTitle,
      content: chapterDraft.value.sourceText || '',
      script: chapterDraft.value.script || '',
      workflow: {
        workflowStage: 'script',
        agentCreated: true,
        agentUpdatedAt: new Date().toISOString(),
      },
    })
    if (chapter) chapter.title = normalizeEpisodeTitle(chapter.title)
    chapters.value = chapter ? [chapter] : []
    if (chapter) selectedChapterId.value = String(chapter.id)
    stage.value = 'script'
    if (draftConversation?.id) {
      const payload = {
        projectId: projectId.value,
        title: conversationTitle(draftConversation.messages || []),
        messages: Array.isArray(draftConversation.messages) ? draftConversation.messages.slice(-80) : [],
        projectDraft: projectDraft.value,
        chapterDraft: chapterDraft.value,
        creationData: creationDataDraft.value,
        updatedAt: new Date().toISOString(),
      }
      await request('PUT', '/project-agent-conversation/' + encodeURIComponent(draftConversation.id), payload)
    }
    conversations.value = []
    resetConversation()
    await loadConversations()
    saveMessage.value = draftConversation?.id ? '已恢复之前的创作草稿，并保存到当前项目' : '项目已创建，下面开始创作第1集'
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    saving.value = false
  }
}

function normalizeAgentDraft(document) {
  if (!document || typeof document !== 'object') return false
  const projectValue = document.project || document.projectDraft || {}
  const chapter = document.chapter || document.chapterDraft || {}
  if (projectValue.name) projectDraft.value.name = String(projectValue.name).slice(0, 100)
  if (projectValue.description) projectDraft.value.description = decodeEscapedText(projectValue.description)
  if (projectValue.style) projectDraft.value.style = String(projectValue.style)
  if (projectValue.ratio) projectDraft.value.ratio = String(projectValue.ratio)

  // 始终锁定并规范化当前正在创作的集数名称，防止 AI 错乱或重置集数
  const currentExpectedTitle = normalizeEpisodeTitle(currentChapter.value?.title || chapterDraft.value.title || '第1集')
  chapterDraft.value.title = currentExpectedTitle

  if (chapter.sourceText || chapter.content || document.sourceText) chapterDraft.value.sourceText = cleanScriptPayload(chapter.sourceText || chapter.content || document.sourceText)
  if (chapter.script || document.script) chapterDraft.value.script = cleanScriptPayload(chapter.script || document.script)
  if (document.creationData) creationDataDraft.value = normalizeCreationData(document.creationData)
  return Boolean(chapterDraft.value.script || chapterDraft.value.sourceText || projectDraft.value.name)
}

async function submit() {
  if (!canSend.value) return
  const prompt = draft.value.trim()
  await ensureConversation()
  messages.value.push({ id: Date.now() + '-user', role: 'user', text: prompt })
  draft.value = ''
  generating.value = true
  error.value = ''
  scrollToEnd()

  const storyContext = buildStorylineContext(currentChapter.value)
  const currentEpTitle = storyContext.currentTitle
  chapterDraft.value.title = currentEpTitle

  const system = `【身份与核心准则】：
你是 CDTV 当前项目专属的专业剧本创作总控 Agent（深度集成漫剧老李 V7.4.20 导演引擎套件）。项目资料：名称=《${projectDraft.value.name}》；简介=${projectDraft.value.description}；风格=${projectDraft.value.style}；比例=${projectDraft.value.ratio}。\n\n${storyContext.contextPrompt}\n\n【视听与时长规划准则（极重要）】：
1. 【时长与分幕分集最佳实践】：AI 单镜头视频通常为 8~10 秒。若用户提出长视频（如 6~10 分钟或多集短剧），严禁在一集内把全片故事草草缩减完！必须采取工业级分幕分集制作：
   - 整体建议规划为 4~6 集/幕（例如每集约 2~3 分钟，包含 12~18 个高精连续分镜，生成极快极稳且制作体验最佳）；
   - 当前你正在创作的是【${currentEpTitle}】。必须聚焦创作当前集/当前幕的扎实可拍摄剧情，体量控制在约 2~3 分钟（包含丰富场景交替、细腻动作、台词与情绪铺垫，足够提炼 12~18 个高精分镜）；
2. 【漫剧老李 V7.4.20 工业级剧本与对白门禁】：
   - 【严格分离对白与旁白 · 智能过滤小说冗余（核心铁律）】：
     * 默认短剧/漫剧赛道：全片以【角色对白、微表情神态、视线流转、肢体动作与现场环境视听】为绝对核心！
     * 彻底清洗小说中冗余的作者旁白、背景介绍与内心独白：将所有抽象心理描写转化为具体可拍的微动作、神态变化或角色的直接对白；
     * 若用户指定或倾向“无旁白”，则严禁输出任何口播旁白（VO），所有信息必须 100% 通过角色对白与表演自然交代；
   - 【对白语气与时序（C16规范）】：所有对白必须采用标准影视格式：【角色名（情绪/语气位）："台词内容"】。台词语速按3.5~5字/秒设计，长台词需有动作停顿或视线转移，绝不写空洞无情感的对白；
   - 【文戏微表情与动作落地】：每个场次人物必须有清晰的身体朝向、视线、左右手动作与微表情变化，杜绝“面部毫无波澜”或空洞假动作；
   - 【动作桥接不跳帧】：进门、转身、拔剑、起身、拿取等动作必须交代桥接过程，禁止出现瞬间瞬移跳跃。
3. 【输出语言与格式铁律】：
   - 必须 100% 全程使用纯中文！严禁输出任何英文分析、英文单词、英文翻译对照、思考自白或分析草稿；
   - 严禁多余的客套闲聊或自言自语，不讲废话，直接输出剧本结果；
   - 只负责创作和修改当前集（${currentEpTitle}）剧本，不要生成资产数据；
   - 必须延续已确认的人物名、场景、世界观；
   - 必须返回合法 JSON 对象，格式如下：
{
  "project": {"name":"${projectDraft.value.name}","description":"${projectDraft.value.description}","style":"${projectDraft.value.style}","ratio":"${projectDraft.value.ratio}"},
  "episodes": [
    {"num": 1, "title": "第1集《...》", "summary": "第1集剧情大纲摘要..."},
    {"num": 2, "title": "第2集《...》", "summary": "第2集剧情大纲摘要..."},
    {"num": 3, "title": "第3集《...》", "summary": "第3集剧情大纲摘要..."},
    {"num": 4, "title": "第4集《...》", "summary": "第4集剧情大纲摘要..."},
    {"num": 5, "title": "第5集《...》", "summary": "第5集剧情大纲摘要..."}
  ],
  "chapter": {
    "title": "${currentEpTitle}",
    "sourceText": "当前集故事摘要/大纲",
    "script": "【场1 暗房 / 夜 / 内】\\n【镜1-1】（特写）老陈右手捏着镊子在定影液中晃动，目光沉郁。\\n老陈（低语）：\\"怎么会是这张……\\"\\n【镜1-2】（全景）暗房红色安全灯闪烁，湿漉漉的照片开始扭曲浮现1983年街景。\\n..."
  }
}
【极重要·纯净剧本与大纲严格分离铁律】：
1. 若用户要求规划全片/多集，必须将各集大纲放入 episodes 数组；
2. chapter.script 必须 100% 是当前集的可拍摄分镜头剧本正文（严格从具体场次【场1 ...】和镜头【镜1-1】开写，包含具体动作与台词）！
3. 严禁在 chapter.script 中包含【全片规划】、各集大纲列表、体量说明或客套话！大纲请严格放在 episodes 或 sourceText，script 必须 100% 纯净可直接拍摄！`

  try {
    const history = messages.value.filter(item => item.role === 'user' || item.role === 'assistant').map(item => ({
      role: item.role,
      content: item.text || '',
    }))
    const result = await request('POST', '/ai/chat', {
      model: selectedModel.value,
      messages: [{ role: 'system', content: system }, ...history],
      temperature: 0.5,
      max_tokens: 16000,
    })
    const rawText = parseText(result).trim()
    if (!rawText) throw new Error('文本模型没有返回内容')
    const document = parseJson(rawText)
    const displayText = cleanAgentText(rawText, document)
    messages.value.push({
      id: Date.now() + '-assistant',
      role: 'assistant',
      text: displayText,
      structured: Boolean(document),
    })
    if (document) {
      normalizeAgentDraft(document)
    }

    // 1. 智能识别大纲中的多集规划，并自动同步创建到集数栏
    const parsedEpisodes = extractEpisodesFromDocumentOrText(document, rawText)
    if (parsedEpisodes.length >= 2) {
      await syncPlannedEpisodes(parsedEpisodes)
    }

    // 2. 严格分离大纲与可拍摄剧本
    let candidateScript = (document?.chapter?.script || document?.script || '').trim()
    let candidateSourceText = (document?.chapter?.sourceText || document?.sourceText || '').trim()

    if (!candidateScript) {
      candidateScript = displayText.trim()
    }

    const { outline, script } = separateOutlineAndScript(candidateScript)

    if (outline && (!chapterDraft.value.sourceText || chapterDraft.value.sourceText.length < 20)) {
      chapterDraft.value.sourceText = cleanScriptPayload(outline)
    }
    if (candidateSourceText && !chapterDraft.value.sourceText) {
      chapterDraft.value.sourceText = cleanScriptPayload(candidateSourceText)
    }

    if (script && script.length > 20) {
      chapterDraft.value.script = cleanScriptPayload(script)
    } else if (!script && outline) {
      // 纯大纲情况：保存大纲到 sourceText，清除剧本中的大纲文本，避免污染可拍摄剧本
      chapterDraft.value.sourceText = cleanScriptPayload(outline)
      chapterDraft.value.script = ''
    }

    // 更新当前集数标题（若有提取出的完整标题）
    const firstEp = parsedEpisodes.find(e => e.num === getEpisodeNumber(currentEpTitle))
    if (firstEp && firstEp.title) {
      chapterDraft.value.title = firstEp.title
    } else {
      chapterDraft.value.title = currentEpTitle
    }

    stage.value = 'script'
    await persistConversation()

    // 自动同步保存剧本到项目章节，无需用户手动到处找保存
    if (projectId.value && (chapterDraft.value.script || chapterDraft.value.sourceText)) {
      await saveChapter(`《${chapterDraft.value.title}》已自动同步`)
    }
  } catch (err) {
    messages.value.push({
      id: Date.now() + '-error',
      role: 'assistant',
      text: '',
      error: cleanError(err),
    })
    error.value = cleanError(err)
  } finally {
    generating.value = false
    scrollToEnd()
  }
}

async function saveChapter(message = '剧本已保存') {
  if (!projectId.value) {
    error.value = '请先创建项目'
    return false
  }
  if (!chapterDraft.value.script.trim() && !chapterDraft.value.sourceText.trim()) {
    error.value = '请先让 Agent 写出剧本，或在右侧手动填写'
    return false
  }
  const keepCreationData = hasCreationData.value && creationScriptSnapshot.value === chapterDraft.value.script && (stage.value === 'assets' || stage.value === 'video')
  if (hasCreationData.value && !keepCreationData) creationDataDraft.value = null
  saving.value = true
  error.value = ''; saveMessage.value = ''
  try {
    await request('PUT', '/project/' + encodeURIComponent(projectId.value), {
      name: projectDraft.value.name.trim() || project.value?.name || '未命名项目',
      description: projectDraft.value.description.trim(),
      style: projectDraft.value.style,
      styleDesc: projectStyleDescription.value,
      ratio: projectDraft.value.ratio,
      coverId: project.value?.coverId || '',
      workflowStage: keepCreationData ? (stage.value === 'video' ? 'video' : 'assets') : 'script',
    })
    const oldWorkflow = currentChapter.value?.workflow && typeof currentChapter.value.workflow === 'object' ? currentChapter.value.workflow : {}
    const workflow = {
      ...oldWorkflow,
      novel: chapterDraft.value.sourceText,
      script: chapterDraft.value.script,
      workflowStage: hasCreationData.value ? (stage.value === 'video' ? 'video' : 'assets') : 'script',
      agentUpdatedAt: new Date().toISOString(),
    }
    if (hasCreationData.value) workflow.creationData = creationDataDraft.value
    const finalTitle = normalizeEpisodeTitle(chapterDraft.value.title.trim() || '第1集')
    chapterDraft.value.title = finalTitle
    const payload = {
      title: finalTitle,
      content: chapterDraft.value.sourceText,
      script: chapterDraft.value.script,
      workflow,
    }
    const targetChapterId = currentChapter.value?.id
    const saved = targetChapterId
      ? await request('PUT', '/chapter/' + encodeURIComponent(targetChapterId), payload)
      : await request('POST', '/project/' + encodeURIComponent(projectId.value) + '/chapter', payload)
    if (saved) {
      saved.title = normalizeEpisodeTitle(saved.title)
      const idx = chapters.value.findIndex(item => String(item.id) === String(saved.id))
      if (idx >= 0) {
        chapters.value[idx] = saved
      } else {
        chapters.value.push(saved)
      }
      sortChaptersList()
      selectedChapterId.value = String(saved.id)
    }
    stage.value = hasCreationData.value ? (stage.value === 'video' ? 'video' : 'assets') : 'script'
    await persistConversation()
    saveMessage.value = message
    return true
  } catch (err) {
    error.value = cleanError(err)
    return false
  } finally {
    saving.value = false
  }
}

async function extractCreationData() {
  if (!hasScript.value) {
    error.value = '请先完成本集剧本，再提取资产与分镜'
    activeTab.value = 'script'
    return
  }
  if (!selectedModel.value) {
    error.value = '请先在模型管理中配置文本模型'
    return
  }
  extracting.value = true
  error.value = ''; saveMessage.value = ''
  const stylePrefix = getProjectStylePrefix(projectDraft.value.style)
  const styleDesc = getProjectStyleDescription(projectDraft.value.style) || stylePrefix
  // 智能识别剧本中已经规划的分镜标号（如【镜1-1】、【镜1-2】、【镜头1】、【第1镜】、【分镜1】等全语法）
  const scriptText = chapterDraft.value.script || ''
  const explicitShots = scriptText.match(/【?(?:第?\s*\d+\s*镜|镜\s*\d+(?:[-—]\d+)?|镜头\s*\d+|分镜\s*\d+)】?/gi) || []
  const explicitCount = explicitShots.length
  const shotCountDesc = explicitCount > 0
    ? `剧本中已规划了约 ${explicitCount} 个明确分镜标号（如【镜1-1】、【镜头1】等），必须 1:1 完整提取全部 ${explicitCount} 个分镜，分镜数量严禁少于剧本原有数量，绝对不允许中途合并或截断`
    : '根据剧本情节提炼 12~18 个高精连续分镜（充足分镜量），单镜 8~10 秒，确保剧情饱满连贯'
  const prompt = `请把下面项目的剧本转换成结构化创作数据 JSON。必须只返回合法 JSON，不要 Markdown。\n项目信息：名称="${projectDraft.value.name}"，题材简介="${projectDraft.value.description}"，美术风格="${projectDraft.value.style}"（${styleDesc}），视频比例="${projectDraft.value.ratio}"。\n\n剧本内容：\n${scriptText}\n\n严格要求（遵循漫剧老李 V7.4.20 规范）：\n1. 稳定资产 ID：同一人物全片始终复用同一个 character id（如 char_luming）；同一场景始终复用同一个 scene id；\n2. 资产列表（精简精准）：\n   - characters: 提炼剧本出场的核心人物，每个包含 id、name、appearance（开头带风格关键词"${stylePrefix}"，紧凑描写核心发型服装与面部特征识别点，控制在 50~80 字）；\n   - scenes: 提炼核心场景，每个包含 id、name、environment（开头带风格关键词"${stylePrefix}"，精炼描写空间几何与光影，控制在 40~60 字）；\n   - props: 核心道具，包含 id（如 prop_amulet）、name、appearance；\n   - audio: 包含核心对白配音（aud_vo_...）与关键音效（aud_sfx_...），其中配音 prompt 严格遵循【六维强感知音频公式】：【统一音色·角色名】职业身份+性别+年龄+音高+声音质地+发声特点+原本台词与情绪，同一角色绑定相同 voice 音色预设且全集声学描述 100% 绝对一致，杜绝同一人物声音漂移；\n   - asset_wirelist: 严格按 M1 编号占位输出素材接线单（[{"slot":"图1","asset_id":"...","name":"...","type":"character/scene","action":"..."}]）；\n3. 分镜规划（核心·必须 100% 完整提取，绝不允许偷懒少给）：\n   - ${shotCountDesc}；\n   - 每个 shot 必须包含：id（如 shot_01、shot_02...）、title、duration_s（8~10秒）、scene_id、references（引用资产ID列表）、wirelist（当前镜头挂载的图号接线列表）、visual（画面与动作精炼描写，30~50字）、camera（专业运镜指导）、dialogue（对白数组，格式：角色名（语气）："台词"）、audio_prompt（【六维音频提示词·全集音色一致性锁定】：同一角色前五维声学特征跨镜头绝对一致，统一标注【统一音色·角色名】，后续出场镜头标注“沿用统一基准音色”，强化视频生成模型对同人同音的感知与表现）、video_prompt（核心生视频提示词，精炼七段式：画风+场景+主体角色+站位朝向+动作时序+对白音效质感+电影质感锁闭，70~100字）；\n   - 保持紧凑精炼，不要输出冗长废话，确保一口气输出完整闭合的合法 JSON！`
  try {
    const result = await request('POST', '/ai/creation-data', {
      model: selectedModel.value,
      scope: 'full',
      title: chapterDraft.value.title || projectDraft.value.name,
      prompt,
    })
    const document = parseJson(result?.document || result?.text || result?.content || '')
    if (!document) throw new Error('文本模型返回的资产数据不是合法 JSON')
    creationDataDraft.value = normalizeCreationData(document)
    creationScriptSnapshot.value = chapterDraft.value.script
    stage.value = 'assets'
    await saveChapter('资产与分镜已提取，请检查一致性后推送制作')
    activeTab.value = 'assets'
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    extracting.value = false
  }
}

async function pushToVideo() {
  if (!hasCreationData.value) {
    error.value = '请先提取资产与分镜'
    return
  }
  if (!await saveChapter('已保存并准备推送到视频制作')) return
  stage.value = 'video'
  emit('open-video', {
    document: creationDataDraft.value,
    projectId: projectId.value,
    chapterId: currentChapter.value?.id || '',
    projectName: projectDraft.value.name,
    chapterTitle: chapterDraft.value.title,
  })
}

function fillSuggestion(text) {
  draft.value = text
  nextTick(() => draftInput.value?.focus())
}

function handleKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault()
    submit()
  }
}

function handleGlobalClick(event) {
  if (!event.target.closest('.episode-add-wrapper')) {
    showAddMenu.value = false
  }
  if (!event.target.closest('.episode-grid-wrapper')) {
    showEpisodeGrid.value = false
  }
}

function setStage(next) {
  if (next === 'setup' || next === 'script' || (next === 'assets' && hasCreationData.value) || (next === 'video' && hasCreationData.value)) {
    stage.value = next
  } else if (next === 'assets' && hasScript.value) {
    stage.value = 'assets'
  }
}

function selectConversation(conversation) {
  if (!generating.value) resetConversation(conversation)
}

function newConversation() {
  if (!generating.value) {
    resetConversation()
    nextTick(() => draftInput.value?.focus())
  }
}

function restoreDraftConversation(conversation) {
  if (!conversation || generating.value) return
  resetConversation(conversation)
  saveMessage.value = '已恢复这条创作记录。补齐项目资料后，点击“创建并进入剧本助手”即可继续。'
}

function removeConversation(conversation) {
  if (!conversation?.id || generating.value) return
  request('DELETE', '/project-agent-conversation/' + encodeURIComponent(conversation.id)).catch(() => {})
  conversations.value = conversations.value.filter(item => String(item.id) !== String(conversation.id))
  if (String(activeConversationId.value) === String(conversation.id)) resetConversation(conversations.value[0])
}

function openExistingProject() {
  if (projectId.value) emit('project-created', project.value || { id: projectId.value })
}

watch(() => props.initialProjectId, async value => {
  projectId.value = String(value || '')
  loading.value = true
  try {
    await loadProject()
    await loadConversations()
    hydrateChapterFromStoredProject()
    if (!projectId.value) await loadExistingProjects()
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    loading.value = false
  }
})

watch([projectDraft, chapterDraft, creationDataDraft], schedulePersist, { deep: true })

onMounted(async () => {
  window.addEventListener('cdtv:models-updated', loadModels)
  window.addEventListener('focus', loadModels)
  window.addEventListener('click', handleGlobalClick)
  loading.value = true
  try {
    await loadModels()
    await loadProject()
    await loadConversations()
    hydrateChapterFromStoredProject()
    if (!projectId.value) await loadExistingProjects()
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('cdtv:models-updated', loadModels)
  window.removeEventListener('focus', loadModels)
  window.removeEventListener('click', handleGlobalClick)
  if (persistTimer) clearTimeout(persistTimer)
})
</script>

<template>
  <section class="project-agent-workspace">
    <header class="project-agent-hero">
      <div>
        <p class="eyebrow">项目剧本工作流</p>
        <h1>{{ projectId ? (projectDraft.name || project?.name || '项目剧本助手') : '先建剧本，再一路做到成片' }}</h1>
        <p>一条清晰链路：先填写项目资料 → Agent 写剧本 → 自动提取资产与分镜 → 推送到生图 / 生视频。</p>
      </div>
      <div class="project-agent-flow">
        <button
          v-for="item in [{id:'setup',label:'新建剧本'},{id:'script',label:'剧本 Agent'},{id:'assets',label:'提取资产'},{id:'video',label:'推送制作'}]"
          :key="item.id"
          type="button"
          :class="{ active: stage === item.id, done: stageIndex > ({setup:0,script:1,assets:2,video:3}[item.id]) }"
          @click="setStage(item.id)"
        >
          {{ item.label }}
        </button>
      </div>
    </header>

    <section v-if="loading" class="project-agent-state">
      <BaseLoadingState size="lg" panel text="正在打开项目剧本助手" description="正在读取项目、章节和文本模型…" />
    </section>

    <section v-else-if="stage === 'setup'" class="project-agent-setup panel">
      <div class="setup-heading">
        <span class="setup-number">01</span>
        <div>
          <h2>新建一个剧本项目</h2>
          <p>这一步只填写项目基础资料；保存后会自动进入这个项目专属的剧本 Agent。</p>
        </div>
      </div>

      <section class="setup-history">
        <header>
          <div>
            <h3>继续已有剧本</h3>
            <p>以前保存过的项目都会在这里，点一下就能回到对应的剧本 Agent，不用重新创建。</p>
          </div>
          <button type="button" class="link-button" :disabled="loadingExistingProjects" @click="loadExistingProjects">
            {{ loadingExistingProjects ? '读取中…' : '刷新' }}
          </button>
        </header>
        <div v-if="loadingExistingProjects" class="setup-history-empty">正在读取历史项目…</div>
        <div v-else-if="!existingProjects.length" class="setup-history-empty">还没有保存过的项目。先创建一个剧本项目，之后它会一直出现在这里。</div>
        <div v-else class="setup-history-list">
          <button v-for="item in existingProjects" :key="item.id" type="button" class="setup-history-item" @click="continueProject(item)">
            <span class="setup-history-copy">
              <strong>{{ item.name || '未命名项目' }}</strong>
              <small>{{ item.description || '暂未填写项目简介' }}</small>
            </span>
            <span class="setup-history-meta">
              <small>{{ projectStageLabel(item) }} · {{ projectDate(item) }}</small>
              <b>继续创作 →</b>
            </span>
          </button>
        </div>
      </section>

      <div class="setup-grid">
        <label class="setup-field setup-field-name">
          <span>项目名称</span>
          <input v-model="projectDraft.name" maxlength="100" placeholder="例如：丹神觉醒" />
        </label>
        <label class="setup-field setup-field-description">
          <span>项目简介</span>
          <textarea v-model="projectDraft.description" placeholder="一句话说明题材、主角和核心冲突，Agent 会一直带着它创作。"></textarea>
        </label>
      </div>

      <fieldset class="style-fieldset">
        <legend>选择风格</legend>
        <div v-for="group in projectStyleGroups" :key="group.label" class="style-group-box">
          <span class="style-group-label">{{ group.label }}</span>
          <div class="style-pill-grid">
            <label
              v-for="option in group.options"
              :key="option.value"
              class="style-pill"
              :class="{ active: projectDraft.style === option.value }"
            >
              <input v-model="projectDraft.style" type="radio" :value="option.value" />
              <span>{{ option.label }}</span>
            </label>
          </div>
        </div>
        <p class="style-desc-preview">{{ projectStyleDescription }}</p>
      </fieldset>

      <fieldset class="ratio-fieldset">
        <legend>视频比例</legend>
        <div class="ratio-pill-grid">
          <label
            v-for="option in projectRatioOptions"
            :key="option.value"
            class="ratio-pill"
            :class="{ active: projectDraft.ratio === option.value }"
          >
            <input v-model="projectDraft.ratio" type="radio" :value="option.value" />
            <span>{{ option.label }}</span>
          </label>
        </div>
      </fieldset>

      <div class="setup-actions">
        <button type="button" class="secondary-button" @click="emit('back')">返回</button>
        <button type="button" class="primary-button" :disabled="saving" @click="createProjectAndEnter">
          {{ saving ? '创建中…' : '创建并进入剧本助手' }}
        </button>
      </div>

      <section class="setup-history setup-draft-history">
        <header>
          <div>
            <h3>最近的创作记录</h3>
            <p>还没建成项目的对话也会保存在这里；恢复后补齐项目资料，就能接着写，不会丢。</p>
          </div>
        </header>
        <div v-if="loadingConversations" class="setup-history-empty">正在读取创作记录…</div>
        <div v-else-if="!conversations.length" class="setup-history-empty">还没有未建项目的创作记录。</div>
        <div v-else class="setup-history-list">
          <button v-for="item in conversations" :key="item.id" type="button" class="setup-history-item" @click="restoreDraftConversation(item)">
            <span class="setup-history-copy">
              <strong>{{ item.title || '新创作对话' }}</strong>
              <small>{{ conversationPreview(item) }}</small>
            </span>
            <span class="setup-history-meta">
              <small>{{ conversationDate(item) }}</small>
              <b>恢复草稿 →</b>
            </span>
          </button>
        </div>
      </section>

      <p v-if="error" class="project-agent-error">{{ error }}</p>
      <p v-if="saveMessage" class="project-agent-success">{{ saveMessage }}</p>
    </section>

    <template v-else>
      <section class="project-agent-projectbar panel">
        <div class="project-agent-project-copy">
          <span class="project-agent-kicker">当前项目</span>
          <div class="project-agent-info-text">
            <strong>{{ projectDraft.name || '未命名项目' }}</strong>
            <small :title="projectDraft.description">{{ projectDraft.description || '暂未填写项目简介' }}</small>
          </div>
        </div>
        <div class="project-agent-meta">
          <span :title="projectStyleDescription">{{ projectStyleDescription }}</span>
          <b>{{ projectDraft.ratio }}</b>
        </div>
        <button type="button" class="link-button" @click="openExistingProject">返回项目</button>
      </section>

      <!-- Compact Horizontal Episode Capsule Bar -->
      <section v-if="projectId" class="project-episode-bar panel">
        <div class="episode-bar-inner">
          <!-- Quick Jump Grid Popover Button -->
          <div class="episode-grid-wrapper">
            <button
              type="button"
              class="episode-quick-btn"
              :class="{ active: showEpisodeGrid }"
              :title="`集数导航 (共 ${chapters.length} 集)`"
              @click.stop="showEpisodeGrid = !showEpisodeGrid"
            >
              <span class="grid-icon">⊞</span>
              <span class="grid-label">{{ chapters.length }} 集</span>
              <span class="progress-pill">{{ completedCount }}/{{ chapters.length }}</span>
            </button>

            <!-- Grid Popover Dropdown -->
            <div v-if="showEpisodeGrid" class="episode-grid-popover" @click.stop>
              <div class="grid-popover-header">
                <strong>全部集数快捷跳转 (共 {{ chapters.length }} 集)</strong>
                <div class="grid-filter-pills">
                  <button type="button" :class="{ active: gridFilter === 'all' }" @click="gridFilter = 'all'">全部</button>
                  <button type="button" :class="{ active: gridFilter === 'done' }" @click="gridFilter = 'done'">已完成</button>
                  <button type="button" :class="{ active: gridFilter === 'draft' }" @click="gridFilter = 'draft'">草稿</button>
                </div>
              </div>
              <div class="grid-items-scroll">
                <div class="grid-items">
                  <button
                    v-for="chap in filteredGridChapters"
                    :key="chap.id"
                    type="button"
                    class="grid-item-btn"
                    :class="{
                      active: String(chap.id) === String(selectedChapterId),
                      prologue: isPrologueTitle(chap.title),
                      done: Boolean(chap.script || chap.workflow?.script),
                      assets: Boolean(chap.workflow?.creationData || chap.creationData),
                    }"
                    :title="`${chap.title} - ${getChapterStatusTitle(chap)}`"
                    @click="selectChapter(chap); showEpisodeGrid = false"
                  >
                    <span class="grid-item-name">{{ formatShortEpisodeTitle(chap.title) }}</span>
                    <i class="status-dot"></i>
                  </button>
                </div>
              </div>
              <div class="grid-popover-footer">
                <span class="legend"><i class="dot done"></i> 剧本完成</span>
                <span class="legend"><i class="dot assets"></i> 资产提取</span>
                <span class="legend"><i class="dot draft"></i> 待写</span>
              </div>
            </div>
          </div>

          <div class="episode-divider"></div>

          <!-- Horizontal Scroll Capsule Strip -->
          <div ref="episodeScrollRef" class="episode-scroll-wrapper">
            <!-- Optional Prologue Quick Add Button if not created and not hidden -->
            <div
              v-if="!hasPrologue && !hideProloguePill"
              class="add-prologue-wrapper"
            >
              <button
                type="button"
                class="add-prologue-pill"
                title="在第1集前添加开局旁白 / 序幕（无旁白可点击右侧 × 隐藏）"
                :disabled="saving"
                @click="addPrologue"
              >
                <span class="prologue-icon">🎙️</span>
                <span>+ 开局旁白</span>
              </button>
              <button
                type="button"
                class="prologue-dismiss-btn"
                title="本次不需要旁白，隐藏此按钮"
                @click.stop="dismissProloguePill"
              >
                ×
              </button>
            </div>

            <!-- Episodes List -->
            <button
              v-for="chap in chapters"
              :key="chap.id"
              type="button"
              class="episode-pill"
              :class="{
                active: String(chap.id) === String(selectedChapterId),
                prologue: isPrologueTitle(chap.title),
                done: Boolean(chap.script || chap.workflow?.script),
                assets: Boolean(chap.workflow?.creationData || chap.creationData),
              }"
              :title="`${chap.title} (${getChapterStatusTitle(chap)})`"
              @click="selectChapter(chap)"
            >
              <span v-if="isPrologueTitle(chap.title)" class="pill-icon">🎙️</span>
              <span class="pill-title">{{ chap.title }}</span>
              <span
                v-if="isPrologueTitle(chap.title)"
                class="prologue-remove-icon"
                title="删除旁白序幕集"
                @click.stop="removeCurrentChapter(chap)"
              >×</span>
              <span
                class="status-dot"
                :class="{
                  done: Boolean(chap.script || chap.workflow?.script),
                  assets: Boolean(chap.workflow?.creationData || chap.creationData),
                }"
              ></span>
            </button>
          </div>

          <!-- Quick Add Episode with Dropdown Menu -->
          <div class="episode-add-wrapper">
            <button
              type="button"
              class="episode-action-btn add-btn"
              :disabled="saving"
              :title="`创建${nextEpisodeLabel}`"
              @click="createNewChapter()"
            >
              ＋ {{ nextEpisodeLabel }}
            </button>
            <button
              type="button"
              class="episode-action-btn menu-toggle-btn"
              :disabled="saving"
              title="更多添加选项"
              @click.stop="showAddMenu = !showAddMenu"
            >
              ▾
            </button>

            <!-- Dropdown Menu -->
            <div v-if="showAddMenu" class="episode-menu-dropdown" @click.stop>
              <button type="button" @click="manualSyncPlannedEpisodes(); showAddMenu = false">
                ⚡ 从剧本大纲智能同步所有集数
              </button>
              <button v-if="!hasPrologue" type="button" @click="addPrologue(); showAddMenu = false">
                🎙️ 添加 开局旁白 / 序幕
              </button>
              <button type="button" @click="createNewChapter(); showAddMenu = false">
                ➕ 添加 {{ nextEpisodeLabel }}
              </button>
              <button type="button" @click="batchAddEpisodes(3); showAddMenu = false">
                📦 批量添加 3 集
              </button>
              <button type="button" @click="batchAddEpisodes(5); showAddMenu = false">
                📦 批量添加 5 集
              </button>
            </div>
          </div>
        </div>
      </section>

      <section class="project-agent-layout">
        <aside class="project-agent-sidebar panel">
          <div class="sidebar-section">
            <div class="sidebar-title">
              <span>项目步骤</span>
              <small>{{ stageIndex }}/3</small>
            </div>
            <button :class="{ active: stage === 'script' }" type="button" @click="setStage('script')">
              <b>02</b>
              <span>剧本 Agent<small>{{ hasScript ? '已生成剧本' : '等待创作' }}</small></span>
            </button>
            <button :class="{ active: stage === 'assets', disabled: !hasScript && !hasCreationData }" type="button" :disabled="!hasScript && !hasCreationData" @click="setStage('assets')">
              <b>03</b>
              <span>资产与分镜<small>{{ hasCreationData ? creationCounts.assets + ' 项资产 · ' + creationCounts.shots + ' 个分镜' : hasScript ? '剧本已就绪，可提取' : '剧本完成后提取' }}</small></span>
            </button>
            <button :class="{ active: stage === 'video', disabled: !hasCreationData }" type="button" :disabled="!hasCreationData" @click="setStage('video')">
              <b>04</b>
              <span>视频制作<small>{{ hasCreationData ? '可推送到生图 / 生视频' : '等待资产' }}</small></span>
            </button>
          </div>

          <div class="sidebar-section conversation-section">
            <div class="sidebar-title">
              <span>项目对话</span>
              <button type="button" @click="newConversation">＋ 新对话</button>
            </div>
            <div v-if="loadingConversations" class="sidebar-empty">读取中…</div>
            <div v-else-if="!conversations.length" class="sidebar-empty">发送第一句话后会自动保存对话</div>
            <button
              v-for="conversation in conversations"
              v-else
              :key="conversation.id"
              type="button"
              class="conversation-item"
              :class="{ active: String(conversation.id) === String(activeConversationId) }"
              @click="selectConversation(conversation)"
            >
              <span class="conversation-title-text" :title="conversation.title || '新创作对话'">
                {{ conversation.title || '新创作对话' }}
              </span>
              <span class="conversation-meta-row">
                <small>{{ conversation.updatedAt ? new Date(conversation.updatedAt).toLocaleDateString() : '未保存' }}</small>
                <i title="删除这条对话" @click.stop="removeConversation(conversation)">×</i>
              </span>
            </button>
          </div>
        </aside>

        <main class="project-agent-main panel">
          <template v-if="stage === 'script'">
            <header class="main-heading">
              <div>
                <span class="setup-number">02</span>
                <div>
                  <h2>剧本 Agent <span v-if="chapterDraft.title" class="current-chapter-tag">【{{ chapterDraft.title }}】</span></h2>
                  <p>把小说、故事、人物要求直接说给当前项目的 Agent，不用再手动拼 JSON。</p>
                </div>
              </div>
              <UiSelect v-model="selectedModel" :options="modelOptions" placeholder="选择文本模型" :disabled="!models.length || loadingModels" status badge="文本" />
            </header>
            <div ref="scrollArea" class="project-agent-messages">
              <div v-if="!messages.length" class="agent-welcome">
                <strong>从这里开始</strong>
                <p>可以粘贴小说、故事梗概，或直接告诉我本集要怎么写。项目名称、简介、风格和比例已经自动带入。</p>
                <div class="suggestion-list">
                  <button v-for="item in suggestions" :key="item.label" type="button" @click="fillSuggestion(item.text)">
                    {{ item.label }}
                  </button>
                </div>
              </div>
              <article v-for="message in messages" :key="message.id" class="project-agent-message" :class="message.role">
                <span>{{ message.role === 'user' ? '你' : 'Agent' }}</span>
                <div v-if="message.error" class="bubble error-bubble">{{ message.error }}</div>
                <div v-else class="bubble">{{ message.text }}</div>
              </article>
              <div v-if="generating" class="agent-typing">Agent 正在整理剧本…</div>
            </div>
            <div class="project-agent-composer">
              <textarea ref="draftInput" v-model="draft" placeholder="粘贴小说、输入故事要求，或告诉 Agent 怎么修改剧本…" @keydown="handleKeydown"></textarea>
              <div class="composer-foot">
                <small>Enter 发送 · Shift + Enter 换行</small>
                <button type="button" class="primary-button" :disabled="!canSend" @click="submit">
                  {{ generating ? '生成中…' : '发送给 Agent' }}
                </button>
              </div>
            </div>
          </template>

          <template v-else-if="stage === 'assets'">
            <header class="main-heading">
              <div>
                <span class="setup-number">03</span>
                <div>
                  <h2>提取资产与分镜</h2>
                  <p>剧本完成后只点一次，AI 会按稳定 ID 建立人物、场景、道具、音频和分镜引用。</p>
                </div>
              </div>
              <span class="ready-badge" :class="{ 'is-ready': hasCreationData }">{{ hasCreationData ? '已提取' : '未提取' }}</span>
            </header>

            <div class="asset-summary">
              <div><b>{{ creationCounts.assets }}</b><span>项一致性资产</span></div>
              <div><b>{{ creationCounts.shots }}</b><span>个连续分镜</span></div>
            </div>

            <div class="consistency-note">
              <strong>💡 一致性已写入生成数据</strong>
              <p>同一人物复用同一个 ID；同一场景保持同一个 scene_id；每个分镜记录视觉描述、运镜、对白及生图提示词，避免换脸和乱切场景。</p>
            </div>

            <!-- Asset Filter Navigation Tabs -->
            <div v-if="hasCreationData" class="asset-nav-bar">
              <button
                type="button"
                class="asset-nav-btn"
                :class="{ active: assetFilterTab === 'all' }"
                @click="assetFilterTab = 'all'"
              >
                ✨ 全部概要
              </button>
              <button
                v-if="extractedCharacters.length"
                type="button"
                class="asset-nav-btn"
                :class="{ active: assetFilterTab === 'characters' }"
                @click="assetFilterTab = 'characters'"
              >
                👤 角色 <small>({{ extractedCharacters.length }})</small>
              </button>
              <button
                v-if="extractedScenes.length"
                type="button"
                class="asset-nav-btn"
                :class="{ active: assetFilterTab === 'scenes' }"
                @click="assetFilterTab = 'scenes'"
              >
                🏞️ 场景 <small>({{ extractedScenes.length }})</small>
              </button>
              <button
                v-if="extractedProps.length"
                type="button"
                class="asset-nav-btn"
                :class="{ active: assetFilterTab === 'props' }"
                @click="assetFilterTab = 'props'"
              >
                🗡️ 道具 <small>({{ extractedProps.length }})</small>
              </button>
              <button
                v-if="extractedVoice.length"
                type="button"
                class="asset-nav-btn"
                :class="{ active: assetFilterTab === 'voice' }"
                @click="assetFilterTab = 'voice'"
              >
                🎙️ 语音配音 <small>({{ extractedVoice.length }})</small>
              </button>
              <button
                v-if="extractedSfx.length"
                type="button"
                class="asset-nav-btn"
                :class="{ active: assetFilterTab === 'sfx' }"
                @click="assetFilterTab = 'sfx'"
              >
                🔊 拟声音效 <small>({{ extractedSfx.length }})</small>
              </button>
              <button
                v-if="extractedShots.length"
                type="button"
                class="asset-nav-btn"
                :class="{ active: assetFilterTab === 'shots' }"
                @click="assetFilterTab = 'shots'"
              >
                🎬 分镜列表 <small>({{ extractedShots.length }})</small>
              </button>
              <button
                type="button"
                class="asset-nav-btn asset-nav-raw"
                :class="{ active: assetFilterTab === 'raw' }"
                @click="assetFilterTab = 'raw'"
              >
                { } 原始 JSON
              </button>
            </div>

            <!-- Structured Content Container -->
            <div v-if="hasCreationData" class="structured-assets-view">
              <!-- RAW JSON VIEW -->
              <div v-if="assetFilterTab === 'raw'" class="raw-json-container">
                <div class="raw-json-toolbar">
                  <span>原始结构化 JSON 数据</span>
                  <button type="button" class="copy-pill-btn" @click="copyToClipboard(JSON.stringify(creationDataDraft, null, 2), 'raw_json')">
                    {{ copySuccessId === 'raw_json' ? '✓ 已复制 JSON' : '复制 JSON' }}
                  </button>
                </div>
                <textarea
                  class="creation-json"
                  :value="JSON.stringify(creationDataDraft, null, 2)"
                  readonly
                  spellcheck="false"
                ></textarea>
              </div>

              <!-- STRUCTURED CARDS VIEW -->
              <div v-else class="structured-cards-container">
                <!-- Visual Style Banner -->
                <div class="asset-style-banner">
                  <div class="style-banner-left">
                    <span class="style-banner-badge">🎨 视觉风格</span>
                    <strong>{{ getProjectStyleName(projectDraft.style) }}</strong>
                  </div>
                  <span class="style-banner-desc">{{ getProjectStyleDescription(projectDraft.style) }}</span>
                </div>

                <!-- CHARACTERS SECTION -->
                <section
                  v-if="(assetFilterTab === 'all' || assetFilterTab === 'characters') && extractedCharacters.length"
                  class="asset-card-section"
                >
                  <div class="section-title">
                    <span class="icon">👤</span>
                    <h3>角色设定 ({{ extractedCharacters.length }})</h3>
                    <small>已自动注入项目视觉风格，用于生图时保持角色一致不换脸</small>
                  </div>
                  <div class="asset-cards-grid">
                    <div v-for="char in extractedCharacters" :key="char.id" class="asset-card character-card">
                      <div class="card-head">
                        <div class="card-name-group">
                          <span class="card-name">{{ char.name || '未命名角色' }}</span>
                          <span class="card-style-pill">{{ getProjectStyleName(projectDraft.style) }}</span>
                        </div>
                        <span class="card-id-tag">{{ char.id }}</span>
                      </div>
                      <p class="card-desc">{{ char.appearance || '暂无详细外貌描述' }}</p>
                    </div>
                  </div>
                </section>

                <!-- SCENES SECTION -->
                <section
                  v-if="(assetFilterTab === 'all' || assetFilterTab === 'scenes') && extractedScenes.length"
                  class="asset-card-section"
                >
                  <div class="section-title">
                    <span class="icon">🏞️</span>
                    <h3>场景设定 ({{ extractedScenes.length }})</h3>
                    <small>已自动注入环境光影与美术基调，避免乱切背景</small>
                  </div>
                  <div class="asset-cards-grid">
                    <div v-for="scene in extractedScenes" :key="scene.id" class="asset-card scene-card">
                      <div class="card-head">
                        <div class="card-name-group">
                          <span class="card-name">{{ scene.name || '未命名场景' }}</span>
                          <span class="card-style-pill scene-style-pill">{{ getProjectStyleName(projectDraft.style) }}</span>
                        </div>
                        <span class="card-id-tag">{{ scene.id }}</span>
                      </div>
                      <p class="card-desc">{{ scene.environment || scene.description || '暂无场景环境描述' }}</p>
                    </div>
                  </div>
                </section>

                <!-- PROPS SECTION -->
                <section
                  v-if="(assetFilterTab === 'all' || assetFilterTab === 'props') && extractedProps.length"
                  class="asset-card-section"
                >
                  <div class="section-title">
                    <span class="icon">🗡️</span>
                    <h3>关键道具 ({{ extractedProps.length }})</h3>
                    <small>核心道具与物品特征</small>
                  </div>
                  <div class="asset-cards-grid">
                    <div v-for="prop in extractedProps" :key="prop.id" class="asset-card prop-card">
                      <div class="card-head">
                        <span class="card-name">{{ prop.name || '未命名道具' }}</span>
                        <span class="card-id-tag">{{ prop.id }}</span>
                      </div>
                      <p class="card-desc">{{ prop.appearance || prop.description || '暂无道具外观描述' }}</p>
                    </div>
                  </div>
                </section>

                <!-- VOICE SECTION (TTS) -->
                <section
                  v-if="(assetFilterTab === 'all' || assetFilterTab === 'voice') && extractedVoice.length"
                  class="asset-card-section"
                >
                  <div class="section-title">
                    <span class="icon">🎙️</span>
                    <h3>语音配音 ({{ extractedVoice.length }})</h3>
                    <small>旁白、对白与系统音（支持 CosyVoice 等语音模型一键生成）</small>
                  </div>
                  <div class="asset-cards-grid">
                    <div v-for="aud in extractedVoice" :key="aud.id" class="asset-card audio-card voice-card">
                      <div class="card-head">
                        <div class="card-name-group">
                          <span class="card-name">{{ aud.name || '未命名配音' }}</span>
                          <span v-if="aud.voice" class="card-style-pill audio-style-pill">{{ aud.voice }}</span>
                        </div>
                        <span class="card-id-tag">{{ aud.id }}</span>
                      </div>
                      <p class="card-desc">{{ aud.style || aud.description || '暂无声音设定描述' }}</p>
                      <div v-if="aud.prompt" class="audio-prompt-preview"><strong>台词：</strong>{{ aud.prompt }}</div>
                    </div>
                  </div>
                </section>

                <!-- SFX SECTION (Sound Effects) -->
                <section
                  v-if="(assetFilterTab === 'all' || assetFilterTab === 'sfx') && extractedSfx.length"
                  class="asset-card-section"
                >
                  <div class="section-title">
                    <span class="icon">🔊</span>
                    <h3>环境音效 ({{ extractedSfx.length }})</h3>
                    <small>环境氛围、打斗拟声（支持本地上传 MP3 资源）</small>
                  </div>
                  <div class="asset-cards-grid">
                    <div v-for="aud in extractedSfx" :key="aud.id" class="asset-card audio-card sfx-card">
                      <div class="card-head">
                        <span class="card-name">{{ aud.name || '未命名音效' }}</span>
                        <span class="card-id-tag">{{ aud.id }}</span>
                      </div>
                      <p class="card-desc">{{ aud.style || aud.description || '暂无音效设定描述' }}</p>
                    </div>
                  </div>
                </section>

                <!-- SHOTS SECTION -->
                <section
                  v-if="(assetFilterTab === 'all' || assetFilterTab === 'shots') && extractedShots.length"
                  class="asset-card-section shots-section"
                >
                  <div class="section-title">
                    <span class="icon">🎬</span>
                    <h3>连续分镜列表 ({{ extractedShots.length }})</h3>
                    <small>包含画面、运镜、对白和视频生图提示词</small>
                  </div>
                  <div class="shots-list">
                    <div v-for="(shot, idx) in extractedShots" :key="shot.id || idx" class="shot-card">
                      <div class="shot-card-header">
                        <div class="shot-title-group">
                          <span class="shot-num-badge">Shot {{ String(idx + 1).padStart(2, '0') }}</span>
                          <strong class="shot-title">{{ shot.title || `分镜 ${idx + 1}` }}</strong>
                        </div>
                        <div class="shot-meta-badges">
                          <span v-if="shot.duration_s" class="shot-duration-badge">⏱ {{ shot.duration_s }}s</span>
                          <span v-if="shot.scene_id" class="shot-scene-badge" :title="'场景: ' + shot.scene_id">
                            📍 {{ getSceneName(shot.scene_id) }}
                          </span>
                          <span v-if="shot.id" class="card-id-tag">{{ shot.id }}</span>
                        </div>
                      </div>

                      <!-- References Pills -->
                      <div v-if="Array.isArray(shot.references) && shot.references.length" class="shot-references-row">
                        <span class="ref-label">关联资产:</span>
                        <div class="ref-pills">
                          <span
                            v-for="refItem in shot.references"
                            :key="refItem"
                            class="ref-pill"
                            :class="getReferenceName(refItem).type"
                          >
                            {{ getReferenceName(refItem).icon }} {{ getReferenceName(refItem).name }}
                          </span>
                        </div>
                      </div>

                      <!-- Visual Content -->
                      <div v-if="shot.visual" class="shot-field-box">
                        <span class="field-tag visual-tag">🎬 画面描述</span>
                        <p class="field-text">{{ shot.visual }}</p>
                      </div>

                      <!-- Camera Movement -->
                      <div v-if="shot.camera" class="shot-field-box">
                        <span class="field-tag camera-tag">🎥 运镜指导</span>
                        <p class="field-text">{{ shot.camera }}</p>
                      </div>

                      <!-- Dialogue -->
                      <div v-if="Array.isArray(shot.dialogue) && shot.dialogue.length" class="shot-field-box">
                        <span class="field-tag dialogue-tag">💬 角色对白</span>
                        <ul class="dialogue-list">
                          <li v-for="(line, lineIdx) in shot.dialogue" :key="lineIdx">
                            {{ line }}
                          </li>
                        </ul>
                      </div>

                      <!-- Video Prompt -->
                      <div v-if="shot.video_prompt" class="shot-field-box prompt-box">
                        <div class="prompt-header">
                          <span class="field-tag prompt-tag">✨ 生图/生视频提示词</span>
                          <button
                            type="button"
                            class="copy-pill-btn"
                            @click="copyToClipboard(shot.video_prompt, shot.id || String(idx))"
                          >
                            {{ copySuccessId === (shot.id || String(idx)) ? '✓ 已复制提示词' : '复制提示词' }}
                          </button>
                        </div>
                        <p class="prompt-text">{{ shot.video_prompt }}</p>
                      </div>
                    </div>
                  </div>
                </section>
              </div>
            </div>

            <!-- Empty State when no data -->
            <div v-else class="creation-unextracted-box">
              <div class="unextracted-icon">⚡</div>
              <strong>当前尚未从剧本中提取资产与分镜</strong>
              <p>点击下方按钮，AI 会自动分析已生成的剧本，将角色、场景、道具、音效及分镜提示词按稳定 ID 提炼出来。</p>
            </div>

            <div class="stage-actions">
              <button type="button" class="secondary-button" @click="setStage('script')">回到剧本</button>
              <button type="button" class="primary-button" :disabled="extracting || !hasScript" @click="extractCreationData">
                {{ extracting ? '提取中…' : hasCreationData ? '重新提取资产与分镜' : '⚡ 提取资产与分镜' }}
              </button>
              <button type="button" class="link-button" :disabled="!hasCreationData" @click="pushToVideo">
                推送到视频制作 →
              </button>
            </div>
          </template>

          <template v-else>
            <header class="main-heading">
              <div>
                <span class="setup-number">04</span>
                <div>
                  <h2>推送到视频制作</h2>
                  <p>资产、分镜、风格和比例会一起带入生图 / 生视频工作区，不再手动搬 JSON。</p>
                </div>
              </div>
              <span class="ready-badge is-ready">已准备</span>
            </header>
            <div class="video-ready">
              <div class="video-ready-icon">✓</div>
              <strong>{{ creationCounts.assets }} 项资产和 {{ creationCounts.shots }} 个分镜已准备好</strong>
              <p>点击“进入视频制作”，系统会保存当前章节并打开对应项目。之后你只需要选择图片模型、视频模型并生成。</p>
            </div>
            <div class="stage-actions">
              <button type="button" class="secondary-button" @click="setStage('assets')">检查资产</button>
              <button type="button" class="primary-button" @click="pushToVideo">进入视频制作</button>
            </div>
          </template>

          <p v-if="error" class="project-agent-error">{{ error }}</p>
          <p v-if="saveMessage" class="project-agent-success">{{ saveMessage }}</p>
        </main>

        <aside class="project-agent-draft panel">
          <header>
            <div class="draft-header-main">
              <span class="project-agent-kicker">{{ isPrologueTitle(chapterDraft.title) ? '当前序幕' : '当前集数' }}</span>
              <div class="draft-title-row">
                <h2>{{ chapterDraft.title || '第1集' }}</h2>
                <button
                  v-if="chapters.length > 1 || isPrologueTitle(chapterDraft.title)"
                  type="button"
                  class="delete-chapter-btn"
                  title="删除当前集数"
                  @click="removeCurrentChapter(currentChapter)"
                >
                  🗑️ 删除
                </button>
              </div>
            </div>
            <span :class="{ ready: hasScript }" class="draft-status">{{ hasScript ? '剧本已生成' : '等待生成' }}</span>
          </header>
          <div class="draft-tabs">
            <button type="button" :class="{ active: activeTab === 'project' }" @click="activeTab = 'project'">项目资料</button>
            <button type="button" :class="{ active: activeTab === 'script' }" @click="activeTab = 'script'">{{ isPrologueTitle(chapterDraft.title) ? '旁白剧本' : '本集剧本' }}</button>
            <button type="button" :class="{ active: activeTab === 'assets' }" @click="activeTab = 'assets'">创作数据</button>
          </div>

          <div v-if="activeTab === 'project'" class="draft-form">
            <label class="field-item">
              <span>项目名称</span>
              <input v-model="projectDraft.name" placeholder="例如：丹神觉醒" />
            </label>
            <label class="field-item">
              <span>项目简介</span>
              <textarea v-model="projectDraft.description" placeholder="一句话说明题材、主角和核心冲突"></textarea>
            </label>
            <label class="field-item">
              <span>章节名称</span>
              <input v-model="chapterDraft.title" placeholder="第1集" />
            </label>

            <fieldset class="style-fieldset">
              <legend>风格选择</legend>
              <div v-for="group in projectStyleGroups" :key="group.label" class="style-group-box">
                <span class="style-group-label">{{ group.label }}</span>
                <div class="style-pill-grid">
                  <label
                    v-for="option in group.options"
                    :key="option.value"
                    class="style-pill"
                    :class="{ active: projectDraft.style === option.value }"
                  >
                    <input v-model="projectDraft.style" type="radio" :value="option.value" />
                    <span>{{ option.label }}</span>
                  </label>
                </div>
              </div>
              <p class="style-desc-preview">{{ projectStyleDescription }}</p>
            </fieldset>

            <fieldset class="ratio-fieldset">
              <legend>视频比例</legend>
              <div class="ratio-pill-grid">
                <label
                  v-for="option in projectRatioOptions"
                  :key="option.value"
                  class="ratio-pill"
                  :class="{ active: projectDraft.ratio === option.value }"
                >
                  <input v-model="projectDraft.ratio" type="radio" :value="option.value" />
                  <span>{{ option.label }}</span>
                </label>
              </div>
            </fieldset>

            <button type="button" class="save-button" :disabled="saving" @click="saveChapter()">
              {{ saving ? '保存中…' : '保存项目与剧本' }}
            </button>
          </div>

          <div v-else-if="activeTab === 'script'" class="draft-form">
            <label class="field-item">
              <span>原文 / 摘要</span>
              <textarea v-model="chapterDraft.sourceText" placeholder="可选：保留原文或摘要，方便后续追溯"></textarea>
            </label>
            <label class="field-item">
              <span>可拍摄剧本</span>
              <textarea v-model="chapterDraft.script" class="script-editor" placeholder="Agent 生成的完整剧本会出现在这里，也可以手动修改"></textarea>
            </label>
            <div class="script-action-row">
              <button type="button" class="secondary-button" :disabled="saving" @click="saveChapter()">
                {{ saving ? '保存中…' : '保存剧本' }}
              </button>
              <button type="button" class="primary-button" :disabled="extracting || !hasScript" @click="extractCreationData">
                {{ extracting ? '提取中…' : '⚡ 提取资产与分镜' }}
              </button>
            </div>
          </div>

          <div v-else class="draft-form">
            <div class="mini-stats">
              <span><b>{{ creationCounts.assets }}</b>资产</span>
              <span><b>{{ creationCounts.shots }}</b>分镜</span>
            </div>

            <div class="creation-explanation-card">
              <strong>💡 什么是创作数据？</strong>
              <p>创作数据是 AI 从剧本中提炼出的<b>固定人物、场景、服装道具</b>及<b>首尾连续的分镜提示词</b>，用于直接驱动生图和生视频模型，确保人物不换脸、场景不乱变。</p>
            </div>

            <div v-if="!hasCreationData" class="creation-empty-card">
              <p>当前剧本尚未提取资产与分镜数据。</p>
              <button type="button" class="primary-button" :disabled="extracting || !hasScript" @click="extractCreationData">
                {{ extracting ? '正在提取…' : '⚡ 立即从剧本提取' }}
              </button>
            </div>
            <div v-else class="creation-ready-card">
              <!-- Quick overview summary in drawer -->
              <div v-if="extractedCharacters.length" class="drawer-asset-summary">
                <span class="drawer-summary-title">👤 人物 ({{ extractedCharacters.length }}):</span>
                <div class="drawer-tags">
                  <span v-for="c in extractedCharacters" :key="c.id" class="drawer-tag">{{ c.name || c.id }}</span>
                </div>
              </div>
              <div v-if="extractedScenes.length" class="drawer-asset-summary">
                <span class="drawer-summary-title">🏞️ 场景 ({{ extractedScenes.length }}):</span>
                <div class="drawer-tags">
                  <span v-for="s in extractedScenes" :key="s.id" class="drawer-tag">{{ s.name || s.id }}</span>
                </div>
              </div>
              <div v-if="extractedShots.length" class="drawer-asset-summary">
                <span class="drawer-summary-title">🎬 分镜 ({{ extractedShots.length }} 镜):</span>
                <div class="drawer-tags">
                  <span v-for="(shot, sIdx) in extractedShots" :key="shot.id || sIdx" class="drawer-tag">{{ shot.title || `镜${sIdx+1}` }}</span>
                </div>
              </div>
              <p class="draft-hint">资产与分镜数据已就绪，可直接推送到视频任务进行生图与成片制作。</p>
              <button type="button" class="primary-button" @click="pushToVideo">
                推送到视频制作 →
              </button>
              <button type="button" class="secondary-button" :disabled="extracting || !hasScript" @click="extractCreationData">
                {{ extracting ? '重新提取中…' : '重新从剧本提取' }}
              </button>
            </div>
          </div>
        </aside>
      </section>
    </template>
  </section>
</template>

<style scoped>
.project-agent-workspace {
  box-sizing: border-box;
  height: 100%;
  min-height: 0;
  padding: 28px 36px 48px;
  color: #ddd;
  background: #101010;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.panel {
  border: 1px solid #2b2b2b;
  border-radius: 14px;
  background: #191919;
  box-shadow: 0 14px 35px #0002;
}
.project-agent-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  max-width: 1500px;
  width: 100%;
  margin: 0 auto 16px;
  flex: 0 0 auto;
}
.project-agent-hero h1 {
  margin: 4px 0 6px;
  font-size: 24px;
  color: #f4f4f4;
}
.project-agent-hero p {
  margin: 0;
  color: #8d8d8d;
  font-size: 12px;
  line-height: 1.6;
}
.eyebrow, .project-agent-kicker {
  color: #8be6ee !important;
  font-size: 10px !important;
  letter-spacing: .12em;
  text-transform: uppercase;
}
.project-agent-flow {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid #303030;
  border-radius: 10px;
  background: #151515;
  white-space: nowrap;
}
.project-agent-flow button {
  padding: 7px 12px;
  border: 0;
  border-radius: 7px;
  color: #777;
  background: transparent;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  transition: all .15s ease;
}
.project-agent-flow button.active {
  color: #111;
  background: #a8ecef;
  font-weight: 600;
}
.project-agent-flow button.done {
  color: #9dd8bb;
}

/* Setup Stage */
.project-agent-setup {
  max-width: 920px;
  width: 100%;
  margin: 0 auto;
  padding: 26px;
  overflow-y: auto;
  flex: 1 1 auto;
}
.setup-heading, .main-heading > div {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.setup-heading h2, .main-heading h2 {
  margin: 0 0 4px;
  color: #f1f1f1;
  font-size: 16px;
}
.setup-heading p, .main-heading p {
  margin: 0;
  color: #888;
  font-size: 11px;
  line-height: 1.5;
}
.setup-number {
  display: grid;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 8px;
  color: #132024;
  background: #a8ecef;
  font-size: 11px;
  font-weight: 800;
}
.setup-grid {
  display: grid;
  grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr);
  align-items: start;
  gap: 16px;
  margin: 20px 0 16px;
}
.setup-field, .field-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  color: #999;
  font-size: 11px;
}
.setup-field input, .setup-field textarea,
.field-item input, .field-item textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 9px 11px;
  border: 1px solid #343434;
  border-radius: 8px;
  outline: 0;
  color: #ddd;
  background: #141414;
  font: 12px/1.5 inherit;
  transition: border-color .15s ease;
}
.setup-field input:focus, .setup-field textarea:focus,
.field-item input:focus, .field-item textarea:focus {
  border-color: #5ea8ac;
}
.setup-field input {
  height: 40px;
}
.setup-field textarea {
  height: 90px;
  min-height: 90px;
  resize: vertical;
}

/* Style and Ratio Group Elements */
.style-fieldset, .ratio-fieldset {
  margin: 0 0 14px;
  padding: 12px 14px;
  border: 1px solid #303030;
  border-radius: 9px;
  background: #161616;
}
.style-fieldset legend, .ratio-fieldset legend {
  padding: 0 6px;
  color: #a8ecef;
  font-size: 11px;
  font-weight: 600;
}
.style-group-box {
  display: grid;
  grid-template-columns: 65px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.style-group-box:last-of-type {
  margin-bottom: 0;
}
.style-group-label {
  color: #888;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.style-pill-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}
.style-pill, .ratio-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border: 1px solid #303030;
  border-radius: 6px;
  background: #1d1d1d;
  color: #bbb;
  font-size: 11px;
  cursor: pointer;
  user-select: none;
  transition: all .15s ease;
  white-space: nowrap;
}
.style-pill:hover, .ratio-pill:hover {
  border-color: #4a4a4a;
  background: #252525;
  color: #eee;
}
.style-pill.active, .ratio-pill.active {
  border-color: #5ea8ac;
  background: #152d30;
  color: #a8ecef;
  font-weight: 600;
}
.style-pill input, .ratio-pill input {
  appearance: none;
  -webkit-appearance: none;
  width: 12px;
  height: 12px;
  margin: 0;
  border: 1.5px solid #666;
  border-radius: 50%;
  outline: none;
  cursor: pointer;
  display: grid;
  place-content: center;
  transition: all .15s ease;
  background: transparent;
  flex-shrink: 0;
}
.style-pill input::before, .ratio-pill input::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  transform: scale(0);
  transition: 120ms transform ease-in-out;
  background-color: #a8ecef;
}
.style-pill input:checked, .ratio-pill input:checked {
  border-color: #8be6ee;
}
.style-pill input:checked::before, .ratio-pill input:checked::before {
  transform: scale(1);
}
.style-desc-preview {
  margin: 10px 0 0;
  padding: 8px 10px;
  border-radius: 6px;
  background: #111a1b;
  border: 1px dashed #244649;
  color: #8bbdc0;
  font-size: 11px;
  line-height: 1.55;
}
.ratio-pill-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* History */
.setup-history {
  margin: 18px 0;
  padding: 14px;
  border: 1px solid #303030;
  border-radius: 10px;
  background: #151515;
}
.setup-history > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.setup-history h3 {
  margin: 0;
  color: #eee;
  font-size: 13px;
}
.setup-history p {
  margin: 3px 0 0;
  color: #777;
  font-size: 10px;
  line-height: 1.5;
}
.setup-history-list {
  display: grid;
  max-height: 200px;
  gap: 6px;
  overflow-y: auto;
  padding-right: 3px;
}
.setup-history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 9px 11px;
  border: 1px solid #2d2d2d;
  border-radius: 8px;
  color: #ccc;
  background: #1b1b1b;
  text-align: left;
  cursor: pointer;
  transition: all .15s ease;
}
.setup-history-item:hover {
  border-color: #4c777a;
  background: #202b2c;
}
.setup-history-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.setup-history-copy strong {
  overflow: hidden;
  color: #eee;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.setup-history-copy small {
  overflow: hidden;
  color: #777;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.setup-history-meta {
  display: grid;
  flex: 0 0 auto;
  justify-items: end;
  gap: 2px;
}
.setup-history-meta small {
  color: #777;
  font-size: 9px;
}
.setup-history-meta b {
  color: #a8ecef;
  font-size: 10px;
}
.setup-history-empty {
  padding: 12px 8px;
  color: #777;
  background: #191919;
  font-size: 10px;
  line-height: 1.6;
  text-align: center;
  border-radius: 6px;
}

/* Actions */
.setup-actions, .stage-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
.primary-button, .secondary-button, .link-button, .save-button {
  padding: 8px 14px;
  border-radius: 8px;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  transition: all .15s ease;
  white-space: nowrap;
}
.primary-button {
  border: 1px solid #8be6ee;
  color: #102022;
  background: #a8ecef;
  font-weight: 600;
}
.primary-button:hover:not(:disabled) {
  background: #c3f4f6;
}
.secondary-button {
  border: 1px solid #444;
  color: #ddd;
  background: #272727;
}
.secondary-button:hover:not(:disabled) {
  background: #333;
}
.link-button {
  border: 1px solid #3c6668;
  color: #a8ecef;
  background: #163337;
}
.save-button {
  border: 1px solid #8be6ee;
  color: #a8ecef;
  background: #163337;
  width: 100%;
}
.save-button:hover:not(:disabled) {
  background: #1e454a;
}
.primary-button:disabled, .secondary-button:disabled, .link-button:disabled, .save-button:disabled {
  cursor: not-allowed;
  opacity: .45;
}

/* Top Project Bar */
.project-agent-projectbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1500px;
  width: 100%;
  margin: 0 auto 14px;
  padding: 10px 16px;
  border-radius: 12px;
  background: #191919;
  border: 1px solid #2b2b2b;
  flex: 0 0 auto;
}
.project-agent-project-copy {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}
.project-agent-kicker {
  flex-shrink: 0;
  padding: 3px 7px;
  border-radius: 6px;
  background: #142e31;
  border: 1px solid #265559;
  color: #8be6ee !important;
  font-size: 10px !important;
  font-weight: 700;
}
.project-agent-info-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.project-agent-info-text strong {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #eee;
  font-size: 13px;
  font-weight: 600;
}
.project-agent-info-text small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #888;
  font-size: 11px;
}
.project-agent-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.project-agent-meta span {
  display: inline-block;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #999;
  font-size: 11px;
}
.project-agent-meta b {
  padding: 3px 7px;
  border-radius: 5px;
  color: #a8ecef;
  background: #163337;
  font-size: 10px;
}

/* Compact Episode Navigation Capsule Bar */
.project-episode-bar {
  max-width: 1500px;
  width: 100%;
  margin: 0 auto 12px;
  padding: 6px 14px;
  border-radius: 10px;
  background: #181818;
  border: 1px solid #282828;
  flex: 0 0 auto;
  box-sizing: border-box;
}
.episode-bar-inner {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-width: 0;
  position: relative;
}
.episode-grid-wrapper {
  position: relative;
  flex-shrink: 0;
}
.episode-quick-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 7px;
  border: 1px solid #333;
  background: #202020;
  color: #ccc;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all .15s ease;
}
.episode-quick-btn .grid-icon {
  font-size: 13px;
  color: #8be6ee;
}
.episode-quick-btn .progress-pill {
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 10px;
  background: #153034;
  color: #8be6ee;
  border: 1px solid #234b50;
}
.episode-quick-btn:hover, .episode-quick-btn.active {
  border-color: #5ea8ac;
  color: #fff;
  background: #262626;
}

/* Popover Grid */
.episode-grid-popover {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  z-index: 100;
  width: 350px;
  padding: 12px;
  border-radius: 10px;
  background: #1b1b1b;
  border: 1px solid #363636;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.7);
}
.grid-popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #282828;
  font-size: 11px;
  color: #eee;
}
.grid-filter-pills {
  display: flex;
  gap: 4px;
}
.grid-filter-pills button {
  padding: 2px 7px;
  font-size: 10px;
  border: 1px solid #333;
  border-radius: 4px;
  background: #222;
  color: #888;
  cursor: pointer;
  transition: all .15s ease;
}
.grid-filter-pills button.active {
  background: #183e42;
  color: #8be6ee;
  border-color: #3b7479;
  font-weight: 600;
}
.grid-items-scroll {
  max-height: 220px;
  overflow-y: auto;
  padding-right: 4px;
}
.grid-items {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
}
.grid-item-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  padding: 6px 4px;
  border: 1px solid #2f2f2f;
  border-radius: 6px;
  background: #151515;
  color: #bbb;
  font-size: 10px;
  cursor: pointer;
  transition: all .15s ease;
  position: relative;
  min-height: 38px;
}
.grid-item-btn:hover {
  background: #242424;
  border-color: #444;
  color: #fff;
}
.grid-item-btn.active {
  border-color: #8be6ee;
  background: #153034;
  color: #8be6ee;
  font-weight: 600;
}
.grid-item-btn.prologue {
  border-color: #d19a42;
  color: #f7ca78;
}
.grid-item-btn.prologue.active {
  background: #392812;
  border-color: #f7ca78;
  color: #ffe6a3;
}
.grid-item-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.grid-item-btn .status-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #444;
}
.grid-item-btn.done .status-dot {
  background: #4ade80;
  box-shadow: 0 0 4px #4ade80;
}
.grid-item-btn.assets .status-dot {
  background: #c084fc;
  box-shadow: 0 0 4px #c084fc;
}
.grid-popover-footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #282828;
  font-size: 10px;
  color: #888;
}
.grid-popover-footer .legend {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.grid-popover-footer .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.grid-popover-footer .dot.done {
  background: #4ade80;
}
.grid-popover-footer .dot.assets {
  background: #c084fc;
}
.grid-popover-footer .dot.draft {
  background: #555;
}

.episode-divider {
  width: 1px;
  height: 20px;
  background: #2d2d2d;
  margin: 0 4px;
  flex-shrink: 0;
}

/* Horizontal Capsule Strip */
.episode-scroll-wrapper {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  scroll-behavior: smooth;
  flex: 1;
  min-width: 0;
  padding: 2px 0;
  -ms-overflow-style: none;
  scrollbar-width: none;
}
.episode-scroll-wrapper::-webkit-scrollbar {
  display: none;
}
.add-prologue-wrapper {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}
.add-prologue-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px 4px 10px;
  border-radius: 20px 0 0 20px;
  border: 1px dashed #d19a42;
  border-right: none;
  background: rgba(209, 154, 66, 0.08);
  color: #f7ca78;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  transition: all .15s ease;
}
.add-prologue-pill:hover:not(:disabled) {
  background: rgba(209, 154, 66, 0.22);
  border-color: #ffd27d;
  color: #fff;
}
.prologue-dismiss-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 6px;
  border-radius: 0 20px 20px 0;
  border: 1px dashed #d19a42;
  border-left: none;
  background: rgba(209, 154, 66, 0.08);
  color: rgba(247, 202, 120, 0.65);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  transition: all .15s ease;
}
.prologue-dismiss-btn:hover {
  background: rgba(209, 154, 66, 0.28);
  color: #fff;
}
.prologue-remove-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  margin-left: 2px;
  font-size: 11px;
  line-height: 1;
  color: #ff7875;
  cursor: pointer;
  transition: all .15s ease;
}
.prologue-remove-icon:hover {
  background: rgba(255, 77, 79, 0.25);
  color: #fff;
}
.episode-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  border: 1px solid #303030;
  background: #161616;
  color: #aaa;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: all .15s ease;
  user-select: none;
}
.episode-pill:hover {
  border-color: #4a4a4a;
  color: #ddd;
  background: #202020;
}
.episode-pill.active {
  border-color: #5ea8ac;
  background: #152d30;
  color: #a8ecef;
  font-weight: 600;
  box-shadow: 0 0 10px rgba(94, 168, 172, 0.2);
}
.episode-pill.prologue {
  border-color: #8c6422;
  color: #e2b057;
}
.episode-pill.prologue.active {
  border-color: #f7ca78;
  background: #352613;
  color: #ffe5a0;
  font-weight: 600;
  box-shadow: 0 0 10px rgba(247, 202, 120, 0.2);
}
.episode-pill .pill-icon {
  font-size: 12px;
}
.episode-pill .status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #444;
  flex-shrink: 0;
}
.episode-pill .status-dot.done {
  background: #4ade80;
  box-shadow: 0 0 5px #4ade80;
}
.episode-pill .status-dot.assets {
  background: #c084fc;
  box-shadow: 0 0 5px #c084fc;
}

/* Episode Add Controls */
.episode-add-wrapper {
  display: inline-flex;
  align-items: center;
  position: relative;
  flex-shrink: 0;
  margin-left: 4px;
}
.episode-action-btn {
  padding: 4px 10px;
  border: 1px solid #3c6668;
  background: #163337;
  color: #a8ecef;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s ease;
}
.episode-action-btn.add-btn {
  border-radius: 7px 0 0 7px;
}
.episode-action-btn.menu-toggle-btn {
  border-radius: 0 7px 7px 0;
  border-left: 0;
  padding: 4px 7px;
}
.episode-action-btn:hover:not(:disabled) {
  background: #1e464c;
  color: #fff;
}
.episode-menu-dropdown {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 100;
  min-width: 170px;
  padding: 6px;
  border-radius: 8px;
  background: #1c1c1c;
  border: 1px solid #383838;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.episode-menu-dropdown button {
  display: flex;
  align-items: center;
  width: 100%;
  padding: 7px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #ccc;
  font-size: 11px;
  text-align: left;
  cursor: pointer;
  transition: all .15s ease;
}
.episode-menu-dropdown button:hover {
  background: #282828;
  color: #8be6ee;
}

.current-chapter-tag {
  color: #8be6ee;
  font-size: 13px;
  font-weight: 500;
  margin-left: 6px;
}

.draft-header-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.draft-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 2px;
}
.draft-title-row h2 {
  margin: 0;
}
.delete-chapter-btn {
  border: 1px solid #482329;
  border-radius: 6px;
  background: #261216;
  color: #ff8da3;
  font-size: 10px;
  padding: 2px 7px;
  cursor: pointer;
  transition: all .15s ease;
  flex-shrink: 0;
}
.delete-chapter-btn:hover {
  background: #3d1b22;
  border-color: #6b2e38;
  color: #ffa6b8;
}

/* 3-Column Layout */
.project-agent-layout {
  display: grid;
  grid-template-columns: 210px minmax(440px, 1fr) 310px;
  gap: 14px;
  max-width: 1500px;
  width: 100%;
  margin: 0 auto;
  min-width: 0;
  flex: 1 1 auto;
  min-height: 0;
  align-items: stretch;
}
.project-agent-layout > * {
  min-width: 0;
  min-height: 0;
  height: 100%;
}

/* Left Sidebar */
.project-agent-sidebar {
  box-sizing: border-box;
  padding: 14px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.sidebar-section {
  display: grid;
  gap: 7px;
}
.sidebar-section + .sidebar-section {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid #2b2b2b;
}
.sidebar-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #aaa;
  font-size: 11px;
}
.sidebar-title small {
  color: #666;
}
.sidebar-title button {
  border: 0;
  color: #8be6ee;
  background: transparent;
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}
.sidebar-section > button:not(.conversation-item) {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  color: #aaa;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: all .15s ease;
}
.sidebar-section > button.active {
  border-color: #315d60;
  color: #eee;
  background: #163337;
}
.sidebar-section > button.disabled {
  opacity: .45;
}
.sidebar-section > button b {
  color: #8be6ee;
  font-size: 10px;
}
.sidebar-section > button span {
  display: grid;
  gap: 2px;
  font-size: 11px;
}
.sidebar-section > button small {
  color: #777;
  font-size: 9px;
}
.conversation-section {
  flex: 1 1 auto;
  min-height: 140px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
}
.conversation-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  box-sizing: border-box;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid #2b2b2b;
  border-radius: 8px;
  color: #aaa;
  background: #181818;
  text-align: left;
  cursor: pointer;
  transition: all .15s ease;
}
.conversation-item:hover {
  border-color: #3a585a;
  background: #1c2425;
}
.conversation-item.active {
  border-color: #457b7f;
  color: #eee;
  background: #162b2d;
}
.conversation-title-text {
  display: block;
  min-width: 0;
  width: 100%;
  overflow-wrap: anywhere;
  word-break: break-all;
  color: #ddd;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.4;
  white-space: normal;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.conversation-item.active .conversation-title-text {
  color: #a8ecef;
}
.conversation-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  padding-top: 3px;
  border-top: 1px solid #242424;
}
.conversation-meta-row small {
  color: #666;
  font-size: 9px;
}
.conversation-meta-row i {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 3px;
  color: #777;
  font-style: normal;
  font-size: 13px;
  line-height: 1;
}
.conversation-meta-row i:hover {
  color: #ff8da3;
  background: #35161e;
}
.sidebar-empty {
  color: #666;
  font-size: 10px;
  line-height: 1.6;
}

/* Center Main Area */
.project-agent-main {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.main-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  border-bottom: 1px solid #2b2b2b;
  flex: 0 0 auto;
}
.main-heading > div {
  flex: 1;
}
.main-heading :deep(.ui-select) {
  min-width: 160px;
}
.project-agent-messages {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
  overflow-y: auto;
}
.agent-welcome {
  display: grid;
  align-content: center;
  min-height: 280px;
  place-items: center;
  text-align: center;
}
.agent-welcome strong {
  color: #eee;
  font-size: 15px;
}
.agent-welcome p {
  max-width: 400px;
  color: #777;
  font-size: 11px;
  line-height: 1.6;
  margin: 6px 0 14px;
}
.suggestion-list {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px;
}
.suggestion-list button {
  padding: 6px 10px;
  border: 1px solid #354e50;
  border-radius: 999px;
  color: #9edfe3;
  background: #142d2f;
  font: inherit;
  font-size: 10px;
  cursor: pointer;
  transition: all .15s ease;
}
.suggestion-list button:hover {
  background: #1b3d40;
  border-color: #5aa1a6;
}
.project-agent-message {
  display: grid;
  gap: 4px;
  max-width: 88%;
  font-size: 10px;
}
.project-agent-message.user {
  align-self: flex-end;
  text-align: right;
}
.project-agent-message > span {
  color: #777;
}
.bubble {
  padding: 10px 13px;
  border: 1px solid #303030;
  border-radius: 10px;
  color: #d2d2d2;
  background: #222;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
  line-height: 1.65;
  text-align: left;
}
.project-agent-message.user .bubble {
  border-color: #3d4149;
  background: #2a2d34;
}
.error-bubble, .project-agent-error {
  color: #ff8da3;
}
.agent-typing {
  color: #8be6ee;
  font-size: 11px;
}
.project-agent-composer {
  padding: 12px 16px;
  border-top: 1px solid #2b2b2b;
  flex: 0 0 auto;
}
.project-agent-composer textarea {
  display: block;
  width: 100%;
  min-height: 80px;
  max-height: 150px;
  box-sizing: border-box;
  resize: vertical;
  padding: 10px;
  border: 1px solid #343434;
  border-radius: 8px;
  outline: 0;
  color: #ddd;
  background: #141414;
  font: 12px/1.5 inherit;
}
.composer-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}
.composer-foot small {
  margin-right: auto;
  color: #666;
  font-size: 10px;
}
.ready-badge, .draft-status {
  padding: 3px 8px;
  border-radius: 999px;
  color: #e6bb75;
  background: #3b2c19;
  font-size: 10px;
}
.ready-badge.is-ready, .draft-status.ready {
  color: #9de4c0;
  background: #163b2c;
}

/* Right Draft Sidebar */
.project-agent-draft {
  display: flex;
  flex-direction: column;
  padding: 14px;
  overflow: hidden;
}
.project-agent-draft > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  flex: 0 0 auto;
}
.project-agent-draft h2 {
  margin: 3px 0 0;
  color: #eee;
  font-size: 14px;
}
.draft-tabs {
  display: flex;
  gap: 3px;
  margin-bottom: 12px;
  padding: 3px;
  border: 1px solid #303030;
  border-radius: 8px;
  background: #151515;
  flex: 0 0 auto;
}
.draft-tabs button {
  flex: 1;
  padding: 6px 3px;
  border: 0;
  border-radius: 6px;
  color: #777;
  background: transparent;
  font: inherit;
  font-size: 10px;
  cursor: pointer;
  transition: all .15s ease;
}
.draft-tabs button.active {
  color: #eee;
  background: #303030;
  font-weight: 600;
}
.draft-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  flex: 1 1 auto;
  overflow-y: auto;
}
.draft-form textarea {
  min-height: 80px;
  resize: vertical;
}
.draft-form .script-editor {
  min-height: 240px;
  flex: 1;
}
.draft-form .style-fieldset, .draft-form .ratio-fieldset {
  margin: 0;
  padding: 10px;
}
.draft-form .style-group-box {
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 6px;
  margin-bottom: 6px;
}
.draft-form .style-pill, .draft-form .ratio-pill {
  padding: 4px 7px;
  font-size: 10.5px;
}
.draft-form .style-pill-grid, .draft-form .ratio-pill-grid {
  gap: 4px;
}
.mini-stats, .asset-summary {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.mini-stats span, .asset-summary > div {
  display: grid;
  gap: 3px;
  padding: 10px;
  border: 1px solid #303030;
  border-radius: 8px;
  color: #888;
  background: #151515;
  text-align: center;
  font-size: 10px;
}
.mini-stats b, .asset-summary b {
  color: #a8ecef;
  font-size: 20px;
}
.creation-explanation-card {
  padding: 10px 12px;
  border: 1px solid #2d4547;
  border-radius: 8px;
  background: #132426;
  color: #9cd5d8;
  font-size: 11px;
  line-height: 1.55;
}
.creation-explanation-card strong {
  display: block;
  margin-bottom: 4px;
  color: #a8ecef;
  font-size: 11.5px;
}
.creation-explanation-card p {
  margin: 0;
  color: #8ebfc2;
}
.creation-empty-card, .creation-ready-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px dashed #343434;
  border-radius: 8px;
  background: #161616;
  text-align: center;
}
.creation-empty-card p {
  margin: 0;
  color: #888;
  font-size: 11px;
}
.script-action-row {
  display: flex;
  gap: 8px;
}
.script-action-row button {
  flex: 1;
}
.draft-hint, .consistency-note p {
  margin: 0;
  color: #777;
  font-size: 11px;
  line-height: 1.6;
}
.asset-summary {
  padding: 16px 18px 10px;
}
.consistency-note {
  margin: 0 18px;
  padding: 10px 12px;
  border: 1px solid #305457;
  border-radius: 8px;
  background: #142c2e;
}
.consistency-note strong {
  color: #a8ecef;
  font-size: 11px;
}

/* Asset Filter Navigation Bar */
.asset-nav-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 12px 18px 0;
  padding: 4px;
  border: 1px solid #2b2b2b;
  border-radius: 8px;
  background: #141414;
  overflow-x: auto;
  white-space: nowrap;
  flex-shrink: 0;
}
.asset-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 11px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #888;
  background: transparent;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  transition: all .15s ease;
}
.asset-nav-btn:hover {
  color: #ddd;
  background: #202020;
}
.asset-nav-btn.active {
  border-color: #315d60;
  color: #a8ecef;
  background: #163337;
  font-weight: 600;
}
.asset-nav-btn small {
  font-size: 10px;
  opacity: .75;
}
.asset-nav-raw {
  margin-left: auto;
  font-family: Consolas, monospace;
}

/* Structured Assets Content Area */
.structured-assets-view {
  flex: 1 1 auto;
  min-height: 0;
  margin: 10px 18px 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding-right: 4px;
}
.structured-cards-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 12px;
}

/* Visual Style Banner */
.asset-style-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #112022;
  border: 1px solid #1f4246;
  flex-wrap: wrap;
}
.style-banner-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.style-banner-badge {
  padding: 2px 7px;
  border-radius: 4px;
  background: #183d40;
  color: #8be6ee;
  font-size: 10px;
  font-weight: 700;
}
.asset-style-banner strong {
  color: #a8ecef;
  font-size: 12px;
}
.style-banner-desc {
  color: #79a8ab;
  font-size: 10.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 550px;
}

/* Asset Card Section */
.asset-card-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #282828;
}
.section-title .icon {
  font-size: 14px;
}
.section-title h3 {
  margin: 0;
  color: #eee;
  font-size: 13px;
  font-weight: 600;
}
.section-title small {
  color: #666;
  font-size: 10.5px;
}
.asset-cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
}
.asset-card {
  padding: 10px 12px;
  border: 1px solid #2c2c2c;
  border-radius: 8px;
  background: #181818;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: border-color .15s ease;
}
.asset-card:hover {
  border-color: #3a5254;
  background: #1a1e1f;
}
.character-card {
  border-left: 3px solid #5ea8ac;
}
.scene-card {
  border-left: 3px solid #d49e5d;
}
.prop-card {
  border-left: 3px solid #a67bc5;
}
.audio-card {
  border-left: 3px solid #6cb88a;
}
.voice-card {
  border-left: 3px solid #6cb88a;
}
.sfx-card {
  border-left: 3px solid #b89c6c;
}
.audio-style-pill {
  background: #172d21;
  color: #8beeb3;
}
.audio-prompt-preview {
  padding: 6px 8px;
  border-radius: 6px;
  background: #131313;
  border: 1px solid #242424;
  color: #bbb;
  font-size: 10.5px;
  line-height: 1.5;
}
.audio-prompt-preview strong {
  color: #6cb88a;
  font-weight: 600;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-name-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.card-name {
  color: #eee;
  font-size: 12px;
  font-weight: 600;
}
.card-style-pill {
  padding: 1px 5px;
  border-radius: 4px;
  background: #142a2d;
  color: #8be6ee;
  font-size: 9.5px;
}
.scene-style-pill {
  background: #2b2216;
  color: #e5b078;
}
.card-id-tag {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  background: #232323;
  color: #888;
  font: 9.5px/1.3 Consolas, monospace;
}
.card-desc {
  margin: 0;
  color: #a0a0a0;
  font-size: 11px;
  line-height: 1.55;
}

/* Shots Section */
.shots-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.shot-card {
  padding: 12px 14px;
  border: 1px solid #2d2d2d;
  border-radius: 10px;
  background: #161616;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border-left: 3px solid #8be6ee;
}
.shot-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.shot-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.shot-num-badge {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 5px;
  background: #18373a;
  color: #8be6ee;
  font-size: 10px;
  font-weight: 700;
}
.shot-title {
  color: #f0f0f0;
  font-size: 13px;
  font-weight: 600;
}
.shot-meta-badges {
  display: flex;
  align-items: center;
  gap: 6px;
}
.shot-duration-badge {
  padding: 2px 7px;
  border-radius: 5px;
  background: #252820;
  color: #d1dc79;
  font-size: 10px;
}
.shot-scene-badge {
  padding: 2px 7px;
  border-radius: 5px;
  background: #2b2219;
  color: #e5b078;
  font-size: 10px;
}
.shot-references-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 8px;
  border-radius: 6px;
  background: #1c1c1c;
}
.ref-label {
  color: #777;
  font-size: 10px;
  flex-shrink: 0;
}
.ref-pills {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
}
.ref-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #252525;
  color: #bbb;
  font-size: 10px;
}
.ref-pill.character { background: #18282b; color: #8ee2e8; }
.ref-pill.scene { background: #2b2318; color: #e8bd8e; }
.ref-pill.prop { background: #281a2e; color: #d6a1f0; }
.ref-pill.audio { background: #192a20; color: #9be2b0; }

.shot-field-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #1a1a1a;
  border: 1px solid #252525;
}
.field-tag {
  display: inline-block;
  color: #777;
  font-size: 10px;
  font-weight: 600;
}
.visual-tag { color: #8be6ee; }
.camera-tag { color: #d5b0ff; }
.dialogue-tag { color: #f5c76c; }
.prompt-tag { color: #78e0ad; }

.field-text {
  margin: 0;
  color: #ccc;
  font-size: 11.5px;
  line-height: 1.6;
}
.dialogue-list {
  margin: 0;
  padding-left: 18px;
  color: #ddd;
  font-size: 11px;
  line-height: 1.6;
}
.prompt-box {
  border: 1px solid #204130;
  background: #112019;
}
.prompt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.prompt-text {
  margin: 0;
  color: #a0d8bb;
  font-size: 11px;
  line-height: 1.55;
  font-family: inherit;
}
.copy-pill-btn {
  padding: 2px 8px;
  border: 1px solid #2f5a43;
  border-radius: 4px;
  background: #163324;
  color: #8be6be;
  font: inherit;
  font-size: 10px;
  cursor: pointer;
  transition: all .15s ease;
}
.copy-pill-btn:hover {
  background: #1e4531;
  border-color: #3e7859;
}

/* Raw JSON and Empty State */
.raw-json-container {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 350px;
  gap: 8px;
}
.raw-json-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #888;
  font-size: 11px;
}
.creation-json {
  flex: 1 1 auto;
  min-height: 320px;
  resize: none;
  box-sizing: border-box;
  padding: 12px;
  border: 1px solid #303030;
  border-radius: 8px;
  color: #aebfc0;
  background: #121c1d;
  font: 11px/1.55 Consolas, monospace;
}
.creation-unextracted-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: auto;
  padding: 36px 20px;
  text-align: center;
}
.unextracted-icon {
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  border-radius: 50%;
  background: #163337;
  color: #8be6ee;
  font-size: 20px;
}
.creation-unextracted-box strong {
  color: #ddd;
  font-size: 14px;
}
.creation-unextracted-box p {
  margin: 0;
  max-width: 440px;
  color: #777;
  font-size: 11px;
  line-height: 1.6;
}

/* Drawer Asset Summary */
.drawer-asset-summary {
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
}
.drawer-summary-title {
  color: #888;
  font-size: 10px;
  font-weight: 600;
}
.drawer-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.drawer-tag {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  background: #232323;
  color: #aaa;
  font-size: 9.5px;
}

.stage-actions {
  padding: 0 18px 16px;
}
.video-ready {
  display: grid;
  justify-items: center;
  gap: 10px;
  margin: auto;
  padding: 30px;
  text-align: center;
}
.video-ready-icon {
  display: grid;
  width: 50px;
  height: 50px;
  place-items: center;
  border-radius: 50%;
  color: #102022;
  background: #a8ecef;
  font-size: 26px;
  font-weight: 800;
}
.video-ready strong {
  color: #eee;
  font-size: 15px;
}
.video-ready p {
  max-width: 390px;
  color: #888;
  font-size: 11px;
  line-height: 1.6;
}
.project-agent-error, .project-agent-success {
  margin: 10px 18px 0;
  padding: 8px 10px;
  border-radius: 7px;
  font-size: 11px;
  line-height: 1.5;
}
.project-agent-error {
  color: #ff8da3;
  background: #35161e;
}
.project-agent-success {
  color: #91d6af;
  background: #123326;
}
.project-agent-state {
  display: grid;
  min-height: 500px;
  place-items: center;
}
.project-agent-state :deep(.loading-state) {
  min-height: 500px;
}

@media(max-width: 1250px) {
  .project-agent-layout {
    grid-template-columns: 190px minmax(340px, 1fr) 280px;
  }
}
@media(max-width: 900px) {
  .project-agent-workspace {
    height: auto;
    overflow-y: auto;
  }
  .project-agent-layout {
    display: flex;
    flex-direction: column;
  }
  .project-agent-sidebar, .project-agent-main, .project-agent-draft {
    height: auto;
    min-height: 400px;
  }
}
</style>
