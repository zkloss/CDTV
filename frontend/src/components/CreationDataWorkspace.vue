<script setup>
import { waitForDesktopApi } from '../utils/desktopApi.js'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import BaseLoadingState from './BaseLoadingState.vue'

const props = defineProps({
  token: { type: String, required: true },
  initialProjectId: { type: [String, Number], default: '' },
})
const emit = defineEmits(['open-video'])

const projects = ref([])
const chapters = ref([])
const models = ref([])
const projectId = ref('')
const chapterId = ref('')
const activeTab = ref('script')
const sourceText = ref('')
const scriptText = ref('')
const requirements = ref('')
const creationPreview = ref('')
const loading = ref(true)
const chapterLoading = ref(false)
const chapterCreating = ref(false)
const chapterTitleDraft = ref('')
const generating = ref(false)
const saving = ref(false)
const error = ref('')
const saveMessage = ref('')
const generationMessage = ref('')
let sourceSaveTimer = null

const projectOptions = computed(() => projects.value.map(item => ({ value: String(item.id), label: item.name || '未命名项目' })))
const chapterOptions = computed(() => chapters.value.map(item => ({ value: String(item.id), label: item.title || '未命名章节' })))
const modelOptions = computed(() => models.value.map(item => ({ value: String(item.id ?? item.modelName ?? ''), label: item.name || item.modelName || '文本模型' })))
const selectedProject = computed(() => projects.value.find(item => String(item.id) === String(projectId.value)) || null)
const selectedChapter = computed(() => chapters.value.find(item => String(item.id) === String(chapterId.value)) || null)
const sourceCount = computed(() => sourceText.value.replace(/\s/g, '').length)
const scriptCount = computed(() => scriptText.value.replace(/\s/g, '').length)
const creationDocument = computed(() => {
  if (!creationPreview.value.trim()) return null
  try { return JSON.parse(creationPreview.value) } catch { return null }
})
const creationSummary = computed(() => {
  const data = creationDocument.value
  if (!data) return '还没有生成创作数据'
  const consistency = data.consistency || data.assets || {}
  const count = ['characters', 'roles', 'people', 'scenes', 'props', 'items', 'audio', 'audios']
    .reduce((sum, key) => sum + (Array.isArray(consistency[key]) ? consistency[key].length : 0), 0)
  return `${count} 项资产 · ${Array.isArray(data.shots) ? data.shots.length : 0} 个分镜`
})

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
  if (import.meta.env.DEV && !window.pywebview?.api) {
    if (path === '/project/list') return [{ id: 'demo-project', name: '演示项目' }]
    if (path.endsWith('/chapter/list')) return [{ id: 'demo-chapter', title: '第1集', content: '', workflow: {} }]
    return body || {}
  }
  const api = await waitForDesktopApi()
  if (!api?.backend_request) return null
  return api.backend_request(method, path, props.token, body)
}

async function loadModels() {
  const result = await request('GET', '/api/admin/models/public/list?modelType=text')
  models.value = Array.isArray(result) ? result : []
}

async function loadProjects() {
  const result = await request('GET', '/project/list')
  projects.value = Array.isArray(result) ? result : []
  if (!projectId.value || !projects.value.some(item => String(item.id) === String(projectId.value))) {
    projectId.value = String(props.initialProjectId || projects.value[0]?.id || '')
  }
}

function hydrateChapter(chapter) {
  if (!chapter) {
    chapterTitleDraft.value = ''
    sourceText.value = ''
    scriptText.value = ''
    creationPreview.value = ''
    return
  }
  const workflow = chapter.workflow && typeof chapter.workflow === 'object' ? chapter.workflow : {}
  sourceText.value = filterEnglishNoise(String(workflow.novel || chapter.content || ''))
  chapterTitleDraft.value = String(chapter.title || '')
  scriptText.value = filterEnglishNoise(String(chapter.script || workflow.script || ''))
  const creationData = workflow.creationData
  creationPreview.value = creationData && typeof creationData === 'object'
    ? JSON.stringify(creationData, null, 2)
    : ''
  saveMessage.value = ''
  generationMessage.value = ''
  error.value = ''
}

async function loadChapters() {
  if (!projectId.value) { chapters.value = []; chapterId.value = ''; hydrateChapter(null); return }
  chapterLoading.value = true
  error.value = ''
  try {
    const result = await request('GET', `/project/${encodeURIComponent(projectId.value)}/chapter/list`)
    const rawList = Array.isArray(result) ? result : []
    const normalizedList = rawList.map(ch => ({
      ...ch,
      title: normalizeEpisodeTitle(ch.title)
    }))
    chapters.value = sortChaptersList(normalizedList)
    if (!chapters.value.some(item => String(item.id) === String(chapterId.value))) chapterId.value = String(chapters.value[0]?.id || '')
    hydrateChapter(selectedChapter.value)
  } catch (err) { error.value = cleanError(err) } finally { chapterLoading.value = false }
}

function selectProject() {
  if (sourceSaveTimer) clearTimeout(sourceSaveTimer)
  chapterId.value = ''
  chapterTitleDraft.value = ''
  loadChapters()
}
function selectChapter() {
  if (sourceSaveTimer) clearTimeout(sourceSaveTimer)
  hydrateChapter(selectedChapter.value)
}

async function createNextChapter() {
  if (!projectId.value || chapterCreating.value) return
  chapterCreating.value = true
  error.value = ''
  try {
    const existingEpNums = chapters.value
      .map(ch => getEpisodeNumber(ch.title))
      .filter(n => n > 0 && n < 999999)
    const nextNum = existingEpNums.length ? Math.max(...existingEpNums) + 1 : 1
    const defaultTitle = `第${nextNum}集`
    const created = await request('POST', `/project/${encodeURIComponent(projectId.value)}/chapter`, {
      title: defaultTitle,
      content: '',
      workflow: {},
    })
    if (!created?.id) throw new Error('新章节创建失败')
    if (created?.title) created.title = normalizeEpisodeTitle(created.title)
    chapters.value = sortChaptersList([...chapters.value, created])
    chapterId.value = String(created.id)
    hydrateChapter(created)
    generationMessage.value = `已新建「${created.title || '下一集'}」；请在左侧粘贴这一集的原文`
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    chapterCreating.value = false
  }
}

async function saveChapter(message = '已保存') {
  const chapter = selectedChapter.value
  if (!chapter) { error.value = '请先选择项目和章节'; return false }
  saving.value = true
  saveMessage.value = ''
  try {
    const title = chapterTitleDraft.value.trim() || chapter.title || '未命名章节'
    chapter.title = title
    const oldWorkflow = chapter.workflow && typeof chapter.workflow === 'object' ? chapter.workflow : {}
    const workflow = { ...oldWorkflow, novel: sourceText.value, script: scriptText.value }
    if (creationDocument.value) {
      workflow.creationData = creationDocument.value
      workflow.creationDataUpdatedAt = new Date().toISOString()
      workflow.creationDataSource = 'ai-workspace'
    } else if (!creationPreview.value.trim()) {
      delete workflow.creationData
    }
    workflow.scriptStatus = scriptText.value.trim() ? 'edited' : 'draft'
    workflow.scriptUpdatedAt = new Date().toISOString()
    if (selectedTextModel.value) workflow.scriptModel = selectedTextModel.value
    const saved = await request('PUT', `/chapter/${encodeURIComponent(chapter.id)}`, {
      title, content: sourceText.value, script: scriptText.value, workflow,
    })
    Object.assign(chapter, saved || {}, { content: sourceText.value, script: scriptText.value, workflow })
    saveMessage.value = message
    return true
  } catch (err) { error.value = cleanError(err); saveMessage.value = '保存失败'; return false } finally { saving.value = false }
}

function scheduleSave() {
  if (!selectedChapter.value || loading.value) return
  if (sourceSaveTimer) clearTimeout(sourceSaveTimer)
  sourceSaveTimer = setTimeout(() => saveChapter('自动保存'), 1400)
}

async function generateScript() {
  if (!sourceText.value.trim()) { error.value = '请先导入或输入章节原文'; return }
  if (!selectedTextModel.value) { error.value = '请先在设置 → 模型管理 → 文本模型中配置自定义 API'; return }
  if (!window.pywebview?.api) { error.value = '请从桌面客户端打开 AI 创作'; return }
  generating.value = true; error.value = ''; generationMessage.value = ''
  try {
    const result = await request('POST', '/ai/script', {
      model: selectedTextModel.value, title: selectedChapter.value?.title || selectedProject.value?.name || '',
      sourceText: sourceText.value, requirements: requirements.value,
    })
    scriptText.value = filterEnglishNoise(String(result?.script || '').trim())
    if (!scriptText.value) throw new Error('文本模型没有返回剧本内容')
    generationMessage.value = `剧本已生成 · ${result.model || '文本模型'}；请检查后保存`
    activeTab.value = 'script'
  } catch (err) { error.value = cleanError(err) } finally { generating.value = false }
}

async function generateCreationData() {
  const prompt = [`章节原文：\n${sourceText.value.trim()}`, scriptText.value.trim() ? `已整理剧本：\n${scriptText.value.trim()}` : '', requirements.value.trim() ? `创作要求：\n${requirements.value.trim()}` : ''].filter(Boolean).join('\n\n')
  if (!sourceText.value.trim() && !scriptText.value.trim()) { error.value = '请先输入原文或剧本'; return }
  if (!selectedTextModel.value) { error.value = '请先在设置 → 模型管理 → 文本模型中配置自定义 API'; return }
  if (!window.pywebview?.api) { error.value = '请从桌面客户端打开 AI 创作'; return }
  generating.value = true; error.value = ''; generationMessage.value = ''
  try {
    const result = await request('POST', '/ai/creation-data', {
      model: selectedTextModel.value, scope: 'full', title: selectedChapter.value?.title || selectedProject.value?.name || '', prompt,
    })
    creationPreview.value = String(result?.text || JSON.stringify(result?.document || {}, null, 2))
    if (!creationDocument.value) throw new Error('文本模型返回的创作数据不是有效 JSON')
    generationMessage.value = `创作数据已生成 · ${result.model || '文本模型'}；确认后保存到当前章节`
    activeTab.value = 'creation'
  } catch (err) { error.value = cleanError(err) } finally { generating.value = false }
}

async function saveCreationData() {
  if (!creationDocument.value) { error.value = '请先生成并检查合法的创作数据 JSON'; return }
  const saved = await saveChapter('创作数据已保存')
  if (saved) generationMessage.value = `已关联到「${selectedProject.value?.name || '项目'} / ${selectedChapter.value?.title || '章节'}」`
}

async function openVideoTask() {
  if (!creationDocument.value) { error.value = '请先生成并保存创作数据'; return }
  if (!await saveChapter('创作数据已保存')) return
  emit('open-video', { document: creationDocument.value, projectId: projectId.value, chapterId: chapterId.value, projectName: selectedProject.value?.name || '', chapterTitle: selectedChapter.value?.title || '' })
}

const selectedTextModel = ref('')
watch(models, (items) => { if (!selectedTextModel.value) selectedTextModel.value = String(items[0]?.id ?? items[0]?.modelName ?? '') }, { deep: true })
watch(projectId, () => { if (!loading.value) selectProject() })
watch(chapterId, () => { if (!chapterLoading.value) selectChapter() })
watch([sourceText, scriptText], scheduleSave)

onMounted(async () => {
  window.addEventListener('cdtv:models-updated', loadModels)
  window.addEventListener('focus', loadModels)
  loading.value = true
  try { await Promise.all([loadModels(), loadProjects()]); await loadChapters() } catch (err) { error.value = cleanError(err) } finally { loading.value = false }
})
onBeforeUnmount(() => {
  window.removeEventListener('cdtv:models-updated', loadModels)
  window.removeEventListener('focus', loadModels)
  if (sourceSaveTimer) clearTimeout(sourceSaveTimer)
})
</script>

<template>
  <section class="creation-workspace">
    <header class="creation-hero">
      <div><p class="eyebrow">剧本完成后的制作整理台</p><h1>资产与分镜</h1><p>这里不负责从零写剧本，而是把当前章节剧本拆成可复用资产和连续分镜，再交给视频任务制作。</p></div>
      <div class="creation-flow"><span>章节原文</span><i>→</i><span>剧本</span><i>→</i><span>资产与分镜</span><i>→</i><span>视频任务</span></div>
    </header>

    <section v-if="loading" class="creation-state"><BaseLoadingState size="lg" panel text="正在打开资产与分镜" description="正在读取项目、章节与文本模型…" /></section>
    <template v-else>
      <section class="creation-purpose panel"><div class="creation-purpose-title"><span class="step">?</span><div><strong>这一页具体做什么？</strong><p>剧本助手负责写戏；资产与分镜负责把戏拆成制作清单；视频任务负责真正生成图片和视频。</p></div></div><div class="creation-purpose-flow"><div><b>剧本助手</b><span>创作、修改、保存章节剧本</span></div><div class="purpose-arrow">→</div><div class="current"><b>资产与分镜</b><span>提取人物、场景、道具、音频和连续分镜</span></div><div class="purpose-arrow">→</div><div><b>视频任务</b><span>引用这些资产生成图片和视频</span></div></div></section>
      <section class="creation-toolbar panel">
        <div class="creation-selects">
          <label><span>当前项目</span><UiSelect v-model="projectId" :options="projectOptions" placeholder="选择项目" /></label>
          <div class="creation-chapter-field"><label><span>当前章节</span><UiSelect v-model="chapterId" :options="chapterOptions" placeholder="选择章节" :disabled="!projectId || chapterLoading" /></label><button class="new-chapter-button" type="button" :disabled="!projectId || chapterCreating" @click="createNextChapter">{{ chapterCreating ? '创建中…' : '＋ 新建下一集' }}</button></div>
          <label><span>文本模型</span><UiSelect v-model="selectedTextModel" :options="modelOptions" placeholder="选择文本模型" :disabled="!models.length" status badge="文本" /></label>
        </div>
        <div class="creation-context"><strong>{{ selectedProject?.name || '未选择项目' }}</strong><span>{{ selectedChapter?.title || '未选择章节' }}</span><small>要写第二集：先点「新建下一集」，确认这里显示“第二集”，再粘贴原文。内容只会保存到当前章节。</small></div>
      </section>

      <section class="creation-body">
        <aside class="creation-source panel">
          <div class="creation-panel-heading"><div><span class="step">01</span><h2>章节原文</h2></div><span>{{ sourceCount.toLocaleString() }} 字</span></div>
          <div v-if="selectedChapter" class="chapter-title-editor"><label>章节名称</label><input v-model="chapterTitleDraft" placeholder="例如：第一集 / 第二集 / 丹神觉醒" @keydown.enter.prevent="saveChapter('章节名称已保存')" /><button class="secondary-button" type="button" :disabled="saving" @click="saveChapter('章节名称已保存')">保存名称</button></div>
          <textarea v-model="sourceText" placeholder="这里粘贴或编辑外部导入的章节原文…"></textarea>
          <label class="creation-requirements"><span>改编要求（可选）</span><textarea v-model="requirements" placeholder="例如：节奏紧凑、保留原对白、单集约 60 秒…"></textarea></label>
        </aside>

        <main class="creation-editor panel">
          <div class="creation-tabs"><button :class="{ active: activeTab === 'script' }" @click="activeTab = 'script'">剧本编辑</button><button :class="{ active: activeTab === 'creation' }" @click="activeTab = 'creation'">资产与分镜</button></div>
          <div v-if="activeTab === 'script'" class="creation-tab-content">
            <div class="creation-panel-heading"><div><span class="step">02</span><h2>当前章节剧本</h2></div><span>{{ scriptCount.toLocaleString() }} 字</span></div>
            <textarea v-model="scriptText" placeholder="点击「生成剧本」，或直接编辑导入的剧本…"></textarea>
            <div class="creation-actions"><button class="secondary-button" type="button" :disabled="generating" @click="generateScript">{{ generating ? '正在生成…' : 'AI 生成剧本' }}</button><button class="primary-button" type="button" :disabled="saving || !selectedChapter" @click="saveChapter('剧本已保存')">{{ saving ? '保存中…' : '保存剧本' }}</button></div>
          </div>
          <div v-else class="creation-tab-content">
            <div class="creation-panel-heading"><div><span class="step">03</span><h2>资产与分镜数据</h2></div><span>{{ creationSummary }}</span></div>
            <textarea v-model="creationPreview" spellcheck="false" placeholder="先保存当前章节剧本，再提取人物、场景、道具、音频和连续分镜…"></textarea>
            <div class="creation-actions"><button class="secondary-button" type="button" :disabled="generating || (!sourceText.trim() && !scriptText.trim())" @click="generateCreationData">{{ generating ? '正在提取…' : '⚡ 提取资产与分镜' }}</button><button class="primary-button" type="button" :disabled="saving || !creationDocument || !selectedChapter" @click="saveCreationData">{{ saving ? '保存中…' : '确认并保存' }}</button><button class="link-button" type="button" :disabled="saving || !creationDocument || !selectedChapter" @click="openVideoTask">去视频任务（新建关联任务）</button></div>
          </div>
          <p v-if="generationMessage" class="creation-message">{{ generationMessage }}</p><p v-if="saveMessage" class="creation-save-message">{{ saveMessage }}</p><p v-if="error" class="creation-error">{{ error }}</p>
        </main>
      </section>
    </template>
  </section>
</template>

<style scoped>
.creation-workspace{min-height:100%;padding:34px 42px 48px;overflow:auto;color:#eee}.creation-hero{display:flex;align-items:flex-end;justify-content:space-between;gap:28px;margin:0 auto 22px;max-width:1500px}.creation-hero h1{margin:4px 0 8px;font-size:32px;letter-spacing:-.03em}.creation-hero p:not(.eyebrow){margin:0;color:#8b8b8b;font-size:14px}.creation-flow{display:flex;align-items:center;gap:9px;padding:11px 14px;border:1px solid #303030;border-radius:12px;color:#aaa;background:#181818;font-size:12px;white-space:nowrap}.creation-flow span{color:#ddd}.creation-flow i{color:var(--theme-accent);font-style:normal}.creation-state{display:grid;min-height:480px;place-items:center}.panel{border:1px solid #303030;border-radius:14px;background:#191919;box-shadow:0 12px 28px #00000012}.creation-purpose{display:grid;grid-template-columns:minmax(280px,.8fr) minmax(520px,1.2fr);align-items:center;gap:22px;max-width:1500px;margin:0 auto 14px;padding:14px 18px}.creation-purpose-title{display:flex;align-items:flex-start;gap:10px}.creation-purpose-title strong{display:block;margin-bottom:4px;color:#eee;font-size:13px}.creation-purpose-title p{margin:0;color:#888;font-size:11px;line-height:1.6}.creation-purpose-flow{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1.15fr) auto minmax(0,1fr);align-items:center;gap:10px}.creation-purpose-flow>div:not(.purpose-arrow){display:grid;gap:4px;padding:10px 12px;border:1px solid #303030;border-radius:9px;background:#151515}.creation-purpose-flow>div.current{border-color:#3a6668;background:#142c2e}.creation-purpose-flow b{color:#eee;font-size:11px}.creation-purpose-flow span{color:#888;font-size:10px;line-height:1.5}.creation-purpose-flow .current b{color:#a8ecef}.purpose-arrow{color:#6f9a9c;font-size:16px}.creation-toolbar{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,.95fr);align-items:stretch;gap:20px;max-width:1500px;margin:0 auto 16px;padding:16px 18px}.creation-selects{display:grid;grid-template-columns:minmax(180px,1fr) minmax(290px,1.25fr) minmax(180px,1fr);align-items:end;gap:12px;min-width:0}.creation-selects label{display:grid;gap:6px;min-width:0}.creation-selects label span,.creation-requirements>span{color:#999;font-size:11px}.creation-chapter-field{display:flex;align-items:flex-end;gap:7px;min-width:0}.creation-chapter-field>label{min-width:0!important;flex:1}.new-chapter-button{height:34px;padding:0 9px;border:1px solid #3c6668;border-radius:8px;color:#a8ecef;background:#163337;cursor:pointer;font:inherit;font-size:11px;white-space:nowrap}.new-chapter-button:hover{background:#1d4749}.new-chapter-button:disabled{cursor:not-allowed;opacity:.45}.creation-context{display:grid;align-content:center;gap:4px;min-width:0;text-align:right}.creation-context strong{color:#eee;font-size:13px}.creation-context span{color:var(--theme-accent);font-size:12px}.creation-context small{color:#777;font-size:11px}.creation-body{display:grid;grid-template-columns:minmax(260px,.75fr) minmax(420px,1.25fr);gap:16px;max-width:1500px;margin:0 auto}.creation-source,.creation-editor{display:flex;min-height:560px;flex-direction:column;padding:18px}.creation-panel-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.creation-panel-heading>div{display:flex;align-items:center;gap:9px}.creation-panel-heading h2{margin:0;font-size:15px}.creation-panel-heading>span{color:#777;font-size:11px}.step{display:grid;width:26px;height:26px;place-items:center;border-radius:7px;color:#111;background:var(--theme-accent);font-size:11px;font-weight:800}.chapter-title-editor{display:grid;grid-template-columns:1fr auto;gap:6px;margin:0 0 10px}.chapter-title-editor label{grid-column:1/-1;color:#999;font-size:11px}.chapter-title-editor input{min-width:0;padding:9px 10px;border:1px solid #343434;border-radius:8px;outline:0;color:#ddd;background:#141414;font:12px inherit}.chapter-title-editor input:focus{border-color:color-mix(in srgb,var(--theme-accent) 50%,transparent)}.chapter-title-editor button{padding:0 11px}.creation-source>textarea,.creation-tab-content>textarea{width:100%;min-height:0;flex:1;resize:none;padding:14px;border:1px solid #343434;border-radius:10px;outline:0;color:#ddd;background:#141414;font:13px/1.75 inherit}.creation-source>textarea:focus,.creation-tab-content>textarea:focus{border-color:color-mix(in srgb,var(--theme-accent) 50%,transparent)}.creation-requirements{display:grid;gap:6px;margin-top:12px}.creation-requirements textarea{min-height:72px;resize:vertical;padding:10px;border:1px solid #343434;border-radius:8px;outline:0;color:#ccc;background:#141414;font:12px/1.5 inherit}.creation-tabs{display:flex;gap:4px;padding:4px;margin-bottom:14px;border:1px solid #303030;border-radius:10px;background:#151515}.creation-tabs button{padding:8px 16px;border:0;border-radius:7px;color:#888;background:transparent;cursor:pointer;font-size:13px}.creation-tabs button.active{color:#eee;background:#303030}.creation-tab-content{display:flex;min-height:0;flex:1;flex-direction:column}.creation-tab-content>textarea{font-family:"Cascadia Code","Fira Code",Consolas,monospace;font-size:12px}.creation-tab-content:first-of-type>textarea{font-family:inherit;font-size:13px}.creation-actions{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:12px}.creation-actions button{padding:9px 14px;border-radius:8px;font:inherit;font-size:12px;cursor:pointer}.secondary-button{border:1px solid #4b4b4b;color:#ddd;background:#252525}.primary-button{border:1px solid color-mix(in srgb,var(--theme-accent) 40%,transparent);color:#102022;background:var(--theme-accent)}.link-button{border:1px solid #3b5b5d;color:#a8ecef;background:transparent}.creation-actions button:disabled{cursor:not-allowed;opacity:.45}.creation-message,.creation-save-message,.creation-error{margin:10px 0 0;padding:8px 10px;border-radius:7px;font-size:12px}.creation-message{color:#a4e8e9;background:#123337}.creation-save-message{color:#91d6af;background:#123326}.creation-error{color:#ff8aa0;background:#35161e}@media(max-width:1100px){.creation-hero{align-items:flex-start;flex-direction:column}.creation-purpose{grid-template-columns:1fr;gap:12px}.creation-toolbar{grid-template-columns:1fr;align-items:stretch}.creation-context{text-align:left}.creation-body{grid-template-columns:1fr}.creation-source,.creation-editor{min-height:430px}}@media(max-width:700px){.creation-workspace{padding:24px 16px}.creation-selects{grid-template-columns:1fr}.creation-chapter-field{min-width:0}.creation-flow{width:max-content;max-width:100%;overflow:auto}.creation-purpose-flow{grid-template-columns:1fr;gap:7px}.purpose-arrow{display:none}.creation-actions{justify-content:stretch;flex-wrap:wrap}.creation-actions button{flex:1}}
</style>
