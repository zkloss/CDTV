<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { desktopBackendRequest } from '../utils/desktopApi.js'
import FinishedVideoTrackPreview from './FinishedVideoTrackPreview.vue'

const props = defineProps({
  token: { type: String, default: 'local-storage' },
  storageBase: { type: String, default: '' },
  apiBase: { type: String, default: '' },
  selectedAccountId: { type: String, default: '' },
  videoModel: { type: String, default: 'Seedance 2.0 Fast' },
  initialProjectId: { type: String, default: '' },
})

const emit = defineEmits(['back', 'open-project'])

// 视图层级：'list' (选项目卡片网格) | 'editor' (选中项目的剪辑台)
const viewMode = ref(props.initialProjectId ? 'editor' : 'list')
const searchKeyword = ref('')

// 项目列表与当前项目
const projects = ref([])
const activeProjectId = ref('')
const projectDetail = ref(null)
const loading = ref(false)
const saving = ref(false)
const toastMessage = ref('')
const toastType = ref('info')
let toastTimer = null

function showToast(msg, type = 'info', duration = 3000) {
  toastMessage.value = msg
  toastType.value = type
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastMessage.value = '' }, duration)
}

function cleanError(err) {
  return String(err?.message || err || '未知错误').replace(/^Error:\s*/, '')
}

function fileDownloadUrl(fileId) {
  const id = String(fileId || '').trim()
  if (!id) return ''
  const base = id.startsWith('local_') ? props.storageBase : props.apiBase
  return `${base}/file/${encodeURIComponent(id)}/download`
}

function absoluteMediaUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//i.test(path) || path.startsWith('data:')) return path
  return fileDownloadUrl(path)
}

// 获取分镜视频播放地址
function getShotVideoUrl(shot) {
  if (!shot) return ''
  const fid = shot.mixedVideoFileId || shot.resultFileId
  if (fid) {
    const u = fileDownloadUrl(fid)
    return u ? `${u}#t=0.001` : ''
  }
  if (shot.resultUrl) {
    const u = absoluteMediaUrl(shot.resultUrl)
    return u ? `${u}#t=0.001` : ''
  }
  return ''
}

// 获取分镜海报/封面
function getShotPoster(shot) {
  if (!shot) return ''
  const frame = shot.continuityTailFrame || shot.continuitySourceFrame
  if (frame?.fileId) return fileDownloadUrl(frame.fileId)
  if (frame?.url) return absoluteMediaUrl(frame.url)
  if (shot.coverId) return fileDownloadUrl(shot.coverId)
  if (shot.cover) return absoluteMediaUrl(shot.cover)
  return ''
}

// 缩略图首帧解码
function onThumbVideoLoaded(e) {
  try {
    const v = e.target
    if (v && v.currentTime < 0.05) {
      v.currentTime = 0.05
    }
  } catch (_) {}
}

// 悬停预览
function onThumbMouseEnter(e) {
  try {
    const v = e.currentTarget.querySelector('video')
    if (v) v.play().catch(() => {})
  } catch (_) {}
}

function onThumbMouseLeave(e) {
  try {
    const v = e.currentTarget.querySelector('video')
    if (v) {
      v.pause()
      v.currentTime = 0.05
    }
  } catch (_) {}
}

async function loadProjects() {
  loading.value = true
  try {
    const list = await desktopBackendRequest('GET', '/video-project/list', props.token)
    projects.value = Array.isArray(list) ? list : []
    if (projects.value.length) {
      if (props.initialProjectId && projects.value.some(p => String(p.id) === String(props.initialProjectId))) {
        activeProjectId.value = String(props.initialProjectId)
        viewMode.value = 'editor'
        await loadActiveProject()
      } else if (viewMode.value === 'editor') {
        if (!activeProjectId.value || !projects.value.some(p => String(p.id) === activeProjectId.value)) {
          activeProjectId.value = String(projects.value[0].id)
        }
        await loadActiveProject()
      }
    }
  } catch (err) {
    showToast(`加载项目失败: ${cleanError(err)}`, 'error')
  } finally {
    loading.value = false
  }
}

// 点击卡片进入具体作品剪辑台
async function openProjectEditor(project) {
  activeProjectId.value = String(project.id)
  viewMode.value = 'editor'
  await loadActiveProject()
}

// 从剪辑台返回项目选择列表
function backToProjectList() {
  activeProjectId.value = ''
  viewMode.value = 'list'
}

// 分集/章节状态
const currentEpisodeId = ref('')

const episodeChips = computed(() => {
  if (!projectDetail.value) return []
  const epMap = projectDetail.value.episodes
  if (!epMap || typeof epMap !== 'object') return []
  const list = []
  for (const [id, ep] of Object.entries(epMap)) {
    if (!ep || typeof ep !== 'object') continue
    const title = ep.title || (String(id).includes('旁白') ? '开局旁白 / 序幕' : `第 ${id} 集`)
    const shots = Array.isArray(ep.storyboards) ? ep.storyboards : []
    list.push({
      id: String(id),
      title,
      shotCount: shots.length,
      storyboards: shots
    })
  }
  list.sort((a, b) => {
    const aIsPrologue = /旁白|序幕/.test(a.title)
    const bIsPrologue = /旁白|序幕/.test(b.title)
    if (aIsPrologue && !bIsPrologue) return -1
    if (!aIsPrologue && bIsPrologue) return 1
    return a.title.localeCompare(b.title, 'zh-CN', { numeric: true })
  })
  return list
})

const totalProjectShotCount = computed(() => {
  if (episodeChips.value.length > 0) {
    return episodeChips.value.reduce((acc, ep) => acc + (ep.shotCount || 0), 0)
  }
  return projectDetail.value?.storyboards?.length || 0
})

const storyboards = computed(() => {
  if (!projectDetail.value) return []
  if (currentEpisodeId.value && projectDetail.value.episodes?.[currentEpisodeId.value]) {
    const ep = projectDetail.value.episodes[currentEpisodeId.value]
    return Array.isArray(ep.storyboards) ? ep.storyboards : []
  }
  return Array.isArray(projectDetail.value.storyboards) ? projectDetail.value.storyboards : []
})

function switchEpisode(epId) {
  if (!epId || currentEpisodeId.value === String(epId)) return
  if (currentEpisodeId.value && projectDetail.value?.episodes?.[currentEpisodeId.value]) {
    projectDetail.value.episodes[currentEpisodeId.value].storyboards = storyboards.value
  }
  currentEpisodeId.value = String(epId)
  if (projectDetail.value) {
    projectDetail.value.currentEpisodeId = String(epId)
    if (projectDetail.value.episodes?.[epId]?.storyboards) {
      projectDetail.value.storyboards = projectDetail.value.episodes[epId].storyboards
    }
  }
  selectedSeamIndex.value = 0
  const ep = episodeChips.value.find(e => String(e.id) === String(epId))
  showToast(`已切换至「${ep?.title || '该集'}」（本集共 ${ep?.shotCount || 0} 镜）`, 'info', 1800)
}

async function loadActiveProject() {
  if (!activeProjectId.value) return
  loading.value = true
  try {
    const detail = await desktopBackendRequest('GET', `/video-project/${encodeURIComponent(activeProjectId.value)}`, props.token)
    if (detail) {
      const normalizeShots = (shots) => {
        if (!Array.isArray(shots)) return
        shots.forEach(shot => {
          if (shot.mixedVideoFileId && !shot.resultFileId) {
            shot.resultFileId = shot.mixedVideoFileId
          }
          if (shot.resultFileId && !shot.resultUrl) {
            shot.resultUrl = fileDownloadUrl(shot.resultFileId)
          }
        })
      }
      normalizeShots(detail.storyboards)
      if (detail.episodes && typeof detail.episodes === 'object') {
        Object.values(detail.episodes).forEach(ep => {
          if (ep && Array.isArray(ep.storyboards)) normalizeShots(ep.storyboards)
        })
      }
      projectDetail.value = detail

      // 初始化分集选中
      const epMap = detail.episodes
      if (epMap && typeof epMap === 'object' && Object.keys(epMap).length > 0) {
        if (detail.currentEpisodeId && epMap[detail.currentEpisodeId]) {
          currentEpisodeId.value = String(detail.currentEpisodeId)
        } else {
          const keys = Object.keys(epMap)
          const prologueKey = keys.find(k => /旁白|序幕/.test(epMap[k]?.title || ''))
          currentEpisodeId.value = prologueKey || keys[0]
        }
      } else {
        currentEpisodeId.value = ''
      }

      if (seams.value.length && selectedSeamIndex.value >= seams.value.length) {
        selectedSeamIndex.value = 0
      }
    }
  } catch (err) {
    showToast(`加载项目详情失败: ${cleanError(err)}`, 'error')
  } finally {
    loading.value = false
  }
}

async function saveProject() {
  if (!activeProjectId.value || !projectDetail.value) return
  saving.value = true
  try {
    if (currentEpisodeId.value && projectDetail.value.episodes?.[currentEpisodeId.value]) {
      projectDetail.value.episodes[currentEpisodeId.value].storyboards = storyboards.value
      if (projectDetail.value.currentEpisodeId === currentEpisodeId.value) {
        projectDetail.value.storyboards = storyboards.value
      }
    }
    await desktopBackendRequest('PUT', `/video-project/${encodeURIComponent(activeProjectId.value)}`, props.token, projectDetail.value)
    showToast('💾 剪辑与连接设置已保存成功！', 'success', 2500)
  } catch (err) {
    showToast(`保存失败: ${cleanError(err)}`, 'error')
  } finally {
    saving.value = false
  }
}

// 项目列表过滤
const filteredProjects = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return projects.value
  return projects.value.filter(p => {
    const name = String(p.name || '').toLowerCase()
    const desc = String(p.description || '').toLowerCase()
    return name.includes(kw) || desc.includes(kw)
  })
})

const stats = computed(() => {
  const list = storyboards.value
  const finished = list.filter(s => s.resultFileId || s.mixedVideoFileId || s.resultUrl).length
  return { total: list.length, finished }
})

const seams = computed(() => {
  const list = storyboards.value
  const res = []
  for (let i = 0; i < list.length - 1; i++) {
    res.push({
      index: i,
      fromIndex: i,
      toIndex: i + 1,
      fromShot: list[i],
      toShot: list[i + 1],
      fromTitle: list[i]?.title || `第 ${i + 1} 镜`,
      toTitle: list[i + 1]?.title || `第 ${i + 2} 镜`,
      mode: list[i + 1]?.continuityMode || 'transition',
      occlusion: list[i + 1]?.occlusionObject || 'smoke_fog',
      momentum: list[i + 1]?.cameraMomentum || list[i + 1]?.occlusionDirection || 'push_in',
    })
  }
  return res
})

const selectedSeamIndex = ref(0)
const currentSeam = computed(() => seams.value[selectedSeamIndex.value] || null)

// 折叠展开控制状态
const showPromptDetails = ref(false)
const showScrubberTool = ref(false)
const showMatrixTool = ref(false)
const showVoiceLockInfo = ref(false)
const showChecklist = ref(false)

// 运镜方向选项
const CAMERA_MOMENTUM_DIRECTIONS = [
  { id: 'none', label: '⏹️ 原机位无动能', text: '保持原机位不变' },
  { id: 'pan_right', label: '➡️ 镜头往右移', text: '向右平滑移动' },
  { id: 'pan_left', label: '⬅️ 镜头往左移', text: '向左平滑移动' },
  { id: 'push_in', label: '⏩ 镜头往前推', text: '快速向前推进' },
  { id: 'pull_out', label: '⏪ 镜头往后拉', text: '快速向后退远' },
  { id: 'orbit_low', label: '🔄 仰头转圈看', text: '仰视环绕移动' },
  { id: 'crane_down', label: '⬇️ 镜头往下压', text: '俯冲快速下移' },
]

// 挡镜头的物体
const OCCLUSION_OBJECT_PRESETS = [
  { id: 'none', label: '🚫 无遮挡 / 原视频', name: '无任何遮挡物', scene: '原视频纯硬切，两镜之间不添加遮挡物' },
  { id: 'smoke_fog', label: '🌫️ 烟雾 / 黑雾', name: '浓烈烟雾黑雾翻滚', scene: '最容易完全挡住视野，转场最丝滑' },
  { id: 'sword_light', label: '🗡️ 剑光 / 刀影', name: '凌厉剑光与兵器残影划过', scene: '打斗对决，刀光闪过瞬间换场景' },
  { id: 'cloak_pass', label: '🥋 披风 / 衣服擦镜', name: '人物黑色衣角与披风快速掠过镜头', scene: '人物走动自然挡住镜头' },
  { id: 'stone_pillar', label: '🪨 石碑 / 柱子', name: '近处石碑立柱快速挡住画面', scene: '场景移动时天然障碍物' },
  { id: 'tree_trunk', label: '🌲 树干 / 树林', name: '粗壮大树从镜头前经过挡住视野', scene: '室外或野外树林绝佳转场' },
  { id: 'ground_shadow', label: '🌑 地面 / 暗影', name: '镜头贴近地面焦土暗影', scene: '镜头快速向下时挡住' },
]

function detectCameraDirectionFromPrompt(prompt = '') {
  const p = String(prompt)
  if (/环绕/.test(p)) return 'orbit_low'
  if (/俯冲|下压/.test(p)) return 'crane_down'
  if (/前推|推进/.test(p)) return 'push_in'
  if (/后拉|后退/.test(p)) return 'pull_out'
  if (/左移|向左/.test(p)) return 'pan_left'
  if (/右移|向右/.test(p)) return 'pan_right'
  return 'pan_right'
}

const currentOcclusionDir = computed({
  get: () => currentSeam.value?.toShot?.occlusionDirection || detectCameraDirectionFromPrompt(currentSeam.value?.toShot?.prompt) || 'pan_right',
  set: (val) => {
    if (currentSeam.value?.toShot) currentSeam.value.toShot.occlusionDirection = val
  }
})

const currentOcclusionObj = computed({
  get: () => currentSeam.value?.toShot?.occlusionObject || 'smoke_fog',
  set: (val) => {
    if (currentSeam.value?.toShot) currentSeam.value.toShot.occlusionObject = val
  }
})

function prevShotOcclusionFormula() {
  if (!currentSeam.value) return ''
  const occ = OCCLUSION_OBJECT_PRESETS.find(o => o.id === currentOcclusionObj.value) || OCCLUSION_OBJECT_PRESETS[1]
  if (occ.id === 'none') return ''
  const dir = CAMERA_MOMENTUM_DIRECTIONS.find(d => d.id === currentOcclusionDir.value) || CAMERA_MOMENTUM_DIRECTIONS[1]
  const dirText = dir.id === 'none' ? '' : `保持${dir.text}，`
  return `【平滑衔接收尾】镜头最后2秒${dirText}${occ.name}逐渐遮住视野，结束最后一帧画面被完全挡住覆盖。`
}

function nextShotOcclusionFormula() {
  if (!currentSeam.value) return ''
  const occ = OCCLUSION_OBJECT_PRESETS.find(o => o.id === currentOcclusionObj.value) || OCCLUSION_OBJECT_PRESETS[1]
  if (occ.id === 'none') return ''
  const dir = CAMERA_MOMENTUM_DIRECTIONS.find(d => d.id === currentOcclusionDir.value) || CAMERA_MOMENTUM_DIRECTIONS[1]
  const dirText = dir.id === 'none' ? '' : `镜头继续保持${dir.text}，不急刹不顿挫；`
  return `【平滑衔接起步·不卡顿】第0秒以被挡住的画面起步，${dirText}【移开挡物】${occ.name}顺着镜头快速移开，平滑露出新场景与人物动作，两镜连贯自然无割裂。`
}

function injectOcclusionToPrevShot() {
  if (!currentSeam.value) return
  const prevShot = currentSeam.value.fromShot
  const formula = prevShotOcclusionFormula()
  let clean = (prevShot.prompt || '').replace(/【运镜动能与遮挡收尾】[^\r\n]+|【平滑衔接收尾】[^\r\n]+/g, '').trim()
  prevShot.prompt = (clean ? clean + '\n' : '') + formula
  saveProject()
  showToast(`✅ 已帮第 ${currentSeam.value.fromIndex + 1} 镜末尾加上挡镜头提示词！`, 'success')
}
function injectOcclusionToNextShot() {
  if (!currentSeam.value) return
  const nextShot = currentSeam.value.toShot
  const formula = nextShotOcclusionFormula()
  let clean = (nextShot.prompt || '').replace(/【运镜动能守恒·连续不顿】[^\r\n]+|【遮挡退出过渡】[^\r\n]+|【平滑衔接起步·不卡顿】[^\r\n]+|【移开挡物】[^\r\n]+/g, '').trim()
  nextShot.prompt = formula + (clean ? '\n' + clean : '')
  nextShot.continuityMode = 'transition'
  nextShot.inheritPrevTail = true
  saveProject()
  showToast(`✅ 已帮第 ${currentSeam.value.toIndex + 1} 镜开头加上移开提示词，并切换为顺畅转场！`, 'success')
}
function applyBothOcclusion() {
  injectOcclusionToPrevShot()
  injectOcclusionToNextShot()
  showToast(`✨ 前后两镜已全部写好！您可以点击右侧“立即试看”检查效果！`, 'success', 4500)
}

function setSeamMode(mode) {
  if (!currentSeam.value) return
  const nextShot = currentSeam.value.toShot
  nextShot.continuityMode = mode
  if (mode === 'transition') {
    nextShot.inheritPrevTail = true
  } else if (mode === 'matchCut') {
    nextShot.inheritPrevTail = false
  } else if (mode === 'raw') {
    nextShot.inheritPrevTail = false
    nextShot.occlusionObject = 'none'
    nextShot.cameraMomentum = 'none'
  } else {
    nextShot.inheritPrevTail = true
  }
  saveProject()
  const modeNames = {
    transition: '🌊 顺畅转场（完全不卡顿穿帮）',
    exact: '🏃 动作接着演（同一个地方动作连贯）',
    matchCut: '🎬 直接换镜头（换个视角看）',
    raw: '🎞️ 原视频纯拼接（硬切无特效）'
  }
  showToast(`已设为: ${modeNames[mode] || mode}`, 'success')
}

// 动作截取（中间帧）
const scrubberFraction = ref(0.85)
const extractingFrame = ref(false)

async function extractScrubFrame(fraction) {
  if (!currentSeam.value) return
  scrubberFraction.value = fraction
  extractingFrame.value = true
  const prevShot = currentSeam.value.fromShot
  const nextShot = currentSeam.value.toShot
  const videoFileId = prevShot.mixedVideoFileId || prevShot.resultFileId
  if (!videoFileId && !prevShot.resultUrl) {
    showToast('⚠️ 上一镜还没生成视频，先生成视频才能截取画面哦', 'warning')
    extractingFrame.value = false
    return
  }
  showToast(`⏱️ 正在截取上一镜动作的 ${Math.round(fraction * 100)}% 画面…`, 'info', 2500)
  try {
    const res = await desktopBackendRequest('POST', '/video/extract-last-frame', props.token, {
      fileId: videoFileId,
      url: prevShot.resultUrl,
      fraction,
    })
    if (res && (res.fileId || res.url)) {
      nextShot.continuityTailFrame = { fileId: res.fileId, url: res.url, isActionScrub: true }
      nextShot.continuitySourceFrame = { fileId: res.fileId, url: res.url }
      nextShot.inheritPrevTail = true
      await saveProject()
      showToast(`✅ 成功截取动作画面，下一镜会接着这个动作演！`, 'success')
    } else {
      throw new Error(res?.message || '截取失败')
    }
  } catch (err) {
    showToast(`截取失败: ${cleanError(err)}`, 'error')
  } finally {
    extractingFrame.value = false
  }
}

// 电影变焦九宫格
const generatingMatrix = ref(false)
async function generateMatrix() {
  if (!currentSeam.value) return
  const prevShot = currentSeam.value.fromShot
  const nextShot = currentSeam.value.toShot
  const tailFrame = nextShot.continuityTailFrame || nextShot.continuitySourceFrame
  if (!tailFrame?.fileId && !tailFrame?.url) {
    showToast('⚠️ 请先提取上一镜画面，才能帮您生成不同角度', 'warning')
    return
  }
  generatingMatrix.value = true
  showToast('🎬 正在为您生成 9 个电影不同拍摄角度（约 20 秒）…', 'info', 6000)
  try {
    const res = await desktopBackendRequest('POST', '/video/generate-camera-matrix', props.token, {
      fileId: tailFrame.fileId,
      url: tailFrame.url,
      model: props.videoModel || '',
    })
    if (res && res.fileId) {
      nextShot.cameraMatrixImage = { fileId: res.fileId, url: res.url }
      await saveProject()
      showToast('✅ 9个电影角度已生成好！', 'success')
    } else {
      throw new Error(res?.message || '生成未返回有效图片')
    }
  } catch (err) {
    showToast(`角度生成失败: ${cleanError(err)}`, 'error')
  } finally {
    generatingMatrix.value = false
  }
}

// 连续试看弹窗及定位控制
const trackPreviewVisible = ref(false)
const previewInitialVideoId = ref('')
const previewInitialOffset = ref(0)
const previewAutoPlay = ref(false)
const previewInitialCompareMode = ref(false)

// 专门试看当前接缝连接效果（定位到上一镜末尾 2.5 秒，跨越接缝播放下一镜）

// 接收来自试看监视器内的实时调换指令
function handleSeamUpdateFromPreview(payload) {
  const { seamIndex, occlusion, momentum, mode, save } = payload
  if (seamIndex >= 0 && seamIndex < seams.value.length) {
    selectedSeamIndex.value = seamIndex
    if (occlusion) currentOcclusionObj.value = occlusion
    if (momentum) currentOcclusionDir.value = momentum
    const seam = seams.value[seamIndex]
    if (seam?.toShot) {
      if (mode) seam.toShot.continuityMode = mode
      if (momentum) {
        seam.toShot.cameraMomentum = momentum
        seam.toShot.occlusionDirection = momentum
      }
      if (occlusion) seam.toShot.occlusionObject = occlusion
    }
    if (save) {
      applyBothOcclusion()
      saveProject()
      showToast(`✅ 已更新【第 ${seamIndex + 1} 镜 ➔ 第 ${seamIndex + 2} 镜】并写入提示词！`, 'success', 2500)
    }
  }
}

function testCurrentSeam() {
  if (!currentSeam.value) {
    openFullTrackPreview()
    return
  }
  previewInitialCompareMode.value = false
  const fromShot = currentSeam.value.fromShot
  const fromVid = exportVideosList.value.find(v => String(v.id) === String(fromShot?.id))
  if (fromVid) {
    previewInitialVideoId.value = String(fromShot.id)
    const dur = fromVid.duration || fromShot.videoDuration || 8
    previewInitialOffset.value = Math.max(0, dur - 2.5)
    previewAutoPlay.value = true
    trackPreviewVisible.value = true
    showToast(`🎬 正在检验【第 ${currentSeam.value.fromIndex + 1} 镜 ➔ 第 ${currentSeam.value.toIndex + 1} 镜】连接效果…`, 'info', 2500)
  } else {
    const toShot = currentSeam.value.toShot
    const toVid = exportVideosList.value.find(v => String(v.id) === String(toShot?.id))
    if (toVid) {
      previewInitialVideoId.value = String(toShot.id)
      previewInitialOffset.value = 0
      previewAutoPlay.value = true
      trackPreviewVisible.value = true
    } else {
      openFullTrackPreview()
    }
  }
}

function testRawSeam() {
  if (!currentSeam.value) {
    openFullTrackPreview()
    return
  }
  const fromShot = currentSeam.value.fromShot
  const fromVid = exportVideosList.value.find(v => String(v.id) === String(fromShot?.id))
  if (fromVid) {
    previewInitialVideoId.value = String(fromShot.id)
    const dur = fromVid.duration || fromShot.videoDuration || 8
    previewInitialOffset.value = Math.max(0, dur - 2.5)
    previewAutoPlay.value = true
    previewInitialCompareMode.value = true
    trackPreviewVisible.value = true
    showToast(`🔀 已开启【上下两版同屏对比】（上屏未消顿硬切 vs 下屏平滑融接）！`, 'info', 2500)
  } else {
    testCurrentSeam()
  }
}

// 从头连续完整试看
function openFullTrackPreview() {
  previewInitialVideoId.value = exportVideosList.value[0]?.id || ''
  previewInitialOffset.value = 0
  previewAutoPlay.value = true
  trackPreviewVisible.value = true
}

const exportVideosList = computed(() => {
  return storyboards.value.map((s, idx) => {
    const fid = s.mixedVideoFileId || s.resultFileId
    return {
      id: s.id,
      fileId: fid,
      title: s.title || `第 ${idx + 1} 镜`,
      src: fid ? fileDownloadUrl(fid) : absoluteMediaUrl(s.resultUrl),
      duration: s.videoDuration || 8,
      occlusion: s.occlusionObject || 'smoke_fog',
      momentum: s.cameraMomentum || s.occlusionDirection || 'push_in',
      mode: s.continuityMode || 'transition',
    }
  }).filter(v => v.src)
})

watch(() => props.initialProjectId, (newId) => {
  if (newId && newId !== activeProjectId.value) {
    activeProjectId.value = String(newId)
    viewMode.value = 'editor'
    loadActiveProject()
  } else if (!newId) {
    activeProjectId.value = ''
    viewMode.value = 'list'
  }
})

onMounted(() => {
  if (props.initialProjectId) {
    activeProjectId.value = String(props.initialProjectId)
    viewMode.value = 'editor'
  } else {
    activeProjectId.value = ''
    viewMode.value = 'list'
  }
  loadProjects()
})
</script>

<template>
  <div class="video-editor-workspace">
    <!-- ==================== 第一层：选择剪辑作品列表 (卡片网格) ==================== -->
    <template v-if="viewMode === 'list'">
      <header class="editor-header hub-header">
        <div class="header-left">
          <div class="header-badge">
            <span class="badge-icon">✂️</span>
            <strong>视频剪辑与镜头连接</strong>
          </div>
          <span class="hub-subtitle">选择需要精细剪辑与镜头连接的作品，消除交接处的卡顿与顿挫</span>
        </div>

        <div class="header-right">
          <label class="hub-search-box">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
            <input v-model="searchKeyword" type="search" placeholder="搜索作品名称…" />
          </label>
          <div class="project-summary-tag">
            <span>可剪辑作品: <b>{{ filteredProjects.length }}</b></span>
          </div>
        </div>
      </header>

      <!-- 加载中 -->
      <div v-if="loading && !projects.length" class="editor-loading">
        <div class="loading-spin"></div>
        <span>正在读取作品列表…</span>
      </div>

      <!-- 空数据 -->
      <div v-else-if="!projects.length" class="editor-empty">
        <div class="empty-icon">🎬</div>
        <strong>暂无可剪辑的作品</strong>
        <p>请先在“短剧创作”或“通用视频”中创建分镜后，再来这里进行视频剪辑与镜头连接。</p>
      </div>

      <!-- 作品卡片网格列表 -->
      <main v-else class="hub-body">
        <div class="hub-grid-title">
          <h2>全部剪辑作品 ({{ filteredProjects.length }})</h2>
          <span>点击任意作品进入专属剪辑工作台</span>
        </div>

        <div class="projects-card-grid">
          <article
            v-for="proj in filteredProjects"
            :key="proj.id"
            class="project-select-card"
            @click="openProjectEditor(proj)"
          >
            <div class="card-top-row">
              <span class="card-badge">视频剪辑作品</span>
              <svg class="card-arrow-icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 10h10m-4-4 4 4-4 4"/></svg>
            </div>

            <h3 class="card-title">{{ proj.name || '未命名作品' }}</h3>
            <p class="card-desc">{{ proj.description || '点击进入镜头连接、过渡与动能平滑剪辑' }}</p>

            <div class="card-stats-row">
              <span class="stat-chip">
                <i class="dot shot-dot"></i>
                <b>{{ proj.storyboardCount || proj.storyboards?.length || 0 }}</b> 分镜
              </span>
              <span class="stat-chip">
                <i class="dot video-dot"></i>
                <b>{{ proj.completedCount || 0 }}</b> 成片
              </span>
              <span class="stat-chip">
                <i class="dot seam-dot"></i>
                <b>{{ Math.max(0, (proj.storyboardCount || proj.storyboards?.length || 1) - 1) }}</b> 处接缝
              </span>
            </div>

            <footer class="card-footer">
              <time class="card-time">更新于 {{ proj.updateTime ? String(proj.updateTime).replace('T', ' ').slice(0, 16) : '--' }}</time>
              <button type="button" class="btn-enter-editor">进入剪辑与连接 ➔</button>
            </footer>
          </article>
        </div>
      </main>
    </template>

    <!-- ==================== 第二层：当前选中作品的剪辑与连接工作台 ==================== -->
    <template v-else>
      <!-- 顶部状态栏：含「< 返回选择作品」大按钮 -->
      <header class="editor-header">
        <div class="header-left">
          <button type="button" class="btn-back-to-list" @click="backToProjectList">
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="m15 18-6-6 6-6"/>
            </svg>
            <span>返回选择作品</span>
          </button>

          <div class="header-badge">
            <span class="badge-icon">✂️</span>
            <strong>镜头剪辑与连接</strong>
          </div>

          <div class="project-selector">
            <span>当前作品：</span>
            <select v-model="activeProjectId" @change="loadActiveProject">
              <option v-for="p in projects" :key="p.id" :value="String(p.id)">
                {{ p.name || '未命名作品' }} (共 {{ p.storyboardCount || p.storyboards?.length || 0 }} 镜)
              </option>
            </select>
          </div>
        </div>

        <div class="header-right">
          <div class="project-summary-tag">
            <span v-if="episodeChips.length > 0">当前集分镜: <b>{{ stats.total }}</b></span>
            <span v-else>分镜总数: <b>{{ stats.total }}</b></span>
            <span>已做好视频: <b>{{ stats.finished }}</b></span>
            <span>需连接处: <b>{{ seams.length }}</b></span>
            <span v-if="episodeChips.length > 0">全剧分镜: <b>{{ totalProjectShotCount }}</b></span>
          </div>
          <button type="button" class="btn-preview-track highlight-btn" @click="openFullTrackPreview">
            ▶️ 连续播放试看（检查顺不顺）
          </button>
          <button type="button" class="btn-save-project" :disabled="saving" @click="saveProject">
            {{ saving ? '正在保存…' : '💾 保存设置' }}
          </button>
        </div>
      </header>

      <!-- 短剧多集 / 章节切换栏（已为您分好旁白与各集） -->
      <nav v-if="episodeChips.length > 0" class="editor-episode-bar" aria-label="分集切换">
        <div class="episode-bar-inner">
          <span class="episode-bar-label">分集 / 章节：</span>
          <div class="editor-episode-chips">
            <button
              v-for="ep in episodeChips"
              :key="ep.id"
              type="button"
              class="editor-episode-chip"
              :class="{ active: currentEpisodeId === String(ep.id) }"
              @click="switchEpisode(ep.id)"
            >
              <span class="chip-icon">📑</span>
              <strong class="chip-title">{{ ep.title }}</strong>
              <small class="chip-count">{{ ep.shotCount }} 镜</small>
            </button>
          </div>
          <span class="episode-bar-hint">（已为您分好集，点击即可切换不同集的分镜进行无缝衔接与剪辑）</span>
        </div>
      </nav>

      <!-- 加载中 -->
      <div v-if="loading" class="editor-loading">
        <div class="loading-spin"></div>
        <span>正在载入作品与分镜连接数据…</span>
      </div>

      <!-- 空数据 -->
      <div v-else-if="!storyboards.length" class="editor-empty">
        <div class="empty-icon">🎬</div>
        <strong>这个作品还没有分镜哦</strong>
        <p>可以先在“短剧创作”中添加好镜头画面，再来这里连接消除卡顿！</p>
        <button type="button" class="btn-back-to-list" style="margin-top: 10px;" @click="backToProjectList">
          ← 返回作品列表
        </button>
      </div>

      <!-- 主体：两两镜头连接导轨与新手向导 -->
      <main v-else class="editor-body">
        <!-- 镜头时间线：点击连接点 -->
        <section class="timeline-strip-container">
          <div class="timeline-strip-head">
            <div class="timeline-title">
              <strong>🎬 镜头顺序时间线（鼠标移到画面上可直接试看片段，点击连接点进行设置）：</strong>
            </div>
          </div>

          <div class="timeline-cards-track">
            <template v-for="(shot, idx) in storyboards" :key="shot.id">
              <!-- 镜头卡片 -->
              <div
                class="shot-node-card"
                @mouseenter="onThumbMouseEnter"
                @mouseleave="onThumbMouseLeave"
              >
                <div class="shot-node-head">
                  <span class="shot-idx-tag">第 {{ idx + 1 }} 镜</span>
                  <span class="shot-name">{{ shot.title || `镜头 ${idx + 1}` }}</span>
                </div>
                <div class="shot-thumb-box">
                  <video
                    v-if="getShotVideoUrl(shot)"
                    :src="getShotVideoUrl(shot)"
                    :poster="getShotPoster(shot)"
                    muted
                    playsinline
                    preload="auto"
                    @loadeddata="onThumbVideoLoaded"
                    @loadedmetadata="onThumbVideoLoaded"
                  ></video>
                  <img
                    v-else-if="getShotPoster(shot)"
                    :src="getShotPoster(shot)"
                    alt="分镜封面"
                    class="shot-thumb-img"
                  />
                  <div v-else class="shot-thumb-placeholder">
                    <span>待生成视频</span>
                  </div>
                  <div v-if="getShotVideoUrl(shot)" class="thumb-hover-hint">▶ 悬停播放</div>
                </div>
                <div class="shot-meta-info">
                  <small>{{ shot.shotType || '画面' }} · 8秒</small>
                  <span v-if="shot.dubbingAudio" class="dubbed-pill">🎙️ 已配音</span>
                </div>
              </div>

              <!-- 连接点 -->
              <div
                v-if="idx < storyboards.length - 1"
                class="seam-connector"
                :class="{
                  active: selectedSeamIndex === idx,
                  'is-transition': storyboards[idx + 1]?.continuityMode === 'transition',
                  'is-exact': storyboards[idx + 1]?.continuityMode === 'exact',
                  'is-matchcut': storyboards[idx + 1]?.continuityMode === 'matchCut',
                }"
                @click="selectedSeamIndex = idx"
              >
                <div class="seam-pill-btn">
                  <span class="seam-link-icon">⚡</span>
                  <span class="seam-label">连接 {{ idx + 1 }} ➔ {{ idx + 2 }}</span>
                  <span class="seam-mode-tag">
                    {{ storyboards[idx + 1]?.continuityMode === 'exact' ? '动作连着演' : storyboards[idx + 1]?.continuityMode === 'matchCut' ? '换角度' : '顺畅转场' }}
                  </span>
                </div>
              </div>
            </template>
          </div>
        </section>

        <!-- 选中接缝：三步清晰向导 -->
        <section v-if="currentSeam" class="active-seam-workspace">
          <div class="seam-header-box">
            <div class="seam-title-row">
              <h2>🔗 第 {{ currentSeam.fromIndex + 1 }} 镜 ➔ 第 {{ currentSeam.toIndex + 1 }} 镜 怎么连？</h2>
              <span class="seam-tip">只需按下面 3 步走，就能让视频连起来顺滑不卡顿！</span>
            </div>
          </div>

          <div class="guide-steps-container">
            <!-- 第 1 步：选连接方式 -->
            <div class="guide-step-card">
              <div class="step-badge">第 1 步</div>
              <div class="step-main">
                <h3 class="step-title">你想怎么接这两个镜头？</h3>
                <div class="seam-choice-cards">
                  <!-- 方式 1: 顺畅转场 -->
                  <div
                    class="choice-card"
                    :class="{ active: currentSeam.toShot?.continuityMode === 'transition' || !currentSeam.toShot?.continuityMode }"
                    @click="setSeamMode('transition')"
                  >
                    <div class="choice-tag-recommend">⭐ 最推荐 · 完全不卡不穿帮</div>
                    <div class="choice-header">
                      <span class="choice-icon">🌊</span>
                      <strong>顺畅遮挡转场</strong>
                    </div>
                    <p class="choice-desc">在第 {{ currentSeam.fromIndex + 1 }} 镜快结束时用烟雾/衣角/树木挡一下，第 {{ currentSeam.toIndex + 1 }} 镜移开露出新画面，最顺畅毫无卡顿！</p>
                  </div>

                  <!-- 方式 2: 动作接着演 -->
                  <div
                    class="choice-card"
                    :class="{ active: currentSeam.toShot?.continuityMode === 'exact' }"
                    @click="setSeamMode('exact')"
                  >
                    <div class="choice-header">
                      <span class="choice-icon">🏃</span>
                      <strong>动作接着演</strong>
                    </div>
                    <p class="choice-desc">同一人在同一地点连贯做动作（如拔剑、跑步）。下一镜直接接着上一镜最后一帧继续演。</p>
                  </div>

                  <!-- 方式 3: 换机位视角 -->
                  <div
                    class="choice-card"
                    :class="{ active: currentSeam.toShot?.continuityMode === 'matchCut' }"
                    @click="setSeamMode('matchCut')"
                  >
                    <div class="choice-header">
                      <span class="choice-icon">🎬</span>
                      <strong>换个视角看</strong>
                    </div>
                    <p class="choice-desc">换个远景、特写或不同角度看。不强制上一镜尾帧，自由切换拍摄机位视角。</p>
                  </div>

                  <!-- 方式 4: 原视频纯拼接 -->
                  <div
                    class="choice-card"
                    :class="{ active: currentSeam.toShot?.continuityMode === 'raw' }"
                    @click="setSeamMode('raw')"
                  >
                    <div class="choice-header">
                      <span class="choice-icon">🎞️</span>
                      <strong>原视频纯拼接</strong>
                    </div>
                    <p class="choice-desc">两镜直接按原视频硬切前后拼接，不添加任何遮挡物或运镜过渡，保持原片最原始拼接样貌。</p>
                  </div>
                </div>
              </div>
            </div>

            <!-- 第 2 步：细节微调 -->
            <div class="guide-step-card" v-if="currentSeam.toShot?.continuityMode === 'transition' || !currentSeam.toShot?.continuityMode">
              <div class="step-badge">第 2 步</div>
              <div class="step-main">
                <h3 class="step-title">简单选两项（系统已帮您选好最顺畅的，也可以点别的）：</h3>
                
                <div class="options-row-group">
                  <div class="option-subgroup">
                    <span class="group-label">1. 镜头往哪边移？（前后两镜保持同一方向移动，就不会卡顿）</span>
                    <div class="pills-flex">
                      <button
                        v-for="d in CAMERA_MOMENTUM_DIRECTIONS"
                        :key="d.id"
                        type="button"
                        class="pill-item"
                        :class="{ selected: currentOcclusionDir === d.id }"
                        @click="currentOcclusionDir = d.id"
                      >
                        {{ d.label }}
                      </button>
                    </div>
                  </div>

                  <div class="option-subgroup">
                    <span class="group-label">2. 用什么东西挡一下镜头？（选一个符合剧情的物体）</span>
                    <div class="pills-flex">
                      <button
                        v-for="o in OCCLUSION_OBJECT_PRESETS"
                        :key="o.id"
                        type="button"
                        class="pill-item"
                        :class="{ selected: currentOcclusionObj === o.id }"
                        @click="currentOcclusionObj = o.id"
                      >
                        {{ o.label }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 第 3 步：一键搞定 + 检验试看 -->
            <div class="guide-step-card highlight-step">
              <div class="step-badge">第 3 步</div>
              <div class="step-main">
                <h3 class="step-title">一键帮您写好提示词，并试看效果：</h3>
                <p class="step-sub">点击下方左侧大按钮自动写好两镜防卡顿提示词；写好后点击右侧按钮直接检验试看连接效果！</p>
                
                <div class="action-btn-row">
                  <button type="button" class="btn-giant-auto-fill" @click="applyBothOcclusion">
                    ✨ 一键帮我把两镜提示词写好（自动防卡顿）
                  </button>

                  <button type="button" class="btn-giant-preview" @click="testCurrentSeam">
                    ▶️ 立即试看连接效果（带消顿）
                  </button>

                  <button type="button" class="btn-raw-preview" @click="testRawSeam">
                    🎞️ 试看原视频纯拼接（无特效）
                  </button>

                  <button
                    type="button"
                    class="btn-toggle-details"
                    @click="showPromptDetails = !showPromptDetails"
                  >
                    {{ showPromptDetails ? '▲ 收起提示词详情' : '▼ 点击查看写好的提示词' }}
                  </button>
                </div>

                <!-- ⚡ 全自动消顿引擎状态标识 -->
                <div class="engine-auto-pill" title="全自动技术，已默认自动开启生效：提前1.5秒后台预解码下一镜首帧，接缝点0ms无感秒级推帧，前后速度守恒无缝融接，全程全自动运行，无需手动操作！">
                  <span class="engine-pill-status">
                    <i class="engine-pulse-dot"></i>
                    <strong>全自动消顿引擎：已生效</strong>
                  </span>
                  <span class="engine-pill-desc">（⚡ 全程自动运行，无需手动调节：提前 1.5 秒后台预解码下一镜首帧 + 提前 0.28 秒启动平滑融接 + 0ms 秒级推帧 + 运镜动量守恒）</span>
                </div>

                <div class="how-to-verify-banner">
                  <span class="verify-icon">💡</span>
                  <div class="verify-text">
                    <strong>剪辑转场与 AI 原生生成双重保障（点击试看即可验收）：</strong>
                    <p>1. <strong>剪辑转场（立即生效·已作用）</strong>：点击上方橙色 <b>【▶️ 立即试看当前连接效果】</b>，监视器在播放到两镜交接瞬间会**实时叠加您选好的黑雾遮挡与运镜动能转场**，遮住上一镜末尾卡顿，实现 0 卡顿过渡！打包成片时也会完整合成此转场。</p>
                    <p>2. <strong>AI 原生重演（已写好提示词）</strong>：点击【一键帮我把两镜提示词写好】后，带有遮挡收尾和起步的提示词已存入分镜。若想让 AI 画面里自然长出遮挡物，可去“短剧创作”重新生成画面。</p>
                  </div>
                </div>

                <div v-show="showPromptDetails" class="prompt-preview-collapsible">
                  <div class="prompt-snippet-box">
                    <div class="snippet-header">
                      <strong>第 {{ currentSeam.fromIndex + 1 }} 镜末尾加上：</strong>
                      <button type="button" class="btn-mini-inject" @click="injectOcclusionToPrevShot">单独更新第 {{ currentSeam.fromIndex + 1 }} 镜</button>
                    </div>
                    <p>{{ prevShotOcclusionFormula() }}</p>
                  </div>

                  <div class="prompt-snippet-box highlight">
                    <div class="snippet-header">
                      <strong>第 {{ currentSeam.toIndex + 1 }} 镜开头加上：</strong>
                      <button type="button" class="btn-mini-inject" @click="injectOcclusionToNextShot">单独更新第 {{ currentSeam.toIndex + 1 }} 镜</button>
                    </div>
                    <p>{{ nextShotOcclusionFormula() }}</p>
                  </div>
                </div>
              </div>
            </div>

            <!-- 进阶实用工具箱 -->
            <div class="advanced-toolbox-card">
              <div class="toolbox-header">
                <strong>🧰 更多实用小工具（需要时点开）：</strong>
              </div>

              <div class="toolbox-items-list">
                <div class="toolbox-item">
                  <div class="toolbox-item-title" @click="showScrubberTool = !showScrubberTool">
                    <span>⏱️ 动作还没演完就被切断了？（截取动作中间帧接着演）</span>
                    <span class="toolbox-arrow">{{ showScrubberTool ? '▲' : '▼' }}</span>
                  </div>
                  <div v-show="showScrubberTool" class="toolbox-item-body">
                    <p class="body-tip">比如拔剑拔到一半、手摸到杯子还没拿起来，可以拖动滑块截取动作发生的那一刻，让下一镜接着做：</p>
                    <div class="scrub-controls-row">
                      <label>截取位置: <b>{{ Math.round(scrubberFraction * 100) }}%</b></label>
                      <input type="range" min="0.5" max="1.0" step="0.05" v-model.number="scrubberFraction" />
                      <button type="button" :disabled="extractingFrame" @click="extractScrubFrame(0.7)">70% (动作刚开始)</button>
                      <button type="button" :disabled="extractingFrame" @click="extractScrubFrame(0.8)">80% (动作做一半)</button>
                      <button type="button" :disabled="extractingFrame" @click="extractScrubFrame(0.9)">90% (快做完)</button>
                      <button type="button" :disabled="extractingFrame" @click="extractScrubFrame(0.98)">100% (结尾)</button>
                      <button type="button" class="btn-confirm-scrub" :disabled="extractingFrame" @click="extractScrubFrame(scrubberFraction)">
                        📌 截取这一秒动作帧
                      </button>
                    </div>
                  </div>
                </div>

                <div class="toolbox-item">
                  <div class="toolbox-item-title" @click="showMatrixTool = !showMatrixTool">
                    <span>🎬 想换不同的电影拍摄角度？（生成 9 个电影景别）</span>
                    <span class="toolbox-arrow">{{ showMatrixTool ? '▲' : '▼' }}</span>
                  </div>
                  <div v-show="showMatrixTool" class="toolbox-item-body">
                    <p class="body-tip">自动基于上一镜生成大远景、特写、俯视、平视等 9 个不同拍摄角度，点选即可换角度切镜头：</p>
                    <button type="button" class="btn-generate-angles" :disabled="generatingMatrix" @click="generateMatrix">
                      {{ generatingMatrix ? '正在生成 9 个电影角度…' : '✨ 点击生成 9 个不同拍摄角度' }}
                    </button>
                    <div v-if="currentSeam.toShot?.cameraMatrixImage?.fileId || currentSeam.toShot?.cameraMatrixImage?.url" class="angles-img-preview">
                      <img :src="fileDownloadUrl(currentSeam.toShot.cameraMatrixImage.fileId) || absoluteMediaUrl(currentSeam.toShot.cameraMatrixImage.url)" alt="9个电影角度" />
                    </div>
                  </div>
                </div>

                <div class="toolbox-item">
                  <div class="toolbox-item-title" @click="showVoiceLockInfo = !showVoiceLockInfo">
                    <span>🎙️ 声音检查（全片声音已锁定统一）</span>
                    <span class="toolbox-arrow">{{ showVoiceLockInfo ? '▲' : '▼' }}</span>
                  </div>
                  <div v-show="showVoiceLockInfo" class="toolbox-item-body">
                    <p class="body-tip">🔒 <strong>全剧统一音色已开启：</strong>本项目内所有角色的声音和旁白音色均已绑定锁定，每个分镜播放时都会保持一致的声音质感，不会变声！</p>
                  </div>
                </div>

                <div class="toolbox-item">
                  <div class="toolbox-item-title" @click="showChecklist = !showChecklist">
                    <span>📋 怎么看两镜接得好不好？（效果自检小清单）</span>
                    <span class="toolbox-arrow">{{ showChecklist ? '▲' : '▼' }}</span>
                  </div>
                  <div v-show="showChecklist" class="toolbox-item-body">
                    <div class="checklist-grid">
                      <span>✅ 挡镜头的物体（烟雾/衣角等）符合当前剧情，出现自然。</span>
                      <span>✅ 转场瞬间画面被基本挡住，看不到杂乱接缝。</span>
                      <span>✅ 前后两个镜头移动方向一样（比如都向右移），没有突然反转方向。</span>
                      <span>✅ 镜头速度均匀顺畅，没有先停住再启动的急刹车感。</span>
                      <span>✅ 移开挡物后，人物长相、衣服和所在地点保持连贯。</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </template>

    <!-- 连续试看弹窗组件 -->
    <FinishedVideoTrackPreview
      v-model:visible="trackPreviewVisible"
      :project-title="projectDetail?.name || '项目成片'"
      :project-id="activeProjectId"
      :videos="exportVideosList"
      :token="props.token"
      :initial-video-id="previewInitialVideoId"
      :initial-offset="previewInitialOffset"
      :auto-play="previewAutoPlay"
      :initial-compare-mode="previewInitialCompareMode"
      :seams="seams"
      :active-seam-index="selectedSeamIndex"
      @update-seam="handleSeamUpdateFromPreview"
      ai-assembly-enabled
    />

    <!-- Toast 提示条 -->
    <div v-if="toastMessage" class="editor-toast" :class="toastType">
      <span>{{ toastMessage }}</span>
    </div>
  </div>
</template>

<style scoped>
.video-editor-workspace {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--theme-bg-surface, #fcfaf6);
  color: var(--theme-text-primary, #2d261e);
  position: relative;
  overflow: hidden;
}

/* ==================== 顶部 Header ==================== */
.editor-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background: #ffffff;
  border-bottom: 1px solid #ebdccb;
  flex-shrink: 0;
  gap: 16px;
  flex-wrap: wrap;
}

.hub-header {
  padding: 14px 24px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.hub-subtitle {
  font-size: 13px;
  color: #78350f;
  margin-left: 6px;
}

.header-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #b45309;
  font-size: 15px;
}

.hub-search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #faf6f0;
  border: 1px solid #d4c5b3;
  border-radius: 8px;
  padding: 4px 10px;
  color: #78350f;
}

.hub-search-box svg {
  width: 14px;
  height: 14px;
  stroke: currentColor;
  stroke-width: 2;
  fill: none;
}

.hub-search-box input {
  border: none;
  background: transparent;
  outline: none;
  font-size: 13px;
  color: #451a03;
  width: 160px;
}

.btn-back-to-list {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid #d4c5b3;
  border-radius: 6px;
  background: #faf6f0;
  color: #7c2d12;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-back-to-list:hover {
  background: #fed7aa;
  border-color: #ea580c;
  color: #431407;
}

.project-selector {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #78350f;
}

.project-selector select {
  padding: 4px 10px;
  border: 1px solid #d4c5b3;
  border-radius: 6px;
  background: #faf6f0;
  color: #451a03;
  font-size: 13px;
  font-weight: 600;
  outline: none;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.project-summary-tag {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px;
  border-radius: 6px;
  background: #fdf2e9;
  color: #9a3412;
  font-size: 12px;
}

.project-summary-tag b {
  font-family: Consolas, monospace;
}

.btn-preview-track {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border: 1px solid #b45309;
  border-radius: 6px;
  background: #fffbeb;
  color: #b45309;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-preview-track.highlight-btn {
  background: #ea580c;
  color: #ffffff;
  border-color: #c2410c;
  box-shadow: 0 2px 6px rgba(234, 88, 12, 0.25);
}

.btn-preview-track.highlight-btn:hover {
  background: #c2410c;
  transform: translateY(-1px);
}

.btn-save-project {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 14px;
  border: 1px solid #b45309;
  border-radius: 6px;
  background: #b45309;
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.btn-save-project:hover:not(:disabled) {
  background: #92400e;
}

/* ==================== 第一层：作品选择卡片网格 ==================== */
.hub-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 32px 40px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hub-grid-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.hub-grid-title h2 {
  font-size: 18px;
  color: #431407;
  margin: 0;
}

.hub-grid-title span {
  font-size: 13px;
  color: #8c7e6c;
}

.projects-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 18px;
}

.project-select-card {
  background: #ffffff;
  border: 1px solid #ebdccb;
  border-radius: 12px;
  padding: 18px 20px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
}

.project-select-card:hover {
  border-color: #ea580c;
  transform: translateY(-3px);
  box-shadow: 0 8px 20px rgba(234, 88, 12, 0.12);
}

.card-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-badge {
  font-size: 11px;
  color: #9a3412;
  background: #fdf2e9;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}

.card-arrow-icon {
  width: 16px;
  height: 16px;
  stroke: #a89f91;
  stroke-width: 2;
  fill: none;
  transition: transform 0.2s;
}

.project-select-card:hover .card-arrow-icon {
  stroke: #ea580c;
  transform: translateX(3px);
}

.card-title {
  margin: 0;
  font-size: 16px;
  color: #431407;
  font-weight: 700;
  line-height: 1.4;
}

.card-desc {
  margin: 0;
  font-size: 12px;
  color: #78350f;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-stats-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 0;
  border-top: 1px dashed #f3e8db;
  border-bottom: 1px dashed #f3e8db;
}

.stat-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #574534;
  background: #faf6f0;
  padding: 3px 8px;
  border-radius: 4px;
}

.stat-chip b {
  font-family: Consolas, monospace;
  color: #7c2d12;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.shot-dot { background: #ea580c; }
.video-dot { background: #16a34a; }
.seam-dot { background: #0284c7; }

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 2px;
}

.card-time {
  font-size: 11px;
  color: #a89f91;
}

.btn-enter-editor {
  background: none;
  border: none;
  color: #ea580c;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  padding: 0;
}

/* ==================== 第二层：剪辑工作台主体 ==================== */
.editor-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 14px 18px 30px;
  gap: 14px;
}

/* 时间线导轨 */
.timeline-strip-container {
  background: #ffffff;
  border: 1px solid #ebdccb;
  border-radius: 10px;
  padding: 12px 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.timeline-title strong {
  font-size: 13px;
  color: #78350f;
}

.timeline-cards-track {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  padding: 10px 0 4px;
}

.shot-node-card {
  width: 148px;
  flex-shrink: 0;
  background: #faf6f0;
  border: 1px solid #e7d8c6;
  border-radius: 8px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  transition: all 0.2s;
  cursor: pointer;
}

.shot-node-card:hover {
  border-color: #f97316;
  transform: translateY(-2px);
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.08);
}

.shot-node-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
}

.shot-idx-tag {
  font-size: 11px;
  font-weight: 700;
  color: #9a3412;
  background: #fed7aa;
  padding: 1px 5px;
  border-radius: 4px;
}

.shot-name {
  font-size: 11px;
  color: #574534;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

.shot-thumb-box {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #1e1b18;
  border-radius: 5px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.shot-thumb-box video,
.shot-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.shot-thumb-placeholder {
  color: #a89f91;
  font-size: 11px;
}

.thumb-hover-hint {
  position: absolute;
  bottom: 4px;
  right: 4px;
  background: rgba(0, 0, 0, 0.65);
  color: #ffffff;
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 3px;
  pointer-events: none;
  opacity: 0.8;
}

.shot-meta-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 10px;
  color: #8c7e6c;
}

.dubbed-pill {
  color: #15803d;
  font-weight: 600;
}

/* 连接点 */
.seam-connector {
  flex-shrink: 0;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 8px;
  transition: all 0.2s;
  display: flex;
  align-items: center;
}

.seam-pill-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 6px 8px;
  border: 1px dashed #d4c5b3;
  border-radius: 6px;
  background: #fdfaf6;
  transition: all 0.15s;
}

.seam-connector:hover .seam-pill-btn {
  border-color: #f97316;
  background: #fff7ed;
}

.seam-connector.active .seam-pill-btn {
  border-style: solid;
  border-color: #ea580c;
  background: #ffedd5;
  box-shadow: 0 0 0 2px rgba(234, 88, 12, 0.2);
}

.seam-link-icon {
  font-size: 12px;
}

.seam-label {
  font-size: 11px;
  font-weight: 600;
  color: #78350f;
}

.seam-mode-tag {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: #fee2e2;
  color: #991b1b;
}

.seam-connector.is-transition .seam-mode-tag {
  background: #fef3c7;
  color: #92400e;
}

.seam-connector.is-exact .seam-mode-tag {
  background: #dcfce7;
  color: #166534;
}

/* 选中接缝控制区 */
.active-seam-workspace {
  background: #ffffff;
  border: 1px solid #ebdccb;
  border-radius: 10px;
  padding: 16px 20px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.seam-header-box {
  border-bottom: 1px solid #f3e8db;
  padding-bottom: 10px;
}

.seam-title-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  flex-wrap: wrap;
}

.seam-title-row h2 {
  font-size: 16px;
  color: #7c2d12;
  margin: 0;
}

.seam-tip {
  font-size: 13px;
  color: #a16207;
}

/* 步骤容器 */
.guide-steps-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.guide-step-card {
  display: flex;
  gap: 14px;
  background: #faf6f0;
  border: 1px solid #ede3d7;
  border-radius: 8px;
  padding: 14px 16px;
}

.guide-step-card.highlight-step {
  background: #fffbf5;
  border-color: #fed7aa;
}

.step-badge {
  flex-shrink: 0;
  height: 24px;
  padding: 0 8px;
  border-radius: 12px;
  background: #ea580c;
  color: #ffffff;
  font-size: 12px;
  font-weight: bold;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 4px rgba(234, 88, 12, 0.2);
}

.step-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-title {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
  color: #431407;
}

.step-sub {
  margin: 0;
  font-size: 12px;
  color: #78350f;
}

/* 第1步单选卡片 */
.seam-choice-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.choice-card {
  position: relative;
  border: 1px solid #d4c5b3;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.choice-card:hover {
  border-color: #f97316;
  transform: translateY(-1px);
}

.choice-card.active {
  border-color: #ea580c;
  background: #fff7ed;
  box-shadow: 0 0 0 2px rgba(234, 88, 12, 0.25);
}

.choice-tag-recommend {
  position: absolute;
  top: -8px;
  right: 10px;
  background: #ea580c;
  color: #ffffff;
  font-size: 10px;
  font-weight: bold;
  padding: 1px 6px;
  border-radius: 4px;
}

.choice-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #7c2d12;
}

.choice-icon {
  font-size: 16px;
}

.choice-desc {
  margin: 0;
  font-size: 12px;
  color: #78350f;
  line-height: 1.4;
}

/* 第2步细节选框 */
.options-row-group {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.option-subgroup {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.group-label {
  font-size: 13px;
  font-weight: 600;
  color: #7c2d12;
}

.pills-flex {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.pill-item {
  padding: 5px 12px;
  border: 1px solid #d4c5b3;
  border-radius: 6px;
  background: #ffffff;
  color: #451a03;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.pill-item:hover {
  border-color: #f97316;
  background: #fff7ed;
}

.pill-item.selected {
  border-color: #ea580c;
  background: #ea580c;
  color: #ffffff;
  font-weight: 600;
}

/* 第3步操作按钮区 */
.action-btn-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.btn-giant-auto-fill {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  background: linear-gradient(135deg, #ea580c, #c2410c);
  color: #ffffff;
  font-size: 13px;
  font-weight: bold;
  cursor: pointer;
  box-shadow: 0 3px 8px rgba(234, 88, 12, 0.35);
  transition: all 0.2s;
}

.btn-giant-auto-fill:hover {
  background: linear-gradient(135deg, #f97316, #ea580c);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(234, 88, 12, 0.45);
}

.btn-giant-preview {
  padding: 10px 20px;
  border: 1px solid #0284c7;
  border-radius: 8px;
  background: linear-gradient(135deg, #0284c7, #0369a1);
  color: #ffffff;
  font-size: 13px;
  font-weight: bold;
  cursor: pointer;
  box-shadow: 0 3px 8px rgba(2, 132, 199, 0.35);
  transition: all 0.2s;
}

.btn-giant-preview:hover {
  background: linear-gradient(135deg, #38bdf8, #0284c7);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(2, 132, 199, 0.45);
}

.btn-raw-preview {
  padding: 10px 18px;
  border: 1px solid #475569;
  border-radius: 8px;
  background: linear-gradient(135deg, #475569, #334155);
  color: #ffffff;
  font-size: 13px;
  font-weight: bold;
  cursor: pointer;
  box-shadow: 0 3px 8px rgba(51, 65, 85, 0.35);
  transition: all 0.2s;
}

.btn-raw-preview:hover {
  background: linear-gradient(135deg, #64748b, #475569);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(51, 65, 85, 0.45);
}

.btn-toggle-details {
  background: none;
  border: 1px solid #d4c5b3;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: #78350f;
  cursor: pointer;
}

.btn-toggle-details:hover {
  background: #faf6f0;
}

/* 全自动消顿引擎标识 */
.engine-auto-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 12px;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  border-radius: 8px;
  font-size: 12px;
}
.engine-pill-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #065f46;
  font-weight: 700;
}
.engine-pill-desc {
  color: #047857;
  font-size: 11.5px;
}
.engine-pulse-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
  animation: engine-pulse 1.8s infinite;
  vertical-align: middle;
}
@keyframes engine-pulse {
  0% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
  }
  70% {
    transform: scale(1.1);
    box-shadow: 0 0 0 6px rgba(16, 185, 129, 0);
  }
  100% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
  }
}

/* 检验效果说明横幅 */
.how-to-verify-banner {
  display: flex;
  gap: 10px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  padding: 10px 14px;
}

.verify-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.verify-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #14532d;
  line-height: 1.5;
}

.verify-text p {
  margin: 0;
}

/* 提示词折叠面板 */
.prompt-preview-collapsible {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px;
  margin-top: 8px;
  background: #ffffff;
  border: 1px solid #ebdccb;
  border-radius: 8px;
  padding: 12px;
}

.prompt-snippet-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #faf6f0;
  border: 1px solid #e7d8c6;
  border-radius: 6px;
  padding: 10px 12px;
}

.prompt-snippet-box.highlight {
  background: #fff7ed;
  border-color: #fed7aa;
}

.snippet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.snippet-header strong {
  font-size: 12px;
  color: #7c2d12;
}

.btn-mini-inject {
  padding: 2px 8px;
  border: 1px solid #d4c5b3;
  border-radius: 4px;
  background: #ffffff;
  font-size: 11px;
  color: #78350f;
  cursor: pointer;
}

.btn-mini-inject:hover {
  background: #fed7aa;
}

.prompt-snippet-box p {
  margin: 0;
  font-size: 12px;
  color: #451a03;
  line-height: 1.5;
  background: #ffffff;
  padding: 6px 8px;
  border-radius: 4px;
  border: 1px solid #ede3d7;
}

/* 进阶工具箱折叠卡片 */
.advanced-toolbox-card {
  border: 1px dashed #d4c5b3;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px 16px;
}

.toolbox-header strong {
  font-size: 13px;
  color: #78350f;
}

.toolbox-items-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.toolbox-item {
  border: 1px solid #ebdccb;
  border-radius: 6px;
  background: #faf6f0;
  overflow: hidden;
}

.toolbox-item-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
  color: #7c2d12;
  cursor: pointer;
  user-select: none;
}

.toolbox-item-title:hover {
  background: #f5eee4;
}

.toolbox-arrow {
  font-size: 11px;
  color: #a89f91;
}

.toolbox-item-body {
  padding: 10px 14px 14px;
  border-top: 1px solid #ede3d7;
  background: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.body-tip {
  margin: 0;
  font-size: 12px;
  color: #78350f;
  line-height: 1.4;
}

.scrub-controls-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.scrub-controls-row label {
  font-size: 12px;
  color: #451a03;
}

.scrub-controls-row input[type="range"] {
  width: 140px;
}

.scrub-controls-row button {
  padding: 4px 8px;
  border: 1px solid #d4c5b3;
  border-radius: 4px;
  background: #faf6f0;
  font-size: 11px;
  color: #451a03;
  cursor: pointer;
}

.scrub-controls-row button:hover {
  background: #fed7aa;
}

.btn-confirm-scrub {
  background: #ea580c !important;
  color: #ffffff !important;
  border: none !important;
  font-weight: bold;
}

.btn-generate-angles {
  align-self: flex-start;
  padding: 7px 14px;
  border: 1px solid #ea580c;
  border-radius: 6px;
  background: #fff7ed;
  color: #ea580c;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.btn-generate-angles:hover:not(:disabled) {
  background: #ea580c;
  color: #ffffff;
}

.angles-img-preview {
  max-width: 320px;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #e7d8c6;
}

.angles-img-preview img {
  width: 100%;
  display: block;
}

.checklist-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: #574534;
}

/* Toast */
.editor-toast {
  position: absolute;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
  z-index: 999;
  animation: toastIn 0.25s ease-out;
}

.editor-toast.success {
  background: #15803d;
  color: #ffffff;
}

.editor-toast.error {
  background: #b91c1c;
  color: #ffffff;
}

.editor-toast.info {
  background: #451a03;
  color: #ffffff;
}

.editor-toast.warning {
  background: #d97706;
  color: #ffffff;
}

@keyframes toastIn {
  from { opacity: 0; transform: translate(-50%, 10px); }
  to { opacity: 1; transform: translate(-50%, 0); }
}

.editor-loading,
.editor-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #8c7e6c;
}

.empty-icon {
  font-size: 36px;
}

.loading-spin {
  width: 28px;
  height: 28px;
  border: 3px solid #f3e8db;
  border-top-color: #ea580c;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>

<style scoped>

/* 短剧分集/章节切换栏 */
.editor-episode-bar {
  display: flex;
  align-items: center;
  padding: 10px 18px;
  margin: 0 0 16px;
  background: var(--theme-bg-surface);
  border: 1px solid var(--theme-border-subtle);
  border-radius: 12px;
}
.episode-bar-inner {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.episode-bar-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--theme-text-primary);
  white-space: nowrap;
}
.editor-episode-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.editor-episode-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 14px;
  border: 1.5px solid var(--theme-border-subtle);
  border-radius: 10px;
  background: var(--theme-bg-elevated);
  color: var(--theme-text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  transition: all .16s ease;
}
.editor-episode-chip:hover {
  border-color: #f97316;
  color: var(--theme-text-primary);
  background: var(--theme-bg-card-hover);
  transform: translateY(-1px);
}
.editor-episode-chip.active {
  border-color: #ea580c;
  background: #fff7ed;
  color: #c2410c;
  font-weight: 750;
  box-shadow: 0 2px 8px rgba(234, 88, 12, 0.15);
}
.editor-episode-chip .chip-icon {
  font-size: 14px;
}
.editor-episode-chip .chip-title {
  font-weight: 650;
}
.editor-episode-chip .chip-count {
  padding: 1px 7px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.06);
  font-size: 11.5px;
  font-weight: 600;
}
.editor-episode-chip.active .chip-count {
  background: #ffedd5;
  color: #c2410c;
}
.episode-bar-hint {
  font-size: 12px;
  color: var(--theme-text-secondary);
}

</style>
