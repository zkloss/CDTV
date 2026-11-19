<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import UiSelect from './components/UiSelect.vue'
import WorkspaceLibraries from './components/WorkspaceLibraries.vue'
import GeneralVideoStudio from './components/GeneralVideoStudio.vue'
import DirectVideoStudio from './components/DirectVideoStudio.vue'
import { projectWorkspace } from './utils/projectWorkspace.js'
import ProjectDetail from './components/ProjectDetail.vue'
import VideoCreationWorkspace from './components/VideoCreationWorkspace.vue'
import CreationDataWorkspace from './components/CreationDataWorkspace.vue'
import ProjectCreationAgent from './components/ProjectCreationAgent.vue'
import VideoEditorWorkspace from './components/VideoEditorWorkspace.vue'
import AIToolboxWorkspace from './components/AIToolboxWorkspace.vue'
import BaseLoadingState from './components/BaseLoadingState.vue'
import ModelManagerPanel from './components/ModelManagerPanel.vue'
import ProjectFileTree from './components/ProjectFileTree.vue'
import { waitForDesktopApi, desktopBackendRequest, isApiAvailable } from './utils/desktopApi.js'

const image = ref(null)
const prompt = ref('让画面中的主体自然移动，镜头缓慢推进，光影柔和，细节清晰。')
const ratio = ref('自动')
const duration = ref(10)
const model = ref('Seedance 2.0 Fast')
const generationProjects = ref([])
const selectedProjectId = ref('')
const task = ref(null)
const error = ref('')
const appInfo = ref(null)
const accounts = ref([])
let accountStatusTimer = null
const selectedAccountId = ref('')
let accountSelectionReady = false
const showSettings = ref(false)
const showProjectFiles = ref(false)
const settingsTab = ref('models')
const newAccountNames = reactive({})
const creatingAccount = ref(false)
const accountSearch = ref('')
const accountPlatformFilter = ref('all')
const accountStatusFilter = ref('all')
const platformPanelOpen = ref(false)
const accountStatusOptions = [
  { value: 'available', label: '可用' },
  { value: 'pending', label: '待登录' },
  { value: 'expired', label: '登录过期' },
  { value: 'running', label: '运行中' },
  { value: 'exhausted', label: '额度耗尽' },
]
const accountTypeOptions = [
  { label: 'OriginaDoubao', value: 'doubao' },
  { label: 'Dola', value: 'dola' },
]
const accountPlatformFilterOptions = [
  { label: '全部平台', value: 'all' },
  ...accountTypeOptions,
]
const accountStatusFilterOptions = [
  { label: '全部状态', value: 'all' },
  ...accountStatusOptions,
]

function accountTypeLabel(account) {
  return accountTypeOptions.find(option => option.value === (account?.accountType || 'doubao'))?.label || '未知类型'
}
const accountMessage = ref('')
const openingAccountId = ref('')
const completingAccountId = ref('')
const settings = ref({ defaultAccountId: '', storageDir: '', autoDownload: true, dailyVideoQuota: 3, dolaDailyVideoQuota: 4 })
const settingsMessage = ref('')
// 存储目录结构详情默认隐藏，点击后展开。
const showStorageStructure = ref(false)
// 项目存储目录内的固定子目录 / 文件，与 local_storage.py、constants.py 保持一致。
const storageStructure = [
  { path: 'storage.db', desc: 'SQLite 数据库，存放项目、章节、素材、视频任务、模型、提示词与额度等记录' },
  { path: 'files/', desc: '文件桶根目录（各桶下按 files/<bucket>/<id>/content.bin 存放）' },
  { path: 'files/assets/', desc: '素材库上传的图片 / 音频 / 视频' },
  { path: 'files/generated-images/', desc: 'AI 生成的图片（关键帧等）' },
  { path: 'files/generated-videos/', desc: 'AI 生成的视频' },
  { path: 'files/generated-audio/', desc: '音色试听与生成的音频' },
  { path: 'files/files/', desc: '通用文件桶（上传未指定 bucket 时的默认位置）' },
  { path: 'files/<自定义 bucket>/', desc: '上传接口 bucket 字段指定的任意文件桶' },
  { path: 'output/', desc: '视频输出目录，成片结果保存在此' },
]
const editingAccountId = ref('')
const editingAccountName = ref('')
const renamingAccountId = ref('')
const deletingAccountId = ref('')
const accountStateAction = ref('')
const draggingAccountId = ref('')
const dragOverAccountId = ref('')
const accountOrderSaving = ref(false)
// 单账号粒度的校验状态：{ [id]: { status: 'checking'|'ok'|'expired'|'failed', message, detail, at } }
// status 不含 idle——没记录过就是没校验过，避免与账号本身状态混淆。
const accountVerifyState = ref({})
// 正在校验中的账号 id 集合，用于禁用对应行按钮（不阻塞其他账号操作）。
const accountVerifyingIds = ref(new Set())
// 批量校验整体进度：{ running, total, done, ok, expired, failed, cancelled }
const accountVerifyBatch = ref(null)
// 当前展开详情的账号 id（点击 chip 切换）。
const accountVerifyDetailId = ref('')
const accountToDelete = ref(null)
const checkedAccountIds = ref([])
let accountListRequest = 0
const accountDeleteProgress = ref('')
const isWindowMaximized = ref(false)
const activeMenu = ref('projects')
const generalProjectId = ref('')
const generalProductionContext = ref(null)
const generalNavigationKey = ref(0)
const generalCreateRequested = ref(0)
const newProjectChooser = ref(false)
const activeProjectId = ref('')
const dramaProductionContext = ref(null)
const agentProjectId = ref('')
const creationDataToImport = ref(null)
const sidebarCollapsed = ref(false)
const platformUser = ref({ username: 'local', nickname: '本地工作区' })
const authToken = ref('local-storage')
const authChecking = ref(true)
const authLoading = ref(false)
const authError = ref('')
let pollTimer = null

// 全局生成任务悬浮窗：任务由后端任务表统一管理，这里只轮询展示，
// 因此切换任意菜单都能看到正在进行的生成任务。
const globalTasks = ref([])
const taskDockCollapsed = ref(false)
const taskNowTick = ref(Date.now())
let globalTaskTimer = null
let taskNowTickTimer = null
const ACTIVE_TASK_STATUSES = new Set(['queued', 'pending', 'preparing', 'opening', 'configuring', 'uploading', 'submitting', 'generating', 'processing', 'running', 'sharing', 'downloading', 'finalizing', 'returning_to_conversation', 'confirming_authorization', 'waiting_confirmation'])
const RECENT_TASK_TTL = 10000
const TASK_STATUS_LABELS = {
  queued: '排队中', pending: '排队中', preparing: '准备中', opening: '准备中', configuring: '配置中',
  uploading: '上传中', submitting: '提交中', generating: '生成中', processing: '处理中', running: '进行中',
  sharing: '读取中', downloading: '保存中', finalizing: '收尾中',
  returning_to_conversation: '生成中', confirming_authorization: '安全确认', waiting_confirmation: '等待确认',
  succeeded: '已完成', failed: '失败', cancelled: '已取消', canceled: '已取消',
}

function isActiveTask(tk) {
  return ACTIVE_TASK_STATUSES.has(String(tk?.status || '').toLowerCase())
}

const dockTasks = computed(() => globalTasks.value.filter(tk => {
  if (isActiveTask(tk)) return true
  const finishedAt = Number(tk.finishedAt || 0)
  return finishedAt > 0 && taskNowTick.value - finishedAt < RECENT_TASK_TTL
}))

const runningTaskCount = computed(() => dockTasks.value.filter(isActiveTask).length)

function toggleTaskDock() {
  if (sidebarCollapsed.value) {
    sidebarCollapsed.value = false
    taskDockCollapsed.value = false
    return
  }
  taskDockCollapsed.value = !taskDockCollapsed.value
}

function taskStatusLabel(tk) {
  const status = String(tk?.status || '').toLowerCase()
  return TASK_STATUS_LABELS[status] || (tk?.statusText ? String(tk.statusText) : '进行中')
}

function taskStatusTone(tk) {
  const status = String(tk?.status || '').toLowerCase()
  if (status === 'succeeded') return 'done'
  if (['failed', 'cancelled', 'canceled'].includes(status)) return 'failed'
  return 'running'
}

async function refreshGlobalTasks() {
  if (typeof window.pywebview?.api?.list_tasks !== 'function') return
  try {
    const tasks = await window.pywebview.api.list_tasks('')
    globalTasks.value = Array.isArray(tasks) ? tasks : []
  } catch (err) {
    globalTasks.value = []
  }
}

const cancellingTaskId = ref('')
async function cancelGlobalTask(tk) {
  const id = String(tk?.id || '')
  if (!id) return
  const api = window.pywebview?.api
  if (typeof api?.cancel_task !== 'function') {
    console.warn('cancel_task API 不可用，请重启客户端后再试')
    return
  }
  cancellingTaskId.value = id
  try {
    await api.cancel_task(id)
    await refreshGlobalTasks()
  } catch (err) {
    console.error('取消任务失败', err)
  } finally {
    cancellingTaskId.value = ''
  }
}

const authenticated = computed(() => Boolean(platformUser.value && authToken.value))
const isRunning = computed(() => task.value && !['succeeded', 'failed'].includes(task.value.status))
const canGenerate = computed(() => image.value && prompt.value.trim() && !isRunning.value)
const selectedAccount = computed(() => accounts.value.find(item => item.id === selectedAccountId.value))
const accountOptions = computed(() => accounts.value.map(account => ({
  label: account.inUse
    ? `${account.name} · ${accountTypeLabel(account)}（运行中）`
    : account.loginExpired
      ? `${account.name} · ${accountTypeLabel(account)}（登录已过期）`
      : `${account.name} · ${accountTypeLabel(account)}（今日 ${accountQuotaRemaining(account)}/${dailyVideoQuota(account)}）`,
  value: account.id,
  disabled: account.inUse || account.quotaExhaustedToday || account.loginExpired,
})))
// 只有曾经登录过的账号才需要校验登录状态；从未登录的账号直接跳过。
const checkableAccounts = computed(() => accounts.value.filter(account => account.hasLoggedIn && !account.manualLoginPending))
const accountFiltersActive = computed(() => Boolean(accountSearch.value.trim() || accountPlatformFilter.value !== 'all' || accountStatusFilter.value !== 'all'))
const canReorderAccounts = computed(() => !accountFiltersActive.value && !accountOrderSaving.value && !editingAccountId.value)
const accountStatusCounts = computed(() => {
  const counts = { available: 0, pending: 0, expired: 0, running: 0, exhausted: 0 }
  for (const account of accounts.value) counts[accountManagementStatus(account)] += 1
  return counts
})
const filteredAccounts = computed(() => {
  const search = accountSearch.value.trim().toLocaleLowerCase()
  return accounts.value.filter(account => (
    (!search || `${account.name} ${accountTypeLabel(account)}`.toLocaleLowerCase().includes(search))
    && (accountPlatformFilter.value === 'all' || (account.accountType || 'doubao') === accountPlatformFilter.value)
    && (accountStatusFilter.value === 'all' || accountManagementStatus(account) === accountStatusFilter.value)
  ))
})
const selectableAccounts = computed(() => filteredAccounts.value.filter(account => !account.inUse && !account.loginCompleting && !isAccountVerifying(account.id)))
const allAccountsChecked = computed(() => selectableAccounts.value.length > 0 && selectableAccounts.value.every(account => checkedAccountIds.value.includes(account.id)))
const someAccountsChecked = computed(() => selectableAccounts.value.some(account => checkedAccountIds.value.includes(account.id)) && !allAccountsChecked.value)
const checkedAccounts = computed(() => selectableAccounts.value.filter(account => checkedAccountIds.value.includes(account.id)))
function toggleAllAccounts() {
  checkedAccountIds.value = allAccountsChecked.value ? [] : selectableAccounts.value.map(account => account.id)
}
function invertAccountSelection() {
  checkedAccountIds.value = selectableAccounts.value.filter(account => !checkedAccountIds.value.includes(account.id)).map(account => account.id)
}
function deleteCheckedAccounts() {
  if (!checkedAccounts.value.length || deletingAccountId.value) return
  accountToDelete.value = { accounts: [...checkedAccounts.value] }
}
watch([accountSearch, accountPlatformFilter, accountStatusFilter], () => { checkedAccountIds.value = [] })
watch(accounts, list => { checkedAccountIds.value = checkedAccountIds.value.filter(id => list.some(account => account.id === id)) })
const generationProjectOptions = computed(() => generationProjects.value.map(project => ({ label: project.name || '未命名项目', value: String(project.id) })))

function apiReady() {
  return isApiAvailable()
}

function dailyVideoQuota(account) {
  const isDola = account?.accountType === 'dola'
  return Math.max(1, Number(settings.value[isDola ? 'dolaDailyVideoQuota' : 'dailyVideoQuota']) || (isDola ? 4 : 3))
}

function accountQuotaRemaining(account) {
  const limit = dailyVideoQuota(account)
  if (account?.quotaExhaustedToday) return 0
  const rawRemaining = account?.quotaRemainingToday
  const remaining = Number(rawRemaining)
  if (rawRemaining !== null && rawRemaining !== undefined && rawRemaining !== '' && Number.isFinite(remaining)) {
    return Math.max(0, Math.min(remaining, limit))
  }
  const rawGenerated = account?.generatedToday
  const generated = Number(rawGenerated)
  if (rawGenerated !== null && rawGenerated !== undefined && rawGenerated !== '' && Number.isFinite(generated)) {
    return Math.max(0, limit - generated)
  }
  return limit
}

function accountManagementStatus(account) {
  // 每个账号只统计一次；登录和额度仍在列表中分别显示。
  if (account.inUse) return 'running'
  if (account.loginExpired) return 'expired'
  if (account.manualLoginPending || account.loginCompleting || !account.authenticated) return 'pending'
  if (accountQuotaRemaining(account) === 0) return 'exhausted'
  return 'available'
}

function accountLoginLabel(account) {
  if (account.loginCompleting || completingAccountId.value === account.id) return '确认登录中'
  if (account.manualLoginPending) return '待确认登录'
  if (account.loginExpired) return '登录已过期'
  return account.authenticated ? '已登录' : '待登录'
}

function clearAccountFilters() {
  accountSearch.value = ''
  accountPlatformFilter.value = 'all'
  accountStatusFilter.value = 'all'
}

watch([accountSearch, accountPlatformFilter, accountStatusFilter], endAccountDrag)
watch(showSettings, (open) => {
  if (!open) {
    window.dispatchEvent(new CustomEvent('cdtv:models-updated'))
  }
})
watch(activeMenu, () => {
  window.dispatchEvent(new CustomEvent('cdtv:models-updated'))
})

function cachedDailyVideoQuota() {
  const value = Number.parseInt(window.localStorage.getItem('cdtv.dailyVideoQuota') || '', 10)
  return Number.isFinite(value) ? Math.max(1, Math.min(value, 99)) : null
}

function waitForApiReady(timeoutMs = 15000) {
  return waitForDesktopApi(timeoutMs)
}

async function initializeAuth() {
  window.cdtvStartup?.set(48, '正在准备工作区…')
  const api = await waitForApiReady()
  if (!api) {
    authError.value = '桌面接口未就绪，请完全退出后重新启动客户端。'
    authChecking.value = false
    window.cdtvStartup?.fail(authError.value)
    return false
  }
  let ready = false
  try {
    window.cdtvStartup?.set(55, '正在读取本地数据…')
    await loadAppInfo()
    ready = true
  } catch (err) {
    authError.value = cleanError(err)
    window.cdtvStartup?.fail(authError.value)
  } finally {
    authChecking.value = false
  }
  if (ready) {
    await nextTick()
    window.cdtvStartup?.finish()
  }
  return ready
}

async function handleLogin(credentials) {
  authLoading.value = true
  authError.value = ''
  try {
    const authMethod = credentials.mode === 'register' ? 'register' : 'login'
    const session = await window.pywebview.api[authMethod](
      credentials.username,
      credentials.password,
      credentials.remember,
    )
    platformUser.value = session.user
    authToken.value = session.token
    await loadAppInfo()
  } catch (err) {
    authError.value = cleanError(err)
  } finally {
    authLoading.value = false
  }
}

async function logoutPlatform() {
  try {
    await window.pywebview.api.logout(authToken.value)
  } finally {
    platformUser.value = null
    authToken.value = ''
    accountSelectionReady = false
    selectedAccountId.value = ''
    accounts.value = []
    showSettings.value = false
    startNewProject()
  }
}

async function runWindowAction(action) {
  if (!apiReady()) return
  if (action === 'minimize') await window.pywebview.api.minimize_window()
  if (action === 'close') await window.pywebview.api.close_window()
  if (action === 'maximize') {
    isWindowMaximized.value = await window.pywebview.api.toggle_maximize_window()
  }
}

function scrollToSection(section) {
  activeProjectId.value = ''
  activeMenu.value = section
  document.getElementById(section)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function focusProjectSearch() {
  await nextTick()
  document.querySelector('.project-search input')?.focus()
}

function openCreationDataWorkspace() {
  activeProjectId.value = ''
  activeMenu.value = 'creation-data'
}

function openProjectAgent(project = null) {
  if (project && projectWorkspace(project) === 'general') { openGeneralProject(project); return }
  activeProjectId.value = ''
  agentProjectId.value = String(project?.id || '')
  activeMenu.value = 'project-agent'
}

function handleProjectAgentCreated(project) {
  agentProjectId.value = String(project?.id || agentProjectId.value || '')
  activeProjectId.value = agentProjectId.value
  activeMenu.value = 'projects'
}

async function openCreationDataInVideo(payload) {
  if (payload?.projectId) {
    try {
      const linked = await desktopBackendRequest('GET', `/project/${encodeURIComponent(payload.projectId)}`, authToken.value)
      if (projectWorkspace(linked) === 'general') { openGeneralProject(linked, payload); return }
      dramaProductionContext.value = payload
      activeProjectId.value = String(payload.projectId)
      activeMenu.value = 'projects'
      return
    } catch (err) { console.warn('读取作品归属失败', err) }
  }
  creationDataToImport.value = payload || null
  activeMenu.value = 'create'
}

function openGeneralProject(project = null, context = null) {
  if (project?.id) {
    activeProjectId.value = String(project.id)
    generalProjectId.value = String(project.id)
    activeMenu.value = 'general'
    return
  }
  activeProjectId.value = ''
  generalProductionContext.value = context
  generalNavigationKey.value += 1
  generalProjectId.value = ''
  generalCreateRequested.value = 0
  activeMenu.value = 'general'
}

function chooseNewWorkspace(workspace) {
  newProjectChooser.value = false
  if (workspace === 'general') {
    generalProjectId.value = ''
    generalCreateRequested.value = Date.now()
    activeMenu.value = 'general'
  } else if (workspace === 'stickman') {
    activeProjectId.value = ''
    activeMenu.value = 'stickman'
  } else openProjectAgent()
}

function openProjectDetail(project) {
  if (projectWorkspace(project) === 'general') { openGeneralProject(project); return }
  dramaProductionContext.value = null
  activeProjectId.value = String(project?.id || '')
  if (project?.type === 'stickman' || String(project?.style || '').startsWith('stickman-')) {
    activeMenu.value = 'stickman'
  } else {
    activeMenu.value = 'projects'
  }
}

function closeProjectDetail() {
  activeProjectId.value = ''
  activeMenu.value = 'projects'
}

let resizeAnimFrame = null
let resizeLastPhysDx = 0
let resizeLastPhysDy = 0

function startWindowResize(edge, ev) {
  if (isWindowMaximized.value) return
  if (!apiReady()) return
  if (ev && ev.button !== 0) return

  if (ev) {
    ev.preventDefault()
    ev.stopPropagation()
  }

  const startScreenX = ev ? ev.screenX : 0
  const startScreenY = ev ? ev.screenY : 0
  const dpr = window.devicePixelRatio || 1

  const target = ev?.currentTarget || ev?.target
  const pointerId = ev?.pointerId

  if (target && pointerId !== undefined && target.setPointerCapture) {
    try {
      target.setPointerCapture(pointerId)
    } catch {}
  }

  document.body.style.userSelect = 'none'

  if (window.pywebview?.api?.begin_window_resize) {
    window.pywebview.api.begin_window_resize(edge)
  }

  const onPointerMove = (moveEv) => {
    resizeLastPhysDx = Math.round((moveEv.screenX - startScreenX) * dpr)
    resizeLastPhysDy = Math.round((moveEv.screenY - startScreenY) * dpr)
    if (!resizeAnimFrame) {
      resizeAnimFrame = window.requestAnimationFrame(() => {
        resizeAnimFrame = null
        if (apiReady() && window.pywebview?.api?.update_window_resize) {
          window.pywebview.api.update_window_resize(resizeLastPhysDx, resizeLastPhysDy)
        }
      })
    }
  }

  const onPointerUp = (upEv) => {
    document.body.style.userSelect = ''
    if (target && pointerId !== undefined && target.releasePointerCapture) {
      try {
        target.releasePointerCapture(pointerId)
      } catch {}
    }
    window.removeEventListener('pointermove', onPointerMove, true)
    window.removeEventListener('pointerup', onPointerUp, true)
    window.removeEventListener('pointercancel', onPointerUp, true)
    if (resizeAnimFrame) {
      window.cancelAnimationFrame(resizeAnimFrame)
      resizeAnimFrame = null
    }
    if (apiReady() && window.pywebview?.api?.end_window_resize) {
      window.pywebview.api.end_window_resize()
    }
  }

  window.addEventListener('pointermove', onPointerMove, true)
  window.addEventListener('pointerup', onPointerUp, true)
  window.addEventListener('pointercancel', onPointerUp, true)
}

function startNewProject() {
  newProjectChooser.value = true
}

async function selectImage() {
  error.value = ''
  if (!apiReady()) {
    error.value = '桌面接口尚未就绪，请从 Python 启动应用。'
    return
  }
  try {
    const selected = await window.pywebview.api.select_image()
    if (selected) image.value = selected
  } catch (err) {
    error.value = String(err)
  }
}

async function generate() {
  if (!canGenerate.value) return
  error.value = ''
  task.value = null
  try {
    const result = await window.pywebview.api.start_generation({
      imagePath: image.value.path,
      prompt: prompt.value,
      ratio: ratio.value,
      duration: duration.value,
      model: model.value,
      accountId: selectedAccountId.value,
      autoAssignAccount: true,
      projectId: selectedProjectId.value,
      ownerType: 'videoTask',
      taskName: image.value.name ? `视频任务 ${image.value.name}` : '视频任务',
    })
    await pollTask(result.taskId)
    pollTimer = window.setInterval(() => {
      // 页面切到后台时降低轮询频率，避免无谓占用调用通道。
      if (document.hidden) return
      pollTask(result.taskId)
    }, 1200)
  } catch (err) {
    error.value = cleanError(err)
  }
}

async function pollTask(taskId) {
  try {
    const latest = await window.pywebview.api.get_task(taskId)
    if (latest) task.value = latest
    if (latest && ['succeeded', 'failed'].includes(latest.status)) {
      window.clearInterval(pollTimer)
      pollTimer = null
      await loadAccounts()
    }
  } catch (err) {
    error.value = cleanError(err)
    window.clearInterval(pollTimer)
  }
}

function cleanError(err) {
  return String(err).replace(/^Error:\s*/, '')
}

async function loadAppInfo() {
  if (!apiReady()) return
  accountSelectionReady = false
  window.cdtvStartup?.set(68, '正在读取工作区设置…')
  appInfo.value = await window.pywebview.api.get_app_info()
  if (appInfo.value.storageReady === false) {
    throw new Error('项目数据暂时无法读取，请重新尝试。原有项目和素材仍保存在本地。')
  }
  const apiSettings = await window.pywebview.api.get_settings()
  const cachedQuota = cachedDailyVideoQuota()
  settings.value = { ...apiSettings, dailyVideoQuota: cachedQuota ?? (Number(apiSettings.dailyVideoQuota) || 3) }
  if (cachedQuota !== null && cachedQuota !== Number(apiSettings.dailyVideoQuota)) {
    const savedSettings = await window.pywebview.api.save_settings(settings.value)
    settings.value = { ...savedSettings, dailyVideoQuota: cachedQuota }
  }
  window.cdtvStartup?.set(78, '正在加载生成账号…')
  await loadAccounts()
  window.cdtvStartup?.set(88, '正在加载项目数据…')
  await loadGenerationProjects(true)
  window.cdtvStartup?.set(96, '正在打开工作台…')
  const defaultAccount = accounts.value.find(item => item.id === settings.value.defaultAccountId)
  if (defaultAccount) {
    selectedAccountId.value = accounts.value.find(item => (item.accountType || 'doubao') === (defaultAccount.accountType || 'doubao') && !item.quotaExhaustedToday && !item.inUse && !item.loginExpired)?.id || defaultAccount.id
  } else {
    selectedAccountId.value = accounts.value.find(item => !item.quotaExhaustedToday && !item.inUse && !item.loginExpired)?.id || ''
  }
  accountSelectionReady = true
}

async function loadGenerationProjects(requireReady = false) {
  try {
    if (!apiReady()) {
      generationProjects.value = [
        { id: 'p1', name: '我不是丹神' }, { id: 'p2', name: '小师妹的符箓作坊' },
        { id: 'p3', name: '满朝文武都在我脑子里看广告' },
      ]
    } else {
      generationProjects.value = await desktopBackendRequest('GET', '/project/list', authToken.value, null) || []
    }
    if (!selectedProjectId.value && generationProjects.value.length) selectedProjectId.value = String(generationProjects.value[0].id)
  } catch (error) {
    if (requireReady) throw error
    generationProjects.value = []
  }
}

async function loadAccounts() {
  if (draggingAccountId.value || accountOrderSaving.value) return
  // 编辑/删除/重命名进行中时跳过轮询刷新，避免覆盖内联编辑态或与操作结果竞争。
  if (editingAccountId.value || deletingAccountId.value || renamingAccountId.value || creatingAccount.value) return
  const request = ++accountListRequest
  const list = await window.pywebview.api.list_accounts()
  if (request !== accountListRequest || deletingAccountId.value) return
  accounts.value = list
  const selected = accounts.value.find(item => item.id === selectedAccountId.value)
  if (!selected || (!selected.manualLoginPending && (selected.quotaExhaustedToday || selected.inUse || selected.loginExpired))) {
    selectedAccountId.value = accounts.value.find(item => (!selected || (item.accountType || 'doubao') === (selected.accountType || 'doubao')) && !item.quotaExhaustedToday && !item.inUse && !item.loginExpired)?.id || selected?.id || ''
  }
}

function startAccountDrag(event, account) {
  if (!canReorderAccounts.value) {
    event.preventDefault()
    return
  }
  draggingAccountId.value = account.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', account.id)
}

function enterAccountDropTarget(account) {
  if (canReorderAccounts.value && draggingAccountId.value && draggingAccountId.value !== account.id) {
    dragOverAccountId.value = account.id
  }
}

async function dropAccount(event, targetAccount) {
  event.preventDefault()
  const sourceId = draggingAccountId.value || event.dataTransfer.getData('text/plain')
  const targetId = targetAccount.id
  dragOverAccountId.value = ''
  draggingAccountId.value = ''
  if (!sourceId || sourceId === targetId || !canReorderAccounts.value) return
  if (typeof window.pywebview?.api?.reorder_accounts !== 'function') {
    accountMessage.value = '客户端后台尚未更新，请完全退出并重新启动客户端后再调整顺序'
    return
  }

  const previousAccounts = [...accounts.value]
  const sourceIndex = previousAccounts.findIndex(account => account.id === sourceId)
  const targetIndex = previousAccounts.findIndex(account => account.id === targetId)
  if (sourceIndex < 0 || targetIndex < 0) return
  const reorderedAccounts = [...previousAccounts]
  const [movedAccount] = reorderedAccounts.splice(sourceIndex, 1)
  reorderedAccounts.splice(targetIndex, 0, movedAccount)
  accounts.value = reorderedAccounts
  accountOrderSaving.value = true
  accountMessage.value = '正在保存账号顺序…'
  try {
    const result = await window.pywebview.api.reorder_accounts(reorderedAccounts.map(account => account.id))
    accountMessage.value = result.cloudSynced
      ? '账号顺序已保存并同步云端'
      : '账号顺序已在本机保存，云端暂未同步'
  } catch (err) {
    accounts.value = previousAccounts
    accountMessage.value = cleanError(err)
  } finally {
    accountOrderSaving.value = false
  }
}

function endAccountDrag() {
  draggingAccountId.value = ''
  dragOverAccountId.value = ''
}

async function createAccount(accountType = 'doubao') {
  if (creatingAccount.value) return
  accountMessage.value = ''
  const name = String(newAccountNames[accountType] || '').trim()
  if (!name) {
    accountMessage.value = '请输入账号名称'
    return
  }
  const api = window.pywebview?.api
  const supportsAccountTypes = typeof api?.create_generation_account === 'function'
  if (!supportsAccountTypes && accountType === 'dola') {
    accountMessage.value = api
      ? '当前后台尚未加载 Dola 账号接口，请完全退出并重新启动客户端后再添加'
      : '桌面接口尚未就绪，请从 Python 启动应用后再添加账号'
    return
  }
  if (!supportsAccountTypes && typeof api?.create_account !== 'function') {
    accountMessage.value = '桌面接口尚未就绪，请从 Python 启动应用后再添加账号'
    return
  }
  creatingAccount.value = true
  accountMessage.value = `正在添加 ${accountTypeLabel({ accountType })} 账号…`
  try {
    const account = supportsAccountTypes
      ? await api.create_generation_account(name, accountType)
      : await api.create_account(name)
    if (!account?.id) throw new Error('添加账号未返回有效结果，请重新启动客户端后重试')
    const createdAccount = { ...account, accountType: account.accountType || 'doubao' }
    accounts.value = [...accounts.value.filter(item => item.id !== account.id), createdAccount]
    newAccountNames[accountType] = ''
    selectedAccountId.value = account.id
    clearAccountFilters()
    accountMessage.value = `已创建 ${accountTypeLabel(createdAccount)} 账号 ${account.name}`
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    creatingAccount.value = false
  }
}

async function openSelectedAccount(account = selectedAccount.value) {
  if (openingAccountId.value || completingAccountId.value) return
  const accountId = account?.id || selectedAccountId.value
  if (!accountId) {
    accountMessage.value = '请先创建并选择一个账号'
    return
  }
  if (account?.inUse || isAccountVerifying(accountId) || account?.loginCompleting) return
  openingAccountId.value = accountId
  try {
    const result = await window.pywebview.api.open_account_login(accountId)
    if (result.status === 'manual') {
      accounts.value = accounts.value.map(account => account.id === accountId
        ? { ...account, manualLoginPending: true, authenticated: false, status: 'Dola 登录待确认 · 请点击完成登录' }
        : account)
      delete accountVerifyState.value[accountId]
    }
    accountMessage.value = result.message
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    openingAccountId.value = ''
  }
}

async function completeSelectedAccountLogin(targetAccount = selectedAccount.value) {
  if (completingAccountId.value || openingAccountId.value) return
  const accountId = targetAccount?.id || selectedAccountId.value
  const account = accounts.value.find(item => item.id === accountId)
  if (!account?.manualLoginPending || account.accountType !== 'dola' || account.inUse || account.loginCompleting || isAccountVerifying(accountId)) return
  const api = window.pywebview?.api
  if (typeof api?.complete_account_login !== 'function') {
    accountMessage.value = '客户端后台尚未更新，请完全退出并重新启动客户端后再完成登录'
    return
  }
  completingAccountId.value = accountId
  accountVerifyingIds.value = new Set([...accountVerifyingIds.value, accountId])
  accountMessage.value = `正在关闭 ${account.name} 的登录窗口并确认登录…`
  try {
    const result = await api.complete_account_login(accountId)
    accounts.value = accounts.value.map(item => item.id === accountId
      ? { ...item, manualLoginPending: false, authenticated: result.loggedIn, hasLoggedIn: item.hasLoggedIn || result.loggedIn }
      : item)
    accountVerifyState.value = { ...accountVerifyState.value, [accountId]: {
      status: result.loggedIn ? 'ok' : account.hasLoggedIn ? 'expired' : 'failed', message: result.message, detail: result, at: Date.now(),
    } }
    accountMessage.value = result.message
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    completingAccountId.value = ''
    const remaining = new Set(accountVerifyingIds.value)
    remaining.delete(accountId)
    accountVerifyingIds.value = remaining
    loadAccounts().catch(() => {})
  }
}

function openSettings(tab = 'models') {
  settingsTab.value = tab
  showSettings.value = true
  accountMessage.value = ''
  settingsMessage.value = ''
}

watch([showSettings, settingsTab], ([open, tab]) => {
  if (accountStatusTimer) {
    window.clearInterval(accountStatusTimer)
    accountStatusTimer = null
  }
})

watch(selectedAccountId, accountId => {
  if (!accountSelectionReady || !authenticated.value || !apiReady()) return
  if (typeof window.pywebview.api.select_account === 'function') {
    window.pywebview.api.select_account(accountId).catch(() => {})
    return
  }
  // 兼容仍在运行的旧版 Python 进程：通过原有设置接口保存最后选择。
  settings.value.defaultAccountId = accountId
  window.pywebview.api.save_settings(settings.value).catch(() => {})
})

function beginRename(account) {
  editingAccountId.value = account.id
  editingAccountName.value = account.name
  accountMessage.value = ''
}

async function finishRename() {
  const accountId = editingAccountId.value
  const accountName = editingAccountName.value.trim()
  if (!accountId || renamingAccountId.value) return
  if (!accountName) {
    accountMessage.value = '账号名称不能为空'
    return
  }
  const previousAccounts = accounts.value
  renamingAccountId.value = accountId
  try {
    const account = await window.pywebview.api.rename_account(accountId, accountName)
    editingAccountId.value = ''
    editingAccountName.value = ''
    // 就地更新单条记录，避免全量 loadAccounts 触发整列表重渲染与轮询叠加造成的卡顿。
    accounts.value = accounts.value.map(item => (
      item.id === accountId ? { ...item, name: account.name } : item
    ))
    accountMessage.value = `名称已修改为 ${account.name}`
  } catch (err) {
    accounts.value = previousAccounts
    accountMessage.value = cleanError(err)
  } finally {
    renamingAccountId.value = ''
  }
}

function cancelRename() {
  if (renamingAccountId.value) return
  editingAccountId.value = ''
  editingAccountName.value = ''
  accountMessage.value = ''
}

function deleteAccount(account) {
  if (deletingAccountId.value) return
  accountToDelete.value = account
}

function cancelDeleteAccount() {
  if (deletingAccountId.value) return
  accountToDelete.value = null
}

async function confirmDeleteAccount() {
  const account = accountToDelete.value
  if (!account || deletingAccountId.value) return
  const targets = account.accounts || [account]
  deletingAccountId.value = 'batch'
  accountListRequest += 1
  accountMessage.value = ''
  const failed = []
  let deletedCount = 0
  try {
    for (const [index, target] of targets.entries()) {
      deletingAccountId.value = target.id
      accountDeleteProgress.value = `${index + 1}/${targets.length}`
      try {
        await window.pywebview.api.delete_account(target.id)
        if (selectedAccountId.value === target.id) selectedAccountId.value = ''
        if (editingAccountId.value === target.id) {
          editingAccountId.value = ''
          editingAccountName.value = ''
        }
        accounts.value = accounts.value.filter(item => item.id !== target.id).map((item, order) => ({ ...item, sortOrder: order }))
        checkedAccountIds.value = checkedAccountIds.value.filter(id => id !== target.id)
        deletedCount += 1
      } catch (err) {
        failed.push(`${target.name}：${cleanError(err)}`)
      }
    }
    accountMessage.value = `${deletedCount ? `已删除 ${deletedCount} 个账号` : '未删除账号'}${failed.length ? `；${failed.length} 个未删除：${failed.join('；')}` : ''}`
  } finally {
    deletingAccountId.value = ''
    accountDeleteProgress.value = ''
    accountToDelete.value = null
  }
}

async function releaseAccount(account) {
  const actionKey = `release:${account.id}`
  if (accountStateAction.value) return
  accountStateAction.value = actionKey
  accountMessage.value = ''
  try {
    const result = await window.pywebview.api.release_account(account.id)
    await loadAccounts()
    accountMessage.value = result.released ? `已释放 ${account.name}` : `${account.name} 当前未被占用`
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    accountStateAction.value = ''
  }
}

async function toggleAccountQuota(account) {
  const exhausted = !account.quotaExhaustedToday
  const actionKey = `quota:${account.id}`
  if (accountStateAction.value) return
  accountStateAction.value = actionKey
  accountMessage.value = ''
  try {
    await window.pywebview.api.set_account_quota(account.id, exhausted)
    await loadAccounts()
    accountMessage.value = exhausted
      ? `已将 ${account.name} 标记为今日无额度`
      : `已恢复 ${account.name} 今日额度`
  } catch (err) {
    accountMessage.value = cleanError(err)
  } finally {
    accountStateAction.value = ''
  }
}

async function updateDailyVideoQuota(value, accountType = 'doubao') {
  const isDola = accountType === 'dola'
  const key = isDola ? 'dolaDailyVideoQuota' : 'dailyVideoQuota'
  const dailyQuota = Math.max(1, Math.min(Number.parseInt(value, 10) || (isDola ? 4 : 3), 99))
  if (accountStateAction.value) return
  const previousSettings = { ...settings.value }
  let quotaSaved = false
  accountStateAction.value = 'daily-limit'
  accountMessage.value = ''
  try {
    settings.value[key] = dailyQuota
    settings.value.defaultAccountId = selectedAccountId.value
    const savedSettings = await window.pywebview.api.save_settings(settings.value)
    settings.value = { ...savedSettings, [key]: dailyQuota }
    quotaSaved = true
    if (!isDola) window.localStorage.setItem('cdtv.dailyVideoQuota', String(dailyQuota))
    await loadAccounts()
    accountMessage.value = `${accountTypeLabel({ accountType })} 每个账号的每日视频额度已保存为 ${dailyQuota} 次`
  } catch (err) {
    if (!quotaSaved) settings.value = previousSettings
    accountMessage.value = quotaSaved ? `额度已保存，刷新失败：${cleanError(err)}` : cleanError(err)
  } finally {
    accountStateAction.value = ''
  }
}

function stepDailyVideoQuota(delta, accountType = 'doubao') {
  updateDailyVideoQuota(dailyVideoQuota({ accountType }) + delta, accountType)
}

function verifyChip(accountId) {
  const state = accountVerifyState.value[accountId]
  if (!state) return null
  if (state.status === 'checking') return { tone: 'checking', icon: 'spinner', label: '校验中', clickable: false }
  if (state.status === 'ok') return { tone: 'ok', icon: 'ok', label: '正常', clickable: false }
  if (state.status === 'expired') return { tone: 'expired', icon: 'expired', label: '登录过期', clickable: true }
  if (state.status === 'failed') return { tone: 'failed', icon: 'failed', label: '校验失败', clickable: true }
  return null
}

function isAccountVerifying(accountId) {
  return accountVerifyingIds.value.has(accountId)
}

function isBatchVerifying() {
  return Boolean(accountVerifyBatch.value?.running)
}

// 单账号校验：仅禁用该账号行，不影响其他账号操作。
async function verifyAccountLogin(account) {
  const accountId = account.id
  if (isAccountVerifying(accountId) || isBatchVerifying()) return
  if (account.manualLoginPending) {
    accountMessage.value = '请先在 Dola 窗口中登录，再点击“完成登录”'
    return
  }
  if (typeof window.pywebview?.api?.check_account_login !== 'function') {
    accountMessage.value = '客户端后台尚未更新，请完全退出并重新启动客户端后再校验登录'
    return
  }
  if (account.inUse) {
    accountMessage.value = `${account.name} 运行中，请等待任务结束或先手动释放`
    return
  }
  if (!account.hasLoggedIn) {
    accountMessage.value = `${account.name} 从未登录过，请先打开登录页完成登录`
    return
  }
  const verifyingIds = new Set(accountVerifyingIds.value)
  verifyingIds.add(accountId)
  accountVerifyingIds.value = verifyingIds
  accountVerifyState.value = {
    ...accountVerifyState.value,
    [accountId]: { status: 'checking', message: '', detail: null, at: Date.now() },
  }
  accountMessage.value = `正在校验 ${account.name}…`
  try {
    const result = await window.pywebview.api.check_account_login(accountId)
    const method = result.method === 'http' ? 'HTTP 探活' : '浏览器校验'
    const next = {
      status: result.loggedIn ? 'ok' : 'expired',
      message: result.message || (result.loggedIn ? '登录状态正常' : '登录已过期'),
      detail: {
        method,
        hasLoginText: result.hasLoginText,
        hasSessionCookie: result.hasSessionCookie,
        url: result.url,
      },
      at: Date.now(),
    }
    accountVerifyState.value = { ...accountVerifyState.value, [accountId]: next }
    accountMessage.value = next.message
  } catch (err) {
    const msg = cleanError(err)
    accountVerifyState.value = {
      ...accountVerifyState.value,
      [accountId]: { status: 'failed', message: msg, detail: null, at: Date.now() },
    }
    accountMessage.value = `${account.name} 校验失败：${msg}`
  } finally {
    const rest = new Set(accountVerifyingIds.value)
    rest.delete(accountId)
    accountVerifyingIds.value = rest
    loadAccounts().catch(() => {})
  }
}

function toggleVerifyDetail(accountId) {
  accountVerifyDetailId.value = accountVerifyDetailId.value === accountId ? '' : accountId
}

// 并发上限 3 的批量校验；支持取消——已发起的请求等其返回，未启动的不再发起。
async function verifyAllAccountsLogin() {
  if (isBatchVerifying()) return
  if (typeof window.pywebview?.api?.check_account_login !== 'function') {
    accountMessage.value = '客户端后台尚未更新，请完全退出并重新启动客户端后再校验登录'
    return
  }
  const targets = [...checkableAccounts.value]
  const skipped = accounts.value.length - targets.length
  if (!targets.length) {
    accountMessage.value = accounts.value.length
      ? '没有已登录过的账号可校验（从未登录的账号已跳过）'
      : '还没有账号可校验'
    return
  }
  accountVerifyState.value = {}
  accountVerifyDetailId.value = ''
  accountVerifyBatch.value = {
    running: true,
    total: targets.length,
    done: 0,
    ok: 0,
    expired: 0,
    failed: 0,
    cancelled: false,
  }
  accountMessage.value = `正在校验 0/${targets.length}…`
  const CONCURRENCY = 3
  let cursor = 0
  const runOne = async () => {
    while (true) {
      if (accountVerifyBatch.value?.cancelled) return
      const idx = cursor++
      if (idx >= targets.length) return
      const account = targets[idx]
      const verifyingIds = new Set(accountVerifyingIds.value)
      verifyingIds.add(account.id)
      accountVerifyingIds.value = verifyingIds
      accountVerifyState.value = {
        ...accountVerifyState.value,
        [account.id]: { status: 'checking', message: '', detail: null, at: Date.now() },
      }
      const batch = { ...accountVerifyBatch.value }
      accountVerifyBatch.value = batch
      try {
        const result = await window.pywebview.api.check_account_login(account.id)
        const method = result.method === 'http' ? 'HTTP 探活' : '浏览器校验'
        if (accountVerifyBatch.value?.cancelled) {
          // 取消后到账的结果不再计入统计，但仍保留 chip 状态供查看。
          accountVerifyState.value = {
            ...accountVerifyState.value,
            [account.id]: {
              status: result.loggedIn ? 'ok' : 'expired',
              message: result.message || '',
              detail: { method, hasLoginText: result.hasLoginText, hasSessionCookie: result.hasSessionCookie, url: result.url },
              at: Date.now(),
            },
          }
          return
        }
        const status = result.loggedIn ? 'ok' : 'expired'
        accountVerifyState.value = {
          ...accountVerifyState.value,
          [account.id]: {
            status,
            message: result.message || (result.loggedIn ? '登录状态正常' : '登录已过期'),
            detail: { method, hasLoginText: result.hasLoginText, hasSessionCookie: result.hasSessionCookie, url: result.url },
            at: Date.now(),
          },
        }
        if (status === 'ok') batch.ok += 1
        else batch.expired += 1
      } catch (err) {
        if (accountVerifyBatch.value?.cancelled) {
          accountVerifyState.value = {
            ...accountVerifyState.value,
            [account.id]: { status: 'failed', message: cleanError(err), detail: null, at: Date.now() },
          }
          return
        }
        accountVerifyState.value = {
          ...accountVerifyState.value,
          [account.id]: { status: 'failed', message: cleanError(err), detail: null, at: Date.now() },
        }
        batch.failed += 1
      } finally {
        const rest = new Set(accountVerifyingIds.value)
        rest.delete(account.id)
        accountVerifyingIds.value = rest
        batch.done += 1
        accountVerifyBatch.value = { ...batch }
        accountMessage.value = `正在校验 ${batch.done}/${batch.total}…`
      }
    }
  }
  const workers = []
  for (let i = 0; i < Math.min(CONCURRENCY, targets.length); i++) workers.push(runOne())
  try {
    await Promise.all(workers)
  } finally {
    const final = { ...accountVerifyBatch.value, running: false }
    accountVerifyBatch.value = final
    const parts = []
    if (final.ok) parts.push(`${final.ok} 个正常`)
    if (final.expired) parts.push(`${final.expired} 个登录过期`)
    if (final.failed) parts.push(`${final.failed} 个校验失败`)
    let message = final.cancelled
      ? `已取消校验：完成 ${final.done}/${final.total}（${parts.join('，') || '无结果'}）`
      : `${final.total} 个账号校验完成：${parts.join('，') || '无结果'}`
    if (skipped) message += `（另有 ${skipped} 个从未登录的账号已跳过）`
    accountMessage.value = message
    loadAccounts().catch(() => {})
  }
}

function cancelVerifyAll() {
  if (!accountVerifyBatch.value?.running) return
  accountVerifyBatch.value = { ...accountVerifyBatch.value, cancelled: true }
  accountMessage.value = '正在取消校验，等待已发起的请求返回…'
}

async function chooseStorageDirectory() {
  const selected = await window.pywebview.api.select_storage_directory()
  if (selected) settings.value.storageDir = selected
}

async function saveSettings() {
  settings.value.defaultAccountId = selectedAccountId.value
  settings.value = await window.pywebview.api.save_settings(settings.value)
  settingsMessage.value = settings.value.storageRestartRequired
    ? '设置已保存，请重启客户端以使用新的项目存储目录'
    : '设置已保存'
}

async function openOutputDirectory() {
  await window.pywebview.api.open_output_directory()
}


async function openStorageDirectory() {
  await window.pywebview.api.open_storage_directory()
}

onMounted(async () => {
  if (import.meta.env.DEV && !apiReady()) {
    if (new URLSearchParams(window.location.search).has('preview-auth')) {
      platformUser.value = { username: 'preview', nickname: 'CDTV 用户' }
      authToken.value = 'preview-token'
    }
    // 浏览器预览没有 pywebview 桥接，保留原有 mock 预览行为；
    // 正式版则必须先完成下面的 API 就绪等待，避免子组件提前访问 undefined。
    authChecking.value = false
    await loadGenerationProjects()
    await nextTick()
    window.cdtvStartup?.finish()
  } else {
    if (!await initializeAuth()) return
  }
  refreshGlobalTasks()
  globalTaskTimer = window.setInterval(refreshGlobalTasks, 2000)
  taskNowTickTimer = window.setInterval(() => { taskNowTick.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  if (accountStatusTimer) window.clearInterval(accountStatusTimer)
  if (globalTaskTimer) window.clearInterval(globalTaskTimer)
  if (taskNowTickTimer) window.clearInterval(taskNowTickTimer)
})
</script>

<template>
  <main class="app-shell" :class="{ 'auth-mode': !authenticated, 'video-workbench-mode': authenticated && activeMenu === 'create' }">
    <div class="window-titlebar" @dblclick="runWindowAction('maximize')">
      <div class="window-identity pywebview-drag-region" aria-hidden="true"></div>
      <div class="window-controls" @dblclick.stop>
        <button data-tooltip="最小化" aria-label="最小化" @click="runWindowAction('minimize')">
          <svg viewBox="0 0 12 12"><path d="M2 6.5h8" /></svg>
        </button>
        <button data-tooltip="最大化" aria-label="最大化或还原" @click="runWindowAction('maximize')">
          <svg v-if="!isWindowMaximized" viewBox="0 0 12 12"><rect x="2.2" y="2.2" width="7.6" height="7.6" rx=".6" /></svg>
          <svg v-else viewBox="0 0 12 12"><path d="M4 3V2.2h5.8V8H9M2.2 4H8v5.8H2.2z" /></svg>
        </button>
        <button class="window-close" data-tooltip="关闭" aria-label="关闭" @click="runWindowAction('close')">
          <svg viewBox="0 0 12 12"><path d="m2.5 2.5 7 7m0-7-7 7" /></svg>
        </button>
      </div>
    </div>
    <template v-if="appInfo?.platform !== 'darwin' && !isWindowMaximized">
      <i v-for="edge in ['top', 'right', 'bottom', 'left', 'top-left', 'top-right', 'bottom-left', 'bottom-right']" :key="edge" :class="['resize-handle', `resize-${edge}`]" @pointerdown="startWindowResize(edge, $event)" @mousedown.prevent></i>
    </template>

    <div v-if="authChecking" class="auth-loading" role="status" aria-live="polite">
      <BaseLoadingState size="lg" text="正在验证登录状态…" description="AI 视频工作台" />
    </div>

    <template v-else>

    <aside class="sidebar studio-sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-brand">
        <button class="sidebar-logo" :data-tooltip="sidebarCollapsed ? '展开菜单' : 'CDTV'" @click="sidebarCollapsed && (sidebarCollapsed = false)">
          <img src="/TV.png" alt="CDTV" />
        </button>
        <span class="sidebar-brand-copy"><strong>CDTV</strong><small>AI 视频工作台</small></span>
        <button class="collapse-button" :data-tooltip="sidebarCollapsed ? '展开菜单' : '收起菜单'" :aria-label="sidebarCollapsed ? '展开菜单' : '收起菜单'" @click="sidebarCollapsed = !sidebarCollapsed">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M9.67272 0.522841C10.8339 0.522841 11.76 0.522714 12.4963 0.602493C13.2453 0.683657 13.8789 0.854248 14.4264 1.25197C14.7504 1.48739 15.0355 1.77247 15.2709 2.0965C15.6686 2.64394 15.8392 3.27758 15.9204 4.02655C16.0002 4.7629 16 5.68895 16 6.85014V9.14986C16 10.3111 16.0002 11.2371 15.9204 11.9735C15.8392 12.7224 15.6686 13.3561 15.2709 13.9035C15.0355 14.2275 14.7504 14.5126 14.4264 14.748C13.8789 15.1458 13.2453 15.3163 12.4963 15.3975C11.76 15.4773 10.8339 15.4772 9.67272 15.4772H6.3273C5.16611 15.4772 4.24006 15.4773 3.50371 15.3975C2.75474 15.3163 2.1211 15.1458 1.57366 14.748C1.24963 14.5126 0.964549 14.2275 0.729131 13.9035C0.331407 13.3561 0.160817 12.7224 0.0796529 11.9735C-0.000126137 11.2371 1.25338e-09 10.3111 1.25338e-09 9.14986V6.85014C1.25329e-09 5.68895 -0.000126137 4.7629 0.0796529 4.02655C0.160817 3.27758 0.331407 2.64394 0.729131 2.0965C0.964549 1.77247 1.24963 1.48739 1.57366 1.25197C2.1211 0.854248 2.75474 0.683657 3.50371 0.602493C4.24006 0.522714 5.16611 0.522841 6.3273 0.522841H9.67272ZM5.54303 1.88715V14.1118C5.78636 14.1128 6.04709 14.1169 6.3273 14.1169H9.67272C10.8639 14.1169 11.7032 14.1164 12.3493 14.0465C12.9824 13.9779 13.3497 13.8494 13.6268 13.6482C13.8354 13.4966 14.0195 13.3125 14.1711 13.1039C14.3723 12.8268 14.5007 12.4595 14.5693 11.8264C14.6393 11.1803 14.6398 10.341 14.6398 9.14986V6.85014C14.6398 5.65896 14.6393 4.81967 14.5693 4.1736C14.5007 3.54048 14.3723 3.17318 14.1711 2.89609C14.0195 2.68747 13.8354 2.50337 13.6268 2.35179C13.3497 2.1506 12.9824 2.02212 12.3493 1.95353C11.7032 1.88358 10.8639 1.88307 9.67272 1.88307H6.3273C6.04709 1.88307 5.78636 1.8862 5.54303 1.88715ZM4.1828 1.91166C3.99125 1.9216 3.8148 1.93577 3.65076 1.95353C3.01764 2.02212 2.65034 2.1506 2.37325 2.35179C2.16463 2.50337 1.98052 2.68747 1.82895 2.89609C1.62776 3.17318 1.49928 3.54048 1.43069 4.1736C1.36074 4.81967 1.36023 5.65896 1.36023 6.85014V9.14986C1.36023 10.341 1.36074 11.1803 1.43069 11.8264C1.49928 12.4595 1.62776 12.8268 1.82895 13.1039C1.98052 13.3125 2.16463 13.4966 2.37325 13.6482C2.65034 13.8494 3.01764 13.9779 3.65076 14.0465C3.81478 14.0642 3.99127 14.0774 4.1828 14.0873V1.91166Z" /></svg>
        </button>
      </div>

      <button class="new-project-button" aria-label="新建任务" data-tooltip="新建任务" data-tooltip-pos="right" @click="startNewProject">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 8.5v7M8.5 12h7" /></svg>
        <span>新建任务</span>
      </button>

      <button type="button" class="sidebar-project-search" aria-label="搜索项目" data-tooltip="搜索项目" data-tooltip-pos="right" @click="scrollToSection('projects'); focusProjectSearch()"><svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></svg><span>搜索项目</span></button>
      <nav class="sidebar-nav studio-navigation" aria-label="主菜单">
        <section class="sidebar-nav-group" aria-labelledby="sidebar-group-0"><h2 id="sidebar-group-0">创作</h2>
          <button type="button" aria-label="短剧创作" data-tooltip="短剧创作" data-tooltip-pos="right" :aria-current="(activeMenu === 'projects') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'projects') && !showProjectFiles }" @click="activeProjectId = ''; activeMenu = 'projects'"><svg viewBox="0 0 24 24"><path d="M3.5 7.5h6l2-2h9v13h-17v-11Z"/><path d="M7 11h10M7 14.5h7"/></svg><span class="sidebar-nav-copy"><strong>短剧创作</strong><small>连续剧情 · 按集制作</small></span></button>
          <button type="button" aria-label="墨柴工坊" data-tooltip="墨柴工坊" data-tooltip-pos="right" :aria-current="(activeMenu === 'stickman') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'stickman') && !showProjectFiles }" @click="activeProjectId = ''; activeMenu = 'stickman'"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="2.5"/><path d="m12 7.5v7m0-4.5 5-2m-5 2-5-1m5 5.5 4 6m-4-6-4 6"/></svg><span class="sidebar-nav-copy"><strong>墨柴工坊</strong><small>火柴人 · 动作与沙雕</small></span></button>
          <button type="button" aria-label="通用视频" data-tooltip="通用视频" data-tooltip-pos="right" :aria-current="(activeMenu === 'general') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'general') && !showProjectFiles }" @click="openGeneralProject()"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 9 5 3-5 3V9Z"/></svg><span class="sidebar-nav-copy"><strong>通用视频</strong><small>宣传 / 科普 / 生活 / 纪录</small></span></button>
        </section>
        <section class="sidebar-nav-group" aria-labelledby="sidebar-group-1"><h2 id="sidebar-group-1">作品与素材</h2>
          <button type="button" aria-label="视频剪辑与衔接" data-tooltip="视频剪辑与衔接" data-tooltip-pos="right" :aria-current="(activeMenu === 'video-editor') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'video-editor') && !showProjectFiles }" @click="showProjectFiles = false; activeProjectId = ''; activeMenu = 'video-editor'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>
            <span class="sidebar-nav-copy"><strong>视频剪辑与衔接</strong><small>消顿衔接 · 遮挡转场</small></span>
          </button>
          <button type="button" aria-label="全部生成记录" data-tooltip="全部生成记录" data-tooltip-pos="right" :aria-current="(activeMenu === 'create') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'create') && !showProjectFiles }" @click="scrollToSection('create')"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="14" height="14" rx="2.5"/><path d="m17 10 4-2v8l-4-2v-4Z"/></svg><span class="sidebar-nav-copy"><strong>全部生成记录</strong></span></button>
          <button type="button" aria-label="共享素材库" data-tooltip="共享素材库" data-tooltip-pos="right" :aria-current="(activeMenu === 'assets') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'assets') && !showProjectFiles }" @click="activeProjectId = ''; activeMenu = 'assets'"><svg viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><circle cx="9" cy="9" r="1.5"/><path d="m5.5 17 4.2-4.2 3.1 3.1 2.5-2.5 3.2 3.6"/></svg><span class="sidebar-nav-copy"><strong>共享素材库</strong></span></button>
          <button type="button" aria-label="项目文件" data-tooltip="项目文件" data-tooltip-pos="right" :aria-current="showProjectFiles ? 'page' : undefined" :class="{ active: showProjectFiles }" @click="showProjectFiles = true"><svg viewBox="0 0 24 24"><path d="M3.5 7.5h6l2-2h9v13h-17v-11Z"/><path d="M7 11h10M7 14.5h7"/></svg><span class="sidebar-nav-copy"><strong>项目文件</strong></span></button>
        </section>
        <section class="sidebar-nav-group" aria-labelledby="sidebar-group-2"><h2 id="sidebar-group-2">实用工具</h2>
          <button type="button" aria-label="短剧助手" data-tooltip="短剧助手" data-tooltip-pos="right" :aria-current="(activeMenu === 'project-agent') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'project-agent') && !showProjectFiles }" @click="openProjectAgent()"><svg viewBox="0 0 24 24"><path d="M5 5.5h14v10H9l-4 3v-13Z"/><path d="M8 9h8M8 12h5"/><path d="m18 3 1.2 2.8L22 7l-2.8 1.2L18 11l-1.2-2.8L14 7l2.8-1.2L18 3Z"/></svg><span class="sidebar-nav-copy"><strong>短剧助手</strong><small>写剧本、提取资产与分镜</small></span></button>
          <button type="button" aria-label="AI 影视工具箱" data-tooltip="AI 影视工具箱" data-tooltip-pos="right" :aria-current="(activeMenu === 'toolbox') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'toolbox') && !showProjectFiles }" @click="activeProjectId = ''; activeMenu = 'toolbox'"><svg viewBox="0 0 24 24"><path d="m14.7 6.3 3 3-9.4 9.4H5.3v-3l9.4-9.4Z"/><path d="m18 3 3 3"/><path d="M4 20h16"/></svg><span class="sidebar-nav-copy"><strong>AI 影视工具箱</strong><small>字幕 · 音频 · 去水印 · 补帧 · 拆解</small></span></button>
          <button type="button" aria-label="创作数据工具" data-tooltip="创作数据工具" data-tooltip-pos="right" :aria-current="(activeMenu === 'creation-data') && !showProjectFiles ? 'page' : undefined" :class="{ active: (activeMenu === 'creation-data') && !showProjectFiles }" @click="openCreationDataWorkspace"><svg viewBox="0 0 24 24"><path d="M4 5.5h16v13H4z"/><path d="M8 9h8M8 12h6M8 15h4"/><path d="m17 3 1.5 1.5L17 6"/></svg><span class="sidebar-nav-copy"><strong>创作数据工具</strong></span></button>
        </section>
      </nav>

      <div class="sidebar-bottom">
        <div v-if="dockTasks.length" class="task-dock" :class="{ collapsed: taskDockCollapsed }">
          <button class="task-dock-head" type="button" :aria-expanded="!taskDockCollapsed && !sidebarCollapsed" aria-controls="background-task-list" :data-tooltip="sidebarCollapsed ? `后台任务 · ${runningTaskCount} 个进行中` : null" @click="toggleTaskDock">
            <span class="task-dock-title">
              <svg class="task-dock-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8 9h8M8 13h5M8 17h3"/></svg>
              <span class="task-dock-label">后台任务</span>
              <span class="task-dock-count">{{ runningTaskCount || dockTasks.length }}</span>
            </span>
            <svg class="task-dock-caret" :class="{ up: !taskDockCollapsed }" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5" /></svg>
          </button>
          <div v-show="!taskDockCollapsed && !sidebarCollapsed" id="background-task-list" class="task-dock-list">
            <div v-for="tk in dockTasks" :key="tk.id" class="task-dock-item" :class="taskStatusTone(tk)">
              <div class="task-dock-row">
                <span class="task-dock-name" :title="tk.taskName || tk.ownerType">{{ tk.taskName || tk.ownerType || '生成任务' }}</span>
                <button v-if="isActiveTask(tk)" class="task-dock-cancel" type="button" data-tooltip="取消任务" :disabled="cancellingTaskId === String(tk.id)" :aria-label="`取消任务 ${tk.taskName || tk.ownerType || ''}`" @click="cancelGlobalTask(tk)">
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>
                </button>
              </div>
              <div class="task-dock-meta">
                <span class="task-dock-badge">{{ taskStatusLabel(tk) }}</span>
                <span v-if="isActiveTask(tk)" class="task-dock-progress-text">{{ Math.min(100, Math.max(0, Number(tk.progress) || 0)) }}%</span>
              </div>
              <div v-if="isActiveTask(tk)" class="task-dock-bar"><span :style="{ width: `${Math.min(100, Math.max(0, Number(tk.progress) || 0))}%` }"></span></div>
            </div>
          </div>
        </div>
        <div class="sidebar-account-row">
          <div class="sidebar-platform-account" :data-tooltip="`工作区：${platformUser.nickname || platformUser.username}`">
            <span class="sidebar-platform-avatar">{{ (platformUser.nickname || platformUser.username || '?').slice(0, 1) }}</span>
            <span class="sidebar-platform-copy"><strong>{{ platformUser.nickname || platformUser.username }}</strong><small>本地配置</small></span>
          </div>
          <button class="sidebar-inline-action sidebar-settings-action" data-tooltip="设置" aria-label="设置" @click="openSettings('models')">
            <svg viewBox="0 0 24 24"><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5v.2h-4v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3v-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.5V3h4v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.1v4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></svg><span>设置</span>
          </button>
        </div>
      </div>
    </aside>

    <div class="ambient ambient-one"></div>
    <div class="ambient ambient-two"></div>

    <header v-if="activeMenu === 'home'" class="topbar">
      <div class="topbar-actions">
      <button class="account-switch" @click="openSettings('models')">
        <span class="account-avatar">⚡</span>
        <span>模型配置中心</span>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4" /></svg>
      </button>
      </div>
    </header>

    <div v-if="newProjectChooser" class="workspace-choice-overlay" @click.self="newProjectChooser=false">
      <section role="dialog" aria-modal="true" aria-label="选择创作工作区" class="workspace-choice">
        <header><div><span>开始新的创作</span><h2>这次，你想做哪类作品？</h2></div><button aria-label="关闭工作区选择" @click="newProjectChooser=false">×</button></header>
        <div><button @click="chooseNewWorkspace('drama')"><small>连续剧情 · 分集制作</small><strong>短剧创作</strong><p>人物、剧情、章节与连续分镜，使用原来的短剧导演流程。</p><span>进入短剧助手 →</span></button>
          <button @click="chooseNewWorkspace('stickman')"><small>极简 · 动作 · 沙雕</small><strong>墨柴工坊</strong><p>火柴人动作漫剧，极简高对比线条、高能打击感与爆笑反转。</p><span>进入工坊 →</span></button><button @click="chooseNewWorkspace('general')"><small>独立作品 · 完整表达</small><strong>通用视频</strong><p>宣传、科普、纪录与日常分享，使用独立助手和 Shotcraft 模板库。</p><span>创建通用视频 →</span></button></div>
      </section>
    </div>

    <template v-if="['projects', 'stickman', 'prompts', 'assets'].includes(activeMenu)">
      <Transition name="project-detail-fade">
        <DirectVideoStudio
          v-if="activeMenu === 'stickman' && activeProjectId"
          :project-id="activeProjectId"
          :key="activeProjectId"
          mode="stickman"
          :token="authToken"
          :api-base="appInfo?.apiBase" :storage-base="appInfo?.storageBase" :selected-account-id="selectedAccountId" :video-model="model"
          @back="activeProjectId = ''"
          @request-model-settings="openSettings('models')"
        />
        <ProjectDetail
          v-else-if="activeMenu === 'projects' && activeProjectId"
          :project-id="activeProjectId"
          :key="activeProjectId"
          :production-context="dramaProductionContext"
          :api-base="appInfo?.apiBase" :storage-base="appInfo?.storageBase" :selected-account-id="selectedAccountId" :video-model="model"
          :token="authToken"
          @back="closeProjectDetail"
          @open-agent="openProjectAgent"
          @open-direct="openGeneralProject($event)"
      @open-video="openCreationDataInVideo"
          @request-model-settings="openSettings('models')"
        />
      </Transition>

      <WorkspaceLibraries
        v-show="!((activeMenu === 'projects' || activeMenu === 'stickman') && activeProjectId)"
        :section="activeMenu"
        :token="authToken"
        :api-base="appInfo?.apiBase"
        :storage-base="appInfo?.storageBase"
        @open-project="openProjectDetail"
        @open-agent="openProjectAgent"
      />
    </template>

    <DirectVideoStudio
      v-else-if="activeMenu === 'general' && activeProjectId"
      :project-id="activeProjectId"
      :key="activeProjectId"
      mode="general"
      :token="authToken"
      :api-base="appInfo?.apiBase" :storage-base="appInfo?.storageBase" :selected-account-id="selectedAccountId" :video-model="model"
      @back="activeProjectId = ''"
      @request-model-settings="openSettings('models')"
    />

    <GeneralVideoStudio
      v-else-if="activeMenu === 'general'"
      :key="generalNavigationKey"
      :token="authToken"
      :initial-project-id="generalProjectId"
      :production-context="generalProductionContext"
      :api-base="appInfo?.apiBase" :storage-base="appInfo?.storageBase" :selected-account-id="selectedAccountId" :video-model="model"
      :create-requested="generalCreateRequested"
      @open-direct="openGeneralProject($event)"
      @open-video="openCreationDataInVideo"
      @open-drama="openProjectDetail"
      @request-model-settings="openSettings('models')"
    />

    <template v-else-if="activeMenu === 'home'">

    <section id="home" class="hero">
      <p class="eyebrow">视频任务工作区</p>
      <h1>视频任务</h1>
      <p class="subtitle">上传参考画面，通过 OriginaDoubao、Dola 或 Seedance 生成视频。</p>
    </section>

    <section id="create" class="workspace section-anchor">
      <div class="panel media-panel">
        <div class="panel-heading">
          <div><span class="step">01</span><h2>参考画面</h2></div>
          <button v-if="image" class="text-button" @click="selectImage">更换</button>
        </div>

        <button class="upload-zone" :class="{ filled: image }" @click="selectImage">
          <img v-if="image" :src="image.preview" :alt="image.name" />
          <template v-else>
            <div class="upload-icon">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
              </svg>
            </div>
            <strong>选择一张图片</strong>
            <span>支持 JPG、PNG、WEBP</span>
          </template>
          <div v-if="image" class="image-caption">{{ image.name }}</div>
        </button>
      </div>

      <div class="panel controls-panel">
        <div class="panel-heading">
          <div><span class="step">02</span><h2>动态描述</h2></div>
          <span class="char-count">{{ prompt.length }} / 500</span>
        </div>

        <textarea v-model="prompt" maxlength="500" placeholder="描述镜头、动作、光影和氛围……"></textarea>

        <div class="model-field">
          <label>关联项目</label>
          <UiSelect v-model="selectedProjectId" :options="generationProjectOptions" :placeholder="generationProjectOptions.length ? '选择项目' : '暂无项目，请先新建项目'" />
        </div>

        <div class="model-field">
          <label>生成模型</label>
          <UiSelect v-model="model" :options="['Seedance 2.0 Fast']" status badge="快速" />
        </div>

        <div class="option-row">
          <div class="option-group">
            <label>画面比例</label>
            <div class="segmented">
              <button v-for="item in ['自动', '16:9', '9:16', '1:1']" :key="item" :class="{ active: ratio === item }" @click="ratio = item">{{ item }}</button>
            </div>
          </div>
          <div class="option-group">
            <label>视频时长</label>
            <div class="duration-control">
              <input v-model.number="duration" type="range" min="4" max="15" step="1" />
              <strong>{{ duration }} 秒</strong>
            </div>
          </div>
        </div>

        <button class="generate-button" :disabled="!canGenerate" @click="generate">
          <span v-if="isRunning" class="spinner"></span>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Zm6.5 12 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" /></svg>
          {{ isRunning ? '正在生成' : '开始生成视频' }}
        </button>

        <p v-if="error" class="error-message">{{ error }}</p>
      </div>
    </section>

    <footer>
      <span>浏览器自动化模式 · 页面更新后可能需要重新适配控件</span>
      <span v-if="appInfo">登录状态目录：{{ appInfo.profileDir }}</span>
    </footer>
    </template>

    <VideoCreationWorkspace
      v-else-if="activeMenu === 'create'"
      ai-assembly-enabled
      :token="authToken"
      :api-base="appInfo?.apiBase"
      :storage-base="appInfo?.storageBase"
      :selected-account-id="selectedAccountId"
      :video-model="model"
      :initial-creation-data="creationDataToImport"
      @open-video-editor="activeProjectId = $event?.id || activeProjectId; activeMenu = 'video-editor'"
      @creation-data-consumed="creationDataToImport = null"
    />

    <CreationDataWorkspace
      v-else-if="activeMenu === 'creation-data'"
      :token="authToken"
      @open-direct="openGeneralProject($event)"
      @open-video="openCreationDataInVideo"
    />

    <ProjectCreationAgent
      v-else-if="activeMenu === 'project-agent'"
      :token="authToken"
      :initial-project-id="agentProjectId"
      @project-created="handleProjectAgentCreated"
      @open-direct="openGeneralProject($event)"
      @open-video="openCreationDataInVideo"
    />

    <AIToolboxWorkspace
      v-else-if="activeMenu === 'toolbox'"
      :token="authToken"
      :storage-base="appInfo?.storageBase"
      :api-base="appInfo?.apiBase"
      @back="activeMenu = 'projects'"
    />

        <VideoEditorWorkspace
      v-else-if="activeMenu === 'video-editor'"
      :token="authToken"
      :storage-base="appInfo?.storageBase"
      :api-base="appInfo?.apiBase"
      :selected-account-id="selectedAccountId"
      :video-model="model"
      :initial-project-id="activeProjectId"
      @open-project="openProjectDetail"
      @back="activeMenu = 'projects'"
    />

    <div v-else class="app-empty-state"></div>

    <div v-if="showSettings" class="modal-backdrop settings-backdrop" @click.self="showSettings = false">
      <section class="account-modal settings-modal">
        <div class="modal-heading">
          <div><span>应用设置</span><h2>设置中心</h2></div>
          <button @click="showSettings = false">×</button>
        </div>

        <div class="settings-layout">
          <nav class="settings-tabs" aria-label="设置分类">
            <button :class="{ active: settingsTab === 'models' }" :aria-current="settingsTab === 'models' ? 'page' : undefined" @click="settingsTab = 'models'">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4h8l4 4v8l-4 4H8l-4-4V8l4-4Z"/><circle cx="9" cy="10" r="1"/><circle cx="15" cy="10" r="1"/><path d="M9 15h6"/></svg>
              <span><strong>模型管理</strong><small>API 与生成模型</small></span>
            </button>
            <button :class="{ active: settingsTab === 'general' }" :aria-current="settingsTab === 'general' ? 'page' : undefined" @click="settingsTab = 'general'">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M6 14v6"/></svg>
              <span><strong>运行设置</strong><small>输出与自动化</small></span>
            </button>
          </nav>

          <div class="settings-content">
            <ModelManagerPanel v-if="settingsTab === 'models'" :token="authToken" />


        <template v-else>
          <div class="settings-form">
            <div class="settings-grid">
              <label class="settings-field">
                <span>自动下载结果</span>
                <span class="settings-toggle-inline">
                  <small>任务完成后保存到输出目录</small>
                  <input v-model="settings.autoDownload" type="checkbox" />
                </span>
              </label>
            </div>

            <div class="settings-field wide">
              <span>项目存储目录</span>
              <div class="directory-row">
                <input v-model="settings.storageDir" readonly />
                <button @click="chooseStorageDirectory">选择</button>
                <button @click="openStorageDirectory">打开</button>
              </div>
              <p class="settings-storage-hint">项目数据、素材与视频输出都保存在此目录；视频结果位于其 output 子目录。修改后重启客户端生效；不会自动搬移原目录的数据。</p>
              <button type="button" class="storage-structure-toggle" :aria-expanded="showStorageStructure" @click="showStorageStructure = !showStorageStructure">
                <span>{{ showStorageStructure ? '隐藏子目录结构' : '显示子目录结构' }}</span>
                <svg viewBox="0 0 24 24" aria-hidden="true" :class="{ open: showStorageStructure }"><path d="m6 9 6 6 6-6"/></svg>
              </button>
              <div v-if="showStorageStructure" class="storage-structure">
                <table>
                  <thead>
                    <tr><th>子目录 / 文件</th><th>内容</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in storageStructure" :key="item.path">
                      <td><code>{{ item.path }}</code></td>
                      <td>{{ item.desc }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div class="settings-actions">
            <button class="login-button" @click="saveSettings">保存设置</button>
            <p v-if="settingsMessage" class="account-message">{{ settingsMessage }}</p>
          </div>
        </template>
          </div>
        </div>
      </section>
    </div>

    <ProjectFileTree v-model:visible="showProjectFiles" />

    </template>
  </main>
</template>





<style>
.workspace-choice-overlay{position:fixed;inset:0;z-index:600;display:grid;place-items:center;padding:30px;background:#11182777}.workspace-choice{width:min(830px,94vw);padding:30px;border-radius:22px;background:var(--theme-bg-elevated);color:var(--theme-text-primary);box-shadow:0 30px 90px #0005}.workspace-choice>header{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}.workspace-choice header span{font-size:12px;color:var(--theme-accent);letter-spacing:2px}.workspace-choice h2{margin:10px 0;font-size:24px}.workspace-choice header button{border:0;background:transparent;color:var(--theme-text-secondary);font-size:28px;cursor:pointer}.workspace-choice>div{display:grid;grid-template-columns:1fr 1fr;gap:18px}.workspace-choice>div>button{text-align:left;display:flex;flex-direction:column;align-items:flex-start;padding:27px;border:1px solid var(--theme-border-subtle);border-radius:16px;background:var(--theme-bg-card);color:var(--theme-text-primary);cursor:pointer}.workspace-choice>div>button:hover{border-color:var(--theme-accent);background:var(--theme-accent-soft)}.workspace-choice small{font-size:11px;color:var(--theme-text-secondary);letter-spacing:1px}.workspace-choice strong{font-size:25px;margin:20px 0 8px}.workspace-choice p{font-size:13px;line-height:1.9;color:var(--theme-text-secondary)}.workspace-choice>div span{font-size:12px;font-weight:600;color:var(--theme-accent);margin-top:15px}
</style>
