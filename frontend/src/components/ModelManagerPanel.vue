<script setup>
import { waitForDesktopApi } from '../utils/desktopApi.js'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import UiSelect from './UiSelect.vue'

const props = defineProps({ token: { type: String, default: '' } })
const tabs = [
  { key: 'text', label: '文本模型' }, { key: 'image', label: '图片模型' },
  { key: 'video', label: '视频模型' }, { key: 'audio', label: '音频模型' },
]
const modelTypeOptions = tabs.map(tab => ({ value: tab.key, label: tab.label }))
const defaultIcons = {
  text: '<svg viewBox="0 0 24 24"><path d="M4 7V4h16v3M9 21h6M12 4v17"/></svg>',
  image: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>',
  video: '<svg viewBox="0 0 24 24"><path d="m6 4 13 8-13 8V4Z"/></svg>',
  audio: '<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
}
const activeTab = ref('text')
const models = ref([])
const loading = ref(true)
const saving = ref(false)
const showForm = ref(false)
const editingId = ref('')
const iconDragOver = ref(false)
const revealKey = ref(false)
const pendingDeleteId = ref('')
const notice = ref({ type: '', text: '' })
const firstInput = ref(null)
const modelNameFieldRef = ref(null)

function createModelItem(modelName = '', name = '', id = '', contextWindow = '', maxTokens = '') {
  return {
    id: id || '',
    modelName: modelName || '',
    name: name || '',
    contextWindow: contextWindow ?? '',
    maxTokens: maxTokens ?? '',
    _prevModelName: modelName || '',
  }
}

const emptyForm = () => ({
  modelType: activeTab.value,
  provider: '',
  apiUrl: '',
  apiKey: '',
  icon: '',
  sortOrder: 0,
  enabled: true,
  items: [createModelItem()],
})

const form = ref(emptyForm())
const initialItemIds = ref(new Set())
const activeDropdownIdx = ref(null)
const filteredModels = computed(() => models.value.filter(model => model.modelType === activeTab.value))
const typeCounts = computed(() => Object.fromEntries(tabs.map(tab => [tab.key, models.value.filter(model => model.modelType === tab.key).length])))
const providerRows = computed(() => {
  const rows = {}; let lastProvider = null; let startIndex = 0
  for (let index = 0; index <= filteredModels.value.length; index += 1) {
    const provider = index < filteredModels.value.length ? (filteredModels.value[index].provider || '') : null
    if (provider !== lastProvider) {
      if (lastProvider !== null) rows[startIndex] = index - startIndex
      lastProvider = provider; startIndex = index
    }
  }
  return rows
})
const canSave = computed(() => {
  if (saving.value) return false
  if (!form.value.provider.trim()) return false
  if (!form.value.apiUrl.trim()) return false
  if (!form.value.items || form.value.items.length === 0) return false
  const valid = form.value.items.filter(it => it.modelName?.trim())
  return valid.length > 0
})

// --- 从 API 获取模型列表（单表单 & 批量导入）相关状态 ---
const showFetchModal = ref(false)
const fetchingRemote = ref(false)
const remoteModels = ref([])
const remoteSearch = ref('')
const remoteTypeFilter = ref('all')
const fetchForm = ref({ apiUrl: '', apiKey: '', provider: '', defaultType: 'text' })
const selectedRemoteIds = ref(new Set())
const importingBatch = ref(false)

const fetchingFormModels = ref(false)
const formFetchedModels = ref([])
const showModelDropdown = ref(false)
const dropdownFilter = ref('')
const filteredFormFetchedModels = computed(() => {
  if (!dropdownFilter.value.trim()) return formFetchedModels.value
  const q = dropdownFilter.value.trim().toLowerCase()
  return formFetchedModels.value.filter(m =>
    m.id?.toLowerCase().includes(q) || m.name?.toLowerCase().includes(q) || m.owned_by?.toLowerCase().includes(q)
  )
})

function handleDocumentClick(e) {
  if ((showModelDropdown.value || activeDropdownIdx.value !== null) && modelNameFieldRef.value && !modelNameFieldRef.value.contains(e.target)) {
    showModelDropdown.value = false
    activeDropdownIdx.value = null
  }
}

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
})

onUnmounted(() => {
  document.removeEventListener('click', handleDocumentClick)
})

function cleanError(value) { return String(value?.message || value || '未知错误').replace(/^Error:\s*/, '') }
function flash(type, text) {
  notice.value = { type, text }
  window.setTimeout(() => { if (notice.value.text === text) notice.value = { type: '', text: '' } }, 3200)
}
async function request(method, path, body = null) {
  if (!window.pywebview?.api && import.meta.env.DEV && method === 'GET') {
    const response = await fetch(`/local-storage${path}`); const result = await response.json()
    if (!response.ok || result?.code !== 200) throw new Error(result?.message || '读取本地模型失败')
    return result.data
  }
  const api = await waitForDesktopApi()
  if (!api?.backend_request) throw new Error('请从桌面客户端打开模型管理')
  return api.backend_request(method, path, props.token, body)
}
async function loadModels() {
  loading.value = true
  try { const result = await request('GET', '/api/admin/models'); models.value = Array.isArray(result) ? result : [] }
  catch (error) { models.value = []; flash('error', cleanError(error)) }
  finally { loading.value = false }
}
async function copyText(text, label) {
  if (!text) return
  try { await navigator.clipboard.writeText(text); flash('success', `${label}已复制`) } catch { flash('error', '复制失败') }
}
function maskKey(key) { return !key ? '未配置' : key.length <= 8 ? '••••••••' : `${key.slice(0, 4)}••••${key.slice(-4)}` }
function addModelItem(modelName = '', name = '', id = '') {
  form.value.items.push(createModelItem(modelName, name, id))
}

function removeModelItem(idx) {
  if (form.value.items.length <= 1) {
    flash('error', '至少需要保留一个模型')
    return
  }
  form.value.items.splice(idx, 1)
  if (activeDropdownIdx.value === idx) {
    activeDropdownIdx.value = null
  }
}

function onModelNameInput(item) {
  if (!item.name || item.name.trim() === (item._prevModelName || '').trim()) {
    item.name = item.modelName
  }
  item._prevModelName = item.modelName
}

function toggleItemDropdown(idx) {
  if (activeDropdownIdx.value === idx) {
    activeDropdownIdx.value = null
    showModelDropdown.value = false
  } else {
    activeDropdownIdx.value = idx
    showModelDropdown.value = true
  }
}

function selectModelForItem(item, m) {
  item.modelName = m.id
  if (!item.name || item.name.trim() === (item._prevModelName || '').trim()) {
    item.name = m.name || m.id
  }
  item._prevModelName = m.id
  if (!form.value.provider && m.owned_by) {
    form.value.provider = m.owned_by
  }
  // 保持 API 地址与所选工作流严格 1:1 联动更新
  syncUrlWithModel(m.id)
  activeDropdownIdx.value = null
  showModelDropdown.value = false
  flash('success', `已切换工作流：${m.name || m.id}，API 地址已同步更新`)
}

function addAllFetchedModels() {
  if (!formFetchedModels.value.length) return
  const existingNames = new Set(
    form.value.items.map(it => it.modelName?.trim().toLowerCase()).filter(Boolean)
  )

  if (form.value.items.length === 1 && !form.value.items[0].modelName?.trim()) {
    const first = formFetchedModels.value[0]
    form.value.items[0].modelName = first.id
    form.value.items[0].name = first.name || first.id
    form.value.items[0]._prevModelName = first.id
    existingNames.add(first.id.toLowerCase())
  }

  for (const m of formFetchedModels.value) {
    if (existingNames.has(m.id.toLowerCase())) continue
    form.value.items.push(createModelItem(m.id, m.name || m.id))
    existingNames.add(m.id.toLowerCase())
  }

  if (!form.value.provider && formFetchedModels.value[0]?.owned_by) {
    form.value.provider = formFetchedModels.value[0].owned_by
  }
  showModelDropdown.value = false
  activeDropdownIdx.value = null
  flash('success', `已将 ${formFetchedModels.value.length} 个模型全部加入配置列表`)
}

function applyWorkflowPreset(type) {
  if (type === 'autodl') {
    form.value.modelType = 'video'
    form.value.provider = 'AutoDL'
    form.value.apiUrl = 'https://www.autodl.art/api/v1/comfyui/comfyui_workflow/minimax_h3_zm_u24'
    if (!form.value.items || form.value.items.length === 0) form.value.items = [createModelItem()]
    form.value.items[0].modelName = 'minimax_h3_zm_u24'
    form.value.items[0].name = 'H3多图多音频生视频(升级画质)'
    flash('success', '已填入 AutoDL ComfyUI 工作流模版！填入 API Key 后点击【获取模型列表】可查看全套 27 款工作流')
  } else if (type === 'runninghub') {
    form.value.modelType = 'video'
    form.value.provider = 'RunningHub'
    form.value.apiUrl = 'https://www.runninghub.cn/task/openapi/create'
    if (!form.value.items || form.value.items.length === 0) form.value.items = [createModelItem()]
    form.value.items[0].modelName = 'runninghub-video'
    form.value.items[0].name = 'RunningHub 视频生成工作流'
    flash('success', '已填入 RunningHub 工作流模版！请在 API Key 中填入您的 RunningHub 令牌')
  } else if (type === 'liblib') {
    form.value.modelType = 'video'
    form.value.provider = 'LiblibAI'
    form.value.apiUrl = 'https://api.liblib.art/api/v1/generate/comfyui'
    if (!form.value.items || form.value.items.length === 0) form.value.items = [createModelItem()]
    form.value.items[0].modelName = 'liblib-video-workflow'
    form.value.items[0].name = 'LiblibAI 视频工作流'
    flash('success', '已填入 LiblibAI 哩布工作流模版！')
  } else if (type === 'comfyui_local') {
    form.value.modelType = 'video'
    form.value.provider = 'ComfyUI'
    form.value.apiUrl = 'http://127.0.0.1:8188'
    if (!form.value.items || form.value.items.length === 0) form.value.items = [createModelItem()]
    form.value.items[0].modelName = 'comfyui-video'
    form.value.items[0].name = 'ComfyUI 原生工作流'
    flash('success', '已填入 ComfyUI 原生接口模版（端口 8188）！')
  } else if (type === 'custom_workflow') {
    form.value.modelType = 'video'
    form.value.provider = 'CustomWorkflow'
    form.value.apiUrl = 'https://api.example.com/v1/workflow/{modelName}'
    if (!form.value.items || form.value.items.length === 0) form.value.items = [createModelItem()]
    form.value.items[0].modelName = 'custom-workflow-id'
    form.value.items[0].name = '自定义工作流'
    flash('success', '已填入通用自定义工作流模版！可将 API 地址替换为您自建或第三方的接口')
  }
}

function openAdd() {
  editingId.value = ''
  form.value = emptyForm()
  initialItemIds.value = new Set()
  formFetchedModels.value = []
  showModelDropdown.value = false
  activeDropdownIdx.value = null
  revealKey.value = false
  showForm.value = true
  nextTick(() => firstInput.value?.focus())
}

function openEdit(model) {
  editingId.value = String(model.id || '')
  const targetType = model.modelType || activeTab.value
  const normApiUrl = (model.apiUrl || '').trim().replace(/\/+$/, '')
  const targetProvider = (model.provider || '').trim()

  const sameApiModels = models.value.filter(m =>
    (m.modelType || 'text') === targetType &&
    (m.apiUrl || '').trim().replace(/\/+$/, '') === normApiUrl &&
    (m.provider || '').trim() === targetProvider
  )

  let items = []
  if (sameApiModels.length > 0) {
    const current = sameApiModels.find(m => String(m.id) === editingId.value) || model
    const others = sameApiModels.filter(m => String(m.id) !== editingId.value)
    items = [
      createModelItem(current.modelName, current.name, String(current.id), current.contextWindow, current.maxTokens),
      ...others.map(m => createModelItem(m.modelName, m.name, String(m.id), m.contextWindow, m.maxTokens)),
    ]
  } else {
    items = [createModelItem(model.modelName || '', model.name || '', String(model.id || ''), model.contextWindow, model.maxTokens)]
  }

  form.value = {
    modelType: targetType,
    provider: model.provider || '',
    apiUrl: model.apiUrl || '',
    apiKey: model.apiKey || '',
    icon: model.icon || '',
    sortOrder: Number(model.sortOrder || 0),
    enabled: model.enabled !== false,
    items: items,
  }

  initialItemIds.value = new Set(items.map(it => it.id).filter(Boolean))
  formFetchedModels.value = []
  showModelDropdown.value = false
  activeDropdownIdx.value = null
  revealKey.value = false
  showForm.value = true
  nextTick(() => firstInput.value?.focus())
}

function closeForm() {
  showForm.value = false
  editingId.value = ''
  form.value = emptyForm()
  initialItemIds.value = new Set()
  formFetchedModels.value = []
  showModelDropdown.value = false
  activeDropdownIdx.value = null
}

function notifyModelsUpdated() {
  window.dispatchEvent(new CustomEvent('cdtv:models-updated'))
  try {
    window.localStorage.setItem('cdtv_models_updated_at', String(Date.now()))
  } catch (_) {}
}

async function save() {
  if (!canSave.value) return
  saving.value = true

  const validItems = form.value.items
    .filter(it => it.modelName?.trim())
    .map(it => ({
      id: it.id || '',
      modelName: it.modelName.trim(),
      name: it.name?.trim() || it.modelName.trim(),
      contextWindow: it.contextWindow ? Number(it.contextWindow) : null,
      maxTokens: it.maxTokens ? Number(it.maxTokens) : null,
    }))

  if (validItems.length === 0) {
    flash('error', '请至少填写一个模型名')
    saving.value = false
    return
  }

  const cleanApiUrl = form.value.apiUrl.trim().replace(/\/+$/, '')
  const cleanProvider = form.value.provider.trim()
  const cleanApiKey = form.value.apiKey.trim()
  const baseSort = Math.max(0, Number(form.value.sortOrder) || 0)

  try {
    const currentItemIds = new Set(validItems.map(it => it.id).filter(Boolean))
    const toDeleteIds = Array.from(initialItemIds.value).filter(id => !currentItemIds.has(id))
    for (const delId of toDeleteIds) {
      try {
        await request('DELETE', `/api/admin/models/${encodeURIComponent(delId)}`)
      } catch (err) {
        console.warn('删除模型失败:', delId, err)
      }
    }

    let count = 0
    for (let i = 0; i < validItems.length; i++) {
      const it = validItems[i]
      const payload = {
        name: it.name,
        modelName: it.modelName,
        modelType: form.value.modelType,
        provider: cleanProvider,
        apiUrl: cleanApiUrl,
        icon: form.value.icon || '',
        sortOrder: baseSort + i,
        enabled: form.value.enabled,
        contextWindow: it.contextWindow ?? null,
        maxTokens: it.maxTokens ?? null,
      }
      if (cleanApiKey) {
        payload.apiKey = cleanApiKey
      }

      if (it.id) {
        await request('PUT', `/api/admin/models/${encodeURIComponent(it.id)}`, payload)
        count++
      } else {
        payload.apiKey = cleanApiKey
        await request('POST', '/api/admin/models', payload)
        count++
      }
    }

    showForm.value = false
    await loadModels()
    notifyModelsUpdated()
    flash('success', `成功保存 ${count} 个模型配置！`)
  } catch (error) {
    flash('error', `保存失败：${cleanError(error)}`)
  } finally {
    saving.value = false
  }
}
async function copyModel(model) {
  const payload = { ...model, name: `${model.name || '模型'} (副本)` }
  for (const key of ['id', 'revision', 'createTime', 'updateTime']) delete payload[key]
  try { await request('POST', '/api/admin/models', payload); await loadModels(); notifyModelsUpdated(); flash('success', '模型已复制') }
  catch (error) { flash('error', `复制失败：${cleanError(error)}`) }
}
async function toggleModel(model) {
  try { await request('PUT', `/api/admin/models/${encodeURIComponent(model.id)}`, { enabled: !model.enabled }); await loadModels(); notifyModelsUpdated(); flash('success', model.enabled ? '模型已停用' : '模型已启用') }
  catch (error) { flash('error', cleanError(error)) }
}
async function removeModel(model) {
  if (pendingDeleteId.value !== model.id) {
    pendingDeleteId.value = model.id
    window.setTimeout(() => { if (pendingDeleteId.value === model.id) pendingDeleteId.value = '' }, 4000)
    return
  }
  try { await request('DELETE', `/api/admin/models/${encodeURIComponent(model.id)}`); pendingDeleteId.value = ''; await loadModels(); notifyModelsUpdated(); flash('success', '模型已删除') }
  catch (error) { flash('error', `删除失败：${cleanError(error)}`) }
}
async function onIconDrop(event) {
  iconDragOver.value = false
  const file = event.dataTransfer?.files?.[0]; if (!file) return
  const isSvg = file.name.toLowerCase().endsWith('.svg') || file.type === 'image/svg+xml'
  if (!isSvg) { flash('error', '图标仅支持 SVG 文件'); return }
  try {
    form.value.icon = await file.text()
    flash('success', 'SVG 图标已导入')
  } catch { flash('error', '读取图标失败') }
}

// --- 内置常用平台工作流全套字典 ---
const BUILTIN_WORKFLOWS = {
  autodl: [
    { id: 'minimax_h3_zm_u24', name: 'H3多图多音频生视频(升级画质)', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_zm_u30', name: 'H3多图多音频生视频(超清画质)', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_image_audio_to_video_v2_15s', name: 'H3多图多音频生视频15秒', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_lightx2v_v5_15s', name: 'H3多图生视频15秒', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_zm_nono', name: 'H3多图多音频生视频(影视画质)', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_lightx2v_v5', name: 'H3多图参考生视频', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_lightx2v', name: 'H3首尾帧生成视频', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_image_audio_to_video_v2', name: 'H3多图多音频生视频', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_zm_u08', name: 'H3多图多音频生视频(高速版)', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_zm_u22', name: 'H3多图多音频生视频(短剧带货版)', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_lightx2v_no_pic', name: 'H3文生视频', modelType: 'video', owned_by: 'Zealman' },
    { id: 'wan2.2animate-v4-motion_retargeting', name: '动作迁移', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_zm_titim', name: 'H3全自动多角色动迁替换', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_zm_titi', name: 'H3全自动角色动迁替换', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_image_audio_to_video', name: 'H3图生视频-音频同步(自动对口型)', modelType: 'video', owned_by: 'Zealman' },
    { id: 'minimax_h3_801', name: 'H3九图15s(无字幕版)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_802', name: 'H3九图15s(画质增强版)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_803', name: 'H3九图三音15s(画质增强版)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_804', name: 'H3九图15s(多模式版)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_805', name: 'H3九图三音15s(多模式版/6合1)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_z0901', name: 'H3文生视频(高质量创意直出)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_z0902', name: 'H3六图生视频(多图一致性创作)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_z0903', name: 'H3六图三音频生视频(高质量音画融合)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_b99_001', name: 'H3文生视频(MH3高画质)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_b99_002', name: 'H3首尾帧生成视频(MH3高画质)', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'minimax_h3_b99_003_12s', name: 'H3多图生视频12秒', modelType: 'video', owned_by: 'AI资源仓' },
    { id: 'indextts2-v1', name: 'IndexTTS2 语音合成工作流', modelType: 'audio', owned_by: 'AutoDL官方' }
  ],
  runninghub: [
    { id: 'runninghub-video', name: 'RunningHub 官方视频生成工作流', modelType: 'video', owned_by: 'RunningHub' },
    { id: 'runninghub-image', name: 'RunningHub 官方生图工作流', modelType: 'image', owned_by: 'RunningHub' },
    { id: 'runninghub-animate', name: 'RunningHub 动作迁移工作流', modelType: 'video', owned_by: 'RunningHub' },
    { id: 'runninghub-lipsync', name: 'RunningHub 音频同步对口型工作流', modelType: 'video', owned_by: 'RunningHub' },
  ],
  liblib: [
    { id: 'liblib-video-workflow', name: 'LiblibAI ComfyUI 视频生成工作流', modelType: 'video', owned_by: 'LiblibAI' },
    { id: 'liblib-wan2.1', name: 'LiblibAI Wan2.1 电影级生视频', modelType: 'video', owned_by: 'LiblibAI' },
    { id: 'liblib-animatediff', name: 'LiblibAI AnimateDiff 动态生视频', modelType: 'video', owned_by: 'LiblibAI' },
  ],
  comfyui: [
    { id: 'comfyui-video', name: 'ComfyUI 原生文生/图生视频工作流', modelType: 'video', owned_by: 'ComfyUI' },
    { id: 'comfyui-animatediff', name: 'ComfyUI AnimateDiff 视频工作流', modelType: 'video', owned_by: 'ComfyUI' },
    { id: 'comfyui-wan2.1', name: 'ComfyUI Wan2.1 视频工作流', modelType: 'video', owned_by: 'ComfyUI' },
    { id: 'comfyui-hunyuan', name: 'ComfyUI 混元视频生成工作流', modelType: 'video', owned_by: 'ComfyUI' },
  ]
}

function resolveWorkflowFallback(provider, url) {
  const p = (provider || '').toLowerCase()
  const u = (url || '').toLowerCase()
  if (p.includes('autodl') || u.includes('autodl') || u.includes('comfyui_workflow')) {
    return { name: 'AutoDL 官方全套', list: BUILTIN_WORKFLOWS.autodl }
  }
  if (p.includes('runninghub') || u.includes('runninghub')) {
    return { name: 'RunningHub 智绘', list: BUILTIN_WORKFLOWS.runninghub }
  }
  if (p.includes('liblib') || u.includes('liblib')) {
    return { name: 'LiblibAI 哩布', list: BUILTIN_WORKFLOWS.liblib }
  }
  if (p.includes('comfy') || u.includes('8188') || u.includes('6006')) {
    return { name: 'ComfyUI 原生', list: BUILTIN_WORKFLOWS.comfyui }
  }
  return null
}

// --- 单表单快捷获取模型 ---
async function fetchFormModels() {
  const url = form.value.apiUrl.trim()
  if (!url) {
    flash('error', '请先填写 API 地址')
    return
  }
  let keyToSend = form.value.apiKey.trim()
  if (!keyToSend) {
    const saved = models.value.find(m => m.id === editingId.value && m.apiKey)
      || models.value.find(m => m.apiUrl?.trim().replace(/\/+$/, '') === url.replace(/\/+$/, '') && m.apiKey)
    if (saved?.apiKey) {
      keyToSend = saved.apiKey
      form.value.apiKey = saved.apiKey
    }
  }

  fetchingFormModels.value = true
  try {
    const list = await request('POST', '/api/admin/models/fetch-remote', {
      apiUrl: url,
      apiKey: keyToSend,
      modelId: editingId.value || undefined,
      provider: form.value.provider,
      modelType: form.value.modelType,
    })
    formFetchedModels.value = Array.isArray(list) ? list : []
    if (formFetchedModels.value.length > 0) {
      showModelDropdown.value = true
      flash('success', `已获取到 ${formFetchedModels.value.length} 个可用模型`)
    } else {
      flash('error', '未获取到任何模型')
    }
  } catch (error) {
    const fb = resolveWorkflowFallback(form.value.provider, url)
    if (fb) {
      formFetchedModels.value = [...fb.list]
      showModelDropdown.value = true
      flash('success', `已载入 ${fb.name} ${fb.list.length} 个工作流`)
      return
    }
    flash('error', `获取失败：${cleanError(error)}`)
  } finally {
    fetchingFormModels.value = false
  }
}


function onApiUrlInput() {
  const url = (form.value.apiUrl || '').trim()
  if (!url) return
  // 如果输入包含具体工作流 ID（如 AutoDL 的 /comfyui_workflow/{id}）
  const m = url.match(/\/comfyui_workflow\/([^/?#]+)/)
  if (m && m[1]) {
    const wfId = m[1].trim()
    if (!form.value.provider) form.value.provider = 'AutoDL'
    form.value.modelType = 'video'
    const matched = BUILTIN_WORKFLOWS.autodl.find(w => w.id === wfId)
    const displayName = matched ? matched.name : wfId
    if (!form.value.items || form.value.items.length === 0) {
      form.value.items = [createModelItem(wfId, displayName)]
    } else {
      form.value.items[0].modelName = wfId
      if (!form.value.items[0].name || form.value.items[0].name === (form.value.items[0]._prevModelName || '')) {
        form.value.items[0].name = displayName
      }
      form.value.items[0]._prevModelName = wfId
    }
  }
}

function syncUrlWithModel(modelName) {
  if (!modelName || !form.value.apiUrl) return
  // 如果当前是 AutoDL 工作流，联动更新末尾的模型 ID
  if (form.value.apiUrl.includes('/comfyui_workflow/')) {
    form.value.apiUrl = form.value.apiUrl.replace(/\/comfyui_workflow\/[^/?#]+/, `/comfyui_workflow/${modelName}`)
  } else if (form.value.apiUrl.includes('/comfyui_workflow')) {
    form.value.apiUrl = form.value.apiUrl.replace(/\/comfyui_workflow\/?$/, `/comfyui_workflow/${modelName}`)
  }
}

function selectModelFromDropdown(m) {
  const emptyItem = form.value.items.find(it => !it.modelName?.trim())
  if (emptyItem) {
    selectModelForItem(emptyItem, m)
  } else {
    form.value.items.push(createModelItem(m.id, m.name || m.id))
    syncUrlWithModel(m.id)
    flash('success', `已添加工作流 ${m.name || m.id}，API 地址已同步`)
  }
  if (!form.value.provider && m.owned_by) {
    form.value.provider = m.owned_by
  }
  showModelDropdown.value = false
  activeDropdownIdx.value = null
}

// --- 批量获取与添加模型弹窗 ---
function openFetchModal() {
  const recent = filteredModels.value.find(m => m.apiKey)
    || filteredModels.value[0]
    || models.value.find(m => m.apiKey)
    || models.value[0]
  fetchForm.value = {
    apiUrl: recent?.apiUrl || '',
    apiKey: recent?.apiKey || '',
    provider: recent?.provider || '',
    defaultType: activeTab.value,
  }
  remoteModels.value = []
  remoteSearch.value = ''
  remoteTypeFilter.value = 'all'
  selectedRemoteIds.value = new Set()
  showFetchModal.value = true
}

function closeFetchModal() {
  showFetchModal.value = false
  remoteModels.value = []
}

function applyWorkflowPresetToFetch(type) {
  if (type === 'autodl') {
    fetchForm.value.defaultType = 'video'
    fetchForm.value.provider = 'AutoDL'
    fetchForm.value.apiUrl = 'https://www.autodl.art/api/v1/comfyui/comfyui_workflow'
    flash('success', '已填入 AutoDL 模版！点击【查询模型】可一键批量勾选全套 27 款工作流')
  } else if (type === 'runninghub') {
    fetchForm.value.defaultType = 'video'
    fetchForm.value.provider = 'RunningHub'
    fetchForm.value.apiUrl = 'https://www.runninghub.cn/task/openapi/create'
    flash('success', '已填入 RunningHub 模版！点击【查询模型】载入工作流')
  } else if (type === 'liblib') {
    fetchForm.value.defaultType = 'video'
    fetchForm.value.provider = 'LiblibAI'
    fetchForm.value.apiUrl = 'https://api.liblib.art/api/v1/generate/comfyui'
    flash('success', '已填入 LiblibAI 哩布模版！点击【查询模型】载入工作流')
  } else if (type === 'comfyui_local') {
    fetchForm.value.defaultType = 'video'
    fetchForm.value.provider = 'ComfyUI'
    fetchForm.value.apiUrl = 'http://127.0.0.1:8188'
    flash('success', '已填入本地 ComfyUI 模版（端口 8188）！')
  } else if (type === 'custom_workflow') {
    fetchForm.value.defaultType = 'video'
    fetchForm.value.provider = 'CustomWorkflow'
    fetchForm.value.apiUrl = 'https://api.example.com/v1/workflow/{modelName}'
    flash('success', '已填入通用自定义工作流模版！')
  }
}

async function queryRemoteModels() {
  const url = fetchForm.value.apiUrl.trim()
  if (!url) {
    flash('error', '请输入 API 地址')
    return
  }
  let keyToSend = fetchForm.value.apiKey.trim()
  if (!keyToSend) {
    const matched = models.value.find(m => m.apiUrl?.trim().replace(/\/+$/, '') === url.replace(/\/+$/, '') && m.apiKey)
    if (matched?.apiKey) {
      keyToSend = matched.apiKey
      fetchForm.value.apiKey = matched.apiKey
    }
  }
  fetchingRemote.value = true
  try {
    const list = await request('POST', '/api/admin/models/fetch-remote', {
      apiUrl: url,
      apiKey: keyToSend,
      provider: fetchForm.value.provider,
      modelType: fetchForm.value.defaultType,
    })
    const items = Array.isArray(list) ? list : []
    const existingModelKeys = new Set(models.value.map(m => `${m.modelType}:${m.modelName.toLowerCase()}`))

    remoteModels.value = items.map(item => {
      const type = fetchForm.value.defaultType || activeTab.value || 'text'
      const isExisting = existingModelKeys.has(`${type}:${item.id.toLowerCase()}`)
      return {
        id: item.id,
        name: item.name || item.id,
        modelType: type,
        owned_by: item.owned_by || fetchForm.value.provider || '',
        exists: isExisting,
        selected: !isExisting,
      }
    })
    selectedRemoteIds.value = new Set(remoteModels.value.filter(m => m.selected).map(m => m.id))
    if (!fetchForm.value.provider && items[0]?.owned_by) {
      fetchForm.value.provider = items[0].owned_by
    }
    flash('success', `成功获取到 ${items.length} 个模型`)
  } catch (error) {
    const fb = resolveWorkflowFallback(fetchForm.value.provider, url)
    if (fb) {
      const existingModelKeys = new Set(models.value.map(m => `${m.modelType}:${m.modelName.toLowerCase()}`))
      remoteModels.value = fb.list.map(item => {
        const type = item.modelType || fetchForm.value.defaultType || 'video'
        const isExisting = existingModelKeys.has(`${type}:${item.id.toLowerCase()}`)
        return {
          id: item.id,
          name: item.name || item.id,
          modelType: type,
          owned_by: item.owned_by || fb.name,
          exists: isExisting,
          selected: !isExisting,
        }
      })
      selectedRemoteIds.value = new Set(remoteModels.value.filter(m => m.selected).map(m => m.id))
      flash('success', `已载入 ${fb.name} ${fb.list.length} 个工作流`)
      return
    }
    flash('error', `获取失败：${cleanError(error)}`)
  } finally {
    fetchingRemote.value = false
  }
}
const filteredRemoteModels = computed(() => {
  return remoteModels.value.filter(m => {
    if (remoteTypeFilter.value !== 'all' && m.modelType !== remoteTypeFilter.value) return false
    if (remoteSearch.value.trim()) {
      const q = remoteSearch.value.trim().toLowerCase()
      return m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)
    }
    return true
  })
})

function toggleSelectAllRemote() {
  const visible = filteredRemoteModels.value
  const allSelected = visible.length > 0 && visible.every(m => selectedRemoteIds.value.has(m.id))
  if (allSelected) {
    for (const m of visible) selectedRemoteIds.value.delete(m.id)
  } else {
    for (const m of visible) selectedRemoteIds.value.add(m.id)
  }
}

function toggleRemoteSelection(id) {
  if (selectedRemoteIds.value.has(id)) {
    selectedRemoteIds.value.delete(id)
  } else {
    selectedRemoteIds.value.add(id)
  }
}

async function importSelectedModels() {
  const toImport = remoteModels.value.filter(m => selectedRemoteIds.value.has(m.id))
  if (toImport.length === 0) {
    flash('error', '请先勾选需要导入的模型')
    return
  }
  importingBatch.value = true
  const provider = fetchForm.value.provider.trim() || '自定义'
  let apiKey = fetchForm.value.apiKey.trim()
  if (!apiKey) {
    const matched = models.value.find(m => m.apiUrl?.trim().replace(/\/+$/, '') === apiUrl && m.apiKey)
    if (matched?.apiKey) apiKey = matched.apiKey
  }

  const payload = toImport.map((m, idx) => ({
    name: m.name.trim() || m.id,
    modelType: m.modelType || 'text',
    provider: provider,
    apiUrl: apiUrl,
    apiKey: apiKey,
    modelName: m.id.trim(),
    icon: '',
    sortOrder: models.value.length + idx,
    enabled: true,
  }))

  try {
    await request('POST', '/api/admin/models/batch', payload)
    showFetchModal.value = false
    await loadModels()
    notifyModelsUpdated()
    flash('success', `成功导入 ${toImport.length} 个模型！`)
  } catch (error) {
    flash('error', `导入失败：${cleanError(error)}`)
  } finally {
    importingBatch.value = false
  }
}

onMounted(loadModels)
</script>

<template>
  <section class="model-manager" aria-labelledby="model-manager-title">
    <header class="model-manager-head">
      <div>
        <span class="model-manager-kicker">MODEL CONFIGURATION</span>
        <h3 id="model-manager-title">模型管理</h3>
        <p>管理客户端生成服务使用的模型、接口与调用顺序。</p>
      </div>
      <div class="head-actions">
        <button class="fetch-models-button" type="button" @click="openFetchModal">
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
          获取模型列表
        </button>
        <button class="add-model-button" type="button" @click="openAdd">
          <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
          添加模型
        </button>
      </div>
    </header>
    <nav class="model-tabs" role="tablist" aria-label="模型类型">
      <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" :aria-selected="activeTab === tab.key" :class="{ active: activeTab === tab.key }" @click="activeTab = tab.key">{{ tab.label }}<span>{{ typeCounts[tab.key] }}</span></button>
    </nav>
    <div class="model-notice" aria-live="polite"><span v-if="notice.text" :class="notice.type">{{ notice.text }}</span></div>
    <div v-if="loading" class="model-state"><i></i><strong>正在读取模型配置…</strong></div>
    <div v-else-if="!filteredModels.length" class="model-state empty">
      <span v-html="defaultIcons[activeTab]"></span>
      <strong>暂无{{ tabs.find(tab => tab.key === activeTab)?.label }}</strong>
      <small>添加或通过 API 获取后即可在对应的生成页面中选择。</small>
      <div class="empty-actions">
        <button class="fetch-models-button" type="button" @click="openFetchModal">
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
          获取模型列表
        </button>
        <button class="add-model-button" type="button" @click="openAdd">添加模型</button>
      </div>
    </div>
    <div v-else class="model-table-shell">
      <table class="model-table">
        <colgroup>
          <col class="col-icon" /><col class="col-provider" /><col class="col-api" /><col class="col-key" /><col class="col-name" /><col class="col-model-name" /><col class="col-number" /><col class="col-status" /><col class="col-action" />
        </colgroup>
        <thead><tr><th>图标</th><th>供应商</th><th>API 地址</th><th>API Key</th><th>名称</th><th>模型名</th><th>排序</th><th>启用</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="(model, index) in filteredModels" :key="model.id" :class="{ disabled: !model.enabled }">
            <td v-if="index in providerRows" :rowspan="providerRows[index]" class="group-cell icon-column"><span class="model-icon" :class="{ empty: !model.icon, 'is-builtin': !model.icon }" v-html="model.icon || defaultIcons[model.modelType]"></span></td>
            <td v-if="index in providerRows" :rowspan="providerRows[index]" class="group-cell provider-column"><strong>{{ model.provider || '未命名' }}</strong><small>{{ providerRows[index] }} 个模型</small></td>
            <td v-if="index in providerRows" :rowspan="providerRows[index]" class="group-cell api-column"><button class="copy-value url" type="button" :title="model.apiUrl" @click="copyText(model.apiUrl, 'API 地址')">{{ model.apiUrl }}</button></td>
            <td v-if="index in providerRows" :rowspan="providerRows[index]" class="group-cell key-column"><button class="copy-value key" type="button" title="点击复制 API Key" @click="copyText(model.apiKey, 'API Key')">{{ maskKey(model.apiKey) }}</button></td>
            <td class="name-column"><button class="copy-value name" type="button" @click="copyText(model.name, '名称')">{{ model.name }}</button></td>
            <td class="model-name-column">
              <div class="model-code-row">
                <button class="copy-value code" type="button" :title="model.modelName" @click="copyText(model.modelName, '模型名')">{{ model.modelName }}</button>
                <span v-if="model.contextWindow" class="context-pill" :title="'上下文窗口: ' + model.contextWindow + ' tokens'">{{ model.contextWindow >= 1000 ? Math.round(model.contextWindow / 1000) + 'k' : model.contextWindow }}</span>
              </div>
            </td>
            <td class="number-column">{{ model.sortOrder ?? 0 }}</td>
            <td class="status-column"><button class="status-switch" :class="{ on: model.enabled }" type="button" :aria-label="model.enabled ? '停用模型' : '启用模型'" @click="toggleModel(model)"><i></i></button></td>
            <td class="action-column"><div class="row-actions">
              <button type="button" title="编辑" @click="openEdit(model)"><svg viewBox="0 0 24 24"><path d="m4 16.5-.8 4.3 4.3-.8L18.8 8.7l-3.5-3.5L4 16.5Z"/><path d="m13.8 6.7 3.5 3.5"/></svg></button>
              <button type="button" title="复制" @click="copyModel(model)"><svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"/></svg></button>
              <button class="delete" :class="{ confirming: pendingDeleteId === model.id }" type="button" :title="pendingDeleteId === model.id ? '再次点击确认删除' : '删除'" @click="removeModel(model)"><span v-if="pendingDeleteId === model.id">确认</span><svg v-else viewBox="0 0 24 24"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13"/></svg></button>
            </div></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 添加/编辑模型弹窗 -->
    <div v-if="showForm" class="model-form-backdrop" @click.self="closeForm" @keydown.esc="closeForm">
      <form class="model-form" role="dialog" aria-modal="true" aria-labelledby="model-form-title" @submit.prevent="save">
        <header><div><span>{{ editingId ? 'EDIT MODEL' : 'NEW MODEL' }}</span><h3 id="model-form-title">{{ editingId ? '编辑模型' : '添加模型' }}</h3></div><button type="button" aria-label="关闭" @click="closeForm">×</button></header>
        <div class="model-form-body">
          <div class="workflow-preset-bar wide">
            <span>⚡ 工作流快捷预设：</span>
            <button type="button" class="workflow-preset-pill" title="一键填入 AutoDL.Art 27款官方工作流模版" @click="applyWorkflowPreset('autodl')">
              AutoDL 工作流 (27款)
            </button>
            <button type="button" class="workflow-preset-pill" title="一键填入 RunningHub (智绘/润影) 云端工作流模版" @click="applyWorkflowPreset('runninghub')">
              RunningHub (智绘)
            </button>
            <button type="button" class="workflow-preset-pill" title="一键填入 LiblibAI 哩布哩布在线工作流模版" @click="applyWorkflowPreset('liblib')">
              LiblibAI (哩布)
            </button>
            <button type="button" class="workflow-preset-pill" title="仅供本地显卡或内网部署 ComfyUI 的用户使用（端口 8188/6006）" @click="applyWorkflowPreset('comfyui_local')">
              原生 ComfyUI (8188)
            </button>
            <button type="button" class="workflow-preset-pill" title="通用自建工作流接口 (FastAPI/Flask/Dify 等)" @click="applyWorkflowPreset('custom_workflow')">
              通用自定义工作流
            </button>
          </div>
          <label class="model-type-field"><span>类型</span><UiSelect v-model="form.modelType" :options="modelTypeOptions" badge="TYPE" /></label>
          <label><span>供应商 <b>*</b></span><input ref="firstInput" v-model="form.provider" required placeholder="如：runninghub" /></label>
          <label class="wide"><span>API 地址 <b>*</b></span><input v-model="form.apiUrl" @input="onApiUrlInput" required type="url" placeholder="http://127.0.0.1:9000 或 https://api.example.com" /></label>
          <label class="wide"><span>API Key</span><span class="key-input"><input v-model="form.apiKey" :type="revealKey ? 'text' : 'password'" autocomplete="off" :placeholder="editingId ? (form.apiKey ? '已配置 Key（可修改或保留）' : '留空则保留原 Key') : 'sk-... (如无需 Key 可留空)'"/><button type="button" @click="revealKey = !revealKey">{{ revealKey ? '隐藏' : '显示' }}</button></span></label>

          <!-- 核心：多模型自定义加减配置区域 -->
          <div ref="modelNameFieldRef" class="model-items-container wide">
            <div class="model-items-header">
              <div class="items-title-group">
                <span>模型配置列表（已配置 {{ form.items.length }} 个模型）<b>*</b></span>
                <small>针对当前 API 地址自定义增加或减少模型，共享上述 API 地址与凭证</small>
              </div>
              <div class="items-header-actions">
                <button
                  class="inline-fetch-btn"
                  type="button"
                  :disabled="fetchingFormModels || !form.apiUrl.trim()"
                  title="自动连接 API 地址查询可用模型名"
                  @click="fetchFormModels"
                >
                  <i v-if="fetchingFormModels" class="btn-spinner"></i>
                  <svg v-else viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
                  {{ fetchingFormModels ? '查询中…' : '获取模型列表' }}
                </button>
                <button class="add-item-btn" type="button" @click="addModelItem()">
                  <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
                  添加模型
                </button>
              </div>
            </div>

            <!-- 全局从 API 获取的模型下拉浮窗（可一键将全部获取到的模型加入） -->
            <div v-if="showModelDropdown && formFetchedModels.length && activeDropdownIdx === null" class="model-fetched-dropdown" @click.stop>
              <div class="dropdown-header">
                <div style="display:flex;align-items:center;gap:8px;">
                  <span :title="form.apiUrl">工作流列表（选中将自动与上方 API 地址同步联动）({{ formFetchedModels.length }})</span>
                  <input
                    v-if="formFetchedModels.length > 5"
                    v-model="dropdownFilter"
                    class="dropdown-filter-input"
                    placeholder="快速搜索 (如超清、801、15s)..."
                    @click.stop
                  />
                </div>
                <div class="dropdown-header-actions">
                  <button class="add-all-fetched-btn" type="button" title="把获取到的所有模型批量添加到列表中" @click="addAllFetchedModels">
                    ＋ 全部加入
                  </button>
                  <button type="button" @click.stop="showModelDropdown = false">✕</button>
                </div>
              </div>
              <ul class="dropdown-list">
                <li
                  v-for="m in filteredFormFetchedModels"
                  :key="m.id"
                  @click.stop="selectModelFromDropdown(m)"
                >
                  <div style="display:flex;align-items:center;gap:6px;overflow:hidden">
                    <strong class="item-id">{{ m.id }}</strong>
                    <span v-if="m.name && m.name !== m.id" class="item-display-hint">{{ m.name }}</span>
                    <span v-if="m.owned_by" class="item-owner-tag">{{ m.owned_by }}</span>
                  </div>
                  <span class="item-add-tag">点击添加 ＋</span>
                </li>
              </ul>
            </div>

            <div class="model-items-list">
              <div v-for="(item, idx) in form.items" :key="idx" class="model-item-row">
                <div class="item-col model-param-col">
                  <span class="sub-label">模型名（API 参数）<b>*</b></span>
                  <div class="model-name-input-wrapper">
                    <input
                      v-model="item.modelName"
                      required
                      placeholder="如：minimax-all-in-one"
                      @input="onModelNameInput(item)"
                    />
                    <button
                      v-if="formFetchedModels.length"
                      class="dropdown-toggle-btn"
                      type="button"
                      :title="activeDropdownIdx === idx ? '收起列表' : '选择已获取的模型'"
                      @click.stop="toggleItemDropdown(idx)"
                    >
                      <svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>
                    </button>
                  </div>

                  <!-- 针对具体某一行的下拉 -->
                  <div v-if="activeDropdownIdx === idx && formFetchedModels.length" class="model-fetched-dropdown" @click.stop>
                    <div class="dropdown-header">
                      <span>选择填入此行 ({{ formFetchedModels.length }})</span>
                      <button type="button" @click.stop="activeDropdownIdx = null">✕</button>
                    </div>
                    <ul class="dropdown-list">
                      <li
                        v-for="m in filteredFormFetchedModels"
                        :key="m.id"
                        :class="{ active: item.modelName === m.id }"
                        @click.stop="selectModelForItem(item, m)"
                      >
                        <div style="display:flex;align-items:center;gap:6px;overflow:hidden">
                          <strong class="item-id">{{ m.id }}</strong>
                          <span v-if="m.name && m.name !== m.id" class="item-display-hint">{{ m.name }}</span>
                          <span v-if="m.owned_by" class="item-owner-tag">{{ m.owned_by }}</span>
                        </div>
                        <span class="item-type-badge" :class="m.modelType">{{ tabs.find(t => t.key === m.modelType)?.label || m.modelType }}</span>
                      </li>
                    </ul>
                  </div>
                </div>

                <div class="item-col model-display-col">
                  <span class="sub-label">显示名称 <b>*</b></span>
                  <input
                    v-model="item.name"
                    required
                    placeholder="如：minimax h3"
                  />
                </div>

                <div v-if="form.modelType === 'text'" class="item-col model-context-col">
                  <span class="sub-label">上下文窗口</span>
                  <input
                    v-model.number="item.contextWindow"
                    type="number"
                    min="0"
                    placeholder="例如: 128000"
                  />
                </div>

                <div v-if="form.modelType === 'text'" class="item-col model-tokens-col">
                  <span class="sub-label">思考预算 / 最大回复</span>
                  <input
                    v-model.number="item.maxTokens"
                    type="number"
                    min="0"
                    placeholder="例如: 16000"
                  />
                </div>

                <div class="item-col model-action-col">
                  <button
                    class="remove-item-btn"
                    type="button"
                    :disabled="form.items.length <= 1"
                    :title="form.items.length <= 1 ? '至少保留一个模型' : '移除此模型'"
                    @click="removeModelItem(idx)"
                  >
                    <svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <label class="wide"><span>SVG 图标（可选）</span><span class="icon-drop-zone" :class="{ over: iconDragOver }" @dragover.prevent="iconDragOver = true" @dragleave.prevent="iconDragOver = false" @drop.prevent="onIconDrop"><textarea v-model="form.icon" rows="3" placeholder="粘贴你的 SVG 代码，也可将 SVG 文件拖到这里"></textarea><i v-if="form.icon" v-html="form.icon"></i><em v-if="iconDragOver">释放以保存 SVG</em></span></label>
          <div class="form-numbers wide"><label><span>排序</span><input v-model.number="form.sortOrder" type="number" min="0" /></label><label class="enabled-field"><span><strong>启用</strong><small>在生成页面显示</small></span><input v-model="form.enabled" type="checkbox" /></label></div>
        </div>
        <footer><button type="button" @click="closeForm">取消</button><button class="save" type="submit" :disabled="!canSave">{{ saving ? '正在保存…' : '保存' }}</button></footer>
      </form>
    </div>

    <!-- 批量获取与添加模型独立弹窗 -->
    <div v-if="showFetchModal" class="model-form-backdrop" @click.self="closeFetchModal" @keydown.esc="closeFetchModal">
      <div class="fetch-models-modal" role="dialog" aria-modal="true" aria-labelledby="fetch-modal-title">
        <header>
          <div>
            <span>FETCH & IMPORT MODELS</span>
            <h3 id="fetch-modal-title">获取模型列表与批量添加</h3>
          </div>
          <button type="button" aria-label="关闭" @click="closeFetchModal">×</button>
        </header>
        <div class="fetch-modal-body">
          <div class="workflow-preset-bar wide" style="margin-bottom:12px;">
            <span>⚡ 常用工作流一键填入：</span>
            <button type="button" class="workflow-preset-pill" title="一键填入 AutoDL.Art 27款官方工作流" @click="applyWorkflowPresetToFetch('autodl')">
              AutoDL 工作流 (27款)
            </button>
            <button type="button" class="workflow-preset-pill" title="一键填入 RunningHub (智绘) 工作流" @click="applyWorkflowPresetToFetch('runninghub')">
              RunningHub (智绘)
            </button>
            <button type="button" class="workflow-preset-pill" title="一键填入 LiblibAI 哩布工作流" @click="applyWorkflowPresetToFetch('liblib')">
              LiblibAI (哩布)
            </button>
            <button type="button" class="workflow-preset-pill" title="一键填入本地原生 ComfyUI (端口 8188)" @click="applyWorkflowPresetToFetch('comfyui_local')">
              原生 ComfyUI (8188)
            </button>
            <button type="button" class="workflow-preset-pill" title="通用自定义工作流" @click="applyWorkflowPresetToFetch('custom_workflow')">
              自定义工作流
            </button>
          </div>
          <div class="fetch-config-bar">
            <label class="config-item api-url-item">
              <span>API 地址 <b>*</b></span>
              <input v-model="fetchForm.apiUrl" placeholder="如：http://127.0.0.1:8765/v1 或 https://api.openai.com/v1" />
            </label>
            <label class="config-item api-key-item">
              <span>API Key</span>
              <span class="key-input">
                <input v-model="fetchForm.apiKey" :type="revealKey ? 'text' : 'password'" placeholder="sk-... (无密码可留空)" autocomplete="off" />
                <button type="button" @click="revealKey = !revealKey">{{ revealKey ? '隐藏' : '显示' }}</button>
              </span>
            </label>
            <label class="config-item provider-item">
              <span>供应商名称</span>
              <input v-model="fetchForm.provider" placeholder="如：cue / OpenAI / Dola" />
            </label>
            <div class="config-action">
              <button class="query-btn" type="button" :disabled="fetchingRemote || !fetchForm.apiUrl.trim()" @click="queryRemoteModels">
                <i v-if="fetchingRemote" class="btn-spinner"></i>
                <svg v-else viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                {{ fetchingRemote ? '正在查询…' : '查询模型' }}
              </button>
            </div>
          </div>

          <!-- 模型结果列表 -->
          <div v-if="remoteModels.length > 0" class="fetch-results-panel">
            <div class="results-toolbar">
              <div class="results-info">
                <button class="select-all-btn" type="button" @click="toggleSelectAllRemote">
                  {{ filteredRemoteModels.length > 0 && filteredRemoteModels.every(m => selectedRemoteIds.has(m.id)) ? '取消全选' : '全选' }}
                </button>
                <span>已选中 <b>{{ selectedRemoteIds.size }}</b> / {{ remoteModels.length }} 个模型</span>
              </div>
              <div class="results-filter">
                <div class="type-pills">
                  <button type="button" :class="{ active: remoteTypeFilter === 'all' }" @click="remoteTypeFilter = 'all'">全部</button>
                  <button v-for="t in tabs" :key="t.key" type="button" :class="{ active: remoteTypeFilter === t.key }" @click="remoteTypeFilter = t.key">
                    {{ t.label }}
                  </button>
                </div>
                <input v-model="remoteSearch" class="search-input" placeholder="搜索模型 ID…" />
              </div>
            </div>

            <div class="remote-table-wrapper">
              <table class="remote-table">
                <thead>
                  <tr>
                    <th class="col-check"></th>
                    <th class="col-remote-id">模型名 (API 参数)</th>
                    <th class="col-remote-name">显示名称</th>
                    <th class="col-remote-type">类型</th>
                    <th class="col-remote-tag">状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="m in filteredRemoteModels" :key="m.id" :class="{ selected: selectedRemoteIds.has(m.id) }" @click="toggleRemoteSelection(m.id)">
                    <td class="col-check" @click.stop>
                      <input type="checkbox" :checked="selectedRemoteIds.has(m.id)" @change="toggleRemoteSelection(m.id)" />
                    </td>
                    <td class="col-remote-id">
                      <code>{{ m.id }}</code>
                    </td>
                    <td class="col-remote-name" @click.stop>
                      <input v-model="m.name" placeholder="显示名称" />
                    </td>
                    <td class="col-remote-type" @click.stop>
                      <select v-model="m.modelType">
                        <option v-for="t in tabs" :key="t.key" :value="t.key">{{ t.label }}</option>
                      </select>
                    </td>
                    <td class="col-remote-tag">
                      <span v-if="m.exists" class="tag exists">已存在</span>
                      <span v-else class="tag new">新模型</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-else-if="!fetchingRemote" class="fetch-empty-state">
            <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
            <p>输入 API 地址后点击“查询模型”，系统将自动连接接口拉取模型列表，并支持一键批量勾选添加。</p>
          </div>
        </div>
        <footer>
          <button type="button" @click="closeFetchModal">取消</button>
          <button class="save" type="button" :disabled="selectedRemoteIds.size === 0 || importingBatch" @click="importSelectedModels">
            {{ importingBatch ? '正在导入…' : `＋ 导入选中的 ${selectedRemoteIds.size} 个模型` }}
          </button>
        </footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.model-manager{display:grid;min-width:0;gap:12px;color:var(--theme-text-primary)}
.model-manager-head{display:flex;align-items:center;justify-content:space-between;gap:24px}
.model-manager-kicker{color:var(--theme-text-secondary);font:700 9px/1 ui-monospace,Consolas,monospace;letter-spacing:.16em}
.model-manager-head h3{margin:6px 0 3px;font-size:21px}
.model-manager-head p{margin:0;color:var(--theme-text-secondary);font-size:11px}
.head-actions{display:flex;align-items:center;gap:10px}
.fetch-models-button{display:flex;height:38px;align-items:center;gap:7px;padding:0 14px;border:1px solid var(--theme-accent-border);border-radius:9px;color:var(--theme-text-primary);background:var(--theme-accent-soft);cursor:pointer;font-size:12.5px;font-weight:500;transition:.15s}
.fetch-models-button:hover{background:var(--theme-accent-soft);border-color:var(--theme-accent-border);color:var(--theme-text-primary)}
.fetch-models-button svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2}
.add-model-button{display:flex;height:38px;align-items:center;gap:7px;padding:0 14px;border:1px solid var(--theme-accent-border);border-radius:9px;color:var(--theme-text-primary);background:var(--theme-accent-soft);cursor:pointer;font-size:12.5px;font-weight:500;transition:.15s}
.add-model-button:hover{background:var(--theme-accent-soft);border-color:var(--theme-accent-border)}
.add-model-button svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2}
.model-tabs{display:flex;gap:5px;padding-bottom:11px;border-bottom:1px solid var(--theme-border-subtle)}
.model-tabs button{display:flex;height:34px;align-items:center;gap:7px;padding:0 12px;border:1px solid transparent;border-radius:8px;color:var(--theme-text-secondary);background:transparent;font-size:11px;cursor:pointer}
.model-tabs button:hover{color:var(--theme-text-primary);background:var(--theme-bg-card-hover)}
.model-tabs button.active{border-color:var(--theme-border-strong);color:var(--theme-text-primary);background:var(--theme-bg-card-hover)}
.model-tabs span{min-width:18px;padding:2px 5px;border-radius:8px;color:var(--theme-text-secondary);background:var(--theme-bg-elevated);font-size:9px}
.model-notice{min-height:16px;font-size:11px}
.model-notice .success{color:var(--theme-success-text)}
.model-notice .error{color:var(--theme-danger-text)}
.model-table-shell{min-width:0;overflow:auto;border:1px solid var(--theme-border-subtle);border-radius:12px;background:var(--theme-bg-elevated);scrollbar-width:none;-ms-overflow-style:none}
.model-table-shell::-webkit-scrollbar{display:none}
.model-table{width:100%;min-width:1030px;border-collapse:separate;border-spacing:0;font-size:12.5px}
.model-table th{position:sticky;z-index:2;top:0;height:40px;padding:0 12px;border-bottom:1px solid var(--theme-border-subtle);color:var(--theme-text-secondary);background:var(--theme-bg-surface);font-size:11px;letter-spacing:.05em;text-align:left;white-space:nowrap}
.model-table td{height:54px;padding:0 12px;border-bottom:1px solid var(--theme-border-subtle);vertical-align:middle}
.model-table tbody tr:last-child td{border-bottom:0}
.model-table tbody tr:hover td:not(.group-cell){background:var(--theme-bg-card-hover)}
.model-table tr.disabled{opacity:.55}
.group-cell{border-right:1px solid var(--theme-border-subtle);background:var(--theme-bg-surface)}
.icon-column{text-align:center}
.provider-column strong,.provider-column small{display:block;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.provider-column small{margin-top:3px;color:var(--theme-text-secondary);font-size:10px}
.number-column,.status-column{text-align:center}
.col-icon{width:46px}.col-provider{width:120px}.col-api{width:200px}.col-key{width:120px}.col-name{width:140px}.col-model-name{width:160px}.col-number{width:48px}.col-status{width:56px}.col-action{width:110px}
.model-icon{display:inline-grid;width:30px;height:30px;place-items:center;border:1px solid var(--theme-border-subtle);border-radius:8px;color:var(--theme-text-primary);background:var(--theme-bg-surface)}
.model-icon :deep(svg){max-width:20px;max-height:20px}
.model-icon.is-builtin :deep(svg){width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.7}
.model-icon :deep(img){max-width:20px;max-height:20px}
.copy-value{display:block;max-width:100%;overflow:hidden;padding:0;border:0;color:var(--theme-text-secondary);background:none;font:inherit;text-align:left;text-overflow:ellipsis;white-space:nowrap;cursor:pointer}
.copy-value:hover{color:var(--theme-text-primary);text-decoration:underline dotted;text-underline-offset:3px}
.copy-value.url{max-width:100%;color:var(--theme-text-secondary)}
.copy-value.key,.copy-value.code{font-family:ui-monospace,Consolas,monospace}
.copy-value.key{color:var(--theme-text-secondary);font-size:10.5px}
.copy-value.name{color:var(--theme-text-primary);font-weight:650}
.copy-value.code{max-width:145px;color:var(--theme-text-secondary);font-size:11px}
.status-switch{position:relative;width:28px;height:16px;padding:0;border:1px solid var(--theme-border-subtle);border-radius:9px;background:var(--theme-bg-surface);cursor:pointer}
.status-switch i{position:absolute;top:3px;left:3px;width:8px;height:8px;border-radius:50%;background:var(--theme-bg-elevated);transition:.15s}
.status-switch.on{border-color:var(--theme-success-border);background:var(--theme-success-soft)}
.status-switch.on i{left:15px;background:var(--theme-success-soft);box-shadow:0 0 7px var(--theme-shadow)}
.row-actions{display:flex;gap:3px}
.row-actions button{display:grid;min-width:28px;height:28px;place-items:center;padding:0 6px;border:1px solid transparent;border-radius:7px;color:var(--theme-text-secondary);background:transparent;cursor:pointer}
.row-actions button:hover{border-color:var(--theme-border-subtle);color:var(--theme-text-primary);background:var(--theme-bg-card-hover)}
.row-actions button.delete:hover,.row-actions button.confirming{border-color:var(--theme-danger-border);color:var(--theme-danger-text);background:var(--theme-danger-soft)}
.row-actions svg{width:14px;fill:none;stroke:currentColor;stroke-width:1.7}
.row-actions span{font-size:9px}
.model-state{display:grid;min-height:230px;place-items:center;align-content:center;gap:9px;border:1px dashed var(--theme-border-subtle);border-radius:12px;color:var(--theme-text-secondary);background:var(--theme-bg-elevated)}
.model-state>i{width:21px;height:21px;border:2px solid var(--theme-border-subtle);border-top-color:var(--theme-border-subtle);border-radius:50%;animation:spin .8s linear infinite}
.model-state.empty>span{display:grid;width:42px;height:42px;place-items:center;border-radius:11px;color:var(--theme-text-primary);background:var(--theme-bg-surface)}
.model-state.empty>span :deep(svg){width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.7}
.model-state small{color:var(--theme-text-secondary)}
.empty-actions{display:flex;gap:10px;margin-top:4px}
.model-form-backdrop{position:fixed;z-index:140;inset:0;display:grid;place-items:center;padding:22px;background:var(--theme-overlay);backdrop-filter:blur(8px)}
.model-form{width:min(720px,calc(100vw - 44px));max-height:calc(100vh - 44px);overflow:auto;border:1px solid var(--theme-border-subtle);border-radius:16px;background:var(--theme-bg-elevated);box-shadow:0 35px 100px var(--theme-shadow);scrollbar-width:none;-ms-overflow-style:none}
.model-form::-webkit-scrollbar{display:none}
.model-form>header{display:flex;align-items:center;justify-content:space-between;padding:20px 22px 16px;border-bottom:1px solid var(--theme-border-subtle)}
.model-form>header span{color:var(--theme-text-secondary);font:700 10px/1 ui-monospace,monospace;letter-spacing:.15em}
.model-form>header h3{margin:6px 0 0;font-size:21px}
.model-form>header button{width:34px;height:34px;border:0;border-radius:9px;color:var(--theme-text-secondary);background:var(--theme-bg-surface);font-size:21px;line-height:1;cursor:pointer}
.model-form>header button:hover{color:var(--theme-text-primary);background:var(--theme-bg-card-hover)}
.model-form-body{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;padding:20px 22px}
.model-form label, .model-form .form-field{display:grid;gap:6px;color:var(--theme-text-secondary);font-size:12px}
.model-form label>span:first-child b, .model-form .form-field>span:first-child b{color:var(--theme-danger-text)}
.model-form .wide{grid-column:1/-1}
.model-form input,.model-form select,.model-form textarea{box-sizing:border-box;width:100%;border:1px solid var(--theme-border-subtle);border-radius:9px;outline:0;color:var(--theme-text-primary);background:var(--theme-bg-input);font:inherit;font-size:12.5px}
.model-form input,.model-form select{height:40px;padding:0 11px}
.model-form textarea{min-height:70px;padding:9px 11px;resize:vertical;font-family:ui-monospace,Consolas,monospace;font-size:12px}
.model-form input::placeholder,.model-form textarea::placeholder{color:var(--theme-text-secondary)}
.model-form input:focus,.model-form select:focus,.model-form textarea:focus{border-color:var(--theme-accent-border);box-shadow:0 0 0 3px var(--theme-shadow)}
.key-input{display:flex}
.key-input input{border-radius:9px 0 0 9px}
.key-input button{width:60px;border:1px solid var(--theme-border-subtle);border-left:0;border-radius:0 9px 9px 0;color:var(--theme-text-secondary);background:var(--theme-bg-input);font-size:12px;cursor:pointer}
.icon-drop-zone{position:relative;display:grid;grid-template-columns:minmax(0,1fr) 44px;gap:8px}
.icon-drop-zone>i{display:grid;height:100%;place-items:center;overflow:hidden;border:1px solid var(--theme-border-subtle);border-radius:9px;color:var(--theme-text-primary);background:var(--theme-bg-surface);font-style:normal}
.icon-drop-zone>i :deep(svg){width:22px;height:22px}
.icon-drop-zone>i :deep(img){max-width:26px;max-height:26px}
.icon-drop-zone>em{position:absolute;inset:0;display:grid;place-items:center;border:1px solid var(--theme-accent-border);border-radius:9px;color:var(--theme-text-primary);background:var(--theme-bg-surface);font-style:normal}
.form-numbers{display:grid;grid-template-columns:1fr 1.2fr;align-items:end;gap:12px}
.enabled-field{display:flex!important;height:40px;box-sizing:border-box;align-items:center;justify-content:space-between;padding:0 11px;border:1px solid var(--theme-border-subtle);border-radius:9px;background:var(--theme-bg-surface)}
.enabled-field>span{display:grid;gap:1px}
.enabled-field small{color:var(--theme-text-secondary);font-size:10px}
.enabled-field input{width:16px;height:16px;accent-color:var(--theme-accent)}
.model-form>footer{display:flex;justify-content:flex-end;gap:9px;padding:0 22px 20px}
.model-form>footer button{min-width:82px;height:38px;padding:0 16px;border:1px solid var(--theme-border-subtle);border-radius:9px;color:var(--theme-text-secondary);background:var(--theme-bg-surface);font-size:12.5px;cursor:pointer}
.model-form>footer button:hover{color:var(--theme-text-primary);background:var(--theme-bg-card-hover)}
.model-form>footer .save{border-color:var(--theme-accent-border);color:var(--theme-text-primary);background:var(--theme-accent-soft)}
.model-form>footer .save:hover:not(:disabled){background:var(--theme-accent-soft)}
.model-form>footer .save:disabled{cursor:not-allowed;opacity:.45}

/* 自定义多模型项配置样式 */
.model-items-container{display:grid;gap:10px;padding:14px;border:1px solid var(--theme-border-subtle);border-radius:12px;background:var(--theme-bg-elevated);position:relative}
.model-items-header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.items-title-group{display:grid;gap:3px}
.items-title-group span{color:var(--theme-text-primary);font-size:12.5px;font-weight:600}
.items-title-group small{color:var(--theme-text-secondary);font-size:11px}
.items-header-actions{display:flex;align-items:center;gap:8px}
.add-item-btn{display:inline-flex;align-items:center;gap:5px;height:30px;padding:0 11px;border:1px solid var(--theme-accent-border);border-radius:7px;color:var(--theme-text-primary);background:var(--theme-accent-soft);font-size:11.5px;font-weight:500;cursor:pointer;transition:.15s}
.add-item-btn:hover{background:var(--theme-accent-soft);border-color:var(--theme-accent-border)}
.add-item-btn svg{width:13px;height:13px;fill:none;stroke:currentColor;stroke-width:2.2}

.model-items-list{display:grid;gap:9px;max-height:280px;overflow-y:auto;padding-right:2px}
.model-item-row{display:flex;align-items:flex-end;gap:10px;padding:10px 12px;border:1px solid var(--theme-border-subtle);border-radius:9px;background:var(--theme-bg-elevated);position:relative}
.item-col{display:grid;gap:5px}
.sub-label{color:var(--theme-text-secondary);font-size:11px;font-weight:500}
.sub-label b{color:var(--theme-danger-text)}
.model-param-col{flex:1.2;position:relative}
.model-display-col{flex:1}
.model-context-col{flex:0.85;min-width:115px}
.model-tokens-col{flex:0.85;min-width:115px}
.context-pill{display:inline-block;padding:1px 6px;border-radius:4px;background:var(--theme-accent-soft);color:var(--theme-accent-text);font-size:10px;font-family:ui-monospace,Consolas,monospace;margin-left:6px;border:1px solid var(--theme-accent-border)}
.model-code-row{display:flex;align-items:center}
.model-action-col{display:flex;align-items:flex-end}
.remove-item-btn{display:grid;place-items:center;width:38px;height:38px;border:1px solid var(--theme-border-subtle);border-radius:8px;color:var(--theme-danger-text);background:var(--theme-bg-surface);cursor:pointer;transition:.15s}
.remove-item-btn:hover:not(:disabled){background:var(--theme-danger-soft);border-color:var(--theme-danger-border);color:var(--theme-danger-text)}
.remove-item-btn:disabled{opacity:.35;cursor:not-allowed;border-color:var(--theme-border-subtle);background:var(--theme-bg-surface);color:var(--theme-text-secondary)}
.remove-item-btn svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:2}

.item-add-tag{font-size:11px;color:var(--theme-accent-text);padding:1px 6px;border-radius:4px;background:var(--theme-accent-soft)}
.dropdown-header-actions{display:flex;align-items:center;gap:8px}
.add-all-fetched-btn{border:1px solid var(--theme-accent-border);border-radius:5px;background:var(--theme-accent-soft);color:var(--theme-accent-text);font-size:10.5px;padding:2px 7px;cursor:pointer;transition:.15s}
.add-all-fetched-btn:hover{background:var(--theme-accent-soft);color:var(--theme-text-primary)}

/* 单表单获取模型扩展样式 */
.label-with-action{display:flex;align-items:center;justify-content:space-between}
.inline-fetch-btn{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border:1px solid var(--theme-accent-border);border-radius:6px;background:var(--theme-accent-soft);color:var(--theme-accent-text);font-size:11px;cursor:pointer;transition:.15s}
.inline-fetch-btn:hover:not(:disabled){background:var(--theme-accent-soft);color:var(--theme-text-primary);border-color:var(--theme-accent-border)}
.inline-fetch-btn:disabled{opacity:.5;cursor:not-allowed}
.inline-fetch-btn svg{width:12px;height:12px;fill:none;stroke:currentColor;stroke-width:2}
.model-name-field{position:relative}
.model-name-input-wrapper{position:relative;display:flex}
.dropdown-toggle-btn{position:absolute;right:4px;top:4px;bottom:4px;width:32px;display:grid;place-items:center;border:0;border-radius:6px;background:transparent;color:var(--theme-text-secondary);cursor:pointer}
.dropdown-toggle-btn:hover{background:var(--theme-bg-card-hover);color:var(--theme-text-primary)}
.dropdown-toggle-btn svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:2}
.model-fetched-dropdown{position:absolute;z-index:20;top:calc(100% + 4px);left:0;right:0;max-height:220px;overflow:auto;border:1px solid var(--theme-border-subtle);border-radius:10px;background:var(--theme-bg-surface);box-shadow:0 12px 30px var(--theme-shadow)}
.dropdown-header{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid var(--theme-border-subtle);color:var(--theme-text-secondary);font-size:11px}
.dropdown-header button{border:0;background:transparent;color:var(--theme-text-secondary);font-size:12px;cursor:pointer}
.dropdown-list{margin:0;padding:4px;list-style:none}
.dropdown-list li{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;border-radius:7px;color:var(--theme-text-primary);font-size:12px;cursor:pointer;transition:.12s}
.dropdown-list li:hover,.dropdown-list li.active{background:var(--theme-bg-card-hover);color:var(--theme-text-primary)}
.dropdown-list .item-id{font-family:ui-monospace,Consolas,monospace;font-size:12px}
.dropdown-filter-input{padding:3px 8px;border:1px solid var(--theme-border-subtle);border-radius:6px;background:var(--theme-bg-elevated);color:var(--theme-text-primary);font-size:11px;outline:none;width:170px}
.item-owner-tag{font-size:10px;padding:1px 5px;border-radius:4px;background:var(--theme-accent-soft);color:var(--theme-accent-text);white-space:nowrap}
.item-display-hint{font-size:11px;color:var(--theme-text-secondary);max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item-type-badge{padding:1px 6px;border-radius:5px;font-size:10px;background:var(--theme-bg-surface);color:var(--theme-text-secondary)}
.item-type-badge.image{background:var(--theme-bg-surface);color:var(--theme-success-text)}
.item-type-badge.video{background:var(--theme-bg-surface);color:var(--theme-accent-text)}
.item-type-badge.audio{background:var(--theme-bg-surface);color:var(--theme-accent-text)}
.item-type-badge.text{background:var(--theme-accent-soft);color:var(--theme-accent-text)}

/* 批量获取弹窗样式 */
.fetch-models-modal{width:min(820px,calc(100vw - 44px));max-height:calc(100vh - 44px);overflow:hidden;display:flex;flex-direction:column;border:1px solid var(--theme-border-subtle);border-radius:16px;background:var(--theme-bg-elevated);box-shadow:0 35px 100px var(--theme-shadow)}
.fetch-models-modal>header{display:flex;align-items:center;justify-content:space-between;padding:20px 22px 16px;border-bottom:1px solid var(--theme-border-subtle)}
.fetch-models-modal>header span{color:var(--theme-text-secondary);font:700 10px/1 ui-monospace,monospace;letter-spacing:.15em}
.fetch-models-modal>header h3{margin:6px 0 0;font-size:21px}
.fetch-models-modal>header button{width:34px;height:34px;border:0;border-radius:9px;color:var(--theme-text-secondary);background:var(--theme-bg-surface);font-size:21px;line-height:1;cursor:pointer}
.fetch-modal-body{padding:20px 22px;overflow:auto;display:grid;gap:16px;flex:1}
.fetch-config-bar{display:grid;grid-template-columns:1.8fr 1.2fr 1fr auto;gap:12px;align-items:end;padding:14px;border:1px solid var(--theme-border-subtle);border-radius:12px;background:var(--theme-bg-elevated)}
.config-item{display:grid;gap:6px;color:var(--theme-text-secondary);font-size:12px}
.config-item input{box-sizing:border-box;width:100%;height:38px;padding:0 10px;border:1px solid var(--theme-border-subtle);border-radius:8px;outline:0;color:var(--theme-text-primary);background:var(--theme-bg-input);font:inherit;font-size:12px}
.config-action{height:38px}
.query-btn{display:flex;height:38px;align-items:center;gap:6px;padding:0 16px;border:1px solid var(--theme-accent-border);border-radius:8px;color:var(--theme-text-primary);background:var(--theme-accent-soft);cursor:pointer;font-size:12.5px;font-weight:600;white-space:nowrap;transition:.15s}
.query-btn:hover:not(:disabled){background:var(--theme-accent-soft);border-color:var(--theme-accent-border)}
.query-btn:disabled{opacity:.5;cursor:not-allowed}
.query-btn svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:2.2}

.fetch-results-panel{display:grid;gap:10px;border:1px solid var(--theme-border-subtle);border-radius:12px;background:var(--theme-bg-elevated);padding:14px}
.results-toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.results-info{display:flex;align-items:center;gap:12px;font-size:12px;color:var(--theme-text-secondary)}
.results-info b{color:var(--theme-success-text)}
.select-all-btn{padding:4px 10px;border:1px solid var(--theme-border-subtle);border-radius:6px;background:var(--theme-bg-input);color:var(--theme-text-primary);font-size:11.5px;cursor:pointer}
.select-all-btn:hover{background:var(--theme-bg-card-hover);color:var(--theme-text-primary)}
.results-filter{display:flex;align-items:center;gap:10px}
.type-pills{display:flex;gap:3px;border:1px solid var(--theme-border-subtle);border-radius:7px;padding:2px;background:var(--theme-bg-elevated)}
.type-pills button{padding:3px 8px;border:0;border-radius:5px;background:transparent;color:var(--theme-text-secondary);font-size:11px;cursor:pointer}
.type-pills button.active{background:var(--theme-bg-card-hover);color:var(--theme-text-primary)}
.search-input{width:140px;height:28px;padding:0 8px;border:1px solid var(--theme-border-subtle);border-radius:6px;background:var(--theme-bg-input);color:var(--theme-text-primary);font-size:11.5px;outline:0}
.search-input:focus{border-color:var(--theme-border-strong)}

.remote-table-wrapper{max-height:300px;overflow:auto;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-elevated)}
.remote-table{width:100%;border-collapse:separate;border-spacing:0;font-size:12px}
.remote-table th{position:sticky;top:0;z-index:2;height:34px;padding:0 10px;border-bottom:1px solid var(--theme-border-subtle);background:var(--theme-bg-surface);color:var(--theme-text-secondary);text-align:left;font-size:11px}
.remote-table td{height:42px;padding:0 10px;border-bottom:1px solid var(--theme-border-subtle);color:var(--theme-text-primary)}
.remote-table tbody tr:hover{background:var(--theme-bg-card-hover)}
.remote-table tbody tr.selected{background:var(--theme-bg-card-hover)}
.col-check{width:36px;text-align:center}
.col-remote-id{width:220px}
.col-remote-id code{color:var(--theme-accent-text);font-family:ui-monospace,Consolas,monospace;font-size:12px}
.col-remote-name input{width:100%;box-sizing:border-box;height:28px;padding:0 8px;border:1px solid var(--theme-border-subtle);border-radius:5px;background:var(--theme-bg-input);color:var(--theme-text-primary);font-size:12px}
.col-remote-type{width:120px}
.col-remote-type select{width:100%;box-sizing:border-box;height:28px;padding:0 6px;border:1px solid var(--theme-border-subtle);border-radius:5px;background:var(--theme-bg-input);color:var(--theme-text-primary);font-size:11.5px}
.col-remote-tag{width:70px;text-align:center}
.tag{display:inline-block;padding:2px 6px;border-radius:4px;font-size:10.5px}
.tag.new{background:var(--theme-success-soft);color:var(--theme-success-text)}
.tag.exists{background:var(--theme-bg-surface);color:var(--theme-danger-text)}

.fetch-empty-state{display:grid;min-height:180px;place-items:center;align-content:center;gap:10px;border:1px dashed var(--theme-border-subtle);border-radius:12px;color:var(--theme-text-secondary);text-align:center;padding:20px}
.fetch-empty-state svg{width:32px;height:32px;fill:none;stroke:var(--theme-text-primary);stroke-width:1.5}
.fetch-empty-state p{margin:0;font-size:12.5px;max-width:380px;line-height:1.6}

.fetch-models-modal>footer{display:flex;justify-content:flex-end;gap:10px;padding:16px 22px;border-top:1px solid var(--theme-border-subtle);background:var(--theme-bg-elevated)}
.fetch-models-modal>footer button{min-width:82px;height:38px;padding:0 16px;border:1px solid var(--theme-border-subtle);border-radius:9px;color:var(--theme-text-secondary);background:var(--theme-bg-surface);font-size:12.5px;cursor:pointer}
.fetch-models-modal>footer button:hover{color:var(--theme-text-primary);background:var(--theme-bg-card-hover)}
.fetch-models-modal>footer .save{border-color:var(--theme-accent-border);color:var(--theme-text-primary);background:var(--theme-accent-soft)}
.fetch-models-modal>footer .save:hover:not(:disabled){background:var(--theme-accent-soft)}
.fetch-models-modal>footer .save:disabled{cursor:not-allowed;opacity:.45}

.btn-spinner{display:inline-block;width:12px;height:12px;border:2px solid var(--theme-border-subtle);border-top-color:var(--theme-border-subtle);border-radius:50%;animation:spin .8s linear infinite}

@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:760px){
  .model-manager-head{align-items:flex-start}
  .model-tabs{overflow:auto}
  .model-form-body{grid-template-columns:1fr}
  .model-form .wide{grid-column:auto}
  .form-numbers{grid-template-columns:1fr 1fr}
  .enabled-field{grid-column:1/-1}
  .fetch-config-bar{grid-template-columns:1fr}
}
.model-table{min-width:900px;table-layout:fixed}
.api-column{min-width:0;overflow:hidden}
.copy-value.url{display:block;width:100%;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.model-icon.empty::after{color:var(--theme-text-secondary);font-size:12px;content:'—'}
.workflow-preset-bar{display:flex;align-items:center;flex-wrap:wrap;gap:8px;padding:8px 12px;background:var(--theme-bg-surface);border:1px dashed var(--theme-accent, #1976d2);border-radius:9px;font-size:12px;margin-bottom:6px}
.workflow-preset-bar>span{color:var(--theme-accent, #1976d2);font-weight:600}
.workflow-preset-pill{border:1px solid var(--theme-border-subtle);background:var(--theme-bg-elevated);border-radius:6px;padding:4px 9px;font-size:11.5px;color:var(--theme-text-primary);cursor:pointer;transition:all .2s ease}
.workflow-preset-pill:hover{border-color:var(--theme-accent);color:var(--theme-accent);background:var(--theme-accent-soft, rgba(25,118,210,.08))}
.model-type-field{position:relative;z-index:4}
.model-type-field :deep(.ui-select-trigger){min-height:40px;border-radius:9px;background:var(--theme-bg-input)}
.model-type-field :deep(.ui-select-value){font-size:12.5px;font-weight:500}
.model-type-field :deep(.ui-select-menu){z-index:150}
</style>
