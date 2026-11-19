<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import { filmLayoutFields, FILM_LAYOUTS } from '../utils/filmLayouts.js'
import ProjectStylePicker from './ProjectStylePicker.vue'
import ShotcraftLibrary from './ShotcraftLibrary.vue'
import VideoCreationWorkspace from './VideoCreationWorkspace.vue'
import GeneralFilmStudio from './GeneralFilmStudio.vue'
import GeneralStylePicker from './GeneralStylePicker.vue'
import HuashuMotionStudio from './HuashuMotionStudio.vue'
import ProjectWorkflowCover from './ProjectWorkflowCover.vue'
import { GENERAL_VIDEO_TYPES, generalTypeName, projectWorkspace } from '../utils/projectWorkspace.js'
import { desktopBackendRequest } from '../utils/desktopApi.js'
import { ensureScriptShotCoverage } from '../utils/scriptShotCoverage.js'
import { projectStyleFields, getProjectStyleDescription, getProjectStyleSummary, validateProjectStyle, PROJECT_RATIO_OPTIONS } from './projectFormOptions.js'

const props = defineProps({ token: String, initialProjectId: { type: String, default: '' }, createRequested: { type: Number, default: 0 }, apiBase: String, storageBase: String, selectedAccountId: String, videoModel: String, productionContext: Object })
const emit = defineEmits(['open-video', 'open-drama', 'open-direct', 'request-model-settings'])
const productionRef = ref(null), productionMounted = ref(false), productionPayload = ref(null)
let lastReadPlanId = ''
const production = ref({ id: '', shots: 0, completed: 0, seconds: 0 })
const productionView = computed(() => tab.value === 'audio' ? 'audio' : tab.value === 'review' ? 'review' : 'visual')
const projects = ref([]), models = ref([]), model = ref(''), catalog = ref(null)
const project = ref(null), plans = ref([]), planId = ref(''), tab = ref('brief')
const loading = ref(false), busy = ref(''), error = ref(''), message = ref('')
const deleteTarget = ref(null), deleteError = ref(''), deleteDialog = ref(null), deleteCancel = ref(null)
let deleteTrigger = null
const keyword = ref(''), category = ref('all'), createOpen = ref(false), pendingTemplate = ref(false), pendingCards = ref([])
const script = ref(''), summary = ref(''), questions = ref([]), prompt = ref('')
const creationData = ref(null), extractionScript = ref(''), selectedCards = ref([]), skillContext = ref(null), turns = ref([])
const brief = reactive({ audience: '', objective: '', duration: 30, mode: 'autonomous', production: 'mixed', materials: '', templateId: '', filmLayout: '', filmTheme: 'auto' })
const advancedProduction = ref(false)
const wholeFilmMode = computed(() => brief.mode === 'template' || brief.production === 'motion' || brief.production === 'huashu')
const isHuashuMode = computed(() => brief.production === 'huashu')
const showWholeFilm = computed(() => wholeFilmMode.value && !advancedProduction.value && ['produce','audio','review'].includes(tab.value))
const draft = reactive({ name: '', description: '', type: 'commercial', production: 'huashu', style: 'tech-future', storyGenres: [], styleNotes: '', ratio: '16:9' })
const modes = [{ value: 'autonomous', label: '自主创作' }, { value: 'template', label: '整片模板' }, { value: 'guided', label: '逐步共创' }]
const productionOptions = [
  { value: 'huashu', label: '花叔商业发布片', desc: '大厂发布会级 UI 快切、3D 立体产品展示与动态大字排版（代码驱动，像素级精准，零乱码变形）' },
  { value: 'motion', label: '模板动效制作 (Shotcraft)', desc: '知识图解、结构说明、卡片飞入与数据图表' },
  { value: 'ai_video', label: '视频模型制作 (AI Video)', desc: '使用 AI 视频模型逐镜生成真实摄影与电影感画面' },
  { value: 'mixed', label: '混合制作', desc: '按镜头自由组合动效图解与 AI 视频模型' }
]
const visibleProjects = computed(() => projects.value.filter(item => (category.value === 'all' || item.type === category.value) && `${item.name} ${item.description}`.toLowerCase().includes(keyword.value.trim().toLowerCase())))
const currentPlan = computed(() => plans.value.find(item => String(item.id) === planId.value))
const planOptions = computed(() => plans.value.map((item, index) => ({ value: String(item.id), label: /^第\s*[\d一二三四五六七八九十]+\s*集/.test(item.title || '') ? (index ? `历史方案 ${index + 1}` : '制作方案') : item.title || `方案 ${index + 1}` })))
const modelOptions = computed(() => models.value.map(item => ({ value: String(item.id || item.modelName), label: item.name || item.modelName })))
const shots = computed(() => { try { return ensureScriptShotCoverage(creationData.value, extractionScript.value)?.shots || [] } catch { return creationData.value?.shots || [] } })
const needsExtraction = computed(() => Boolean(creationData.value && script.value !== extractionScript.value))
const suggestions = computed(() => project.value?.type === 'science'
  ? ['先解释核心原理，再给一个生活中的例子，避免夸大和无依据结论。', '把内容改成容易看懂的步骤演示，给图示和旁白留足时间。']
  : ['先明确受众和核心卖点，选合适镜头做一支完整短片。', '结合已选镜头效果，减少空泛特效，突出实际使用效果。'])

const request = (method, path, body = null) => desktopBackendRequest(method, path, props.token, body, 0)
const cleanError = err => String(err?.message || err || '').replace(/^Error:\s*/, '')
async function askDelete(item, event) {
  if (busy.value || !item?.id || projectWorkspace(item) !== 'general') return
  deleteTrigger = event?.currentTarget || null
  deleteTarget.value = { id: String(item.id), name: item.name || '未命名作品' }
  deleteError.value = ''
  await nextTick()
  deleteCancel.value?.focus()
}
async function cancelDelete() {
  if (busy.value === 'delete') return
  deleteTarget.value = null; deleteError.value = ''
  await nextTick()
  if (deleteTrigger?.isConnected) deleteTrigger.focus()
}
function trapDeleteFocus(event) {
  const buttons = [...(deleteDialog.value?.querySelectorAll('button:not(:disabled)') || [])]
  if (!buttons.length) { event.preventDefault(); return }
  if (event.shiftKey && document.activeElement === buttons[0]) { event.preventDefault(); buttons.at(-1).focus() }
  else if (!event.shiftKey && document.activeElement === buttons.at(-1)) { event.preventDefault(); buttons[0].focus() }
}
async function confirmDelete() {
  const target = deleteTarget.value
  if (!target || busy.value) return
  busy.value = 'delete'; deleteError.value = ''
  try {
    const latest = await request('GET', `/project/${encodeURIComponent(target.id)}`)
    if (projectWorkspace(latest) !== 'general') throw new Error('作品归属已变化，请刷新列表后再操作')
    if (String(project.value?.id || '') === target.id && await productionRef.value?.flush() === false) throw new Error('制作记录未保存成功，请先处理保存问题后再删除作品')
    await request('DELETE', `/project/${encodeURIComponent(target.id)}`)
    projects.value = projects.value.filter(item => String(item.id) !== target.id)
    if (String(project.value?.id || '') === target.id) {
      productionMounted.value = false; productionPayload.value = null
      project.value = null; plans.value = []; planId.value = ''; tab.value = 'brief'
    }
    deleteTarget.value = null
    message.value = `已删除“${target.name}”的作品记录；已有视频任务、媒体和共享素材保留。`
    try { await loadLibrary() } catch (err) { error.value = `作品已删除，列表刷新失败：${cleanError(err)}` }
  } catch (err) { deleteError.value = cleanError(err) }
  finally { busy.value = '' }
}
async function loadLibrary() {
  const list = await request('GET', '/project/list')
  projects.value = (Array.isArray(list) ? list : []).filter(item => projectWorkspace(item) === 'general')
}
async function initialize() {
  loading.value = true; error.value = ''
  try {
    const result = await Promise.allSettled([loadLibrary(), request('GET', '/shotcraft/catalog'), request('GET', '/api/admin/models/public/list?modelType=text')])
    for (let index = 0; index < result.length; index++) {
      if (result[index].status === 'rejected') { error.value = cleanError(result[index].reason); continue }
      if (index === 1) catalog.value = result[index].value
      if (index === 2) { models.value = result[index].value || []; model.value = String(models.value[0]?.id || models.value[0]?.modelName || '') }
    }
    if (props.initialProjectId) await openProject({ id: props.initialProjectId })
    else if (props.createRequested) newProject()
  } finally { loading.value = false }
}
function newProject() {
  Object.assign(draft, { name: '', description: '', type: 'commercial', production: 'huashu', style: 'tech-future', storyGenres: [], styleNotes: '', ratio: '16:9' })
  pendingTemplate.value = false
  pendingCards.value = project.value ? [] : [...selectedCards.value]
  error.value = ''; createOpen.value = true
}
async function createProject() {
  busy.value = 'create'; error.value = ''
  try {
    if (!draft.name.trim()) throw new Error('请输入项目名称')
    validateProjectStyle(draft)
    const saved = await request('POST', '/project', { ...draft, ...projectStyleFields(draft), name: draft.name.trim(), styleDesc: getProjectStyleDescription(draft), workspace: 'general', workflowStage: 'brief', production: draft.production, productionBrief: { mode: pendingTemplate.value ? 'template' : 'autonomous', templateId: pendingTemplate.value ? 'ink-press' : '', selectedCards: [...pendingCards.value], production: draft.production } })
    createOpen.value = false; await loadLibrary(); await openProject(saved)
  } catch (err) { error.value = cleanError(err) } finally { busy.value = '' }
}
async function openProject(item) {
  loading.value = true; error.value = ''; message.value = ''; questions.value = []; summary.value = ''; skillContext.value = null; prompt.value = ''
  try {
    const detail = await request('GET', `/project/${encodeURIComponent(item.id)}`)
    if (projectWorkspace(detail) !== 'general') { emit('open-drama', detail); return }
    const list = await request('GET', `/project/${encodeURIComponent(item.id)}/chapter/list`)
    productionMounted.value = false; productionPayload.value = null; production.value = { id: '', shots: 0, completed: 0, seconds: 0 }
    project.value = detail; plans.value = Array.isArray(list) ? list : []; planId.value = String(plans.value.find(p=>String(p.id)===String(props.productionContext?.chapterId))?.id || plans.value[0]?.id || '')
    Object.assign(brief, { audience: '', objective: '', duration: 30, mode: 'autonomous', production: 'mixed', materials: '', templateId:'', filmLayout:'', filmTheme:'auto', ...(detail.productionBrief || {}) })
    selectedCards.value = Array.isArray(detail.productionBrief?.selectedCards) ? [...detail.productionBrief.selectedCards] : []
    advancedProduction.value=false
    readPlan(); tab.value = wholeFilmMode.value && plans.value[0]?.script ? 'produce' : creationData.value?.shots?.length ? 'produce' : plans.value[0]?.script ? 'script' : 'brief'
    if (tab.value === 'produce' && !wholeFilmMode.value) productionMounted.value = true
    if (props.productionContext) { productionPayload.value=props.productionContext; productionMounted.value=true; tab.value='produce' }
  } catch (err) { error.value = cleanError(err) } finally { loading.value = false }
}
function readPlan() {
  if (lastReadPlanId !== planId.value) { lastReadPlanId=planId.value; productionMounted.value=false; productionPayload.value=null; advancedProduction.value=false; production.value={id:'',shots:0,completed:0,seconds:0} }
  const current = currentPlan.value
  script.value = current?.script || current?.workflow?.script || ''
  creationData.value = current?.workflow?.creationData || null
  extractionScript.value = current?.workflow?.creationScriptSnapshot || script.value
  summary.value = current?.workflow?.generalVideo?.summary || ''
  questions.value = current?.workflow?.generalVideo?.questions || []
  skillContext.value = current?.workflow?.generalVideo?.skillContext || null
  turns.value = current?.workflow?.generalVideo?.turns || []
  if (current?.workflow?.generalVideo?.brief) Object.assign(brief, current.workflow.generalVideo.brief)
  if (FILM_LAYOUTS.some(item=>item.value===project.value?.productionBrief?.filmLayout)) Object.assign(brief, filmLayoutFields(project.value.productionBrief.filmLayout))
  if (Array.isArray(current?.workflow?.generalVideo?.selectedCards)) selectedCards.value = [...current.workflow.generalVideo.selectedCards]
  if (['produce','audio','review'].includes(tab.value) && !wholeFilmMode.value) productionMounted.value=true
}
watch(planId, readPlan)
function contextPayload() {
  return { model: model.value, project: { name: project.value.name, description: project.value.description, type: project.value.type, ...projectStyleFields(project.value), ratio: project.value.ratio, styleDescription: getProjectStyleDescription(project.value) }, brief: { ...brief }, mode: brief.mode, selectedCards: selectedCards.value, history: turns.value.slice(-40), script: script.value, prompt: prompt.value.trim() || '根据项目资料和制作简报生成完整单片脚本。' }
}
async function saveBrief() {
  busy.value = 'save'; error.value = ''; message.value = ''
  try {
    validateProjectStyle(project.value)
    const saved = await request('PUT', `/project/${encodeURIComponent(project.value.id)}`, { description: project.value.description || '', ...projectStyleFields(project.value), ratio: project.value.ratio, productionBrief: { ...brief, selectedCards: [...selectedCards.value] } })
    project.value = { ...project.value, ...saved }
    if (currentPlan.value) {
      const current = currentPlan.value
      const updated = await request('PUT', `/chapter/${encodeURIComponent(current.id)}`, { workflow: { ...(current.workflow || {}), generalVideo: { ...(current.workflow?.generalVideo || {}), brief: { ...brief }, selectedCards: [...selectedCards.value] } } })
      plans.value = plans.value.map(item => String(item.id) === String(updated.id) ? updated : item)
    }
    message.value = '制作简报已保存'; return true
  } catch (err) { error.value = cleanError(err); return false } finally { busy.value = '' }
}
async function persistPlan(extra = {}) {
  const current = currentPlan.value
  const prior = current?.script || current?.workflow?.script || ''
  const history = [...(current?.workflow?.generalVideo?.scriptHistory || [])]
  if (prior && prior !== script.value) history.push({ script: prior, savedAt: new Date().toISOString() })
  const workflow = { ...(current?.workflow || {}), script: script.value,
    ...(creationData.value ? { creationData: creationData.value, creationScriptSnapshot: extractionScript.value } : {}),
    generalVideo: { ...(current?.workflow?.generalVideo || {}), summary: summary.value, questions: questions.value, skillContext: skillContext.value, turns: turns.value, brief: { ...brief }, selectedCards: [...selectedCards.value], scriptHistory: history }, ...extra }
  const saved = current
    ? await request('PUT', `/chapter/${encodeURIComponent(current.id)}`, { script: script.value, workflow })
    : await request('POST', `/project/${encodeURIComponent(project.value.id)}/chapter`, { title: '制作方案', content: '', script: script.value, workflow })
  const index = plans.value.findIndex(item => String(item.id) === String(saved.id))
  if (index < 0) plans.value.push(saved); else plans.value[index] = saved
  planId.value = String(saved.id)
  return saved
}
async function saveScript() {
  busy.value = 'save'; error.value = ''
  try { await persistPlan(); message.value = '脚本已保存，原有版本保留在方案记录中'; return true }
  catch (err) { error.value = cleanError(err); return false } finally { busy.value = '' }
}
async function generateScript() {
  busy.value = 'plan'; error.value = ''; message.value = ''
  try {
    const payload = contextPayload()
    const result = await request('POST', '/shotcraft/plan', payload)
    turns.value.push({ role: 'user', content: payload.prompt }, { role: 'assistant', content: JSON.stringify({ script: result.script || '', summary: result.summary || '', questions: result.questions || [] }) })
    if (!selectedCards.value.length && result.skillContext?.selectedCards?.length) selectedCards.value = [...result.skillContext.selectedCards]
    if (result.script) script.value = result.script
    summary.value = result.summary || ''; questions.value = result.questions || []; skillContext.value = result.skillContext
    await persistPlan(); tab.value = 'script'; message.value = result.script ? '单片脚本已生成并保存' : '共创问题已保存，请补充后继续'
  } catch (err) { error.value = cleanError(err) } finally { busy.value = '' }
}
async function extractShots() {
  if (wholeFilmMode.value && !advancedProduction.value) { if(await saveScript()) openProduction(); return }
  busy.value = 'extract'; error.value = ''; message.value = ''
  try {
    if (!script.value.trim()) throw new Error('请先编写或生成脚本')
    const result = await request('POST', '/shotcraft/extract', contextPayload())
    if (!result.document?.shots?.length) throw new Error('没有返回可用分镜，当前内容未替换')
    creationData.value = ensureScriptShotCoverage(result.document, script.value)
    extractionScript.value = script.value; skillContext.value = result.skillContext
    await persistPlan(); await prepareProduction(); message.value = `已整理 ${creationData.value.shots.length} 个镜头，可直接开始制作`
  } catch (err) { error.value = cleanError(err) } finally { busy.value = '' }
}
async function prepareProduction() {
  error.value = ''
  if (needsExtraction.value) { error.value = '脚本已修改，请先整理最新镜头；已有视频和素材仍保留'; tab.value = 'script'; return }
  if (!shots.value.length) { tab.value = 'script'; return }
  try {
    const saved = currentPlan.value || await persistPlan()
    productionMounted.value = true
    productionPayload.value = { document: JSON.parse(JSON.stringify(ensureScriptShotCoverage(creationData.value, script.value))), script: script.value, projectId: String(project.value.id), chapterId: String(saved.id), videoProjectId: production.value.id || saved.workflow?.videoProjectId || '', projectName: project.value.name, chapterTitle: '制作方案', workspaceKind: 'general' }
    tab.value = 'produce'
  } catch (err) { error.value = cleanError(err) }
}
function openProduction(view='produce') { if (!wholeFilmMode.value || advancedProduction.value) productionMounted.value = true; tab.value = view }
function openAdvancedProduction(){advancedProduction.value=true;productionMounted.value=true;tab.value='produce'}
function productionRequest(view) { if (view==='visual') openProduction(); else prepareProduction() }
async function back() { await productionRef.value?.flush(); project.value = null; productionMounted.value = false; tab.value = 'brief'; await loadLibrary() }
async function selectFilmLayout(value) {
  if (busy.value || !project.value) return
  const id=String(project.value.id)
  busy.value='film-layout'; error.value=''; message.value=''
  try {
    const fields=filmLayoutFields(value)
    const saved=await request('PUT', `/project/${encodeURIComponent(id)}`, {productionBrief:{...(project.value.productionBrief||{}),...fields}})
    if(String(project.value?.id)!==id)return
    project.value={...project.value,...saved};Object.assign(brief,fields)
    message.value=`已保存：${FILM_LAYOUTS.find(item=>item.value===value).label}，下次生成时应用；旧成片保留`
  } catch(err) {error.value=cleanError(err)} finally {busy.value=''}
}
async function useTemplate() {
  if (!project.value) { newProject(); pendingTemplate.value = true; return }
  Object.assign(brief,filmLayoutFields('ink-press')); if(!await saveBrief())return;message.value = '已保存 Ink Press 整片模板；生成时执行原版10镜头、运镜和音效，演示素材替换成你的内容'; tab.value = 'brief'
}
watch(() => props.createRequested, () => newProject())
watch(() => props.initialProjectId, id => { if (id && String(project.value?.id) !== id) openProject({ id }) })
onMounted(initialize)
</script>

<template>
  <section class="general-video-studio" :class="{ 'gv-home': !project, 'gv-project-open': project, 'gv-script-active': project && tab==='script', 'gv-making': ['produce','audio','review'].includes(tab) }">
    <template v-if="!project">
      <header class="gv-hub-head">
        <div class="gv-hub-copy"><span class="gv-eyebrow">宣传科普 · 单片制作</span><div class="gv-hub-title"><h1>通用视频</h1><b>{{ projects.length }} 个作品</b></div><p>宣传、科普、生活与纪录，从内容到成片，在作品内完成。</p></div>
        <div class="gv-hub-actions"><label class="gv-hub-search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></svg><input v-model="keyword" type="search" placeholder="搜索通用视频项目" aria-label="搜索通用视频项目"/></label><button class="gv-primary" @click="newProject">＋ 新建通用视频</button></div>
      </header>
      <p v-if="error" class="gv-error" role="alert">{{ error }}</p><p v-if="message" class="gv-message" role="status">{{ message }}</p>
      <template v-if="tab!=='library'">
        <div class="gv-hub-tools"><div class="gv-tabs"><button :class="{active:category==='all'}" @click="category='all'">全部作品</button><button v-for="type in GENERAL_VIDEO_TYPES" :key="type.value" :class="{active:category===type.value}" @click="category=type.value">{{ type.label }}</button></div><button class="gv-library-link" @click="tab='library'"><span>模板与镜头库</span><small>{{ catalog?.cardCount || '—' }} 镜头 · {{ catalog?.styleCount || '—' }} 效果</small><span aria-hidden="true">→</span></button></div>
        <p v-if="loading" role="status">正在读取项目…</p>
        <div v-else class="gv-project-grid">
          <button class="gv-create-card" aria-label="开始一个新作品" @click="newProject"><div class="gv-create-art"><ProjectWorkflowCover create/><strong>开始创作</strong></div><div class="gv-create-info"><strong>＋ 新建作品</strong><small>选择用途，填写简报，开始制作</small></div></button>
          <article v-for="(item,index) in visibleProjects" :key="item.id" class="gv-project-card"><button class="gv-project-open-button" :aria-label="'打开作品 '+item.name" @click="openProject(item)"><div class="gv-project-art"><ProjectWorkflowCover :tone="index%3"/><span class="gv-cover-kind">{{ generalTypeName(item) }}</span></div><div class="gv-project-info"><h3 :title="item.name">{{ item.name }}</h3><p :title="item.description || ''">{{ item.description || '打开作品，继续脚本与视频制作' }}</p><footer><time>{{ String(item.updateTime || '').slice(0,10) }}</time><span :title="getProjectStyleSummary(item)">{{ getProjectStyleSummary(item) }}</span></footer></div></button><button class="gv-project-delete" type="button" :aria-label="'删除作品 '+item.name" title="删除作品" :disabled="!!busy" @click.stop="askDelete(item, $event)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg></button></article>
          <p v-if="!visibleProjects.length && (keyword.trim() || category!=='all')" class="gv-hub-no-results">没有找到符合条件的作品，可以换个分类或关键词。</p>
        </div>
      </template>
      <template v-else><button class="gv-back" @click="tab='brief'">← 返回作品</button><ShotcraftLibrary :catalog="catalog" :token="token" v-model:selected="selectedCards" @template="useTemplate"/></template>
    </template>
    <template v-else>
      <header class="gv-project-header"><button class="gv-back" @click="back">← 全部作品</button><div><span class="gv-eyebrow">{{ generalTypeName(project) }}</span><h1>{{ project.name }}</h1><p>{{ getProjectStyleSummary(project) }} · {{ project.ratio || '16:9' }}</p></div><div class="gv-header-actions"><UiSelect v-if="plans.length>1" v-model="planId" :options="planOptions" aria-label="制作方案"/><button class="gv-secondary gv-delete-action" type="button" :disabled="!!busy" @click="askDelete(project, $event)">删除作品</button><span class="gv-workspace-chip">完整作品 · 无需推送</span><button class="gv-primary" :disabled="!!busy" @click="openProduction()">继续制作</button></div></header>
      <nav class="gv-main-tabs gv-tabs" aria-label="通用作品流程"><button v-for="(item,index) in [['brief','创作简报'],['script','脚本方案'],['produce',wholeFilmMode?'整片制作':'镜头制作'],['audio','声音旁白'],['review','成片预览'],['library','模板与镜头库']]" :key="item[0]" :class="{active:tab===item[0]}" @click="['produce','audio','review'].includes(item[0]) ? openProduction(item[0]) : tab=item[0]"><i>{{ index+1 }}</i>{{ item[1] }}<small v-if="item[0]==='produce' && shots.length && !wholeFilmMode">{{ shots.length }}</small></button></nav>
      <p v-if="error" class="gv-error" role="alert">{{ error }}</p><p v-if="message" class="gv-message" role="status">{{ message }}</p>
      <div v-if="tab==='brief'" class="gv-brief-layout"><section class="gv-panel"><h2>这支视频，要让谁看懂什么？</h2><p class="gv-muted">简报会贯穿脚本、镜头选择和制作，不需要规划集数。</p><label>内容介绍<textarea v-model="project.description" placeholder="介绍产品、要解释的知识，或想记录的内容"></textarea></label><div class="gv-form-row"><label>目标受众<input v-model="brief.audience" placeholder="例如：第一次接触这个产品的人"/></label><label>计划总时长（秒）<input v-model.number="brief.duration" type="number" min="5" max="3600"/></label></div><label>核心信息<input v-model="brief.objective" placeholder="观众看完应记住的一件事"/></label><div class="gv-form-row"><label>创作模式<UiSelect v-model="brief.mode" :options="modes" aria-label="创作模式"/></label><label>制作方式<UiSelect v-model="brief.production" :options="productionOptions" aria-label="制作方式"/></label></div><label>已有素材与参考<textarea v-model="brief.materials" placeholder="说明有哪些截图、Logo、产品照片、录屏、音乐或参考片；可在素材与分镜中继续使用现有资产。"></textarea></label><button class="gv-primary" :disabled="!!busy" @click="saveBrief">保存制作简报</button><button class="gv-secondary" @click="tab='script'">开始写脚本 →</button></section><aside class="gv-panel gv-brief-aside"><span class="gv-pill">VIDEO SHOTCRAFT</span><h2>内容决定表达，风格统一画面</h2><p>自主创作按简报连续规划；逐步共创先明确方向；整片模板沿用已经调好的镜头结构。</p><GeneralStylePicker :model-value="project" @update:model-value="Object.assign(project,$event)"/><label>画幅<UiSelect v-model="project.ratio" :options="PROJECT_RATIO_OPTIONS" aria-label="通用视频画幅"/></label></aside></div>
      <div v-else-if="tab==='script'" class="gv-script-layout"><section class="gv-panel gv-script-panel"><header><div><h2>单片脚本</h2><span class="gv-muted">画面、文案、旁白与转场，按整支作品安排。</span></div><div><button class="gv-secondary" :disabled="!!busy" @click="saveScript">保存脚本</button><button class="gv-primary" :disabled="!!busy || !script.trim()" @click="extractShots">{{ busy==='extract'?'正在整理…':wholeFilmMode?'保存并进入整片制作':'整理镜头并制作' }}</button></div></header><textarea v-model="script" class="gv-script-editor" placeholder="在这里写脚本，或让右侧助手按简报和已选镜头生成。"></textarea><p v-if="needsExtraction" class="gv-muted">脚本已有修改，已有镜头和视频仍保留；整理最新镜头后继续制作。</p></section><aside class="gv-panel gv-agent"><header class="gv-agent-header"><span class="gv-eyebrow">通用视频创作助手</span><h2>让镜头为内容服务</h2><UiSelect v-model="model" :options="modelOptions" placeholder="选择文本模型" aria-label="通用视频文本模型"/><p class="gv-muted">{{ brief.mode==='template'?'沿用 Ink Press 整片结构，适配你的内容。':brief.mode==='guided'?'先讨论关键方向，再形成完整脚本。':'依据简报自主规划，输出完整单片脚本。' }}</p></header><div class="gv-agent-scroll" tabindex="0" role="region" aria-label="创作助手回复"><div class="gv-suggestions"><button v-for="suggestion in suggestions" :key="suggestion" @click="prompt=suggestion">{{ suggestion }}</button></div><div v-if="summary" class="gv-agent-response">{{ summary }}</div><div v-if="questions.length" class="gv-agent-response"><p v-for="question in questions" :key="question">{{ question }}</p></div><details v-if="skillContext"><summary>本次使用的技能资料（{{ skillContext.sources?.length || 0 }}）</summary><p v-for="source in skillContext.sources || []" :key="source.path">{{ source.path }}</p></details></div><footer class="gv-agent-composer"><textarea v-model="prompt" placeholder="告诉助手要做什么，或提出修改要求"></textarea><button class="gv-primary" :disabled="!!busy || !model" @click="generateScript">{{ busy==='plan'?'正在创作…':script?'按要求修改脚本':'生成单片脚本' }}</button><small class="gv-muted">已选 {{ selectedCards.length }} 个效果，可到模板库调整。</small></footer></aside></div>
      <section v-else-if="tab==='shots'" class="gv-panel"><header class="gv-shot-head"><div><h2>素材与分镜</h2><p class="gv-muted">现有素材和视频在原制作任务中保留，可继续使用原来的生成模型。</p></div><button class="gv-primary" :disabled="!!busy || !script.trim()" @click="extractShots">{{ busy==='extract'?'正在提取…':'重新提取分镜' }}</button></header><p v-if="needsExtraction" class="gv-error">脚本已修改，请重新提取。当前保存的分镜没有被清空。</p><div v-if="shots.length" class="gv-shots-grid"><article v-for="(shot,index) in shots" :key="shot.id || index"><span>{{ String(index+1).padStart(2,'0') }} · {{ shot.duration_s || '—' }}秒</span><h3>{{ shot.title }}</h3><p>{{ shot.visual }}</p><small v-if="shot.shotcraft_card">镜头配方：{{ shot.shotcraft_card }}</small></article></div><div v-else class="gv-empty"><h3>把脚本整理成可制作的镜头</h3><p>先在脚本页完成内容，再提取素材与分镜。</p><button class="gv-secondary" @click="tab='script'">前往脚本方案</button></div></section>
      <ShotcraftLibrary v-else-if="tab==='library'" :catalog="catalog" :token="token" v-model:selected="selectedCards" @template="useTemplate"/>
      <HuashuMotionStudio v-if="isHuashuMode && showWholeFilm" :key="`huashu-${project.id}-${planId}`" :project="project" :brief="brief" :script="script" :token="token" :storage-base="storageBase" @advanced="openAdvancedProduction" @save-script="saveScript" />
      <GeneralFilmStudio v-else-if="showWholeFilm" :key="`${project.id}-${planId}`" :token="token" :project="project" :chapter-id="planId" :script="script" :brief="brief" :model="model" :model-options="modelOptions" :storage-base="storageBase" :settings-busy="busy==='film-layout'" @select-layout="selectFilmLayout" @template-library="tab='library'" @update:model="model=$event" @model-settings="emit('request-model-settings')" @advanced="openAdvancedProduction" @save-script="saveScript" />
      <div v-if="wholeFilmMode && advancedProduction && ['produce','audio','review'].includes(tab)" class="whole-film-return"><span>高级编辑 · 原有素材与逐镜功能</span><button class="gv-primary" @click="advancedProduction=false;tab='produce'">返回整片制作</button></div>
      <div v-if="productionMounted" v-show="['produce','audio','review'].includes(tab) && !showWholeFilm" class="gv-production-shell">
        <VideoCreationWorkspace :key="`${project.id}-${planId}`" ref="productionRef" embedded workspace-kind="general" :ai-assembly-enabled="!wholeFilmMode" :token="token" :api-base="apiBase" :storage-base="storageBase" :selected-account-id="selectedAccountId" :video-model="videoModel" :scope-project-id="String(project.id)" :scope-chapter-id="planId" :initial-video-project-id="String(currentPlan?.workflow?.videoProjectId || '')" :initial-creation-data="productionPayload" :production-view="productionView" @creation-data-consumed="productionPayload=null" @production-state="production=$event" @request-plan="productionRequest" @request-model-settings="emit('request-model-settings')" />
      </div>
    </template>
    <div v-if="deleteTarget" class="gv-modal-overlay gv-delete-overlay" @click.self="cancelDelete" @keydown.esc.stop.prevent="cancelDelete" @keydown.tab="trapDeleteFocus">
      <section ref="deleteDialog" class="gv-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="gv-delete-title" aria-describedby="gv-delete-description" :aria-busy="busy==='delete'">
        <span>作品管理</span><h2 id="gv-delete-title">删除通用视频作品？</h2><p class="gv-delete-name">{{ deleteTarget.name }}</p>
        <p id="gv-delete-description">删除后，该作品入口将从列表移除，无法直接恢复。已有视频任务、媒体文件和共享素材不会随之删除，视频任务仍可在“全部生成记录”查看。</p>
        <p v-if="deleteError" class="gv-error" role="alert">{{ deleteError }}</p>
        <footer><button ref="deleteCancel" class="gv-secondary" type="button" :disabled="busy==='delete'" @click="cancelDelete">取消</button><button class="gv-delete-confirm" type="button" :disabled="!!busy" @click="confirmDelete">{{ busy==='delete'?'正在删除…':'确认删除作品' }}</button></footer>
      </section>
    </div>
    <div v-if="createOpen" class="gv-modal-overlay" @click.self="createOpen=false"><form class="gv-modal" @submit.prevent="createProject"><header><div><span class="gv-eyebrow">通用视频创作</span><h2>新建一个完整作品</h2></div><button type="button" aria-label="关闭新建通用视频" @click="createOpen=false">×</button></header><div class="gv-modal-body"><p v-if="error" class="gv-error" role="alert">{{ error }}</p><label>项目名称<input v-model="draft.name" placeholder="例如：AI工具产品介绍 / 一分钟看懂光合作用" maxlength="100"/></label><label>视频用途</label><div class="gv-type-grid"><button v-for="type in GENERAL_VIDEO_TYPES" :key="type.value" type="button" :class="{active:draft.type===type.value}" @click="draft.type=type.value"><strong>{{ type.label }}</strong><small>{{ type.description }}</small></button></div><label>制作引擎与方式</label>
        <div class="gv-type-grid gv-prod-grid">
          <button v-for="p in productionOptions" :key="p.value" type="button" :class="{active:draft.production===p.value}" @click="draft.production=p.value">
            <strong>{{ p.label }}</strong>
            <small>{{ p.desc }}</small>
          </button>
        </div>
        <label>内容介绍<textarea v-model="draft.description" placeholder="这支视频要介绍、解释或记录什么？说明核心亮点或讲解重点"></textarea></label>
        <GeneralStylePicker :model-value="draft" @update:model-value="Object.assign(draft,$event)"/>
        <label>视频比例<UiSelect v-model="draft.ratio" :options="PROJECT_RATIO_OPTIONS" aria-label="新通用视频比例"/></label></div><footer><button type="button" class="gv-secondary" @click="createOpen=false">取消</button><button class="gv-primary" type="submit" :disabled="!!busy">{{ busy==='create'?'正在创建…':'创建作品' }}</button></footer></form></div>
  </section>
</template>

<style>
.gv-project-card{position:relative}.gv-project-card>.gv-project-delete{position:absolute;top:12px;right:12px;z-index:2;display:grid;place-items:center;width:34px;height:34px;padding:8px;border:1px solid #ffffff55;border-radius:8px;background:#ffffffed;color:#a33543;cursor:pointer}.gv-project-delete svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.gv-project-delete:hover{background:#fff1f2;color:#b42338}.gv-project-delete:focus-visible,.gv-delete-action:focus-visible{outline:3px solid var(--theme-accent);outline-offset:3px}.gv-project-art>span{padding-right:38px}.gv-delete-action{color:var(--theme-danger-text);border-color:var(--theme-danger-border)}.gv-delete-overlay{z-index:450}.gv-delete-dialog{width:min(460px,92vw);max-height:85vh;overflow:auto;box-sizing:border-box;padding:26px;border-radius:16px;background:var(--theme-bg-card);box-shadow:0 24px 80px #0003}.gv-delete-dialog>span{font-size:11px;color:var(--theme-text-secondary)}.gv-delete-dialog h2{font-size:21px;margin:10px 0 18px}.gv-delete-name{font-weight:700;overflow-wrap:anywhere}.gv-delete-dialog p{font-size:13px;line-height:1.85;color:var(--theme-text-secondary)}.gv-delete-dialog footer{display:flex;justify-content:flex-end;gap:10px;margin-top:25px}.gv-delete-confirm{padding:11px 15px;border:1px solid var(--theme-danger-text);border-radius:8px;background:var(--theme-danger-text);color:#fff;font-size:13px;font-weight:600;cursor:pointer}.gv-delete-confirm:disabled{opacity:.5;cursor:wait}

.general-video-studio{height:calc(100vh - 48px);overflow:auto;padding:30px 36px 60px;box-sizing:border-box;color:var(--theme-text-primary)}.gv-eyebrow{font-size:11px;font-weight:700;letter-spacing:2px;color:var(--theme-accent)}.gv-hub-head,.gv-project-header{display:flex;align-items:center;justify-content:space-between;gap:22px;margin-bottom:25px}.gv-hub-head h1{font-size:27px;margin:12px 0}.gv-hub-head p,.gv-project-header p{color:var(--theme-text-secondary);font-size:13px}.gv-primary,.gv-secondary{border-radius:9px;padding:11px 17px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap}.gv-primary{border:1px solid var(--theme-accent);background:var(--theme-accent);color:white}.gv-secondary{border:1px solid var(--theme-border-subtle);background:var(--theme-bg-card);color:var(--theme-text-primary)}.gv-primary:disabled,.gv-secondary:disabled{opacity:.5;cursor:default}.gv-pill{display:inline-flex;padding:6px 10px;border-radius:7px;background:var(--theme-accent-soft);color:var(--theme-accent);font-size:11px;font-weight:600}.gv-intro{display:grid;grid-template-columns:1.5fr 1fr;gap:30px;padding:30px 34px;border:1px solid var(--theme-border-subtle);border-radius:20px;background:linear-gradient(110deg,var(--theme-bg-card),color-mix(in srgb,var(--theme-accent) 10%,var(--theme-bg-card)));margin-bottom:28px}.gv-intro h2{font-size:23px;margin:18px 0 12px}.gv-intro p{max-width:570px;line-height:1.85;font-size:13px;color:var(--theme-text-secondary);margin:0}.gv-library-stat{display:flex;justify-content:flex-end;align-items:center;gap:30px;flex-wrap:wrap}.gv-library-stat strong{font-size:35px;color:var(--theme-accent)}.gv-library-stat small{display:block;font-size:11px;color:var(--theme-text-secondary);margin-top:7px;font-weight:400}.gv-library-stat button{flex-basis:100%;border:0;background:transparent;color:var(--theme-accent);text-align:right;cursor:pointer}.gv-tabs{display:flex;gap:5px;align-items:center;flex-wrap:wrap}.gv-tabs button{border:0;border-radius:8px;padding:10px 13px;background:transparent;color:var(--theme-text-secondary);cursor:pointer;font-size:13px}.gv-tabs button.active{color:var(--theme-accent);background:var(--theme-accent-soft);font-weight:700}.gv-tabs small{display:inline-block;margin-left:7px;padding:1px 5px;border-radius:4px;background:var(--theme-bg-card)}.gv-hub-tools{display:flex;justify-content:space-between;gap:20px;align-items:center;margin:0 0 20px}.general-video-studio input,.general-video-studio textarea{width:100%;box-sizing:border-box;border:1px solid var(--theme-border-subtle);border-radius:9px;padding:12px 13px;background:var(--theme-bg-input,var(--theme-bg-elevated));color:var(--theme-text-primary);font:inherit;font-size:13px;outline:none}.general-video-studio input:focus,.general-video-studio textarea:focus{border-color:var(--theme-accent)}.gv-hub-tools>input{max-width:250px}.gv-project-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}.gv-create-card,.gv-project-card{min-width:0;border:1px solid var(--theme-border-subtle);border-radius:16px;overflow:hidden;background:var(--theme-bg-card);color:var(--theme-text-primary)}.gv-create-card{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:13px;min-height:250px;cursor:pointer;border-style:dashed}.gv-create-card>span{font-size:36px;color:var(--theme-accent)}.gv-create-card small{color:var(--theme-text-secondary)}.gv-project-card>button{display:block;width:100%;height:100%;text-align:left;border:0;padding:0;background:transparent;color:inherit;cursor:pointer}.gv-project-art{padding:22px;aspect-ratio:2.1;background:linear-gradient(125deg,#182644,#456390);display:flex;flex-direction:column;justify-content:space-between;color:#fff;position:relative}.gv-project-art>span{font-size:10px;opacity:.75;letter-spacing:2px}.gv-project-art i{position:absolute;right:25px;top:35%;font:normal 30px sans-serif;opacity:.35}.gv-project-art strong{font-size:22px;max-width:80%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gv-project-info{padding:17px 20px}.gv-project-info h3{margin:0;font-size:16px}.gv-project-info p{font-size:12px;color:var(--theme-text-secondary);line-height:1.7;height:40px;overflow:hidden}.gv-project-info footer{display:flex;justify-content:space-between;gap:12px;font-size:11px;color:var(--theme-text-secondary)}.gv-project-info footer span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.gv-back{padding:8px 0;border:0;background:transparent;color:var(--theme-text-secondary);cursor:pointer;font-size:13px}.gv-project-header h1{font-size:24px;margin:7px 0}.gv-project-header>div:nth-child(2){flex:1}.gv-header-actions{display:flex;gap:12px;align-items:center}.gv-main-tabs{padding:6px;border:1px solid var(--theme-border-subtle);background:var(--theme-bg-card);border-radius:12px;margin-bottom:22px}.gv-panel{padding:25px;border:1px solid var(--theme-border-subtle);border-radius:15px;background:var(--theme-bg-card);min-width:0}.gv-panel h2{font-size:18px;margin:0 0 10px}.gv-muted{font-size:12px;color:var(--theme-text-secondary);line-height:1.8}.gv-brief-layout{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:22px}.general-video-studio label{display:block;font-size:13px;font-weight:600;margin:19px 0}.general-video-studio label input,.general-video-studio label textarea,.general-video-studio label>.ui-select{margin-top:9px}.general-video-studio textarea{min-height:90px;resize:vertical;line-height:1.8}.gv-form-row{display:grid;grid-template-columns:1fr 1fr;gap:18px}.gv-form-row label{margin:0}.gv-brief-layout .gv-secondary{margin-left:10px}.gv-brief-aside>h2{margin-top:15px}.gv-brief-aside>p{line-height:1.9;font-size:12px;color:var(--theme-text-secondary)}.gv-script-layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(300px,1fr);gap:22px;align-items:start}.gv-script-panel>header{display:flex;justify-content:space-between;align-items:center;gap:20px}.gv-script-panel header button{margin-left:8px}.gv-script-editor{margin-top:20px;min-height:570px!important;border-color:transparent!important;padding:10px 0!important;font-size:14px!important;line-height:2!important}.gv-agent h2{margin-top:12px}.gv-agent>.gv-primary{width:100%;margin:12px 0}.gv-suggestions{display:flex;flex-direction:column;gap:8px;margin:20px 0}.gv-suggestions button{padding:11px;border:1px solid var(--theme-border-subtle);border-radius:9px;background:var(--theme-bg-elevated);color:var(--theme-text-secondary);font-size:12px;line-height:1.7;text-align:left;cursor:pointer}.gv-agent-response{white-space:pre-wrap;padding:13px;background:var(--theme-accent-soft);border-radius:9px;font-size:12px;line-height:1.85;margin:12px 0}.gv-agent details{font-size:11px;line-height:1.8;margin-top:15px;color:var(--theme-text-secondary);overflow-wrap:anywhere}.gv-shot-head{display:flex;justify-content:space-between;align-items:center;gap:20px}.gv-shots-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px;margin-top:20px}.gv-shots-grid article{padding:18px;border:1px solid var(--theme-border-subtle);border-radius:12px;background:var(--theme-bg-elevated)}.gv-shots-grid span{font-size:11px;color:var(--theme-accent)}.gv-shots-grid h3{font-size:14px;line-height:1.6}.gv-shots-grid p{font-size:12px;line-height:1.85;color:var(--theme-text-secondary);white-space:pre-wrap}.gv-shots-grid small{font-size:11px;color:var(--theme-accent)}.gv-error{padding:12px 15px;border-radius:9px;background:color-mix(in srgb,#dc4d42 8%,var(--theme-bg-card));color:#cf503f;font-size:13px;line-height:1.8}.gv-message{padding:11px 15px;border-radius:9px;background:var(--theme-accent-soft);color:var(--theme-accent);font-size:13px}.gv-empty{padding:70px 20px;text-align:center;color:var(--theme-text-secondary)}.gv-empty p{font-size:13px;margin:18px}.gv-modal-overlay{position:fixed;inset:0;z-index:400;background:#11182766;display:grid;place-items:center;padding:30px}.gv-modal{width:min(780px,94vw);max-height:92vh;display:flex;flex-direction:column;border-radius:20px;background:var(--theme-bg-elevated);overflow:hidden;box-shadow:0 25px 80px #0004}.gv-modal>header{display:flex;justify-content:space-between;align-items:center;padding:25px 30px;border-bottom:1px solid var(--theme-border-subtle)}.gv-modal h2{margin:8px 0 0;font-size:23px}.gv-modal header>button{font-size:26px;border:0;background:transparent;color:var(--theme-text-secondary);cursor:pointer}.gv-modal-body{padding:0 30px 25px;overflow:auto}.gv-modal>footer{padding:19px 30px;display:flex;justify-content:flex-end;gap:12px;border-top:1px solid var(--theme-border-subtle)}.gv-type-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.gv-type-grid button{display:flex;flex-direction:column;gap:8px;text-align:left;padding:13px;border:1px solid var(--theme-border-subtle);border-radius:10px;background:var(--theme-bg-card);color:var(--theme-text-primary);cursor:pointer}.gv-type-grid button.active{border-color:var(--theme-accent);background:var(--theme-accent-soft)}.gv-prod-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important}.gv-type-grid small{font-size:10px;line-height:1.6;color:var(--theme-text-secondary)}@media(max-width:1200px){.gv-project-grid,.gv-shots-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.gv-hub-tools{align-items:flex-start;flex-direction:column}.gv-script-layout{grid-template-columns:minmax(0,1.4fr) 300px}.gv-script-panel>header{align-items:flex-start;flex-direction:column}}@media(max-width:900px){.gv-intro,.gv-brief-layout,.gv-script-layout{grid-template-columns:1fr}.general-video-studio{padding:22px}.gv-project-header{flex-wrap:wrap}.gv-type-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>

<style scoped>
.gv-home{padding:32px 36px 44px;overflow-x:hidden}
.gv-home .gv-hub-head{display:flex;flex-wrap:wrap;gap:20px 28px;min-height:176px;box-sizing:border-box;padding:28px 34px;margin-bottom:22px;border:1px solid var(--theme-border-subtle);border-radius:22px;background:var(--theme-bg-card);box-shadow:0 10px 30px var(--theme-shadow)}
.gv-hub-copy{flex:1;min-width:280px}.gv-hub-title{display:flex;align-items:center;gap:12px;margin:11px 0}.gv-home .gv-hub-head h1{font-size:clamp(30px,3vw,40px);line-height:1.1;margin:0;letter-spacing:-.04em}.gv-hub-title b{padding:4px 10px;border:1px solid var(--theme-border-subtle);border-radius:20px;background:var(--theme-bg-surface);color:var(--theme-text-secondary);font-size:12px;white-space:nowrap}.gv-home .gv-hub-head p{margin:0;line-height:1.8;font-size:12px}.gv-home .gv-eyebrow{display:inline-flex;align-items:center;gap:9px;letter-spacing:.1em}.gv-hub-copy>.gv-eyebrow::before{content:'';width:20px;height:2px;background:var(--theme-accent);border-radius:2px}
.gv-hub-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;min-width:0}.gv-home .gv-hub-search{display:flex;align-items:center;gap:9px;width:220px;height:42px;padding:0 12px;box-sizing:border-box;margin:0;border:1px solid var(--theme-border-subtle);border-radius:10px;background:var(--theme-bg-input,var(--theme-bg-elevated))}.gv-hub-search svg{width:17px;flex:none;fill:none;stroke:var(--theme-text-secondary);stroke-width:1.7}.gv-home .gv-hub-search input{min-width:0;width:100%;border:0;padding:0;margin:0;outline:0;background:transparent;font-size:13px}.gv-home .gv-hub-search:focus-within{border-color:var(--theme-accent)}.gv-home .gv-hub-actions>.gv-primary{height:42px}
.gv-home .gv-hub-tools{display:flex;flex-direction:row;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:18px}.gv-home .gv-hub-tools>.gv-tabs{flex:1;min-width:0;gap:3px}.gv-home .gv-hub-tools .gv-tabs button{padding:9px 11px;font-size:12px;white-space:nowrap}.gv-library-link{display:flex;align-items:center;gap:8px;border:1px solid var(--theme-border-subtle);border-radius:9px;padding:10px 12px;background:var(--theme-bg-card);color:var(--theme-accent);font-size:12px;cursor:pointer;white-space:nowrap}.gv-library-link small{font-size:10px;color:var(--theme-text-secondary)}
.gv-home .gv-project-grid{grid-template-columns:repeat(5,minmax(0,1fr));align-items:stretch;gap:18px}.gv-home .gv-create-card,.gv-home .gv-project-card{box-shadow:0 4px 16px var(--theme-shadow);border-radius:16px;transition:box-shadow .18s,border-color .18s}.gv-home .gv-create-card:hover,.gv-home .gv-project-card:hover{border-color:var(--theme-accent);box-shadow:0 10px 26px var(--theme-shadow)}.gv-home .gv-create-card{display:flex;justify-content:flex-start;gap:0;min-height:0;padding:0;border-style:solid;text-align:center;font:inherit}.gv-create-art,.gv-home .gv-project-art{position:relative;width:100%;aspect-ratio:16/9;box-sizing:border-box;padding:0;overflow:hidden;border-bottom:1px solid var(--theme-border-subtle);background:var(--theme-bg-elevated)}.gv-create-art>.workflow-cover{height:82%}.gv-create-art>strong{position:absolute;bottom:12px;left:0;width:100%;font-size:14px;line-height:1.3;color:var(--theme-text-primary)}.gv-create-info{display:flex;flex:1;min-height:115px;box-sizing:border-box;flex-direction:column;align-items:center;justify-content:space-between;gap:12px;padding:20px 12px 14px}.gv-create-info>strong{font-size:14px}.gv-create-info small{font-size:11px;line-height:1.65;color:var(--theme-text-secondary)}.gv-home .gv-cover-kind{position:absolute;top:10px;left:12px;padding:0 32px 0 0;font-size:10px;letter-spacing:0;opacity:1;color:var(--theme-text-secondary)}.gv-home .gv-project-info{box-sizing:border-box;min-height:115px;padding:14px 16px 12px}.gv-home .gv-project-info h3{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px;line-height:22px}.gv-home .gv-project-info p{height:auto;margin:4px 0 0;font-size:12px;line-height:18px;white-space:nowrap;text-overflow:ellipsis}.gv-home .gv-project-info footer{align-items:center;gap:8px;margin-top:12px;padding-top:10px;border-top:1px solid var(--theme-border-subtle)}.gv-home .gv-project-info time{flex:none;font-size:11px;color:var(--theme-text-secondary)}.gv-home .gv-project-info footer>span{max-width:65%;padding:2px 7px;border:1px solid var(--theme-border-subtle);border-radius:10px;background:var(--theme-bg-surface);color:var(--theme-accent);font-size:10px;font-weight:600;line-height:14px}.gv-home .gv-project-card>.gv-project-delete{top:9px;right:9px;width:28px;height:28px;padding:6px;border-color:var(--theme-border-subtle);background:var(--theme-bg-card);color:var(--theme-text-secondary)}.gv-home .gv-project-delete:hover{color:var(--theme-danger-text);background:var(--theme-danger-soft)}.gv-hub-no-results{grid-column:1/-1;padding:20px 0;margin:0;font-size:13px;color:var(--theme-text-secondary)}.gv-create-card:focus-visible,.gv-project-open-button:focus-visible,.gv-library-link:focus-visible{outline:3px solid var(--theme-accent);outline-offset:-3px}
@media(max-width:1450px){.gv-home .gv-project-grid{grid-template-columns:repeat(4,minmax(0,1fr))}.gv-home .gv-hub-head{padding:24px 28px}}
@media(max-width:1180px){.gv-home .gv-project-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.gv-hub-actions{width:100%}.gv-home .gv-hub-search{width:auto;flex:1}.gv-home .gv-hub-head{min-height:0}.gv-home .gv-hub-tools>.gv-tabs{flex-basis:100%}}
@media(max-width:900px){.gv-home{padding:22px}.gv-home .gv-project-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.gv-home .gv-hub-head{padding:22px;gap:18px}.gv-hub-copy{min-width:0;flex-basis:100%}.gv-home .gv-hub-actions>.gv-primary{font-size:12px;padding:10px 12px}.gv-home .gv-library-link{max-width:100%}}
@media(max-width:600px){.gv-home .gv-project-grid{grid-template-columns:minmax(0,1fr)}.gv-home .gv-hub-actions{flex-direction:column;align-items:stretch}.gv-home .gv-hub-search{flex:none;width:100%}.gv-home .gv-hub-title h1{font-size:28px}}
</style>
