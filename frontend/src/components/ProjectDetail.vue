<script setup>
import { waitForDesktopApi, desktopBackendRequest } from '../utils/desktopApi.js'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import BaseLoadingState from './BaseLoadingState.vue'

const props = defineProps({
  projectId: { type: [String, Number], required: true },
  token: { type: String, required: true },
})
const emit = defineEmits(['back', 'open-agent', 'open-video'])

const project = ref(null)
const chapters = ref([])
const selectedChapterId = ref('')
const loading = ref(true)
const error = ref('')
const chapterError = ref('')
const renamingChapterId = ref('')
const chapterTitleDraft = ref('')
const activeStage = ref('script')
const content = ref('')
const scriptContent = ref('')
const viewMode = ref('text')
const scriptViewMode = ref('text')
const saveStatus = ref('')
let saveTimer = null
let savedTimer = null

const selectedChapter = computed(() => chapters.value.find(item => String(item.id) === String(selectedChapterId.value)) || null)
const characterCount = computed(() => content.value.replace(/\s/g, '').length)
const scriptCharacterCount = computed(() => scriptContent.value.replace(/\s/g, '').length)

const creationData = computed(() => {
  const cd = selectedChapter.value?.workflow?.creationData
  return cd && typeof cd === 'object' ? cd : null
})
const creationShotsCount = computed(() => (Array.isArray(creationData.value?.shots) ? creationData.value.shots.length : 0))
const hasCreationData = computed(() => Boolean(creationData.value && creationShotsCount.value > 0))

const creationSummary = computed(() => {
  if (!creationData.value) return '暂无资产与分镜数据'
  const cd = creationData.value
  const shots = Array.isArray(cd.shots) ? cd.shots.length : 0
  const root = cd.consistency || cd.assets || cd
  const roles = Array.isArray(root.characters || root.roles) ? (root.characters || root.roles).length : 0
  const scenes = Array.isArray(root.scenes) ? root.scenes.length : 0
  const propsCount = Array.isArray(root.props || root.items) ? (root.props || root.items).length : 0
  const audio = Array.isArray(root.audio || root.audios) ? (root.audio || root.audios).length : 0
  return `${shots} 个分镜 · ${roles} 人物 · ${scenes} 场景 · ${propsCount} 道具 · ${audio} 音频`
})

marked.setOptions({ breaks: true, gfm: true })
function createMarkdownDoc(rawText) {
  const source = rawText || ''
  if (!source.trim()) return { html: '', headings: [] }
  try {
    const html = marked.parse(source)
    const template = document.createElement('template')
    template.innerHTML = html
    const headings = Array.from(template.content.querySelectorAll('h1, h2, h3'))
      .map((heading, index) => {
        const id = `client-md-heading-${Math.random().toString(36).slice(2, 7)}-${index + 1}`
        heading.id = id
        return {
          id,
          text: heading.textContent?.trim() || `标题 ${index + 1}`,
          level: Number(heading.tagName.slice(1)),
        }
      })
    return { html: template.innerHTML, headings }
  } catch {
    return { html: '', headings: [] }
  }
}

const markdownDocument = computed(() => createMarkdownDoc(content.value))
const renderedMarkdown = computed(() => markdownDocument.value.html)
const markdownHeadings = computed(() => markdownDocument.value.headings)

const scriptMarkdownDoc = computed(() => createMarkdownDoc(scriptContent.value))
const renderedScriptMarkdown = computed(() => scriptMarkdownDoc.value.html)
const scriptMarkdownHeadings = computed(() => scriptMarkdownDoc.value.headings)

function scrollToMarkdownHeading(headingId) {
  document.getElementById(headingId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function parseChineseNumber(numStr) {
  if (!numStr) return 0
  const trimmed = String(numStr).trim()
  if (/^\d+$/.test(trimmed)) return parseInt(trimmed, 10)
  const cnMap = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '百': 100, '千': 1000, '万': 10000,
  }
  if (trimmed === '十') return 10
  let total = 0
  let r = 0
  for (let i = 0; i < trimmed.length; i++) {
    const char = trimmed[i]
    const val = cnMap[char]
    if (val === undefined) continue
    if (val >= 10) {
      if (r === 0) r = 1
      total += r * val
      r = 0
    } else {
      r = val
    }
  }
  total += r
  return total
}

function isPrologueTitle(title) {
  const t = String(title || '').trim().toLowerCase()
  return /旁白|序幕|序章|前言|楔子|开篇|开局|导言|00|第0集|第00集|prologue|intro/.test(t)
}

function normalizeEpisodeTitle(title) {
  const raw = String(title || '').trim()
  if (!raw) return '第1集'
  if (isPrologueTitle(raw)) {
    if (['开局旁白 / 序幕', '开局旁白', '序幕', '序章', '楔子', '第0集', '第00集', '旁白'].includes(raw)) {
      return '开局旁白 / 序幕'
    }
    return raw
  }
  const match = raw.match(/第\s*([0-9零一二两三四五六七八九十百千万]+)\s*([集章节回话幕])/)
  if (match) {
    const num = parseChineseNumber(match[1])
    const unit = match[2]
    if (num === 0) return '开局旁白 / 序幕'
    const prefix = `第${num}${unit}`
    const suffix = raw.slice(match.index + match[0].length).replace(/^[\s\-:：·—]+/, '').trim()
    return suffix ? `${prefix} ${suffix}` : prefix
  }
  const pureNumMatch = raw.match(/^([0-9]+)$/)
  if (pureNumMatch) {
    const num = parseInt(pureNumMatch[1], 10)
    return num === 0 ? '开局旁白 / 序幕' : `第${num}集`
  }
  return raw
}

function getEpisodeNumber(title) {
  if (isPrologueTitle(title)) return 0
  const match = String(title || '').match(/第\s*([0-9零一二两三四五六七八九十百千万]+)\s*[集章节回话幕]/)
  if (match) return parseChineseNumber(match[1])
  const numMatch = String(title || '').match(/(\d+)/)
  if (numMatch) return parseInt(numMatch[1], 10)
  return 999999
}

function sortChaptersList(list) {
  if (!Array.isArray(list)) return []
  return [...list].sort((a, b) => {
    const isProA = isPrologueTitle(a?.title)
    const isProB = isPrologueTitle(b?.title)
    if (isProA && !isProB) return -1
    if (!isProA && isProB) return 1
    if (isProA && isProB) return 0
    const numA = getEpisodeNumber(a?.title)
    const numB = getEpisodeNumber(b?.title)
    if (numA !== numB) return numA - numB
    return String(a?.createdAt || a?.id || '').localeCompare(String(b?.createdAt || b?.id || ''))
  })
}

function filterEnglishNoise(text) {
  if (!text || typeof text !== 'string') return ''
  let cleaned = text.trim()
  cleaned = cleaned.replace(/<think>[\s\S]*?<\/think>/gi, '').trim()
  cleaned = cleaned.replace(/\*{0,2}(?:My Analysis|Analysis of|Thought Process|Thinking Process|Chain of Thought|Task Breakdown|Analysis)[\s\S]*?(?=(?:(?:\n\s*|\A)(?:第[0-9一二两三四五六七八九十]+[集章回话幕]|开局旁白|序幕|序章|【|#|\*\*【|\*\*第|\[场景|场景[：:]|镜头[：:]|\n\n[\u4e00-\u9fa5]{2,})))/gi, '').trim()
  cleaned = cleaned.replace(/^```(?:json|markdown|text)?\s*/i, '').replace(/\s*```$/i, '').trim()

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
      if (!hasChinese || (englishWords > 3 && chineseChars < 4 && !line.includes('第') && !line.includes('集') && !line.includes('旁白') && !line.includes('序幕'))) {
        continue
      }
      reachedChineseContent = true
      keptLines.push(rawLine)
    } else {
      if (!hasChinese && englishWords > 2 && /^(?:hope this helps|let me know|if you need|feel free|here is|enjoy|best regards)/i.test(line)) {
        continue
      }
      keptLines.push(rawLine)
    }
  }

  const result = keptLines.join('\n').trim()
  return result || cleaned
}

function cleanError(err) { return String(err).replace(/^Error:\s*/, '') }
async function request(method, path, body = null) {
  return desktopBackendRequest(method, path, props.token, body)
}

function selectChapter(chapter) {
  if (saveTimer) saveChapter()
  selectedChapterId.value = String(chapter.id)
  content.value = filterEnglishNoise(chapter.workflow?.novel || chapter.content || '')
  scriptContent.value = filterEnglishNoise(chapter.script || chapter.workflow?.script || '')
  chapterTitleDraft.value = chapter.title || ''
  saveStatus.value = ''
  chapterError.value = ''
  
  if (scriptContent.value.trim()) {
    if (activeStage.value === 'novel') activeStage.value = 'script'
  } else {
    activeStage.value = 'novel'
  }
}

async function loadDetail() {
  loading.value = true
  error.value = ''
  try {
    const [projectData, chapterData] = await Promise.all([
      request('GET', `/project/${props.projectId}`),
      request('GET', `/project/${props.projectId}/chapter/list`),
    ])
    project.value = projectData
    const rawList = Array.isArray(chapterData) ? chapterData : []
    const normalizedList = rawList.map(ch => ({
      ...ch,
      title: normalizeEpisodeTitle(ch.title)
    }))
    chapters.value = sortChaptersList(normalizedList)
    if (chapters.value.length) selectChapter(chapters.value[0])
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    loading.value = false
  }
}

async function addChapter() {
  chapterError.value = ''
  try {
    const existingEpNums = chapters.value
      .map(ch => getEpisodeNumber(ch.title))
      .filter(n => n > 0 && n < 999999)
    const nextNum = existingEpNums.length ? Math.max(...existingEpNums) + 1 : 1
    const defaultTitle = `第${nextNum}集`
    const created = await request('POST', `/project/${props.projectId}/chapter`, { title: defaultTitle, content: '', workflow: {} })
    if (created?.title) created.title = normalizeEpisodeTitle(created.title)
    chapters.value = sortChaptersList([...chapters.value, created])
    selectChapter(created)
  } catch (err) { chapterError.value = cleanError(err) }
}

function beginRenameChapter(chapter) {
  if (!chapter?.id) return
  renamingChapterId.value = String(chapter.id)
  chapterTitleDraft.value = chapter.title || ''
  requestAnimationFrame(() => document.querySelector('.chapter-title-input')?.focus())
}

function cancelRenameChapter() {
  renamingChapterId.value = ''
  chapterTitleDraft.value = selectedChapter.value?.title || ''
}

async function saveChapterTitle(chapter) {
  if (!chapter?.id || String(renamingChapterId.value) !== String(chapter.id)) return
  const title = normalizeEpisodeTitle(chapterTitleDraft.value.trim())
  if (!title) {
    chapterError.value = '章节名称不能为空'
    return
  }
  const previousTitle = chapter.title || ''
  const chapterContent = content.value
  const chapterScript = scriptContent.value
  const workflow = { ...(chapter.workflow || {}), novel: chapterContent, script: chapterScript }
  chapter.title = title
  renamingChapterId.value = ''
  try {
    const saved = await request('PUT', `/chapter/${encodeURIComponent(chapter.id)}`, {
      title,
      content: chapterContent,
      script: chapterScript,
      workflow,
    })
    Object.assign(chapter, saved || {}, { title, content: chapterContent, script: chapterScript, workflow })
    chapters.value = sortChaptersList(chapters.value)
    if (String(selectedChapterId.value) === String(chapter.id)) {
      chapterTitleDraft.value = title
      saveStatus.value = 'saved'
    }
    chapterError.value = ''
  } catch (err) {
    chapter.title = previousTitle
    chapterTitleDraft.value = previousTitle
    chapterError.value = cleanError(err)
  }
}

async function deleteChapter(chapter) {
  if (!window.confirm(`确认删除章节“${chapter.title || '未命名章节'}”？`)) return
  try {
    await request('DELETE', `/chapter/${chapter.id}`)
    chapters.value = chapters.value.filter(item => String(item.id) !== String(chapter.id))
    if (String(selectedChapterId.value) === String(chapter.id)) {
      selectedChapterId.value = ''
      content.value = ''
      scriptContent.value = ''
      if (chapters.value.length) selectChapter(chapters.value[0])
    }
  } catch (err) { chapterError.value = cleanError(err) }
}

async function saveChapter() {
  const chapter = selectedChapter.value
  if (!chapter) return
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = null
  const savedContent = content.value
  const savedScript = scriptContent.value
  saveStatus.value = 'saving'
  const workflow = { ...(chapter.workflow || {}), novel: savedContent, script: savedScript }
  Object.assign(chapter, { content: savedContent, script: savedScript, workflow })
  try {
    const saved = await request('PUT', `/chapter/${chapter.id}`, {
      title: chapter.title || '未命名章节',
      content: savedContent,
      script: savedScript,
      workflow,
    })
    if (chapter.content === savedContent && chapter.script === savedScript) {
      Object.assign(chapter, saved || {}, { content: savedContent, script: savedScript, workflow })
    }
    if (String(selectedChapterId.value) === String(chapter.id)) {
      saveStatus.value = 'saved'
      if (savedTimer) window.clearTimeout(savedTimer)
      savedTimer = window.setTimeout(() => { if (saveStatus.value === 'saved') saveStatus.value = '' }, 1800)
    }
  } catch (err) {
    if (String(selectedChapterId.value) === String(chapter.id)) {
      saveStatus.value = 'error'
      chapterError.value = cleanError(err)
    }
  }
}

function openVideoForCreation() {
  if (!creationData.value) return
  emit('open-video', {
    document: creationData.value,
    projectId: props.projectId,
    chapterId: selectedChapterId.value,
    projectName: project.value?.name || '',
    chapterTitle: selectedChapter.value?.title || '',
  })
}

function getChapterScriptCount(ch) {
  const s = ch.script || ch.workflow?.script || ''
  return s.replace(/\s/g, '').length
}
function formatChapterCount(count) {
  if (!count) return '0字'
  if (count >= 10000) return `${(count / 10000).toFixed(1)}w字`
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k字`
  return `${count}字`
}
function getChapterShotsCount(ch) {
  return ch.workflow?.creationData?.shots?.length || 0
}

watch([content, scriptContent], () => {
  if (!selectedChapter.value || loading.value) return
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(saveChapter, 1200)
})

onMounted(loadDetail)
onBeforeUnmount(() => { if (saveTimer) saveChapter(); if (savedTimer) window.clearTimeout(savedTimer) })
</script>

<template>
  <section class="client-detail-page">
    <header class="client-detail-header">
      <button class="client-detail-back" @click="emit('back')"><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6" /></svg>返回</button>
      <div v-if="project" class="client-detail-heading">
        <h1>{{ project.name || '未命名项目' }}</h1>
        <div class="client-detail-meta">
          <span v-if="project.style" class="style-pill">{{ project.style }}</span><span v-if="project.ratio" class="ratio-pill">{{ project.ratio }}</span>
          <p>{{ project.description || '暂未添加项目简介' }}</p><time v-if="project.updateTime">更新于 {{ String(project.updateTime).slice(0, 10) }}</time>
        </div>
      </div>
      <button v-if="project" type="button" class="client-detail-agent-button" @click="emit('open-agent', project)">
        <svg viewBox="0 0 24 24"><path d="M5 5.5h14v10H9l-4 3v-13Z"/><path d="M8 9h8M8 12h5"/><path d="m18 3 1.2 2.8L22 7l-2.8 1.2L18 11l-1.2-2.8L14 7l2.8-1.2L18 3Z"/></svg>打开项目创作助手
      </button>
    </header>

    <div v-if="loading" class="client-detail-state" role="status" aria-live="polite">
      <BaseLoadingState size="lg" panel text="正在打开项目" description="正在同步项目详情与章节内容…" />
    </div>
    <div v-else-if="error" class="client-detail-state error">{{ error }}</div>
    <div v-else class="client-detail-body">
      <aside class="client-chapter-sidebar">
        <header><div><strong>章节目录</strong><span>{{ chapters.length }}</span></div><button data-tooltip="新增章节" aria-label="新增章节" @click="addChapter"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg></button></header>
        <p v-if="!chapters.length" class="client-chapter-empty">还没有章节<br>点击右上角 + 新增第一个章节</p>
        <ul v-else>
          <li v-for="(chapter, index) in chapters" :key="chapter.id" :class="{ active: String(chapter.id) === String(selectedChapterId) }">
            <button class="chapter-select" @click="selectChapter(chapter)" @dblclick.stop="beginRenameChapter(chapter)">
              <span class="chapter-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <div class="chapter-select-info">
                <strong v-if="String(renamingChapterId) !== String(chapter.id)">{{ chapter.title || '未命名章节' }}</strong>
                <div class="chapter-tags-bar">
                  <span v-if="getChapterScriptCount(chapter)" class="chapter-tag script">剧本 {{ formatChapterCount(getChapterScriptCount(chapter)) }}</span>
                  <span v-if="getChapterShotsCount(chapter)" class="chapter-tag shots">{{ getChapterShotsCount(chapter) }}分镜</span>
                </div>
              </div>
            </button>
            <input v-if="String(renamingChapterId) === String(chapter.id)" v-model="chapterTitleDraft" class="chapter-title-input" aria-label="章节名称" @click.stop @keydown.enter.prevent="saveChapterTitle(chapter)" @keydown.esc.prevent="cancelRenameChapter" @blur="saveChapterTitle(chapter)" />
            <button v-else class="chapter-rename" data-tooltip="重命名章节" aria-label="重命名章节" @click.stop="beginRenameChapter(chapter)"><svg viewBox="0 0 24 24"><path d="m4 16.5-.8 3.3 3.3-.8L17.8 7.7a2.2 2.2 0 0 0-3.1-3.1L3.4 15.9ZM13.5 6.5l4 4" /></svg></button>
            <button class="chapter-remove" data-tooltip="删除章节" aria-label="删除章节" @click="deleteChapter(chapter)"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l-1-13M10 11v5M14 11v5" /></svg></button>
          </li>
        </ul>
      </aside>

      <main class="client-chapter-main">
        <div v-if="!selectedChapter" class="client-main-empty">从左侧选择一个章节开始编辑</div>
        <template v-else>
          <p v-if="chapterError" class="client-detail-error">{{ chapterError }}</p>
          
          <nav class="client-stage-stepper">
            <button :class="{ active: activeStage === 'novel' }" type="button" @click="activeStage = 'novel'">
              <span class="step-num">1</span>
              <span class="step-label">章节原文</span>
              <span class="step-count">{{ characterCount.toLocaleString() }}字</span>
            </button>
            <button :class="{ active: activeStage === 'script' }" type="button" @click="activeStage = 'script'">
              <span class="step-num">2</span>
              <span class="step-label">分幕剧本</span>
              <span class="step-count">{{ scriptCharacterCount.toLocaleString() }}字</span>
              <span v-if="scriptContent.trim()" class="step-tag-ok">✓ 已生成</span>
            </button>
            <button :class="{ active: activeStage === 'creation' }" type="button" @click="activeStage = 'creation'">
              <span class="step-num">3</span>
              <span class="step-label">资产与分镜</span>
              <span class="step-count">{{ creationShotsCount }}分镜</span>
              <span v-if="hasCreationData" class="step-tag-ok">✓ 已生成</span>
            </button>
          </nav>

          <!-- Stage 1: 原文 -->
          <template v-if="activeStage === 'novel'">
            <div v-if="scriptContent.trim()" class="stage-notice-banner" @click="activeStage = 'script'">
              <div class="stage-notice-left">
                <svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                <span>当前章节已生成 <strong>{{ scriptCharacterCount.toLocaleString() }} 字</strong> 完整分幕剧本</span>
              </div>
              <button type="button" class="stage-notice-btn">立即切换查看/编辑剧本 →</button>
            </div>

            <div class="client-stage-header">
              <div><h2>章节原文（故事梗概 / 小说源文）</h2><p>输入或粘贴需要改编的内容 <span>{{ characterCount.toLocaleString() }} 字</span></p></div>
              <div class="client-stage-tools">
                <span class="client-save-status" :class="saveStatus">{{ saveStatus === 'saving' ? '保存中…' : saveStatus === 'saved' ? '✓ 已保存' : saveStatus === 'error' ? '保存失败' : '' }}</span>
                <div class="client-view-tabs">
                  <button :class="{ active: viewMode === 'text' }" @click="viewMode = 'text'">文本</button>
                  <button :class="{ active: viewMode === 'preview' }" @click="viewMode = 'preview'">预览</button>
                </div>
              </div>
            </div>
            <textarea v-if="viewMode === 'text'" v-model="content" class="client-stage-editor" placeholder="在这里写「原文」…" @blur="saveChapter"></textarea>
            <div v-else class="client-markdown-shell">
              <aside v-if="markdownHeadings.length" class="client-markdown-toc" aria-label="Markdown 目录">
                <strong>目录</strong>
                <nav>
                  <button
                    v-for="heading in markdownHeadings"
                    :key="heading.id"
                    type="button"
                    :class="`is-level-${heading.level}`"
                    :data-tooltip="heading.text"
                    @click="scrollToMarkdownHeading(heading.id)"
                  >{{ heading.text }}</button>
                </nav>
              </aside>
              <div class="client-markdown-view">
                <article v-if="renderedMarkdown" class="client-markdown-content" v-html="renderedMarkdown"></article>
                <p v-else class="client-markdown-empty">暂无原文，切到「文本」输入内容</p>
              </div>
            </div>
          </template>

          <!-- Stage 2: 剧本 -->
          <template v-else-if="activeStage === 'script'">
            <div v-if="hasCreationData" class="stage-notice-banner creation" @click="activeStage = 'creation'">
              <div class="stage-notice-left">
                <svg viewBox="0 0 24 24"><rect x="2" y="2" width="20" height="20" rx="2"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/></svg>
                <span>剧本已成功提取 <strong>{{ creationSummary }}</strong></span>
              </div>
              <button type="button" class="stage-notice-btn">查看资产与分镜卡片 ({{ creationShotsCount }} 个) →</button>
            </div>

            <div class="client-stage-header">
              <div><h2>当前章节分幕剧本</h2><p>由 AI 改编或手动编写的分幕分场剧本 <span>{{ scriptCharacterCount.toLocaleString() }} 字</span></p></div>
              <div class="client-stage-tools">
                <span class="client-save-status" :class="saveStatus">{{ saveStatus === 'saving' ? '保存中…' : saveStatus === 'saved' ? '✓ 已保存' : saveStatus === 'error' ? '保存失败' : '' }}</span>
                <div class="client-view-tabs">
                  <button :class="{ active: scriptViewMode === 'text' }" @click="scriptViewMode = 'text'">文本</button>
                  <button :class="{ active: scriptViewMode === 'preview' }" @click="scriptViewMode = 'preview'">预览</button>
                </div>
              </div>
            </div>
            <textarea v-if="scriptViewMode === 'text'" v-model="scriptContent" class="client-stage-editor" placeholder="在这里写「分幕剧本」或通过上方「打开项目创作助手」生成剧本…" @blur="saveChapter"></textarea>
            <div v-else class="client-markdown-shell">
              <aside v-if="scriptMarkdownHeadings.length" class="client-markdown-toc" aria-label="Markdown 目录">
                <strong>目录</strong>
                <nav>
                  <button
                    v-for="heading in scriptMarkdownHeadings"
                    :key="heading.id"
                    type="button"
                    :class="`is-level-${heading.level}`"
                    :data-tooltip="heading.text"
                    @click="scrollToMarkdownHeading(heading.id)"
                  >{{ heading.text }}</button>
                </nav>
              </aside>
              <div class="client-markdown-view">
                <article v-if="renderedScriptMarkdown" class="client-markdown-content" v-html="renderedScriptMarkdown"></article>
                <p v-else class="client-markdown-empty">暂无剧本，切到「文本」输入或通过「创作助手」生成</p>
              </div>
            </div>
          </template>

          <!-- Stage 3: 资产与分镜 -->
          <template v-else-if="activeStage === 'creation'">
            <div class="client-stage-header">
              <div><h2>资产与分镜数据</h2><p>{{ creationSummary }}</p></div>
              <div class="client-stage-tools">
                <button v-if="hasCreationData" type="button" class="client-detail-video-btn" @click="openVideoForCreation">
                  <svg viewBox="0 0 24 24"><path d="m15 12-8.5 5V7z"/><rect x="3" y="3" width="18" height="18" rx="2"/></svg>
                  进入视频任务制作
                </button>
              </div>
            </div>

            <div class="client-creation-overview">
              <div v-if="hasCreationData" class="creation-cards-shell">
                <div class="creation-cards-head">
                  <strong>分镜卡片预览 (共 {{ creationData.shots.length }} 幕)</strong>
                  <span>点击右上角「进入视频任务制作」可一键生成视频</span>
                </div>
                <div class="creation-shots-preview">
                  <div v-for="(shot, idx) in (creationData.shots || [])" :key="shot.id || idx" class="creation-shot-card">
                    <header>
                      <span>分镜 {{ String(idx + 1).padStart(2, '0') }}</span>
                      <strong>{{ shot.title || '未命名分镜' }}</strong>
                      <small v-if="shot.duration_s">{{ shot.duration_s }}s</small>
                    </header>
                    <p>{{ shot.visual || shot.description || '无画面描述' }}</p>
                  </div>
                </div>
              </div>
              <div v-else class="client-markdown-empty">
                <p>当前章节尚未生成资产与分镜数据</p>
                <button type="button" class="client-detail-agent-button" @click="emit('open-agent', project)">
                  打开创作助手生成资产与分镜
                </button>
              </div>
            </div>
          </template>

        </template>
      </main>
    </div>
  </section>
</template>

<style scoped>
.client-detail-page{position:relative;z-index:1;display:flex;width:100%;height:calc(100vh - 98px);min-height:0;flex-direction:column;padding:20px 28px 25px;overflow:hidden;box-sizing:border-box}.client-detail-header{display:flex;flex:0 0 auto;align-items:flex-start;gap:16px;margin-bottom:18px}.client-detail-back{display:inline-flex;height:32px;align-items:center;gap:6px;padding:0 10px;border:1px solid transparent;border-radius:8px;color:#aaa;background:transparent;cursor:pointer;font-size:13px}.client-detail-back:hover{color:#fff;background:#292929}.client-detail-back svg{width:15px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}.client-detail-heading{min-width:0;flex:1}.client-detail-heading h1{margin:0 0 7px;color:#f2f2f2;font-size:22px;line-height:1.3}.client-detail-meta{display:flex;align-items:center;gap:8px;min-width:0}.client-detail-meta>span{position:relative;display:inline-flex;height:23px;padding:0 9px;align-items:center;border:1px solid #3c3c3c;border-radius:6px;color:#aaa;background:#202020;font-size:11px;font-weight:600;line-height:1;white-space:nowrap;box-shadow:inset 0 1px 0 rgba(255,255,255,0.04)}.client-detail-meta .style-pill{gap:6px;padding-left:7px;max-width:160px;overflow:hidden;text-overflow:ellipsis;border-color:color-mix(in srgb, var(--theme-accent) 38%, #3c3c3c);color:#f2f2f2;background:color-mix(in srgb, var(--theme-accent) 8%, #202020)}.client-detail-meta .style-pill::before{width:3px;height:11px;flex:0 0 3px;border-radius:2px;background:var(--theme-accent);content:''}.client-detail-meta .ratio-pill{color:#8a8a8a;font-variant-numeric:tabular-nums}.client-detail-meta p{min-width:0;max-width:520px;margin:0;overflow:hidden;color:#8a8a8a;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.client-detail-meta time{margin-left:auto;color:#666;font-size:12px;white-space:nowrap}.client-detail-body{display:grid;min-height:0;flex:1;grid-template-columns:280px 1fr;gap:18px}.client-chapter-sidebar{display:flex;min-height:0;flex-direction:column;overflow:hidden;border:1px solid #383838;border-radius:9px;background:#1c1c1c}.client-chapter-sidebar>header{display:flex;min-height:54px;align-items:center;justify-content:space-between;padding:0 12px 0 15px;border-bottom:1px solid #303030}.client-chapter-sidebar>header>div{display:flex;align-items:center;gap:8px;font-size:14px}.client-chapter-sidebar>header span{display:grid;min-width:20px;height:20px;padding:0 5px;place-items:center;border:1px solid #363636;border-radius:5px;color:#777;background:#161616;font-size:12px}.client-chapter-sidebar>header button{display:grid;width:30px;height:30px;place-items:center;border:1px solid color-mix(in srgb, var(--theme-accent) 27%, transparent);border-radius:7px;color:var(--theme-accent);background:color-mix(in srgb, var(--theme-accent) 7%, transparent);cursor:pointer}.client-chapter-sidebar>header svg{width:15px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}.client-chapter-sidebar ul{min-height:0;flex:1;margin:0;padding:7px;overflow:hidden auto;list-style:none}.client-chapter-sidebar li{position:relative;display:flex;min-height:54px;padding:6px 0;align-items:center;border:1px solid transparent;border-radius:8px;box-sizing:border-box}.client-chapter-sidebar li+li{margin-top:4px}.client-chapter-sidebar li:hover{border-color:#373737;background:#242424}.client-chapter-sidebar li.active{border-color:color-mix(in srgb, var(--theme-accent) 22%, transparent);background:color-mix(in srgb, var(--theme-accent) 9%, transparent)}.client-chapter-sidebar li.active::before{position:absolute;top:8px;bottom:8px;left:0;width:3px;border-radius:0 3px 3px 0;background:var(--theme-accent);content:''}.chapter-select{display:flex;width:100%;height:100%;min-width:0;align-items:center;gap:10px;padding:0 64px 0 10px;border:0;color:#ddd;background:transparent;text-align:left;cursor:pointer;box-sizing:border-box}.chapter-select .chapter-index{display:grid;width:24px;height:24px;flex:0 0 24px;place-items:center;border:1px solid #373737;border-radius:5px;color:#777;font-size:12px}.active .chapter-select .chapter-index{border-color:color-mix(in srgb, var(--theme-accent) 33%, transparent);color:var(--theme-accent);background:color-mix(in srgb, var(--theme-accent) 12%, transparent)}.chapter-select-info{min-width:0;flex:1;display:flex;flex-direction:column;justify-content:center;gap:3px;overflow:hidden}.chapter-select-info strong{overflow:hidden;font-size:13px;font-weight:600;text-overflow:ellipsis;white-space:nowrap;color:#eee;line-height:1.3}.chapter-tags-bar{display:flex;gap:6px;align-items:center;margin-top:2px;flex-wrap:nowrap;white-space:nowrap;overflow:hidden}.chapter-tag{display:inline-flex;align-items:center;height:18px;padding:0 6px;border-radius:4px;font-size:10px;font-weight:500;line-height:1;white-space:nowrap;flex-shrink:0;box-sizing:border-box}.chapter-tag.script{background:rgba(0, 209, 178, 0.15);color:#3be0d7;border:1px solid rgba(0,209,178,0.3)}.chapter-tag.shots{background:rgba(255, 170, 0, 0.15);color:#ffaa00;border:1px solid rgba(255,170,0,0.3)}.chapter-remove{position:absolute;right:7px;display:grid;width:28px;height:28px;place-items:center;border:0;border-radius:6px;color:#666;background:transparent;cursor:pointer;opacity:0}.client-chapter-sidebar li:hover .chapter-remove,.client-chapter-sidebar li.active .chapter-remove{opacity:1}.chapter-remove:hover{color:#ff8299;background:#ff456012}.chapter-remove svg{width:14px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}.chapter-rename{position:absolute;right:36px;display:grid;width:28px;height:28px;place-items:center;border:0;border-radius:6px;color:#777;background:transparent;cursor:pointer;opacity:0}.client-chapter-sidebar li:hover .chapter-rename,.client-chapter-sidebar li.active .chapter-rename{opacity:1}.chapter-rename:hover{color:var(--theme-accent);background:color-mix(in srgb,var(--theme-accent) 10%,transparent)}.chapter-rename svg{width:14px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}.chapter-title-input{position:absolute;left:47px;right:68px;width:auto;height:28px;padding:0 7px;border:1px solid color-mix(in srgb,var(--theme-accent) 55%,transparent);border-radius:5px;outline:0;color:#eee;background:#191919;font:13px inherit}.client-chapter-empty{padding:35px 15px;color:#777;text-align:center;font-size:13px;line-height:1.8}.client-chapter-main{display:flex;min-width:0;min-height:0;flex-direction:column;gap:12px;overflow:hidden}.client-main-empty{display:grid;height:100%;place-items:center;border:1px dashed #373737;border-radius:12px;color:#777;font-size:14px}

/* Stage Stepper Styles - Perfectly Formatted & No Overflow Wrapping */
.client-stage-stepper{display:flex;align-items:center;gap:8px;padding:5px 6px;border:1px solid #323232;border-radius:10px;background:#1a1a1a;overflow-x:auto;box-sizing:border-box}
.client-stage-stepper button{display:inline-flex;align-items:center;gap:8px;height:36px;padding:0 14px;border:1px solid transparent;border-radius:7px;color:#8e8e8e;background:transparent;font-size:13px;font-weight:500;white-space:nowrap;flex-shrink:0;cursor:pointer;transition:all 150ms ease}
.client-stage-stepper button:hover{color:#ddd;background:#242424}
.client-stage-stepper button.active{border-color:color-mix(in srgb, var(--theme-accent) 45%, transparent);color:#fff;background:color-mix(in srgb, var(--theme-accent) 12%, #1e1e1e)}
.step-num{display:grid;width:20px;height:20px;place-items:center;border-radius:50%;color:#777;background:#262626;font-size:11px;font-weight:700;flex-shrink:0}
.client-stage-stepper button.active .step-num{color:#081316;background:var(--theme-accent)}
.step-label{color:inherit;white-space:nowrap}
.step-count{padding:1px 6px;border-radius:4px;color:#777;background:#242424;font-size:11px;font-weight:normal;white-space:nowrap}
.client-stage-stepper button.active .step-count{color:var(--theme-accent);background:color-mix(in srgb, var(--theme-accent) 18%, #1f1f1f)}
.step-tag-ok{display:inline-flex;align-items:center;padding:1px 6px;border-radius:4px;background:rgba(96, 201, 154, 0.15);color:#60c99a;border:1px solid rgba(96, 201, 154, 0.25);font-size:11px;font-weight:600;white-space:nowrap;flex-shrink:0}

.stage-notice-banner{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border:1px solid rgba(0, 209, 178, 0.3);border-radius:8px;background:rgba(0, 209, 178, 0.07);cursor:pointer;transition:all 150ms ease}
.stage-notice-banner:hover{background:rgba(0, 209, 178, 0.12)}
.stage-notice-banner.creation{border-color:rgba(255, 170, 0, 0.3);background:rgba(255, 170, 0, 0.07)}
.stage-notice-banner.creation:hover{background:rgba(255, 170, 0, 0.12)}
.stage-notice-left{display:flex;align-items:center;gap:8px;color:#d8d8d8;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stage-notice-left strong{color:#fff}
.stage-notice-left svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:2;flex-shrink:0}
.stage-notice-btn{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border:1px solid rgba(255,255,255,0.1);border-radius:6px;background:rgba(255,255,255,0.06);color:#fff;font-size:12px;font-weight:600;white-space:nowrap;flex-shrink:0;cursor:pointer}

.client-stage-header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:2px}
.client-stage-header h2{margin:0;color:#eee;font-size:14px}
.client-stage-header p{margin:3px 0 0;color:#777;font-size:12px}
.client-stage-header p span{margin-left:8px;padding-left:8px;border-left:1px solid #3a3a3a}
.client-stage-tools{display:flex;align-items:center;gap:10px}
.client-save-status{width:62px;color:#777;font-size:12px;text-align:right}
.client-save-status.saved{color:#60c99a}
.client-save-status.error{color:#ff7898}
.client-view-tabs{display:flex;padding:3px;border:1px solid #343434;border-radius:8px;background:#1c1c1c}
.client-view-tabs button{height:26px;padding:0 12px;border:0;border-radius:6px;color:#777;background:transparent;cursor:pointer;font-size:12px}
.client-view-tabs button.active{color:#eee;background:#303030}
.client-stage-editor,.client-stage-preview{width:100%;min-height:0;flex:1;margin:0;padding:16px;border:1px solid #323232;border-radius:11px;outline:0;color:#ddd;background:#151515;font:14px/1.8 inherit;box-sizing:border-box}
.client-stage-editor{resize:none}
.client-stage-editor:focus{border-color:color-mix(in srgb, var(--theme-accent) 40%, transparent)}
.client-stage-preview{overflow:auto;white-space:normal;padding:24px 28px}
.client-detail-video-btn{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 12px;border:1px solid color-mix(in srgb, var(--theme-accent) 40%, transparent);border-radius:7px;color:var(--theme-accent);background:color-mix(in srgb, var(--theme-accent) 12%, transparent);font-size:12px;font-weight:600;cursor:pointer}
.client-detail-video-btn:hover{background:color-mix(in srgb, var(--theme-accent) 22%, transparent)}
.client-detail-video-btn svg{width:14px;fill:none;stroke:currentColor;stroke-width:2}
.client-creation-overview{display:flex;flex-direction:column;flex:1;min-height:0;overflow-y:auto;gap:14px}
.creation-cards-shell{display:flex;flex-direction:column;gap:12px}
.creation-cards-head{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border:1px solid #303030;border-radius:9px;background:#1a1a1a}
.creation-cards-head strong{color:#eee;font-size:14px}
.creation-cards-head span{color:#888;font-size:12px}
.creation-shots-preview{display:grid;grid-template-columns:repeat(auto-fill, minmax(280px, 1fr));gap:12px}
.creation-shot-card{padding:12px 14px;border:1px solid #2e2e2e;border-radius:8px;background:#181818;display:flex;flex-direction:column;gap:6px}
.creation-shot-card header{display:flex;align-items:center;gap:8px}
.creation-shot-card header span{padding:2px 6px;border-radius:4px;color:#888;background:#242424;font-size:11px}
.creation-shot-card header strong{flex:1;color:#ddd;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.creation-shot-card header small{color:#777;font-size:11px}
.creation-shot-card p{margin:0;color:#999;font-size:12px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.client-markdown-shell{display:grid;grid-template-columns:200px minmax(0,1fr);flex:1;min-height:0;gap:12px}
.client-markdown-toc{min-height:0;overflow-y:auto;padding:16px 12px;border:1px solid #303030;border-radius:12px;background:#181818}
.client-markdown-toc>strong{display:flex;align-items:center;gap:6px;margin:0 4px 12px;color:#f2f2f2;font-size:13px;font-weight:700;letter-spacing:.04em}
.client-markdown-toc>strong::before{content:'';width:3px;height:14px;border-radius:2px;background:var(--theme-accent)}
.client-markdown-toc nav{display:grid;gap:3px}
.client-markdown-toc button{position:relative;width:100%;overflow:hidden;padding:7px 10px 7px 14px;border:0;border-radius:7px;color:#b8b8b8;background:transparent;font:inherit;font-size:12px;font-weight:500;line-height:18px;text-align:left;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;transition:color 150ms ease,background-color 150ms ease}
.client-markdown-toc button::before{content:'';position:absolute;left:6px;top:50%;width:4px;height:4px;border-radius:50%;background:#555;transform:translateY(-50%);transition:background-color 150ms ease}
.client-markdown-toc button:hover,.client-markdown-toc button:focus-visible{color:#fff;background:#262626;outline:0}
.client-markdown-toc button:hover::before{background:var(--theme-accent)}
.client-markdown-toc button.is-level-2{padding-left:24px;color:#9a9a9a}
.client-markdown-toc button.is-level-2::before{left:16px;width:3px;height:3px;background:#444}
.client-markdown-toc button.is-level-3{padding-left:34px;color:#7a7a7a;font-size:11px}
.client-markdown-toc button.is-level-3::before{left:26px;width:3px;height:3px;background:#3a3a3a}
.client-markdown-view{min-height:0;overflow-y:auto;padding:24px 28px;border:1px solid #2a2a2a;border-radius:11px;background:#151515}
.client-markdown-empty{color:#777;font-size:14px;text-align:center;padding:40px 0;display:flex;flex-direction:column;align-items:center;gap:12px}
.client-markdown-content :deep(h1),.client-markdown-content :deep(h2),.client-markdown-content :deep(h3),.client-markdown-content :deep(h4),.client-markdown-content :deep(h5),.client-markdown-content :deep(h6){margin:1.4em 0 .6em;color:#f2f2f2;font-weight:700;line-height:1.3}
.client-markdown-content :deep(h1:first-child),.client-markdown-content :deep(h2:first-child),.client-markdown-content :deep(h3:first-child){margin-top:0}
.client-markdown-content :deep(h1){font-size:24px;padding-bottom:.3em;border-bottom:1px solid #2e2e2e}
.client-markdown-content :deep(h2){font-size:20px}
.client-markdown-content :deep(h3){font-size:17px}
.client-markdown-content :deep(p){margin:0 0 1em;color:#d4d4d4;font-size:14px;line-height:1.85}
.client-markdown-content :deep(ul),.client-markdown-content :deep(ol){margin:0 0 1em;padding-left:1.6em;color:#d4d4d4;font-size:14px;line-height:1.85}
.client-markdown-content :deep(li+li){margin-top:.3em}
.client-markdown-content :deep(blockquote){margin:0 0 1em;padding:8px 14px;border-left:3px solid var(--theme-accent);color:#aaa;background:rgba(255,255,255,0.03);border-radius:0 6px 6px 0}
.client-markdown-content :deep(blockquote>:last-child){margin-bottom:0}
.client-markdown-content :deep(code){padding:2px 6px;border-radius:4px;color:#ffb6a8;background:rgba(255,109,177,0.12);font-family:"Cascadia Code","Fira Code",Consolas,monospace;font-size:.92em}
.client-markdown-content :deep(pre){margin:0 0 1em;padding:14px 16px;border:1px solid #2a2a2a;border-radius:8px;background:#0d0d0d;overflow-x:auto}
.client-markdown-content :deep(pre code){padding:0;color:#e6e6e6;background:transparent;font-size:.92em}
.client-markdown-content :deep(a){color:#8be6ee;text-decoration:none;border-bottom:1px solid #2c6166}
.client-markdown-content :deep(a:hover){color:#a8f0f6;border-bottom-color:#8be6ee}
.client-markdown-content :deep(hr){margin:1.5em 0;border:0;border-top:1px solid #2a2a2a}
.client-markdown-content :deep(table){width:100%;margin:0 0 1em;border-collapse:collapse;font-size:13px}
.client-markdown-content :deep(th),.client-markdown-content :deep(td){padding:8px 12px;border:1px solid #2a2a2a;text-align:left}
.client-markdown-content :deep(th){color:#f2f2f2;background:#1a1a1a;font-weight:700}
.client-markdown-content :deep(img){max-width:100%;height:auto;border-radius:6px}
.client-detail-state{display:grid;min-height:400px;place-items:center;align-content:center;gap:12px;color:#777;font-size:13px}
.client-detail-state.error,.client-detail-error{color:#ff8299}
.client-detail-error{margin:0;padding:9px 11px;border:1px solid #ff45602e;border-radius:8px;background:#ff45600d;font-size:12px}
@media(max-width:900px){
  .client-detail-page{height:auto;min-height:calc(100vh - 48px);overflow:visible}
  .client-detail-body{grid-template-columns:1fr}
  .client-chapter-sidebar{max-height:280px}
  .client-chapter-main{min-height:500px;overflow:visible}
}
.client-detail-agent-button{display:inline-flex;align-items:center;gap:7px;align-self:flex-start;padding:9px 12px;border:1px solid #385b5d;border-radius:8px;color:#a8ecef;background:#163337;font:inherit;font-size:12px;cursor:pointer}
.client-detail-agent-button:hover{background:#1d4749}
.client-detail-agent-button svg{width:15px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}
</style>
