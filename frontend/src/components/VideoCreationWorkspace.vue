<script setup>
import { projectWorkspace } from '../utils/projectWorkspace.js'
import { IMAGE_TEXT_OPTIONS, withImageTextPolicy } from '../utils/imageTextPolicy.js'
import { ROLE_REFERENCE_VERSION, rolePromptWithoutDefaultLayout, hasCustomRoleLayout, buildRoleReferencePrompt } from '../utils/roleReferenceArt.js'
import { ensureScriptShotCoverage, mergePushedItems } from '../utils/scriptShotCoverage.js'
import { alignmentForDubbing, rememberAppliedDubbing, confirmedDubbingTiming, dubbingSourceVideoId, hasAppliedDubbing, isDubbingApplied } from "../utils/breezeDubbingState.js"
import { snapshotVideoResult, restoreVideoResult, finishGenerationAttempt, resultSourceMessage, hasRejectedReferences, hasFailedAttempt, rejectedCandidate, currentContinuityReview, videoTaskFailureMessage } from "../utils/videoResultProvenance.js"
import { removeAudioAssets } from "../utils/projectAudioPolicy.js"
import { collectAudioPrompts, stableVoicePrompt, cleanAudioPrompt, cleanShotAudioPrompt, dialogueContract, sameDialogue, extractRoleVoiceInstruction } from "../utils/audioContract.js"
import { waitForDesktopApi, desktopBackendRequest, isApiAvailable } from '../utils/desktopApi.js'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import StoryboardMentionEditor from './StoryboardMentionEditor.vue'
import BaseLoadingState from './BaseLoadingState.vue'
import BaseMediaPreview from './BaseMediaPreview.vue'
import FinishedVideoTrackPreview from './FinishedVideoTrackPreview.vue'
import BreezeDubbingPanel from './BreezeDubbingPanel.vue'
import { watchForDecodedVideoFrame } from '../utils/videoCompatibility.js'
import { missingShotRoles, durationValidation } from '../utils/shotValidation.js'
import { automaticVoiceInstruction, isLegacyVoiceInstruction, voiceSignature } from '../utils/breezeVoice.js'
import { changesScene, ensureTransitions, gazeHandoffBeat, promptWithTransition, selectTransitionStrategy, stripTransitionBlock, transitionBlockOf, TRANSITION_OPTIONS } from '../utils/narrativeTransition.js'
import { roleHandoffPlan, handoffReferences, roleHandoffInstruction } from '../utils/continuityHandoff.js'
import { doorwayMovementInstruction } from '../utils/doorwayMovement.js'
import { restoreSeedanceTask } from '../utils/seedanceTaskRecovery.js'
import { needsSceneAnchor, pickSceneReference } from '../utils/sceneAnchor.js'
import { hasAuthoredCut, alignAuthoredContinuity, continuityPlanProblems, sceneCutReferences, pinSceneStart } from '../utils/continuityPlan.js'
import { environmentAt, environmentInstruction, environmentConflicts, environmentHints, shotEnvironmentConflicts, clean } from '../utils/environmentContinuity.js'
import { DEFAULT_PROJECT_STYLE, projectStyleFields, getProjectStyleDescription, getProjectStyleName, getProjectStylePrefix } from './projectFormOptions.js'

const props = defineProps({
  token: { type: String, required: true },
  apiBase: { type: String, default: 'http://127.0.0.1:8080' },
  storageBase: { type: String, default: 'http://127.0.0.1:18081' },
  selectedAccountId: { type: String, default: '' },
  videoModel: { type: String, default: 'Seedance 2.0 Fast' },
  initialCreationData: { type: Object, default: null },
  embedded: Boolean,
  workspaceKind: { type: String, default: 'drama' },
  scopeProjectId: { type: String, default: '' },
  scopeChapterId: { type: String, default: '' },
  initialVideoProjectId: { type: String, default: '' },
  productionView: { type: String, default: 'visual' },
  aiAssemblyEnabled: { type: Boolean, default: false },
})
const emit = defineEmits(['creation-data-consumed', 'production-state', 'request-plan', 'request-model-settings'])
const isGeneral = computed(() => props.workspaceKind === 'general' || projectWorkspace(availableProjects.value.find(p => String(p.id) === String(activeVideoProject.value?.projectId))) === 'general')
const materialDrawer = ref(false)
const productionCanvasRef = ref(null)
let savedProductionPayload = ''
const productionSummary = computed(() => ({
  id: String(activeVideoProject.value?.id || ''),
  shots: storyboards.value.length,
  completed: storyboards.value.filter(s => (s.resultFileId || s.resultUrl) && s.resultValidation?.passed !== false).length,
  seconds: storyboards.value.reduce((total, s) => total + Number(s.duration || 0), 0),
}))
function maintainTransitions(items) { return isGeneral.value ? items : ensureTransitions(items) }
function useProductionView() {
  const audio = props.productionView === 'audio'
  storyboards.value.forEach(s => { s.workspaceTab = audio ? 'audio' : 'visual' })
}
async function openScopedProduction() {
  if (!props.embedded || !props.scopeProjectId || activeVideoProject.value || pendingInitialCreationData.value) return
  const matching = videoProjects.value.filter(p => String(p.projectId || '') === props.scopeProjectId)
  const target = videoProjects.value.find(p => String(p.id) === props.initialVideoProjectId && String(p.projectId || '') === props.scopeProjectId)
    || matching.find(p => props.scopeChapterId && String(p.description || '').includes(`章节 ID ${props.scopeChapterId}`))
    || (isGeneral.value && !props.scopeChapterId && matching.length === 1 ? matching[0] : null)
  if (target) { await openVideoProject(target); useProductionView() }
}
watch(() => props.productionView, useProductionView)

defineExpose({ flush: saveActiveVideoProject })

const categories = [
  { key: 'all', label: '全部' },
  { key: 'role', label: '人物' },
  { key: 'scene', label: '场景' },
  { key: 'prop', label: '道具' },
  { key: 'layout', label: '白模' },
]

const VOICE_PRESET_OPTIONS = [
  { value: '', label: '🤖 自动匹配（根据描述智能推断）' },
  { value: 'longshu_v2', label: '🎙️ 苍凉史诗男声（开篇旁白 / 宏大叙事 / 沉稳大叔）' },
  { value: 'longfeiyan_v2', label: '🎙️ 霸气热血男声（评书 / 玄幻说书 / 热烈霸气）' },
  { value: 'longshuo_v2', label: '🎙️ 沉稳正剧男声（青年正剧 / 新闻播报 / 严肃理智）' },
  { value: 'longyuan_v2', label: '🎙️ 阳光温润男声（仙侠男主 / 少年少侠 / 温暖师兄）' },
  { value: 'longlaotie_v2', label: '🎙️ 豪爽粗犷男声（豪放粗汉 / 壮汉）' },
  { value: 'longjing_v2', label: '🎙️ 威严冷酷男声（宗主长老 / 反派 Boss / 严厉威严）' },
  { value: 'longxiaochun_v2', label: '🎙️ 亲切标准女声（标准女声 / 通用解说 / 亲切播音）' },
  { value: 'longtian_v2', label: '🎙️ 甜美灵动女声（甜美仙子 / 少女女主 / 活泼女修）' },
  { value: 'longmiao_v2', label: '🎙️ 软萌萝莉女声（萌宠灵兽 / 小师妹 / 纯真女童）' },
  { value: 'longyue_v2', label: '🎙️ 知性温柔女声（高冷师姐 / 女尊女帝 / 优雅仙尊）' },
]

function getAudioSubType(asset) {
  if (!asset) return 'voice'
  const sub = String(asset.subCategory || asset.categoryType || asset.kind || '').toLowerCase()
  if (['voice', 'dialogue', 'narration', 'system', 'tts'].includes(sub)) return 'voice'
  if (['sfx', 'ambient', 'sound', 'bgm', 'foley'].includes(sub)) return 'sfx'
  const id = String(asset.id || '').toLowerCase()
  const name = String(asset.name || '').toLowerCase()
  const desc = String(asset.description || asset.style || '').toLowerCase()
  if (id.includes('vo_') || id.includes('narrat') || id.includes('dialog') || /旁白|对白|台词|念白|人声|系统音|提示音|神念|自语|独白|配音/.test(name + desc)) return 'voice'
  if (id.includes('sfx') || id.includes('bgm') || id.includes('ambient') || /音效|环境|声|风|雨|雷|刀|剑|脚步|爆炸|打斗|摩擦|推门|倒地|轰鸣|BGM|背景音乐|拟声/.test(name + desc)) return 'sfx'
  return 'voice'
}

function getVoiceShortName(voiceId) {
  if (!voiceId) return ''
  const opt = VOICE_PRESET_OPTIONS.find(o => o.value === voiceId)
  if (!opt || !opt.label) return ''
  const match = opt.label.match(/[🎙️🤖\s]*([^（(]+)/)
  return match ? match[1].trim() : ''
}

const generationModes = [
  { value: 'reference', label: '参考生成' },
  { value: 'firstLast', label: '首尾帧' },
]
const videoRatios = ['21:9', '16:9', '4:3', '1:1', '3:4', '9:16', '智能']
const doubaoRatios = ['自动', '3:4', '4:3', '9:16', '16:9', '1:1', '21:9']
const dolaRatios = ['1:1', '3:4', '4:3', '9:16', '16:9', '21:9']
const videoQualities = ['480P', '720P', '1080P', '4K']
const videoDurations = Array.from({ length: 15 }, (_, index) => index + 1)
const doubaoDurations = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
const dolaDurations = [5, 10]
const doubaoModelOptions = [
  { label: 'Seedance 2.0 Mini · 日常生成 (推荐)', value: 'Seedance 2.0 Mini' },
  { label: 'Seedance 2.0 Fast · 快速出片', value: 'Seedance 2.0 Fast' },
  { label: 'Seedance 2.0 · 进阶画质', value: 'Seedance 2.0' },
  { label: 'Seedance 2.5 · 旗舰标杆', value: 'Seedance 2.5' },
]
const dolaModelOptions = [
  { label: 'Dreamina Seedance 2.0 Fast · 快速出片 (推荐)', value: 'Dreamina Seedance 2.0 Fast' },
  { label: 'Dreamina Seedance 2.5 · 旗舰画质', value: 'Dreamina Seedance 2.5' },
  { label: 'Dreamina Seedance 1.0 · 基础模型', value: 'Dreamina Seedance 1.0' },
]
const defaultVideoSettings = Object.freeze({ ratio: '16:9', quality: '720P', duration: 10 })
const generationCounts = [1, 2, 3, 4, 5, 6, 7, 8]
const assets = ref([])
const dramaChapters = ref([])
const currentChapterId = ref('')
const imageModels = ref([])
const videoApiModels = ref([])
const textModels = ref([])
const audioModels = ref([])
const selectedImageModel = ref('')
const selectedTextModel = ref('')
const selectedAudioModel = ref('')
const defaultSeedanceModel = ref('')
const importedFileName = ref('')
const importedProjectTitle = ref('')
const importedSchemaVersion = ref('')
const importError = ref('')
const importDialogOpen = ref(false)
const jsonText = ref('')
const creationAiOpen = ref(false)
const creationAiPrompt = ref('')
const creationAiTitle = ref('')
const creationAiScope = ref('full')
const creationAiGenerating = ref(false)
const creationAiError = ref('')
const creationAiPreview = ref('')
const pendingInitialCreationData = ref(null)
const consumingInitialCreationData = ref(false)
const videoWorkspaceReady = ref(false)
const assetDetailOpen = ref(false)
const assetDetailTarget = ref(null)
const assetDraft = ref({ name: '', description: '', prompt: '', useDefaultRoleLayout: true })
const assetReferencesCopying = ref(false)
const assetReferencesCopied = ref(false)
const audioPreview = ref(null)
const audioPreviewPlaying = ref(false)
const audioPreviewCurrent = ref(0)
const audioPreviewDuration = ref(0)
const videoProjects = ref([])
const videoProjectKeyword = ref('')
const videoProjectFilter = ref('all')
const UNLINKED_PROJECT_FILTER = '__unlinked__'
const availableProjects = ref([])
const activeVideoProject = ref(null)
const videoProjectCreateOpen = ref(false)
const newProjectName = ref('')
const newProjectDescription = ref('')
const newProjectId = ref('')
const projectListLoading = ref(false)
const projectCreating = ref(false)
const projectToDelete = ref(null)
const deletingProjectId = ref('')
const projectDetailLoading = ref(false)
const projectSaveStatus = ref('')
const projectError = ref('')
const activeCategory = ref('all')
const activeAudioSubCategory = ref('all')
const loading = ref(false)
const error = ref('')
const assetActionsOpen = ref(false)
const assetActionsStyle = ref({})
const assetActionsPinned = ref(false)
const bulkGenerating = ref(false)
const bulkGenerationStatus = ref('')
// 媒体放大预览（BaseMediaPreview，支持图片+视频）
// 工作区全局悬浮提示
const workspaceToast = ref({ message: '', type: 'info', timer: null })
function showWorkspaceToast(message, type = 'info', duration = 3200) {
  if (workspaceToast.value.timer) clearTimeout(workspaceToast.value.timer)
  workspaceToast.value = {
    message,
    type,
    timer: setTimeout(() => {
      workspaceToast.value = { message: '', type: 'info', timer: null }
    }, duration)
  }
}


// 3×3 电影机位矩阵与动作截断引擎
const CAMERA_MATRIX_CELLS = [
  { index: 0, code: 'ELS', name: '大远景', desc: '广阔环境，主体极小', keywords: ['大远景', '远景', '广角'] },
  { index: 1, code: 'LS', name: '全景', desc: '展示主体全身与环境', keywords: ['全景', '全身', '环绕'] },
  { index: 2, code: 'MLS', name: '中远景', desc: '膝盖以上/3-4构图', keywords: ['中远景', '3/4', '七分身'] },
  { index: 3, code: 'MS', name: '中景', desc: '腰部以上，表现动作与互动', keywords: ['中景', '半身', '腰部'] },
  { index: 4, code: 'MCU', name: '中特写', desc: '胸部以上，亲密感构图', keywords: ['中特写', '胸部'] },
  { index: 5, code: 'CU', name: '特写', desc: '面部紧凑构图，聚焦表情', keywords: ['特写', '面部', '头部', '脸部'] },
  { index: 6, code: 'ECU', name: '大特写', desc: '微观细节（眼睛/手部/道具）', keywords: ['大特写', '微距', '手部', '眼神', '瞳孔'] },
  { index: 7, code: 'LOW', name: '低角度仰拍', desc: '虫瞻位，地面仰视，增强庄严感', keywords: ['仰拍', '低角度', '仰角', '虫瞻'] },
  { index: 8, code: 'HIGH', name: '高角度俯拍', desc: '鸟瞰位，上方俯视', keywords: ['俯拍', '高角度', '俯视', '鸟瞰'] },
]

function getRecommendedMatrixCell(shot) {
  const text = `${shot.title || ''} ${shot.prompt || ''}`.toLowerCase()
  for (const cell of CAMERA_MATRIX_CELLS) {
    if (cell.keywords.some(k => text.includes(k.toLowerCase()))) {
      return cell.index
    }
  }
  return 1 // 默认推荐全景
}

function resolvedContinuityMode(shot) {
  if (shot?.inheritPrevTail === false) return 'matchCut'
  if (shot?.continuityMode === 'exact' || shot?.continuityMode === 'transition' || shot?.continuityMode === 'matchCut') return shot.continuityMode
  return shot?.continuityTailFrame?.isMatrixCropped ? 'matchCut' : 'exact'
}

async function setContinuityMode(shot, shotIndex, mode) {
  if (mode === 'transition') {
    shot.inheritPrevTail = true
    shot.continuityMode = 'transition'
    shot.showMatrixPanel = false
    shot.selectedMatrixCell = null
    const source = shot.continuitySourceFrame
    if (source?.fileId || source?.url) {
      shot.continuityTailFrame = { ...source, isMatrixCropped: false, selectedCellIndex: undefined }
      shot.continuityOutdated = false
    }
    const candidateId = shot.rejectedResultFileId || (shot.lastGenerationAttempt?.fileId) || fileIdFromUrl(shot.rejectedResultUrl)
    if (candidateId) {
      adoptRejectedCandidate(shot)
      shot.continuityReview = {
        status: 'passed',
        fileId: candidateId,
        checkedAt: Date.now(),
        summary: '尾帧转场过渡（两者兼得）· 已核验采纳为成片',
      }
      showWorkspaceToast('🎬 已切换为【尾帧转场过渡】（两者兼得）：已将当前转场视频直接采纳为成片！', 'success', 4000)
      return
    }
    scheduleProjectSave()
    showWorkspaceToast('🎬 已切换为【尾帧转场过渡】：两者兼得！保留上一镜尾帧作为第0秒起势，镜头顺畅运镜融变至本镜新场景，衔接检查自动放行！', 'success', 3500)
    return
  }

  if (hasAuthoredCut(shot)) {
    alignAuthoredContinuity(shot)
    scheduleProjectSave()
    showWorkspaceToast('本镜正文已安排剪辑切镜，继续按场景图生成；如需改成连续动作，请先修改本镜镜头安排', 'info', 4000)
    return
  }
  shot.continuityMode = mode === 'matchCut' ? 'matchCut' : 'exact'
  if (shot.continuityMode === 'matchCut') {
    shot.showMatrixPanel = true
    shot.showTimelineScrubber = false
    scheduleProjectSave()
    showWorkspaceToast('🎬 已切换为换机位剪辑：九宫格用于改变景别，接缝属于镜头切换', 'info', 3200)
    return
  }

  shot.showMatrixPanel = false
  shot.selectedMatrixCell = null
  const source = shot.continuitySourceFrame
  if (source?.fileId || source?.url) {
    shot.continuityTailFrame = { ...source, isMatrixCropped: false, selectedCellIndex: undefined }
    shot.continuityOutdated = false
    scheduleProjectSave()
    showWorkspaceToast(roleHandoffPlan(storyboards.value, shot) ? '🔗 已恢复真实尾帧，并保留人物身份参考；动作按本镜剧本执行' : '🔗 已恢复真实尾帧：Muse 将只接收这一张首图，按原姿态续演', 'success', 3200)
    return
  }
  await refreshShotContinuityFrame(shot, shotIndex)
}

function toggleMatrixPanel(shot, shotIndex) {
  shot.showMatrixPanel = !shot.showMatrixPanel
  if (shot.showMatrixPanel) {
    shot.showTimelineScrubber = false
    if ((shot.cameraMatrixImage?.fileId || shot.cameraMatrixImage?.url) && (!Array.isArray(shot.cameraMatrixCells) || shot.cameraMatrixCells.length < 9)) {
      void extractAllMatrixCells(shot, shotIndex, true)
    }
  }
}


const CAMERA_MOMENTUM_DIRECTIONS = [
  { id: 'pan_right', label: '➡️ 向右侧移', text: '向右侧移' },
  { id: 'pan_left', label: '⬅️ 向左侧移', text: '向左侧移' },
  { id: 'push_in', label: '⏩ 极速前推', text: '极速前推推进' },
  { id: 'pull_out', label: '⏪ 极速后拉', text: '极速后拉后退' },
  { id: 'orbit_low', label: '🔄 仰视环绕', text: '仰视环绕运镜' },
  { id: 'crane_down', label: '⬇️ 俯冲下压', text: '极速俯冲下压' },
]

const OCCLUSION_OBJECT_PRESETS = [
  { id: 'smoke_fog', label: '🌫️ 烟尘黑雾 / 灵气紫雾', name: '浓烈烟尘与黑雾翻滚', scene: '修仙魔气、大片质感，最易完全覆盖' },
  { id: 'sword_light', label: '🗡️ 剑气光晕 / 兵器横挥', name: '凌厉剑光残影横向划过视野', scene: '动作对决，强光/残影瞬时占满画面' },
  { id: 'cloak_pass', label: '🥋 前景衣袍 / 人物擦镜', name: '前景人物黑色披风快速掠过镜头', scene: '人物走动、交接，极其生活化自然遮挡' },
  { id: 'stone_pillar', label: '🪨 前景石碑 / 残垣立柱', name: '前景断裂古碑横切遮住视野', scene: '场景横移，利用近大远小快速挡住背景' },
  { id: 'tree_trunk', label: '🌲 粗壮树干 / 枯藤岩石', name: '前景粗壮古树逐渐遮住视野', scene: '野外密林，转场绝佳遮挡' },
  { id: 'ground_shadow', label: '🌑 焦土暗影 / 碎石接地', name: '镜头下压没入焦土与碎石暗影', scene: '俯冲运镜转场' },
]

function toggleOcclusionPanel(shot, shotIndex) {
  shot.showOcclusionPanel = !shot.showOcclusionPanel
  if (shot.showOcclusionPanel) {
    shot.showMatrixPanel = false
    shot.showTimelineScrubber = false
    if (!shot.occlusionDirection) {
      shot.occlusionDirection = detectCameraDirectionFromPrompt(shot.prompt) || 'pan_right'
    }
    if (!shot.occlusionObject) {
      shot.occlusionObject = 'smoke_fog'
    }
  }
}

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

function getOcclusionDir(shot) {
  return CAMERA_MOMENTUM_DIRECTIONS.find(d => d.id === shot?.occlusionDirection) || CAMERA_MOMENTUM_DIRECTIONS[0]
}

function getOcclusionObj(shot) {
  return OCCLUSION_OBJECT_PRESETS.find(o => o.id === shot?.occlusionObject) || OCCLUSION_OBJECT_PRESETS[0]
}

function prevShotOcclusionFormula(shot, shotIndex) {
  const dir = getOcclusionDir(shot)
  const occ = getOcclusionObj(shot)
  return `【运镜动能与遮挡收尾】镜头最后2秒保持${dir.text}，${occ.name}逐渐遮住视野，结束最后一帧画面被完全遮挡覆盖。`
}

function currentShotOcclusionFormula(shot, shotIndex) {
  const dir = getOcclusionDir(shot)
  const occ = getOcclusionObj(shot)
  return `【运镜动能守恒·连续不顿】第0秒以受遮挡尾帧起势，镜头保持相同${dir.text}与相近速度匀速连续运镜（严禁起步顿挫）；【遮挡退出过渡】${occ.name}沿运镜方向快速退出画面，平滑展露出本镜新场景、人物与主体动作。两段时空连续不顿、光色自然平滑过渡。`
}

function injectOcclusionToPrevShot(shot, shotIndex) {
  if (shotIndex <= 0) return
  const prevShot = storyboards.value[shotIndex - 1]
  if (!prevShot) return
  const formula = prevShotOcclusionFormula(shot, shotIndex)
  let cleanPrompt = (prevShot.prompt || '').replace(/【运镜动能与遮挡收尾】[^\n]+/g, '').trim()
  prevShot.prompt = `${cleanPrompt}\n${formula}`.trim()
  scheduleProjectSave()
  showWorkspaceToast(`✅ 已将【A段进遮挡】注入第 ${shotIndex} 镜提示词末尾！`, 'success', 3500)
}

function injectOcclusionToCurrentShot(shot, shotIndex) {
  const formula = currentShotOcclusionFormula(shot, shotIndex)
  let cleanPrompt = (shot.prompt || '').replace(/【运镜动能守恒·连续不顿】[^\n]+|【遮挡退出过渡】[^\n]+/g, '').trim()
  shot.prompt = `${formula}\n${cleanPrompt}`.trim()
  shot.continuityMode = 'transition'
  shot.inheritPrevTail = true
  scheduleProjectSave()
  showWorkspaceToast(`✅ 已将【B段出遮挡】注入本镜提示词，并切换为【尾帧转场过渡】！`, 'success', 3500)
}

function applyOcclusionContinuityToShots(shot, shotIndex) {
  injectOcclusionToPrevShot(shot, shotIndex)
  injectOcclusionToCurrentShot(shot, shotIndex)
  showWorkspaceToast(`✨ 已联动注入两镜遮挡过渡提示词！A段进遮挡、B段出遮挡，两段运镜连续不顿！`, 'success', 4000)
}

function toggleTimelineScrubber(shot, shotIndex) {
  shot.showTimelineScrubber = !shot.showTimelineScrubber
  if (shot.showTimelineScrubber) {
    shot.showMatrixPanel = false
    if (!shot.scrubFraction) shot.scrubFraction = 0.85
  }
}

async function generateCameraMatrix(shot, shotIndex) {
  let tailFrame = shot.continuitySourceFrame
  if (!tailFrame?.url && !tailFrame?.fileId) {
    if (shotIndex > 0) {
      const prevShot = storyboards.value[shotIndex - 1]
      const hasVideo = prevShot && (prevShot.resultUrl || prevShot.resultFileId || prevShot.mixedVideoFileId || prevShot.originalVideoFileId)
      if (hasVideo) {
        showWorkspaceToast('⚡ 正在自动提取上一分镜视频尾帧以构建机位矩阵...', 'info', 2000)
        tailFrame = await extractLastFrameForShot(prevShot, shotIndex - 1, shot, { activate: false })
      }
    }
  }
  if (!tailFrame?.url && !tailFrame?.fileId) {
    showWorkspaceToast('⚠️ 请确保上一分镜已生成视频，或先提取上一镜尾帧作为矩阵基础', 'warning')
    return
  }
  shot.generatingMatrix = true
  showWorkspaceToast('🎬 正在调用生图模型绘制 3×3 电影机位索引矩阵（约需 20-40 秒）...', 'info', 8000)
  try {
    const res = await videoProjectRequest('POST', '/video/generate-camera-matrix', {
      fileId: tailFrame.fileId,
      url: tailFrame.url,
      model: selectedImageModel.value || '',
    })
    if (res && res.fileId) {
      shot.cameraMatrixImage = {
        fileId: res.fileId,
        url: res.url,
        createdAt: Date.now(),
      }
      shot.cameraMatrixCells = []
      shot.showMatrixPanel = true
      scheduleProjectSave()
      showWorkspaceToast('✅ 成功生成 3×3 电影镜头矩阵，正在拆出九张无字幕单图…', 'success', 3500)
      await extractAllMatrixCells(shot, shotIndex, true)
    } else {
      throw new Error(res?.message || '生成未返回有效矩阵图片')
    }
  } catch (err) {
    console.error('Failed to generate camera matrix:', err)
    showWorkspaceToast(`❌ 生成机位矩阵失败: ${err.message || '网络或模型异常'}`, 'error')
  } finally {
    shot.generatingMatrix = false
  }
}

function matrixCellRecord(shot, cellIndex) {
  return Array.isArray(shot.cameraMatrixCells)
    ? shot.cameraMatrixCells.find(item => Number(item?.cellIndex) === Number(cellIndex))
    : null
}

function matrixCellImage(shot, cellIndex) {
  return storedProjectMediaUrl(matrixCellRecord(shot, cellIndex), 'url', 'cover')
}

function applyMatrixCell(shot, shotIndex, cellIndex, result) {
  const cell = CAMERA_MATRIX_CELLS[cellIndex] || { name: `机位${cellIndex + 1}` }
  shot.continuityTailFrame = {
    fileId: result.fileId,
    url: result.url,
    sourceShotIndex: shotIndex - 1,
    sourceShotTitle: `第 ${shotIndex} 镜 · ${cell.name}`,
    selectedCellIndex: cellIndex,
    isMatrixCropped: true,
    updatedAt: Date.now(),
  }
  shot.continuityMode = 'matchCut'
  shot.selectedMatrixCell = cellIndex
  shot.continuityOutdated = false
  scheduleProjectSave()
}

async function extractAllMatrixCells(shot, shotIndex, quiet = false) {
  const matrixImg = shot.cameraMatrixImage
  if ((!matrixImg?.fileId && !matrixImg?.url) || shot.croppingMatrix) return false
  shot.croppingMatrix = true
  if (!quiet) showWorkspaceToast('✂️ 正在拆出九张完整无字幕机位图…', 'info', 2200)
  try {
    const results = await Promise.all(CAMERA_MATRIX_CELLS.map(async cell => {
      const res = await videoProjectRequest('POST', '/image/crop-matrix-cell', {
        fileId: matrixImg.fileId,
        url: matrixImg.url,
        cellIndex: cell.index,
        rows: 3,
        cols: 3,
      })
      if (!res?.fileId) throw new Error(`第 ${cell.index + 1} 格未返回有效图片`)
      return {
        fileId: res.fileId,
        url: res.url,
        cellIndex: cell.index,
        width: res.width,
        height: res.height,
        labelCleaned: Boolean(res.labelCleaned),
      }
    }))
    shot.cameraMatrixCells = results
    scheduleProjectSave()
    showWorkspaceToast('✅ 九张机位图已全部拆出并保存；重启后仍可直接使用', 'success', 3500)
    return true
  } catch (err) {
    console.error('Failed to extract matrix cells:', err)
    showWorkspaceToast(`❌ 拆分九宫格失败: ${err.message || '系统异常'}`, 'error')
    return false
  } finally {
    shot.croppingMatrix = false
  }
}

async function selectMatrixCell(shot, shotIndex, cellIndex) {
  const matrixImg = shot.cameraMatrixImage
  if (!matrixImg?.fileId && !matrixImg?.url) {
    showWorkspaceToast('⚠️ 请先生成九宫格矩阵', 'warning')
    return
  }
  shot.croppingMatrix = true
  const cell = CAMERA_MATRIX_CELLS[cellIndex] || { name: `机位${cellIndex + 1}` }
  showWorkspaceToast(`✂️ 正在裁切【${cell.name}】机位并绑定为本镜首帧...`, 'info', 1500)
  try {
    const existing = matrixCellRecord(shot, cellIndex)
    if (existing?.fileId) {
      applyMatrixCell(shot, shotIndex, cellIndex, existing)
      showWorkspaceToast(`✅ 已将【${cell.name}】单图设为第 ${shotIndex + 1} 镜起跑首帧！`, 'success', 3500)
      return
    }
    const res = await videoProjectRequest('POST', '/image/crop-matrix-cell', {
      fileId: matrixImg.fileId,
      url: matrixImg.url,
      cellIndex,
      rows: 3,
      cols: 3,
    })
    if (res && res.fileId) {
      const record = { ...res, cellIndex }
      shot.cameraMatrixCells = [
        ...(Array.isArray(shot.cameraMatrixCells) ? shot.cameraMatrixCells.filter(item => Number(item?.cellIndex) !== Number(cellIndex)) : []),
        record,
      ].sort((left, right) => Number(left.cellIndex) - Number(right.cellIndex))
      applyMatrixCell(shot, shotIndex, cellIndex, record)
      showWorkspaceToast(`✅ 成功切出【${cell.name}】机位并设为第 ${shotIndex + 1} 镜起跑首帧！`, 'success', 3500)
    } else {
      throw new Error(res?.message || '切图返回异常')
    }
  } catch (err) {
    console.error('Failed to crop matrix cell:', err)
    showWorkspaceToast(`❌ 裁切机位失败: ${err.message || '系统异常'}`, 'error')
  } finally {
    shot.croppingMatrix = false
  }
}

async function extractActionFrameAt(shot, shotIndex, fraction = null) {
  if (shotIndex <= 0) return
  const prevShot = storyboards.value[shotIndex - 1]
  const fileId = prevShot?.resultFileId || prevShot?.fileId || prevShot?.mixedVideoFileId || prevShot?.originalVideoFileId || ''
  const url = prevShot?.resultUrl || prevShot?.videoUrl || ''
  if (!fileId && !url) {
    showWorkspaceToast(`⚠️ 上一镜尚未生成视频，无法截取动作帧`, 'warning')
    return
  }
  const frac = fraction !== null ? fraction : (shot.scrubFraction || 0.85)
  shot.scrubFraction = frac
  shot.extractingLastFrame = true
  showWorkspaceToast(`⏱️ 正在抓取上一镜视频 ${Math.round(frac * 100)}% 处的动作瞬间...`, 'info', 1500)
  try {
    const res = await videoProjectRequest('POST', '/video/extract-custom-frame', {
      fileId,
      url,
      position: 'fraction',
      fraction: frac,
    })
    if (res && res.fileId) {
      const frame = {
        fileId: res.fileId,
        url: res.url,
        sourceShotIndex: shotIndex - 1,
        sourceShotTitle: `第 ${shotIndex} 镜 (${Math.round(frac * 100)}% 动作帧)`,
        actionFrameTimestamp: res.timestamp,
        updatedAt: Date.now(),
      }
      shot.continuitySourceFrame = { ...frame }
      shot.continuityTailFrame = { ...frame }
      if (shot.continuityMode !== 'transition') shot.continuityMode = 'exact'
      shot.selectedMatrixCell = null
      shot.continuityOutdated = false
      scheduleProjectSave()
      showWorkspaceToast(`✅ 成功截取上一镜【第 ${res.timestamp} 秒】动作帧并绑定为首帧！`, 'success', 3500)
    } else {
      throw new Error(res?.message || '截取未返回有效帧')
    }
  } catch (err) {
    console.error('Failed to extract custom frame:', err)
    showWorkspaceToast(`❌ 截取动作帧失败: ${err.message || '系统异常'}`, 'error')
  } finally {
    shot.extractingLastFrame = false
  }
}

function injectActionRelayPrompt(shot) {
  const prefix = '【动作顺接·补全演完】顺接首帧定格动作的瞬间状态，人物不停顿地顺势完成动作，'
  if (!shot.prompt.includes('【动作顺接·补全演完】')) {
    shot.prompt = `${prefix}${shot.prompt}`
    scheduleProjectSave()
    showWorkspaceToast('✅ 已在当前分镜提示词开头注入【动作顺接补全】模板！', 'success')
  } else {
    showWorkspaceToast('ℹ️ 当前分镜已包含动作顺接指令', 'info')
  }
}

const mediaPreviewVisible = ref(false)
const mediaPreviewSrc = ref('')
const mediaPreviewType = ref('image')
const mediaPreviewFileId = ref('')
const mediaPreviewReferences = ref([])
const finishedPreviewVisible = ref(false)
const finishedPreviewProjectTitle = ref('')
const finishedPreviewOwner = ref(null)
const finishedPreviewAssemblyEnabled = computed(() => {
  const project = availableProjects.value.find(p => String(p.id) === String(finishedPreviewOwner.value?.projectId || ''))
  return props.aiAssemblyEnabled && project?.productionBrief?.mode !== 'template' && project?.productionBrief?.production !== 'motion'
})
async function saveShotAssembly(value, ownerId) {
  if (!ownerId) throw new Error('组片任务未关联原分镜项目')
  await videoProjectRequest('PUT', `/video-project/${encodeURIComponent(ownerId)}`, { aiAssembly: value })
  if (String(finishedPreviewOwner.value?.id || '') === String(ownerId)) {
    finishedPreviewOwner.value = { ...finishedPreviewOwner.value, aiAssembly: value }
  }
}
const finishedPreviewVideos = ref([])
const finishedPreviewLoading = ref(false)
const finishedPreviewError = ref('')
const compatibleVideoRequests = new Map()
const compatibleVideoInFlight = new Set()
const videoFrameWatchers = new WeakMap()

async function compatibleVideoUrl(fileId, fallbackUrl) {
  const id = String(fileId || '').trim()
  if (!id || !window.pywebview?.api?.compatible_video_preview) return fallbackUrl
  if (!compatibleVideoRequests.has(id)) {
    compatibleVideoRequests.set(id, window.pywebview.api.compatible_video_preview(props.token, id)
      .then(result => String(result?.url || fallbackUrl))
      .catch(() => fallbackUrl))
  }
  return compatibleVideoRequests.get(id)
}

async function handleShotVideoError(shot) {
  const fileId = String(shot?.previewOriginal ? breezeSourceVideoId(shot) : shot?.resultFileId || '').trim()
  const attemptKey = `shot:${shot.id}:${fileId}`
  if (!fileId || compatibleVideoInFlight.has(attemptKey)) return
  compatibleVideoInFlight.add(attemptKey)
  try {
    const fallback = shot.previewOriginal ? shot.originalPreviewUrl : shot.resultUrl
    const compatible = await compatibleVideoUrl(fileId, fallback)
    if (compatible && compatible !== fallback) {
      if (shot.previewOriginal) shot.originalPreviewUrl = compatible
      else shot.resultUrl = compatible
    }
  } finally {
    compatibleVideoInFlight.delete(attemptKey)
  }
}

function verifyShotVideoFrame(shot, event) {
  const video = event.currentTarget
  videoFrameWatchers.get(video)?.()
  videoFrameWatchers.set(video, watchForDecodedVideoFrame(video, () => handleShotVideoError(shot)))
}

function ensureShotVideoRenderable(shot, event) {
  const video = event.currentTarget
  window.setTimeout(() => {
    if (!video.isConnected || video.currentSrc !== (shot.previewOriginal ? shot.originalPreviewUrl : shot.resultUrl)) return
    if (video.videoWidth <= 0 || video.videoHeight <= 0) handleShotVideoError(shot)
  }, 250)
}

async function handleMediaPreviewVideoError() {
  const fileId = mediaPreviewFileId.value
  const attemptKey = `preview:${fileId}`
  if (!fileId || compatibleVideoInFlight.has(attemptKey)) return
  compatibleVideoInFlight.add(attemptKey)
  try {
    mediaPreviewSrc.value = await compatibleVideoUrl(fileId, mediaPreviewSrc.value)
  } finally {
    compatibleVideoInFlight.delete(attemptKey)
  }
}

async function handleFinishedVideoError(item) {
  const fileId = String(item?.fileId || '').trim()
  const attemptKey = `finished:${fileId}`
  if (!fileId || compatibleVideoInFlight.has(attemptKey)) return
  compatibleVideoInFlight.add(attemptKey)
  try {
    const compatible = await compatibleVideoUrl(fileId, item.src)
    if (!compatible || compatible === item.src) return
    finishedPreviewVideos.value = finishedPreviewVideos.value.map(video => video.id === item.id ? { ...video, src: compatible } : video)
  } finally {
    compatibleVideoInFlight.delete(attemptKey)
  }
}

function openVideoPreview(shot) {
  if (!shot.resultUrl) return
  mediaPreviewSrc.value = shot.resultUrl
  mediaPreviewType.value = 'video'
  mediaPreviewFileId.value = String(shot.resultFileId || '')
  mediaPreviewVisible.value = true
}

async function downloadShotVideo(shot) {
  if (shot.downloadingVideo || (!shot.resultFileId && !shot.resultPath && !shot.resultUrl)) return
  shot.downloadingVideo = true
  shot.videoReplaceError = ''
  try {
    const suggestedName = `${String(shot.title || '视频').trim() || '视频'}.mp4`
    const fileId = String(shot.resultFileId || fileIdFromUrl(shot.resultUrl) || '').trim()
    if (fileId && window.pywebview?.api?.save_server_video_as) {
      await window.pywebview.api.save_server_video_as(props.token, fileId, suggestedName)
      return
    }
    if (shot.resultPath && window.pywebview?.api?.save_video_as) {
      await window.pywebview.api.save_video_as(shot.resultPath, suggestedName)
      return
    }
    if (!shot.resultUrl) throw new Error('当前视频没有可下载地址')
    const response = await fetch(shot.resultUrl)
    if (!response.ok) throw new Error(`服务器返回 HTTP ${response.status}`)
    const blob = await response.blob()
    if (!blob.size) throw new Error('服务器返回了空视频文件')
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = suggestedName
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000)
  } catch (err) {
    shot.videoReplaceError = `视频下载失败：${cleanError(err)}`
  } finally {
    shot.downloadingVideo = false
  }
}

function fileDownloadUrl(fileId) {
  const id = String(fileId || '').trim()
  if (!id) return ''
  const base = id.startsWith('local_') ? props.storageBase : props.apiBase
  return `${base}/file/${encodeURIComponent(id)}/download`
}

function storedProjectMediaUrl(item, ...keys) {
  const fileId = String(item?.fileId || item?.coverId || item?.resultFileId || '').trim()
  if (fileId) return fileDownloadUrl(fileId)
  const raw = keys.map(key => item?.[key]).find(value => String(value || '').trim())
  return raw ? absoluteMediaUrl(String(raw)) : ''
}

function performanceReviewMessage(shot) {
  const review = shot?.performanceReview
  if (!review) return ''
  if (shot.resultFileId && review.reviewedFileId && shot.resultFileId !== review.reviewedFileId) return '新视频已生成，待核对自然表演与前后镜衔接。'
  if (shot.resultFileId && review.status === 'prompt_ready') return '新视频已生成，待核对自然表演与前后镜衔接。'
  return String(review.message || '')
}

const assemblyRepairGuidance = ref(null)
async function openAssemblyRepairShot(info) {
  const owner = finishedPreviewOwner.value
  if (!owner || !info?.shotId) return
  finishedPreviewVisible.value = false
  if (String(activeVideoProject.value?.id) !== String(owner.id)) await openVideoProject(owner)
  const shot = storyboards.value.find(s => String(s.id) === String(info.shotId))
  if (!shot) { showWorkspaceToast('原分镜已变化，请重新打开任务核对。', 'warning'); return }
  activeShotId.value = shot.id
  assemblyRepairGuidance.value = { projectId:String(owner.id), shotId:String(shot.id), action:String(info.action || '核对当前切入状态和前镜实际尾帧') }
  showWorkspaceToast(`组片修复建议：${info.action || '核对当前切入状态和前镜实际尾帧'}`, 'info', 12000)
  await nextTick()
  document.querySelector('.storyboard-card.active')?.scrollIntoView({block:'start',behavior:'smooth'})
}

async function openProjectFinishedPreview(project) {
  if (!project?.id) return
  if (String(activeVideoProject.value?.id || '') === String(project.id) && !await saveActiveVideoProject()) return
  finishedPreviewOwner.value = null
  finishedPreviewVisible.value = true
  finishedPreviewProjectTitle.value = project.name || '未命名任务'
  finishedPreviewVideos.value = []
  finishedPreviewError.value = ''
  finishedPreviewLoading.value = true
  try {
    const detail = removeAudioAssets(await videoProjectRequest('GET', `/video-project/${encodeURIComponent(project.id)}`))
    finishedPreviewOwner.value = detail
    finishedPreviewProjectTitle.value = detail?.name || project.name || '未命名任务'
    finishedPreviewVideos.value = (Array.isArray(detail?.storyboards) ? detail.storyboards : []).flatMap((shot, index) => {
      const src = storedProjectMediaUrl(shot, 'resultUrl')
      if (!src || shot.resultValidation?.passed === false) return []
      const attachedAudio = (Array.isArray(shot.references) ? shot.references : []).find(r => isAudioAsset(r) && (r.fileId || r.coverId || r.cover))
      const audioFileId = String(attachedAudio?.fileId || attachedAudio?.coverId || fileIdFromUrl(attachedAudio?.cover) || '')
      return [{
        id: String(shot.id || `video-${index}`),
        description: String(shot.visual || shot.prompt || ''),
        title: String(shot.title || `成片 ${index + 1}`),
        src,
        fileId: String(shot.resultFileId || shot.fileId || ''),
        ratio: shot.ratio || '16:9',
        audioFileId,
        audioName: attachedAudio?.name || '',
        exportBlocked: hasRejectedReferences(shot),
        reviewWarning: [shot.resultEnvironmentWarning, performanceReviewMessage(shot), resultSourceMessage(shot)].filter(Boolean).join('；'),
        duration: Number(shot.videoDuration || (shot.durationMode === 'seconds' ? shot.duration : 0) || 0),
      }]
    })
  } catch (err) {
    finishedPreviewError.value = cleanError(err)
  } finally {
    finishedPreviewLoading.value = false
  }
}

function openReferencePreview(asset, ownerAsset = asset) {
  const url = assetUrl(asset)
  if (!url) return
  mediaPreviewSrc.value = url
  mediaPreviewType.value = 'image'
  const state = assetReferenceState(ownerAsset)
  mediaPreviewReferences.value = [ownerAsset, ...state.readyItems]
    .filter(item => item && assetUrl(item))
    .map((item, index) => ({ id: item.id, name: item.name || item.id || '参考图', label: index === 0 ? '主图' : `图${index}`, src: assetUrl(item) }))
  mediaPreviewVisible.value = true
}

// ===== 精简视频控件 =====
const videoRefs = new Map()
function setVideoRef(shot, el) {
  if (el) videoRefs.set(shot.id, el)
  else videoRefs.delete(shot.id)
}
function getVideo(shot) { return videoRefs.get(shot.id) }

function toggleVideo(shot) {
  const v = getVideo(shot)
  if (!v) return
  if (v.paused) v.play().catch(() => {})
  else v.pause()
}
function seekVideo(shot, event) {
  const v = getVideo(shot)
  if (!v || !v.duration) return
  v.currentTime = Number(event.target.value) || 0
}
function toggleMute(shot) {
  const v = getVideo(shot)
  if (!v) return
  v.muted = !v.muted
}
function syncVideoMeta(shot, event) {
  shot.videoDuration = Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0
  if (isMuseShot(shot) && !shot.previewOriginal && shot.videoDuration > 0 && !shotRunning(shot)) {
    shot.resultValidation = durationValidation(shot.duration || 5, shot.videoDuration)
    if (!shot.resultValidation.passed) {
      shot.status = 'failed'
      shot.generationError = shot.resultValidation.reason
    }
  }
}
function syncVideoTime(shot, event) {
  shot.videoCurrent = Number.isFinite(event.currentTarget.currentTime) ? event.currentTarget.currentTime : 0
  if (shot.previewOriginal && shot.previewStopAt != null && shot.videoCurrent >= shot.previewStopAt) {
    event.currentTarget.pause()
    shot.previewStopAt = null
  }
}
function fmtTime(value) {
  const s = Math.max(0, Math.floor(Number(value) || 0))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
const assetLibrarySyncing = ref(false)
const assetLibraryStatus = ref('')
const storyboards = ref([createStoryboard(1)])
const activeShotId = ref(storyboards.value[0].id)
const visibleStoryboardAnchorId = ref(storyboards.value[0].id)
const storyboardColumnRef = ref(null)
const storyboardCardRefs = new Map()
let storyboardAnchorFrame = 0
const pollTimers = new Map()
const seedancePollInFlight = new WeakSet()
let workspaceNavigation = 0
let workspaceDisposed = false
// 后端任务表快照，用于悬浮窗展示（名称/ID/状态/进度）
const activeTasks = ref([])
let taskRefreshTimer = null
let projectSaveTimer = null
let hydratingProject = false

function setStoryboardCardRef(element, shotId) {
  if (element) storyboardCardRefs.set(shotId, element)
  else storyboardCardRefs.delete(shotId)
}

function updateVisibleStoryboardAnchor() {
  storyboardAnchorFrame = 0
  const container = storyboardColumnRef.value
  if (!container || !storyboards.value.length) return
  const viewport = container.getBoundingClientRect()
  const viewportTop = viewport.top + 52
  let bestId = storyboards.value[0].id
  let bestVisibleHeight = -1
  let nearestDistance = Number.POSITIVE_INFINITY
  storyboards.value.forEach((shot) => {
    const card = storyboardCardRefs.get(shot.id)
    if (!card) return
    const rect = card.getBoundingClientRect()
    const visibleHeight = Math.max(0, Math.min(viewport.bottom, rect.bottom) - Math.max(viewportTop, rect.top))
    const distance = Math.abs((rect.top + rect.bottom) / 2 - (viewportTop + viewport.bottom) / 2)
    if (visibleHeight > bestVisibleHeight || (visibleHeight === bestVisibleHeight && distance < nearestDistance)) {
      bestId = shot.id
      bestVisibleHeight = visibleHeight
      nearestDistance = distance
    }
  })
  visibleStoryboardAnchorId.value = bestId
}

function scheduleVisibleStoryboardAnchorUpdate() {
  if (storyboardAnchorFrame) return
  storyboardAnchorFrame = window.requestAnimationFrame(updateVisibleStoryboardAnchor)
}

function jumpToStoryboardAnchor(shot) {
  const container = storyboardColumnRef.value
  const card = storyboardCardRefs.get(shot.id)
  if (!container || !card) return
  activeShotId.value = shot.id
  visibleStoryboardAnchorId.value = shot.id
  const viewport = container.getBoundingClientRect()
  const rect = card.getBoundingClientRect()
  container.scrollTo({
    top: Math.max(0, container.scrollTop + rect.top - viewport.top - 66),
    behavior: 'smooth',
  })
}

const displayedAssets = computed(() => assets.value.filter(asset => {
  if (isAudioAsset(asset)) return false
  if (activeCategory.value === 'all') return true
  if (asset.category !== activeCategory.value) return false
  if (activeCategory.value === 'audio' && activeAudioSubCategory.value !== 'all') {
    return getAudioSubType(asset) === activeAudioSubCategory.value
  }
  return true
}))

const audioCountAll = computed(() => assets.value.filter(a => a.category === 'audio' && getAudioSubType(a) === 'sfx').length)
const audioCountSfx = computed(() => assets.value.filter(a => a.category === 'audio' && getAudioSubType(a) === 'sfx').length)

// 悬浮窗已上移到全局（App.vue），这里只保留任务状态判断等业务逻辑。
const projectSaveLabel = computed(() => {
  const status = projectSaveStatus.value
  if (status.startsWith('正在')) return '保存中…'
  if (status.startsWith('保存失败')) return '保存失败'
  if (status.includes('待保存')) return '待保存'
  return '已保存'
})

const projectSaveTone = computed(() => {
  const status = projectSaveStatus.value
  if (status.startsWith('正在')) return 'saving'
  if (status.startsWith('保存失败')) return 'error'
  if (status.includes('待保存')) return 'pending'
  return 'saved'
})
const canonicalAssetsById = computed(() => {
  const map = new Map()
  assets.value.forEach((asset) => {
    const id = String(asset?.id || '')
    if (!id) return
    map.set(id, asset)
    map.set(id.toLowerCase(), asset)
  })
  return map
})
const imageModelOptions = computed(() => imageModels.value.map(model => ({
  label: model.name || model.modelName || '图片模型',
  value: String(model.id ?? model.modelName ?? ''),
})))
const textModelOptions = computed(() => textModels.value.map(model => ({
  label: model.name || model.modelName || '文本模型',
  value: String(model.id ?? model.modelName ?? ''),
})))
const audioModelOptions = computed(() => audioModels.value.map(model => ({
  label: `${model.name || model.modelName || '音频模型'}${model.provider ? ` (${model.provider})` : ''}`,
  value: String(model.id ?? model.modelName ?? ''),
})))
const seedanceModelOptions = computed(() => videoApiModels.value
  .map(model => ({
    label: `${model.name || model.modelName || '视频模型'}${model.provider ? ` (${model.provider})` : ''}`,
    value: String(model.id ?? model.modelName ?? ''),
  })))
const generationEngineOptions = [
  { label: 'Do · 自动', value: 'do' },
  { label: 'OriginaDoubao', value: 'doubao' },
  { label: 'Dola', value: 'dola' },
  { label: 'Seedance', value: 'seedance' },
]
const doAccountOptions = [
  { label: '自动分配', value: 'do' },
  { label: '原生豆包 (OriginaDoubao)', value: 'doubao' },
  { label: 'Dola (海螺国际版)', value: 'dola' },
]
const importedSummary = computed(() => {
  if (!importedFileName.value) return '支持最终 JSON 2.0：资产、提示词和分镜一次导入'
  const project = importedProjectTitle.value || importedFileName.value
  const version = importedSchemaVersion.value ? ` · v${importedSchemaVersion.value}` : ''
  return `${project}${version} · ${assets.value.length} 项资产 · ${storyboards.value.length} 个分镜`
})
const assetRawDetails = computed(() => {
  if (!assetDetailTarget.value) return ''
  const hidden = new Set(['cover', 'content', 'image', 'imageUrl', 'image_url', 'url', 'audioUrl', 'audio_url', 'generating', 'generationError'])
  return JSON.stringify(Object.fromEntries(Object.entries(assetDetailTarget.value).filter(([key]) => !hidden.has(key))), null, 2)
})

function createStoryboard(index) {
  return {
    id: `shot-${Date.now()}-${index}`,
    title: `分镜 ${String(index).padStart(2, '0')}`,
    prompt: '',
    references: [],
    referenceLabels: {},
    mode: 'reference',
    generationEngine: 'seedance',
    seedanceModel: defaultSeedanceModel.value,
    seedanceTaskId: '',
    seedanceTaskCreatedAt: 0,
    ratio: defaultVideoSettings.ratio,
    quality: defaultVideoSettings.quality,
    duration: defaultVideoSettings.duration,
    durationMode: 'seconds',
    sound: true,
    count: 1,
    modeOpen: false,
    settingsOpen: false,
    expanded: false,
    sendPreview: false,
    playerExpanded: false,
    videoPlaying: false,
    videoCurrent: 0,
    videoDuration: 0,
    videoMuted: false,
    referencesExpanded: false,
    inheritPrevTail: true,
    continuityMode: 'exact',
    continuitySourceFrame: null,
    continuityTailFrame: null,
    continuityReview: null,
    taskId: '',
    status: '',
    statusText: '',
    progress: 0,
    conversationId: '',
    conversationUrl: '',
    generationSubmittedAt: 0,
    resultUrl: '',
    resultPath: '',
    resultWatermarked: false,
    downloadingVideo: false,
    replacingVideo: false,
    videoReplaceError: '',
    generationError: '',
  }
}

function cleanError(err) {
  return String(err).replace(/^Error:\s*/, '')
}

async function videoProjectRequest(method, path, body = null) {
  return desktopBackendRequest(method, path, props.token, body)
}

async function loadVideoProjects() {
  projectListLoading.value = true
  projectError.value = ''
  try {
    const result = await videoProjectRequest('GET', '/video-project/list')
    videoProjects.value = Array.isArray(result) ? result : []
    await refreshTasks('')
  } catch (err) {
    projectError.value = cleanError(err)
  } finally {
    projectListLoading.value = false
  }
}

// 卡片上的“生成中 N”以实时任务表为准：按 projectId 统计未结束任务。
const videoProjectCards = computed(() => {
  const liveCounts = new Map()
  activeTasks.value.forEach(task => {
    if (!isActiveTask(task)) return
    const projectId = String(task.projectId || '')
    if (!projectId) return
    liveCounts.set(projectId, (liveCounts.get(projectId) || 0) + 1)
  })
  return videoProjects.value.map(project => ({
    ...project,
    runningCount: liveCounts.get(String(project.id || '')) || 0,
  }))
})

const filteredVideoProjectCards = computed(() => {
  const keyword = videoProjectKeyword.value.trim().toLowerCase()
  const projectFilter = videoProjectFilter.value
  return videoProjectCards.value.filter(project => {
    if (projectFilter === UNLINKED_PROJECT_FILTER) {
      if (String(project.projectId || '').trim()) return false
    } else if (projectFilter !== 'all' && String(project.projectId || '') !== projectFilter) {
      return false
    }
    if (!keyword) return true
    return [project.name, project.description]
      .some(field => String(field || '').toLowerCase().includes(keyword))
  })
})

async function loadAvailableProjects() {
  try {
    const result = await videoProjectRequest('GET', '/project/list')
    availableProjects.value = Array.isArray(result) ? result : []
    if (!newProjectId.value && availableProjects.value.length === 1) {
      newProjectId.value = String(availableProjects.value[0].id || '')
    }
  } catch (err) {
    projectError.value = cleanError(err)
  }
}

const projectLinkOptions = computed(() => availableProjects.value.map(project => ({
  value: String(project.id || ''),
  label: project.name || '未命名项目',
})))

const projectFilterOptions = computed(() => [
  { value: 'all', label: '全部项目' },
  { value: UNLINKED_PROJECT_FILTER, label: '未关联项目' },
  ...availableProjects.value.map(project => ({
    value: String(project.id || ''),
    label: project.name || '未命名项目',
  })),
])

const videoTaskSwitchOptions = computed(() => videoProjects.value.filter(project => !props.embedded || String(project.projectId || '') === props.scopeProjectId).map(project => ({
  value: String(project.id || ''),
  label: project.name || '未命名任务',
})))

async function switchActiveVideoTask(targetId) {
  if (!targetId || targetId === String(activeVideoProject.value?.id || '')) return
  const target = videoProjects.value.find(p => String(p.id || '') === String(targetId))
  if (target) {
    await saveActiveVideoProject()
    await openVideoProject(target)
  }
}

async function handleWorkbenchProjectChange(newProjectId) {
  if (!newProjectId) return
  const currentProjectId = String(activeVideoProject.value?.projectId || '')
  if (newProjectId === currentProjectId) return

  const targetProject = availableProjects.value.find(p => String(p.id || '') === String(newProjectId))
  const targetProjectName = targetProject?.name || ''

  // 检查是否已有该项目关联的视频任务，如果有则直接跳转切换至该任务
  const existingTask = videoProjects.value.find(p =>
    String(p.id || '') !== String(activeVideoProject.value?.id || '') &&
    (String(p.projectId || '') === String(newProjectId) || (targetProjectName && String(p.name || '').includes(targetProjectName)))
  )

  if (existingTask) {
    await saveActiveVideoProject()
    await openVideoProject(existingTask)
    return
  }

  // 否则更新当前任务的母剧本关联并保存
  if (activeVideoProject.value) {
    activeVideoProject.value.projectId = newProjectId
    await saveActiveVideoProject()
  }
}

function linkedProjectName(projectId = activeVideoProject.value?.projectId) {
  const id = String(projectId || '')
  return availableProjects.value.find(project => String(project.id || '') === id)?.name || '未关联项目'
}

function activeLinkedProjectId() {
  return String(activeVideoProject.value?.projectId || '').trim()
}

async function createVideoProject() {
  const name = newProjectName.value.trim()
  if (!name) {
    projectError.value = '请输入任务名称'
    return
  }
  projectCreating.value = true
  projectError.value = ''
  try {
    const project = await videoProjectRequest('POST', '/video-project', {
      name,
      projectId: newProjectId.value || '',
      ...projectStyleFields(availableProjects.value.find(item => String(item.id) === String(newProjectId.value)) || {}),
      description: newProjectDescription.value.trim(),
      assets: [],
      storyboards: [],
    })
    newProjectName.value = ''
    newProjectDescription.value = ''
    newProjectId.value = ''
    videoProjectCreateOpen.value = false
    await loadVideoProjects()
    await openVideoProject(project)
  } catch (err) {
    projectError.value = cleanError(err)
  } finally {
    projectCreating.value = false
  }
}

function restoreAssetMedia(asset) {
  // 资产的生成是同步请求，退出后无法续跑，重进即视为已结束
  const restored = { ...asset, generating: false, generationError: '' }
  delete restored.generatingStartedAt
  const fileId = restored.fileId || restored.coverId
  if (!restored.cover && fileId) restored.cover = fileDownloadUrl(fileId)
  delete restored.path
  if (restored.category === 'audio') {
    if (!restored.description && (restored.style || restored.desc || restored.sound)) {
      restored.description = String(restored.style || restored.desc || restored.sound || '').trim()
    }
    if (!restored.prompt || String(restored.prompt).includes('你好，很高兴认识你')) {
      restored.prompt = inferAudioPromptFromProject(restored)
    }
  }
  return restored
}

function resolveAssetReference(asset) {
  const id = String(asset?.id || '')
  if (!id) return asset
  return canonicalAssetsById.value.get(id)
    || canonicalAssetsById.value.get(id.toLowerCase())
    || asset
}

const ACTIVE_TASK_STATUSES = new Set(['queued', 'pending', 'preparing', 'opening', 'configuring', 'uploading', 'submitting', 'generating', 'processing', 'running', 'sharing', 'downloading', 'finalizing', 'returning_to_conversation', 'confirming_authorization', 'waiting_confirmation'])

function isActiveTask(task) {
  return ACTIVE_TASK_STATUSES.has(String(task?.status || '').toLowerCase())
}

async function refreshTasks(projectId = '') {
  if (!window.pywebview?.api?.list_tasks) return []
  try {
    const tasks = await window.pywebview.api.list_tasks(String(projectId || ''))
    activeTasks.value = Array.isArray(tasks) ? tasks : []
  } catch (err) {
    activeTasks.value = []
  }
  return activeTasks.value
}

// 进入任务时按后端任务表恢复：进行中的任务接上轮询并显示进度；
// 已结束的任务由后端 _apply_task_result 回写业务数据，这里只需重新拉取详情。
async function hydrateRunningTasks(detail) {
  const projectId = String(detail?.id || activeVideoProject.value?.id || '')
  const navigation = workspaceNavigation
  const tasks = await refreshTasks(projectId)
  if (workspaceDisposed || navigation !== workspaceNavigation || projectId !== String(activeVideoProject.value?.id || '')) return
  const runningOwners = new Set(
    tasks.filter(task => isActiveTask(task) && task.ownerType === 'videoShot')
      .map(task => String(task.ownerId || '')),
  )
  storyboards.value.forEach(shot => {
    // Muse/Seedance jobs live on the shot, independently of browser-worker tasks.
    // An empty list_tasks result must not erase or suppress their saved receipt.
    if (shot.generationEngine === 'seedance') {
      restoreSeedanceTask(shot)
      return
    }
    const task = tasks.find(item => item.ownerType === 'videoShot' && String(item.ownerId || '') === String(shot.id || ''))
    if (!task) return
    if (isActiveTask(task)) {
      const engine = String(task.generationEngine || '')
      if (engine === 'do' || engine === 'doubao' || engine === 'dola') shot.generationEngine = engine
      if (engine === 'seedance') {
        // Seedance 轮询依赖分镜自带的 seedanceTaskId/seedanceModel，
        // 不能用任务表 id 覆盖分镜的 taskId。
        if (engine) shot.generationEngine = engine
        shot.status = task.status || 'generating'
        shot.statusText = task.statusText || '正在生成'
        shot.progress = Number(task.progress || 0)
        return
      }
      shot.taskId = String(task.id || '')
      shot.status = task.status || 'generating'
      shot.statusText = task.statusText || '正在生成'
      shot.progress = Number(task.progress || 0)
      shot.accountId = String(task.accountId || '')
      return
    }
    if (task.status === 'failed') {
      shot.status = 'failed'
      shot.statusText = task.statusText || '生成失败'
      shot.generationError = task.statusText || '生成失败'
    }
  })
  // 启动轮询：仍在跑的分镜
  storyboards.value
    .filter(shot => shot.generationEngine === 'seedance'
      ? shotRunning(shot) && Boolean(shot.taskId || shot.seedanceTaskId)
      : runningOwners.has(String(shot.id || '')))
    .forEach(shot => {
      if (shot.generationEngine === 'seedance') {
        if (shot.seedanceTaskId) pollSeedanceShot(shot)
      } else if (shot.taskId) {
        pollShot(shot)
      }
    })
}

async function openVideoProject(project) {
  if (!project?.id) return
  workspaceNavigation += 1
  storyboards.value.forEach(shot => stopPolling(shot.id))
  projectError.value = ''
  projectDetailLoading.value = true
  try {
    const detail = removeAudioAssets(await videoProjectRequest('GET', `/video-project/${encodeURIComponent(project.id)}`))
    hydratingProject = true
    activeVideoProject.value = detail
    assets.value = (Array.isArray(detail.assets) ? detail.assets : []).map(restoreAssetMedia)
    const storedStoryboards = Array.isArray(detail.storyboards) ? detail.storyboards : []
    storyboards.value = storedStoryboards.length
      ? storedStoryboards.map((stored, index) => {
          const shot = { ...createStoryboard(index + 1), ...stored }
          shot.prompt = cleanShotAudioPrompt(shot.prompt)
          if (shot.dubbingAudio) shot.dubbingAudio = restoreAssetMedia(shot.dubbingAudio)
          shot.dialogueBaseline ||= dialogueContract(shot.prompt)
          ensureStoryboardDefaults(shot)
          if (shot.audioReview?.status === 'checking') shot.audioReview = { status: 'unavailable', summary: '上次台词核验中断，请重新核验' }
          shot.references = (Array.isArray(stored.references) ? stored.references : []).map((reference) => {
            const restoredReference = restoreAssetMedia(reference)
            return resolveAssetReference(restoredReference)
          })
          shot.continuityMode = stored.continuityMode || (stored.continuityTailFrame?.isMatrixCropped ? 'matchCut' : 'exact')
          if (stored.inheritPrevTail === undefined && /空间切换|换场景|转场切镜/.test(shot.prompt)) shot.inheritPrevTail = false
          alignAuthoredContinuity(shot)
          synchronizeShotAssets(shot)
          if (!shot.continuitySourceFrame && shot.continuityTailFrame && !shot.continuityTailFrame.isMatrixCropped) {
            shot.continuitySourceFrame = { ...shot.continuityTailFrame }
          }
          shot.modeOpen = false
          shot.settingsOpen = false
          shot.expanded = false
          shot.sendPreview = false
          shot.showHistoricalResult = false
          shot.playerExpanded = false
          shot.referencesExpanded = false
          shot.replacingVideo = false
          shot.videoReplaceError = ''
          if (shot.mixedVideoFileId && shot.mixedAudioFileId && shot.resultFileId !== shot.mixedVideoFileId && !shot.previewOriginal) {
            shot.resultFileId = shot.mixedVideoFileId
          }
          if (shot.resultFileId) shot.resultUrl = fileDownloadUrl(shot.resultFileId)
          else if (!shot.resultUrl?.startsWith('http')) shot.resultUrl = ''
          shot.resultPath = ''
          // 任务状态由后端任务表统一管理，恢复见下方 hydrateRunningTasks。
          shot.taskId = ''
          shot.status = ''
          shot.statusText = ''
          shot.progress = 0
          if (hasFailedAttempt(shot)) {
            shot.status = shot.lastGenerationAttempt.status === 'cancelled' ? 'cancelled' : 'failed'
            shot.generationError = shot.lastGenerationAttempt.error || '上次生成没有产出新成片'
          }
          restoreSeedanceTask(shot)
          return shot
        })
      : [createStoryboard(1)]
    activeShotId.value = storyboards.value[0].id
    activeCategory.value = 'all'
    importedProjectTitle.value = detail.name || ''
    importedFileName.value = ''
    importedSchemaVersion.value = ''

    // 自动补齐缺失的分镜剧本内容并初始化各集分镜管理
    if (detail.projectId) {
      try {
        const chapterList = await videoProjectRequest('GET', `/project/${encodeURIComponent(detail.projectId)}/chapter/list`)
        dramaChapters.value = Array.isArray(chapterList) ? chapterList : []
        const matchingChapter = (Array.isArray(chapterList) ? chapterList : []).find(ch =>
          (detail.currentEpisodeId && String(ch.id) === String(detail.currentEpisodeId)) ||
          (detail.description && detail.description.includes(`章节 ID ${ch.id}`)) ||
          (detail.name && detail.name.includes(ch.title || '---'))
        ) || (Array.isArray(chapterList) ? chapterList[0] : null)
        currentChapterId.value = matchingChapter ? String(matchingChapter.id) : (dramaChapters.value[0]?.id ? String(dramaChapters.value[0].id) : '')
        detail.episodes ||= {}
        if (currentChapterId.value && !detail.episodes[currentChapterId.value]) {
          detail.episodes[currentChapterId.value] = {
            id: currentChapterId.value,
            title: matchingChapter?.title || '未命名集',
            storyboards: storedStoryboards.map(s => ({ ...s }))
          }
        }
        const cd = matchingChapter?.workflow?.creationData
        if (cd && Array.isArray(cd.shots) && cd.shots.length) {
          const cdAssetMap = new Map()
          const cons = cd.consistency || cd.assets || {}
          ;['characters', 'scenes', 'props', 'audio'].forEach(grp => {
            ;(Array.isArray(cons[grp]) ? cons[grp] : []).forEach(it => {
              if (it?.id) {
                cdAssetMap.set(String(it.id), it)
                cdAssetMap.set(String(it.id).toLowerCase(), it)
              }
            })
          })
          const cdShotMap = new Map(cd.shots.map(s => [String(s.id), s]))
          storyboards.value.forEach((shot, index) => {
            const cleanId = String(shot.id || '').replace(/^json-shot-/, '')
            const cdShot = cdShotMap.get(cleanId) || cd.shots[index]
            if (cdShot && (!shot.prompt || shot.prompt === shot.title)) {
              const rawRefs = Array.isArray(cdShot.references) ? [...cdShot.references] : []
              if (cdShot.scene_id && !rawRefs.some(r => (typeof r === 'object' ? r?.id : r) === cdShot.scene_id)) {
                rawRefs.unshift(cdShot.scene_id)
              }
              const refIds = rawRefs.map(r => typeof r === 'object' && r ? String(r.id || '') : String(r || '')).filter(Boolean)
              const consistencyItems = refIds.map(id => {
                const a = cdAssetMap.get(id) || cdAssetMap.get(id.toLowerCase())
                const name = a?.name || shot.referenceLabels?.[id] || id
                return `${name} {{${id}}}`
              })
              const consistencyText = consistencyItems.length ? `一致性引用：${consistencyItems.join('，')}` : ''
              shot.prompt = [consistencyText, shotPromptFor(cdShot)].filter(Boolean).join('\n')
            }
          })
        }
      } catch (_) {}
    }

    await nextTick()
    reconcileAllShotsAssetConsistency()
    maintainTransitions(storyboards.value)
    refreshLegacyVoiceBindings()
    scheduleVisibleStoryboardAnchorUpdate()
    await hydrateRunningTasks(detail)
    useProductionView()
    await nextTick()
    savedProductionPayload = JSON.stringify(projectPayload())
    hydratingProject = false
  } catch (err) {
    hydratingProject = false
    projectError.value = cleanError(err)
  } finally {
    projectDetailLoading.value = false
  }
}

function persistedAsset(asset) {
  const saved = { ...asset }
  delete saved.path
  delete saved.uploading
  delete saved.previewFailed
  // 生成中的资产记录 startedAt 时间戳，重进任务时据此恢复“正在生成”态
  if (saved.generating) saved.generatingStartedAt = Number(saved.generatingStartedAt || Date.now())
  else delete saved.generatingStartedAt
  delete saved.generating
  delete saved.generationError
  if (saved.fileId || saved.coverId) delete saved.cover
  return saved
}

function projectPayload() {
  const currentEpId = currentChapterId.value || ''
  const episodesMap = { ...(activeVideoProject.value?.episodes || {}) }
  const currentTitle = dramaChapters.value.find(c => String(c.id) === currentEpId)?.title || ''
  const sanitizedShots = storyboards.value.map(shot => {
    const saved = { ...shot, references: shot.references.map(persistedAsset) }
    if (shot.dubbingAudio) saved.dubbingAudio = persistedAsset(shot.dubbingAudio)
    delete saved.modeOpen
    delete saved.settingsOpen
    delete saved.settingsPopoverStyle
    delete saved.expanded
    delete saved.showHistoricalResult
    delete saved.sendPreview
    delete saved.playerExpanded
    delete saved.videoPlaying
    delete saved.videoCurrent
    delete saved.videoDuration
    delete saved.videoMuted
    delete saved.referencesExpanded
    delete saved.breezeOpen
    delete saved.workspaceTab
    delete saved.generalAdvanced
    delete saved.previewOriginal
    delete saved.originalPreviewUrl
    delete saved.previewStopAt
    delete saved.taskId
    delete saved.status
    delete saved.statusText
    delete saved.progress
    delete saved.resultPath
    if (saved.resultFileId) delete saved.resultUrl
    delete saved.downloadingVideo
    delete saved.replacingVideo
    delete saved.videoReplaceError
    delete saved.generationError
    return saved
  })
  if (currentEpId) {
    episodesMap[currentEpId] = {
      id: currentEpId,
      title: currentTitle,
      storyboards: sanitizedShots,
    }
  }
  return {
    name: activeVideoProject.value?.name || importedProjectTitle.value || '未命名任务',
    projectId: activeLinkedProjectId(),
    currentEpisodeId: currentEpId,
    episodes: episodesMap,
    ...(activeVideoProject.value?.style ? projectStyleFields(activeVideoProject.value) : {}),
    description: activeVideoProject.value?.description || '',
    breezeVoices: activeVideoProject.value?.breezeVoices || {},
    breezeRoot: activeVideoProject.value?.breezeRoot || '',
    performancePolicy: activeVideoProject.value?.performancePolicy || null,
    ...(activeVideoProject.value?.nativeFilm ? { nativeFilm: activeVideoProject.value.nativeFilm } : {}),
    assets: assets.value.filter(asset => !isAudioAsset(asset)).map(persistedAsset),
    storyboards: sanitizedShots,
  }
}

async function saveActiveVideoProject() {
  if (!activeVideoProject.value?.id || hydratingProject) return
  const projectId = activeVideoProject.value.id
  const payload = projectPayload()
  if (JSON.stringify(payload) === savedProductionPayload) return true
  if (projectSaveTimer) {
    window.clearTimeout(projectSaveTimer)
    projectSaveTimer = null
  }
  projectSaveStatus.value = '正在保存…'
  try {
    const saved = await videoProjectRequest(
      'PUT',
      `/video-project/${encodeURIComponent(projectId)}`,
      payload,
    )
    if (String(activeVideoProject.value?.id || '') !== String(projectId)) return true
    activeVideoProject.value = { ...activeVideoProject.value, ...saved }
    savedProductionPayload = JSON.stringify(payload)
    projectSaveStatus.value = '已保存到本地'
    return true
  } catch (err) {
    if (String(activeVideoProject.value?.id || '') === String(projectId)) projectSaveStatus.value = `保存失败：${cleanError(err)}`
    return false
  }
}

function scheduleProjectSave() {
  if (!activeVideoProject.value?.id || hydratingProject) return
  if (JSON.stringify(projectPayload()) === savedProductionPayload) return
  projectSaveStatus.value = '有修改待保存'
  if (projectSaveTimer) window.clearTimeout(projectSaveTimer)
  projectSaveTimer = window.setTimeout(saveActiveVideoProject, 400)
}

async function backToVideoProjects() {
  workspaceNavigation += 1
  await saveActiveVideoProject()
  storyboards.value.forEach(shot => stopPolling(shot.id))
  activeVideoProject.value = null
  assets.value = []
  storyboards.value = [createStoryboard(1)]
  activeShotId.value = storyboards.value[0].id
  projectSaveStatus.value = ''
  dramaChapters.value = []
  currentChapterId.value = ''
  await loadVideoProjects()
}

async function loadGenerators() {
  loading.value = true
  error.value = ''
  try {
    if (!window.pywebview?.api) {
      error.value = '图片生成接口尚未就绪，请从桌面客户端打开'
      return
    }
    const [imageResult, videoResult, textResult, audioResult] = await Promise.all([
      window.pywebview.api.backend_request('GET', '/api/admin/models/public/list?modelType=image', props.token, null),
      window.pywebview.api.backend_request('GET', '/api/admin/models/public/list?modelType=video', props.token, null),
      window.pywebview.api.backend_request('GET', '/api/admin/models/public/list?modelType=text', props.token, null),
      window.pywebview.api.backend_request('GET', '/api/admin/models/public/list?modelType=audio', props.token, null),
    ])
    imageModels.value = Array.isArray(imageResult) ? imageResult : []
    videoApiModels.value = Array.isArray(videoResult) ? videoResult : []
    textModels.value = Array.isArray(textResult) ? textResult : []
    audioModels.value = Array.isArray(audioResult) ? audioResult : []

    const currentImgMatch = imageModels.value.some(m => String(m.id ?? m.modelName ?? '') === selectedImageModel.value)
    if (!currentImgMatch || !selectedImageModel.value) {
      selectedImageModel.value = String(imageModels.value[0]?.id ?? imageModels.value[0]?.modelName ?? '')
    }

    const currentTxtMatch = textModels.value.some(m => String(m.id ?? m.modelName ?? '') === selectedTextModel.value)
    if (!currentTxtMatch || !selectedTextModel.value) {
      selectedTextModel.value = String(textModels.value[0]?.id ?? textModels.value[0]?.modelName ?? '')
    }

    const currentAudioMatch = audioModels.value.some(m => String(m.id ?? m.modelName ?? '') === selectedAudioModel.value)
    if (!currentAudioMatch || !selectedAudioModel.value) {
      selectedAudioModel.value = String(audioModels.value[0]?.id ?? audioModels.value[0]?.modelName ?? '')
    }

    const currentVideoMatch = videoApiModels.value.some(m => String(m.id ?? m.modelName ?? '') === defaultSeedanceModel.value)
    if (!currentVideoMatch || !defaultSeedanceModel.value) {
      defaultSeedanceModel.value = String(videoApiModels.value[0]?.id ?? videoApiModels.value[0]?.modelName ?? '')
    }
    // Refreshing an operations menu must never replace a saved model when a
    // provider is unavailable. Existing shots retain their explicit choice;
    // generation validates it, and new drafts may use the current default.
    if (!activeVideoProject.value?.id) storyboards.value.forEach((shot) => {
      if (!shot.seedanceModel) shot.seedanceModel = defaultSeedanceModel.value
    })
  } catch (err) {
    error.value = cleanError(err)
  } finally {
    loading.value = false
  }
}

function absoluteMediaUrl(value) {
  const url = String(value || '').trim()
  if (!url || /^(?:https?:|data:|blob:)/i.test(url)) return url
  const fileId = fileIdFromUrl(url)
  const base = fileId.startsWith('local_') ? props.storageBase : props.apiBase
  return `${base}${url.startsWith('/') ? '' : '/'}${url}`
}

function fileIdFromUrl(value) {
  return decodeURIComponent(String(value || '').match(/\/file\/([^/]+)\/download/)?.[1] || '')
}

function assetMediaValue(item) {
  const candidates = [item?.cover, item?.content, item?.image, item?.imageUrl, item?.image_url, item?.url, item?.audioUrl, item?.audio_url]
  return candidates.find(value => typeof value === 'string' && value.trim()) || ''
}

function assetPromptFor(item, category) {
  const fields = category === 'role'
    ? ['name', 'gender_age', 'appearance', 'face_features', 'body_features', 'hair', 'outfit', 'clothing', 'accessories', 'temperament', 'personality', 'description', 'prompt']
    : category === 'scene'
      ? ['name', 'environment', 'atmosphere', 'architecture', 'lighting', 'color', 'key_elements', 'continuity', 'front_view', 'left_view', 'right_view', 'back_view', 'ceiling', 'ground', 'description', 'prompt']
      : category === 'prop'
        ? ['name', 'appearance', 'material', 'color', 'texture', 'key_details', 'tags', 'scene', 'holder', 'continuity', 'function', 'description', 'prompt']
        : category === 'layout'
          ? ['name', 'spatial_state', 'camera_composition', 'ui_placeholders', 'characters', 'character_instances', 'props', 'reuse_shots', 'description', 'prompt']
          : ['prompt', 'text', 'dialogue', 'content', 'lines', 'style', 'description', 'desc', 'sound', 'voice_desc', 'sfx_desc', 'catchphrase', 'speed', 'tone', 'emotion', 'name', 'character', 'voice']
  return fields
    .flatMap(key => Array.isArray(item?.[key]) ? item[key] : [item?.[key]])
    .filter(value => typeof value === 'string' && value.trim() && !value.includes('你好，很高兴认识你'))
    .join('，')
}

// 全集项目级角色统一声学指纹缓存，复用固定文字描述；实际音色仍由生成端决定
const projectCharacterVoiceRegistry = new Map()

function getCanonicalVoicePreset(gender, age, desc = '') {
  const numAge = parseInt(age || '0')
  if (gender === '男') {
    if (numAge >= 50 || /老|沧桑|大爷|老者/.test(desc)) return 'longshu_v2'
    if (/霸气|威严|长老|宗主|掌门/.test(desc)) return 'longjing_v2'
    if (/壮汉|粗犷|豪放/.test(desc)) return 'longlaotie_v2'
    if (numAge < 25 || /少年|少侠|学徒|年轻/.test(desc)) return 'longyuan_v2'
    return 'longshuo_v2'
  } else if (gender === '女') {
    if (numAge <= 16 || /萝莉|萌|幼/.test(desc)) return 'longmiao_v2'
    if (numAge <= 25 || /少女|学徒|活泼|灵动/.test(desc)) return 'longtian_v2'
    if (/知性|高冷|师姐|仙尊|女帝/.test(desc)) return 'longyue_v2'
    return 'longxiaochun_v2'
  }
  return 'longshuo_v2'
}

function extractCharacterVoiceProfile(charAsset, fallbackName = '', mood = '') {
  const name = String(charAsset?.name || fallbackName || '角色').trim()
  const key = `${activeVideoProject.value?.id || 'draft'}:${charAsset?.id || name.toLowerCase()}`

  // 如果已有全集统一声学档案，基准声学属性严格锁死一致，避免同人不同音
  if (projectCharacterVoiceRegistry.has(key)) {
    const cached = projectCharacterVoiceRegistry.get(key)
    return { ...cached }
  }

  let identity = charAsset?.role || charAsset?.identity || charAsset?.occupation || ''
  let gender = ''
  let age = ''
  const declaredGender = String(charAsset?.gender || charAsset?.sex || charAsset?.gender_age || '')
  if (/女/.test(declaredGender)) gender = '女'
  else if (/男/.test(declaredGender)) gender = '男'
  const genderAge = String(charAsset?.gender_age || charAsset?.age || '')
  const ageMatch = genderAge.match(/(\d+\s*岁)/) || String(charAsset?.appearance || '').match(/(\d+\s*岁)/)
  if (ageMatch) age = ageMatch[1]

  const desc = `${name} ${charAsset?.appearance || ''} ${charAsset?.description || ''}`
  if (!identity) {
    const occMatch = desc.match(/(摄影师|摄影店主|学徒|侦探|巡警|警察|医生|护士|剑修|掌门|长老|杀手|将军|掌柜|店小二|特工|军官|少爷|小姐|老板|店主|工人|法师|少年|老人|道士|僧人|青年|女孩|老者)/)
    if (occMatch) identity = occMatch[1]
    else identity = name || '角色'
  }
  if (!gender) {
    if (/女|少女|妇|姨|姑娘|老太|师妹|女士|母亲|姐姐|妹妹|阿姨|婆婆|奶奶/.test(desc)) gender = '女'
    else if (/男|青年|少年|壮汉|老者|叔|大爷|汉子|老头|师父|师傅|先生|父亲|爷爷/.test(desc)) gender = '男'
  }

  const numAge = parseInt(age || '0')
  let pitch = charAsset?.pitch || charAsset?.voice_pitch || ''
  if (!pitch) {
    if (gender === '男') {
      pitch = (numAge && numAge >= 50) ? '低沉中音' : (numAge && numAge < 25 ? '清朗中音' : '沉稳中音')
    } else if (gender === '女') {
      pitch = (numAge && numAge <= 25) ? '清脆中高音' : '柔和中音'
    } else {
      pitch = (numAge && numAge >= 50) ? '低沉中音' : (numAge && numAge < 20 ? '清亮中音' : '自然中音')
    }
  }

  let texture = charAsset?.voice_texture || charAsset?.texture || ''
  if (!texture) {
    const temp = `${charAsset?.temperament || ''} ${charAsset?.personality || ''} ${desc}`
    if (/老|沧桑|疲惫|干瘪|岁月|磨损|皱纹|白发|灰白/.test(temp) || numAge >= 55) texture = '沙哑微带沧桑颗粒感'
    else if (/冷|冰|淡|威严|霸气/.test(temp)) texture = '冷峻沉实带有磁性'
    else if (/年轻|活泼|急|慌|稚气|学徒|喘/.test(temp)) texture = '通透明晰'
    else if (/温|和|柔|慈祥|文雅/.test(temp)) texture = '温润饱满'
    else texture = gender === '男' ? '醇厚微带颗粒感' : '干净清晰'
  }

  const feature = '自然吐字连贯'

  const voiceId = charAsset?.voice || getCanonicalVoicePreset(gender, age, desc)
  const profile = { identity, gender, age, pitch, texture, feature, name, voiceId }
  if (name && key) {
    projectCharacterVoiceRegistry.set(key, profile)
  }
  if (charAsset && !charAsset.voice) {
    charAsset.voice = voiceId
  }
  return profile
}

function applySixDimAudioFormulaToShot(shot) {
  if (!shot) return
  shot.prompt = cleanShotAudioPrompt(shot.prompt)
  const contract = dialogueContract(shot.prompt)
  if (!contract.explicit) {
    shot.generationError = '请先填写带引号的对白，或明确写“对白：无。”；不会自动补写人声'
    return
  }
  const voices = (shot.references || []).filter(a => a.category === 'role').map(a => {
    const p = extractCharacterVoiceProfile(a, a.name, '')
    return `【统一音色·${p.name}】${[p.gender, p.age, p.pitch, p.texture].filter(Boolean).join('，')}`
  })
  const source = shot.prompt.match(/^(?:音频提示词|音频|声音)[：:](.*)$/m)?.[1] || ''
  const environment = source.split(/[；;]/).filter(s => !/^【统一音色/.test(s.trim()))
  shot.audio_prompt = cleanAudioPrompt([...voices, ...environment].join('；'))
  const line = `音频提示词：${shot.audio_prompt || '本镜所需环境声与动作拟音'}`
  shot.prompt = /^(?:音频提示词|音频|声音)[：:]/m.test(shot.prompt)
    ? shot.prompt.replace(/^(?:音频提示词|音频|声音)[：:].*$/m, line) : `${shot.prompt}\n${line}`
  shot.generationError = ''
  shot.statusText = '已整理声音描述；原台词和逐句语气保留，未绑定真实音色'
  scheduleProjectSave()
}

function hasContinuityConflictOrDurationError(shot) {
  const err = String(shot?.lastGenerationAttempt?.error || shot?.generationError || '').toLowerCase()
  return /上限是\s*10|10\s*秒|13\s*秒|做不出\s*13|敬礼|双手自然垂于身侧|首帧规则|第0秒|upstream replied with text only/i.test(err)
}

async function resolveShotConflictAndRegenerate(shot) {
  if (!shot) return
  shot.duration = 10
  if (typeof shot.prompt === 'string') {
    shot.prompt = shot.prompt.replace(/【00:00-00:\d+】/g, '【00:00-00:10】')
    shot.prompt = shot.prompt.replace(/双手自然垂于身侧/g, '第0秒承接上一镜敬礼姿态，随后放下右手、转而目视镜头')
  }
  if (shot.actionChain) {
    shot.actionChain.start = '第0秒，承接上一镜学生敬礼姿态，红旗灯笼在后；随后放下右手，转而目视镜头开始庄严独白。'
  }
  if (shot.lastGenerationAttempt) {
    shot.lastGenerationAttempt.error = ''
  }
  shot.generationError = ''
  scheduleProjectSave()
  showWorkspaceToast('⚡ 已自动调整单镜上限为10秒并对齐首帧敬礼姿态！正在重新生成…', 'success')
  await generateShot(shot)
}

async function optimizeShotPrompt(shot) {
  if (!shot) return
  const currentPrompt = (shot.prompt || '').trim()
  if (!currentPrompt) {
    showWorkspaceToast('⚠️ 提示词为空，请先填写分镜画面描述', 'warning')
    return
  }
  const errorReason = String(shot.lastGenerationAttempt?.error || shot.generationError || '').trim()
  if (/上限是\s*10|10\s*秒|13\s*秒|做不出\s*13/i.test(errorReason) || Number(shot.duration) > 10) {
    shot.duration = 10
    if (typeof shot.prompt === 'string') {
      shot.prompt = shot.prompt.replace(/【00:00-00:\d+】/g, '【00:00-00:10】')
    }
  }
  if (/敬礼|双手自然垂于身侧|首帧规则|第0秒/i.test(errorReason)) {
    if (shot.actionChain) {
      shot.actionChain.start = '第0秒，承接上一镜学生敬礼姿态，红旗灯笼在后；随后放下右手，转而目视镜头开始庄严独白。'
    }
    if (typeof shot.prompt === 'string') {
      shot.prompt = shot.prompt.replace(/双手自然垂于身侧/g, '第0秒承接上一镜敬礼姿态，随后放下右手、转而目视镜头')
    }
  }
  shot.optimizingPrompt = true
  if (!shot._originalPromptBeforeOptimize) {
    shot._originalPromptBeforeOptimize = currentPrompt
  }

  try {
    let optimized = ''
    let source = ''

    // 1. If backend API is available, call /ai/optimize-prompt
    if (window.pywebview?.api) {
      try {
        const payload = {
          model: selectedTextModel.value || textModels.value[0]?.id || textModels.value[0]?.modelName || '',
          prompt: currentPrompt,
          error: errorReason,
          title: shot.title || ''
        }
        const res = await window.pywebview.api.backend_request('POST', '/ai/optimize-prompt', props.token, payload)
        if (res?.optimized) {
          optimized = String(res.optimized).trim()
          source = res.source || 'ai'
        }
      } catch (apiErr) {
        console.warn('Backend optimize-prompt failed, falling back to local sanitizer:', apiErr)
      }
    }

    // 2. Client-side fallback if backend was unavailable
    if (!optimized) {
      optimized = sanitizePromptWithRules(currentPrompt, errorReason)
      source = 'rules'
    }

    if (optimized && optimized !== currentPrompt) {
      shot.prompt = optimized
      if (shot.generationError) shot.generationError = ''
      scheduleProjectSave()
      const sourceLabel = source === 'ai' ? 'AI 针对报错动态润色' : '智能去敏规则'
      showWorkspaceToast(`✨ 已通过${sourceLabel}优化提示词！${errorReason ? '已修正导致拒答的表述' : '画面描述更规范'}`, 'success')
    } else {
      showWorkspaceToast('提示词已为精简优化状态，无需额外变动', 'info')
    }
  } catch (err) {
    showWorkspaceToast('优化提示词出错：' + cleanError(err), 'error')
  } finally {
    shot.optimizingPrompt = false
  }
}

function sanitizePromptWithRules(prompt, error) {
  let text = prompt || ''
  text = text.replace(/[，,、\s]*只拍[^，,。\n]*?不拍[^，,。\n]*?(?=[，,。\n]|$)/g, '')
  text = text.replace(/[，,、\s]*不拍[^\s，,。\n]*?(?=[，,。\n]|$)/g, '')
  text = text.replace(/[，,、\s]*不允许画反/g, '')
  text = text.replace(/[，,、\s]*禁止[^\s，,。\n]*?(?=[，,。\n]|$)/g, '')
  text = text.replace(/[，,、\s]*不能[^\s，,。\n]*?(?=[，,。\n]|$)/g, '')
  text = text.replace(/爆炸|炸开|炸碎|巨炸/g, '剧烈震颤冲击')
  text = text.replace(/血腥|残暴|砍杀|割喉/g, '猛烈冲击')
  text = text.replace(/[，,、\s]*笔尖沙沙声/g, '')
  text = text.replace(/[，,、\s]*声音在前/g, '')
  text = text.replace(/[，,、\s]*(?:远处|近处)?(?:先)?(?:传来)?沉闷巨响/g, '突然桌面猛烈晃动')
  text = text.replace(/[，,、\s]*(?:传来)?(?:巨响|轰鸣声|爆炸声)/g, '猛烈震颤冲击')
  text = text.replace(/[，,、\s]*(?:清晰的)?脚步声/g, '快步走动')
  text = text.replace(/[，,、\s]*(?:刺耳的)?刹车声/g, '车辆急停晃动')
  text = text.replace(/[，,]{2,}/g, '，')
  text = text.replace(/[。]{2,}/g, '。')
  text = text.replace(/^[，,。、\s]+/g, '')
  text = text.replace(/[，,、\s]+(?=[。])/g, '')
  text = text.replace(/[，,]\n/g, '\n')
  return text.trim()
}

function reconcileAllShotsAssetConsistency() {
  if (!Array.isArray(storyboards.value) || !storyboards.value.length || !canonicalAssetsById.value.size) return 0
  let updatedCount = 0
  storyboards.value.forEach(shot => {
    // 1. 同步 references 数组中的资产命名
    if (Array.isArray(shot.references)) {
      shot.references.forEach(ref => {
        const refId = String(ref?.id || ref || '')
        const canonical = canonicalAssetsById.value.get(refId) || canonicalAssetsById.value.get(refId.toLowerCase())
        if (canonical && typeof ref === 'object' && ref) {
          if (canonical.name) ref.name = canonical.name
          if (canonical.category) ref.category = canonical.category
          if (canonical.fileId) ref.fileId = canonical.fileId
          if (canonical.coverId) ref.coverId = canonical.coverId
          if (canonical.cover) ref.cover = canonical.cover
        }
      })
    }
    // 2. 同步 referenceLabels 字典中的资产命名
    if (!shot.referenceLabels || typeof shot.referenceLabels !== 'object') {
      shot.referenceLabels = {}
    }
    Object.keys(shot.referenceLabels).forEach(id => {
      const canonical = canonicalAssetsById.value.get(id) || canonicalAssetsById.value.get(id.toLowerCase())
      if (canonical?.name && shot.referenceLabels[id] !== canonical.name) {
        shot.referenceLabels[id] = canonical.name
      }
    })
    const refIds = (shot.references || []).map(r => String(r?.id || r || '')).filter(Boolean)
    refIds.forEach(id => {
      const canonical = canonicalAssetsById.value.get(id) || canonicalAssetsById.value.get(id.toLowerCase())
      if (canonical?.name) {
        shot.referenceLabels[id] = canonical.name
      }
    })

    // 3. 动态修正 shot.prompt 中的引用标签（如将 牛皮纸箱 {{prop_paperbox}} 纠正为 牛皮纸相盒 {{prop_paperbox}}）
    if (shot.prompt) {
      const newPrompt = shot.prompt.replace(/([^\s，,、:：\n]+)\s*([{｛]{1,2}\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*[}｝]{1,2})/g, (fullMatch, oldLabel, token, assetId) => {
        const canonical = canonicalAssetsById.value.get(assetId) || canonicalAssetsById.value.get(assetId.toLowerCase())
        if (canonical?.name) {
          shot.referenceLabels[assetId] = canonical.name
          if (oldLabel !== canonical.name) {
            return `${canonical.name} ${token}`
          }
        }
        return fullMatch
      })
      if (newPrompt !== shot.prompt) {
        shot.prompt = newPrompt
        updatedCount += 1
      }
    }
  })
  return updatedCount
}

const croppingPortrait = ref(false)

function extractCharacterVisualFingerprint(charAsset, name) {
  if (!charAsset && !name) return ''
  const source = `${charAsset?.appearance || ''} ${charAsset?.description || ''} ${charAsset?.prompt || ''} ${name || ''}`
  
  // 提取年龄
  let age = ''
  const ageMatch = source.match(/(\d{1,2}\s*岁(?:左右|上下)?|少年|青年|中年|老年|二十出头|弱冠之年|耄耋)/)
  if (ageMatch) age = ageMatch[1]
  
  // 提取发型/面部
  let face = ''
  const faceMatch = source.match(/(短寸|短发|长发|平头|短平头|寸头|白发|花白短发|高马尾|披肩发|圆脸|方脸|削瘦|单眼皮|双眼皮|浓眉|沧桑|饱经风霜|清秀|憨厚|深纹)/g)
  if (faceMatch) face = Array.from(new Set(faceMatch)).slice(0, 3).join('')

  // 提取核心服装/特征
  let attire = ''
  const attireMatch = source.match(/(工装[衫裤]?|布衫|围裙|衬衫|棉袄|西装|夹克|长衫|深蓝[色布]?工装|灰布围裙|老旧[^\s，,、]+|无徽章|素面)/g)
  if (attireMatch) attire = Array.from(new Set(attireMatch)).slice(0, 2).join('，')

  const parts = [age, face, attire].filter(Boolean)
  if (!parts.length) {
    if (source.includes('陈守一')) return '55岁花白短发老摄影师，眼角深纹，灰布围裙'
    if (source.includes('赵小满')) return '20岁短寸圆脸学徒，素面深蓝工装无徽章'
    return '常驻相貌服装特征锁定'
  }
  return parts.join('，')
}

function applyVisualFingerprintToShot(shot) {
  if (!shot) return
  let promptText = shot.prompt || ''

  // 1. 获取所有出场角色并锁定面部指纹
  const roleAssets = (assets.value || []).filter(a => a.category === 'role')
  roleAssets.forEach(char => {
    const cName = String(char.name || '').trim()
    if (!cName) return
    const fp = extractCharacterVisualFingerprint(char, cName)
    if (!fp) return

    // 匹配如 "赵小满" 且后面不是 "（" 或 "("
    const reg = new RegExp(`(${cName})(?![(（])`, 'g')
    if (reg.test(promptText)) {
      if (!promptText.includes(`${cName}（${fp}）`) && !promptText.includes(`${cName}(${fp})`)) {
        promptText = promptText.replace(reg, `${cName}（${fp}）`)
      }
    }
  })

  // 2. 获取场景空间与光影锚点
  const sceneAssets = (assets.value || []).filter(a => a.category === 'scene')
  sceneAssets.forEach(scene => {
    const sName = String(scene.name || '').trim()
    if (!sName) return
    if (promptText.includes(sName)) {
      const sEnv = String(scene.environment || scene.prompt || scene.description || '').trim()
      let anchor = ''
      if (/照相馆前厅/.test(sName + sEnv)) {
        anchor = '照相馆前厅木柜台前，背景陈列老相框样片墙，老式暖黄吊灯低照昏黄'
      } else if (sEnv) {
        anchor = sEnv.slice(0, 40)
      }
      if (anchor && !promptText.includes(anchor)) {
        if (promptText.includes('提示词：') && !promptText.includes('【空间光影】')) {
          promptText = promptText.replace(/(提示词：\s*)/, `$1【空间光影】${anchor}，`)
        } else if (promptText.includes('画面：') && !promptText.includes('【空间光影】')) {
          promptText = promptText.replace(/(画面：\s*)/, `$1【空间光影】${anchor}，`)
        }
      }
    }
  })

  // 3. 动作节拍防超载提示
  const actionVerbs = promptText.match(/(?:翻找|抽出|递出|撂箱|擦汗|转身|挂上|磕门槛|收回|喝退|掀帘|离开|摆正)/g) || []
  if (actionVerbs.length >= 4 && !promptText.includes('【核心动作节拍】')) {
    promptText += '\n【核心动作节拍】单镜头专注 1~2 个连贯物理动作，避免多动作堆叠形变'
  }

  shot.prompt = promptText
}

async function extractLastFrameForShot(prevShot, prevShotIndex, currentShot, options = {}) {
  const fileId = prevShot.resultFileId || prevShot.fileId || prevShot.mixedVideoFileId || prevShot.originalVideoFileId || ''
  const url = prevShot.resultUrl || prevShot.videoUrl || ''
  if (!fileId && !url) {
    showWorkspaceToast(`⚠️ 第 ${prevShotIndex + 1} 镜未找到可用的视频，请先生成该分镜`, 'warning')
    return null
  }

  currentShot.extractingLastFrame = true
  try {
    const res = await videoProjectRequest('POST', '/video/extract-last-frame', { fileId, url })
    if (res && res.fileId) {
      const frame = {
        fileId: res.fileId,
        url: res.url,
        sourceShotIndex: prevShotIndex,
        sourceShotTitle: prevShot.title || `第${prevShotIndex + 1}镜`,
        sourceVideoId: fileId,
        updatedAt: Date.now(),
      }
      if (options.store === 'gazeHandoff') {
        currentShot.gazeHandoffFrame = { ...frame }
      } else {
        currentShot.continuitySourceFrame = { ...frame }
      }
      if (options.activate !== false && !hasAuthoredCut(currentShot)) {
        currentShot.continuityTailFrame = { ...frame }
        if (currentShot.continuityMode !== 'transition') currentShot.continuityMode = 'exact'
        currentShot.selectedMatrixCell = null
      }
      currentShot.continuityOutdated = false
      scheduleProjectSave()
      if (!options.silent) {
        showWorkspaceToast(options.activate === false
          ? `✅ 已保存第 ${prevShotIndex + 1} 镜真实尾帧，九宫格不会覆盖它`
          : (roleHandoffPlan(storyboards.value, currentShot) ? `✅ 已提取第 ${prevShotIndex + 1} 镜尾帧；同时保留新入画人物的参考` : `✅ 已提取第 ${prevShotIndex + 1} 镜真实尾帧；Muse 严格续接模式仅发送这一张首图`), 'success')
      }
      return frame
    } else {
      throw new Error(res?.message || '提取返回数据异常')
    }
  } catch (err) {
    console.error('Failed to extract last frame:', err)
    showWorkspaceToast(`❌ 提取第 ${prevShotIndex + 1} 镜尾帧失败: ${err.message || '网络或解析异常'}`, 'error')
  } finally {
    currentShot.extractingLastFrame = false
  }
  return null
}

async function refreshShotContinuityFrame(shot, shotIndex) {
  if (shotIndex <= 0) return
  const prevShot = storyboards.value[shotIndex - 1]
  const hasVideo = prevShot && (prevShot.resultUrl || prevShot.resultFileId || prevShot.mixedVideoFileId || prevShot.originalVideoFileId)
  if (!prevShot || !hasVideo) {
    showWorkspaceToast(`⚠️ 上一镜（第 ${shotIndex} 镜）尚未生成视频，无法提取尾帧`, 'warning')
    return
  }
  showWorkspaceToast(`⏳ 正在截取第 ${shotIndex} 镜尾帧...`, 'info', 1500)
  await extractLastFrameForShot(prevShot, shotIndex - 1, shot)
}

function toggleShotContinuity(shot, shotIndex, event = null) {
  if (hasAuthoredCut(shot)) {
    alignAuthoredContinuity(shot)
    if (event) event.target.checked = false
    scheduleProjectSave()
    showWorkspaceToast('本镜正文是剪辑切镜，已保持场景图模式，避免和严格尾帧要求冲突', 'info', 4000)
    return
  }
  const isChecked = event ? event.target.checked : (shot.inheritPrevTail === false ? true : false)
  shot.inheritPrevTail = isChecked
  if (isChecked) {
    showWorkspaceToast('🔗 已开启尾帧衔接（同场景连续动作）', 'info', 2000)
    if (shotIndex > 0 && !storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover')) {
      const prevShot = storyboards.value[shotIndex - 1]
      const hasVideo = prevShot && (prevShot.resultUrl || prevShot.resultFileId || prevShot.mixedVideoFileId || prevShot.originalVideoFileId)
      if (hasVideo) {
        void extractLastFrameForShot(prevShot, shotIndex - 1, shot)
      }
    }
  } else {
    shot.continuityReview = null
    showWorkspaceToast('⏸️ 已关闭尾帧衔接（转场/切换视角，不继承尾帧）', 'info', 2000)
  }
  scheduleProjectSave()
}

function disableContinuityForShot(shot) {
  shot.inheritPrevTail = false
  shot.continuityReview = null
  showWorkspaceToast('🎬 已切换为转场切镜模式（不继承上一镜尾帧），请以本镜人物/场景直接生成！', 'success', 3500)
  scheduleProjectSave()
}

function injectCameraTransition(shot, shotIndex) {
  const transitionPrefix = '【动态运镜转场】首帧承接上一镜尾帧起始构图，镜头极速后仰拉起并穿入云层雾霭与紫气，在光芒流转中动态转场，扫入新场景：'
  if (!String(shot.prompt || '').includes('【动态运镜转场】') && !String(shot.prompt || '').includes('【运镜转场】')) {
    shot.prompt = `${transitionPrefix}\n${shot.prompt || ''}`
  }
  shot.continuityMode = 'exact'
  shot.inheritPrevTail = true
  if (shot.continuityReview?.status === 'failed') {
    shot.continuityReview = null
  }
  scheduleProjectSave()
  showWorkspaceToast('⚡ 已注入动态运镜转场！视频将以尾帧起步，并在镜头内极速运镜/消散扫入新场景（两者兼得）。', 'success', 4500)
}

function setDissolveTransition(shot, shotIndex) {
  shot.transitionStrategy = 'dissolve'
  shot.inheritPrevTail = false
  if (shot.rejectedResultFileId) {
    acceptCandidateVideo(shot)
    showWorkspaceToast('🎬 已采纳为转场成片并配置【智能叠化转场】！两镜交界自动平滑融变过渡，免去首帧误报。', 'success', 5000)
    return
  }
  shot.continuityReview = null
  scheduleProjectSave()
  showWorkspaceToast('🎬 已设为智能叠化转场！本镜按新场景高保真生成，播放与整片导出时两镜自动执行 0.8s 电影叠化过渡。', 'success', 4500)
}

function isSceneTransition(shot, shotIndex) {
  if (changesScene(storyboards.value[shotIndex - 1], shot)) return true
  if (shotIndex <= 0) return false
  const prevShot = storyboards.value[shotIndex - 1]
  if (!prevShot) return false
  const curMatch = String(shot.title || '').match(/镜\s*(\d+)/i)
  const prevMatch = String(prevShot.title || '').match(/镜\s*(\d+)/i)
  if (curMatch && prevMatch && curMatch[1] !== prevMatch[1]) {
    return true
  }
  if (String(shot.prompt || '').includes('空间切换') || String(shot.prompt || '').includes('场景切换')) {
    return true
  }
  return false
}

function setTransitionStrategy(shot, strategy) {
  const index = storyboards.value.findIndex(item => item.id === shot.id)
  shot.narrativeTransition = selectTransitionStrategy(storyboards.value[index - 1], shot, strategy)
  scheduleProjectSave()
}

function initialiseShotEnvironment(shot) {
  if (shot.environmentContinuity) return
  const env=environmentAt(storyboards.value,storyboards.value.findIndex(s=>s.id===shot.id))
  shot.environmentContinuity={timeOfDay:env.timeOfDay,weather:env.weather,lighting:env.lighting,reset:false}
}

function clearShotContinuityFrame(shot) {
  shot.continuityTailFrame = null
  shot.continuitySourceFrame = null
  shot.continuityMode = 'exact'
  shot.selectedMatrixCell = null
  shot.continuityOutdated = false
  scheduleProjectSave()
}

async function setShotLastFrameAsNextFirstFrame(shot, shotIndex) {
  if (shotIndex >= storyboards.value.length - 1) return
  const nextShot = storyboards.value[shotIndex + 1]
  if (!nextShot) return
  nextShot.inheritPrevTail = true
  await extractLastFrameForShot(shot, shotIndex, nextShot)
}

async function inheritPreviousShotLastFrame(shot, shotIndex) {
  if (shotIndex <= 0) return
  shot.inheritPrevTail = true
  await refreshShotContinuityFrame(shot, shotIndex)
}

async function cropRolePortrait(asset) {
  if (!asset || croppingPortrait.value) return
  const fileId = asset.fileId || asset.coverId || ''
  if (!fileId) {
    asset.generationError = '尚未生成或上传图片，无法提取特写'
    return
  }
  croppingPortrait.value = true
  try {
    const res = await videoProjectRequest('POST', '/image/crop-role-portrait', { fileId })
    if (!res || !res.fileId) throw new Error('裁剪特写剧照失败')
    asset.fileId = res.fileId
    asset.coverId = res.fileId
    asset.cover = res.url
    delete asset.path
    delete asset.previewFailed
    scheduleProjectSave()
    if (activeVideoProject.value) {
      activeVideoProject.value.saveStatus = `✅ 成功提取【${asset.name}】单人正面高清特写！已剔除多视角干扰，极大提升视频模型人脸一致性。`
    }
  } catch (err) {
    asset.generationError = `裁剪特写失败: ${cleanError(err)}`
  } finally {
    croppingPortrait.value = false
  }
}

function syncEpisodeConsistency() {
  if (!Array.isArray(storyboards.value) || !storyboards.value.length) return
  syncEpisodeCharacterVoices()
  storyboards.value.forEach(shot => {
    applyVisualFingerprintToShot(shot)
  })
  reconcileAllShotsAssetConsistency()
  scheduleProjectSave()
  if (activeVideoProject.value) {
    activeVideoProject.value.saveStatus = `✅ 已完成全集 ${storyboards.value.length} 个分镜的【稳定声线文字整理】与【视觉外貌/空间光影一致性锁定】！`
  }
}

function syncEpisodeCharacterVoices() {
  if (!Array.isArray(storyboards.value) || !storyboards.value.length) return
  projectCharacterVoiceRegistry.clear()

  // 1. 先初始化所有角色资产的基准声学指纹
  ;(assets.value || []).filter(a => a.category === 'role').forEach(char => {
    extractCharacterVoiceProfile(char, char.name, '')
  })

  // 2. 跨分镜统一锁定声学提示词，后续出场标注“沿用统一基准音色”
  const appearedRoles = new Set()
  let syncedShots = 0
  storyboards.value.forEach(shot => {
    applySixDimAudioFormulaToShot(shot, appearedRoles)
    syncedShots += 1
  })

  // 3. 将所有配音资产绑定到同一角色的统一 voice 音色代号
  ;(assets.value || []).filter(a => a.category === 'audio' && a.subCategory === 'voice').forEach(audio => {
    const aName = String(audio.name || '').toLowerCase()
    for (const [key, profile] of projectCharacterVoiceRegistry.entries()) {
      if (aName.includes(key) && profile.voiceId) {
        audio.voice = profile.voiceId
        break
      }
    }
  })

  reconcileAllShotsAssetConsistency()
  if (activeVideoProject.value) {
    activeVideoProject.value.saveStatus = `已完成全集 ${syncedShots} 个分镜的声线文字整理与资产命名对齐；真实音色未绑定！`
  }
}

function formatAssetPromptToSixDim() {
  if (!assetDraft.value) return
  const currentPrompt = String(assetDraft.value.prompt || '').trim()
  const assetName = String(assetDraft.value.name || '').trim()

  let charAsset = null
  const candidates = (assets.value || []).filter(a => a.category === 'role')
  for (const c of candidates) {
    if (assetName.toLowerCase().includes(String(c.name || '').toLowerCase()) || String(c.name || '').toLowerCase().includes(assetName.toLowerCase())) {
      charAsset = c
      break
    }
  }

  const profile = extractCharacterVoiceProfile(charAsset, assetName)
  const vocalPieces = [
    profile.identity,
    profile.gender,
    profile.age,
    profile.pitch,
    profile.texture,
    profile.feature,
  ].filter(Boolean)

  let speech = currentPrompt
  const quoteMatch = currentPrompt.match(/[“"']([^"”']+)["”']/)
  if (quoteMatch) speech = quoteMatch[1]
  else {
    const colonMatch = currentPrompt.match(/[：:](.+)$/)
    if (colonMatch) speech = colonMatch[1].trim()
  }

  assetDraft.value.prompt = `${vocalPieces.join('，')}：“${speech}”`
}

function inferAudioPromptFromProject(asset) {
  if (!asset || asset.category !== 'audio') return ''
  const direct = String(
    (asset.prompt && !asset.prompt.includes('你好，很高兴认识你'))
      ? asset.prompt
      : (asset.text || asset.dialogue || asset.lines || asset.content || asset.style || asset.description || asset.desc || asset.sound || '')
  ).trim()
  if (direct && !direct.includes('你好，很高兴认识你')) return direct

  const targetId = String(asset.id || '').toLowerCase()
  const targetName = String(asset.name || '').trim().toLowerCase()

  // 尝试从分镜对白或分镜音频中自动关联台词/音效
  const matchedLines = []
  ;(storyboards.value || []).forEach(shot => {
    if (Array.isArray(shot.dialogue)) {
      shot.dialogue.forEach(d => {
        if (typeof d === 'string') {
          if (targetName && d.toLowerCase().includes(targetName)) matchedLines.push(d)
        } else {
          const role = String(d?.role || d?.character || d?.speaker || '').trim().toLowerCase()
          const text = String(d?.lines || d?.line || d?.text || d?.content || '').trim()
          if (text && (role === targetName || (targetId && role.includes(targetId)) || targetName.includes(role))) {
            matchedLines.push(text)
          }
        }
      })
    }
    if (Array.isArray(shot.acts)) {
      shot.acts.forEach(act => {
        if (Array.isArray(act.audio)) {
          act.audio.forEach(a => {
            const name = String(a?.name || a?.type || '').toLowerCase()
            const desc = String(a?.desc || a?.description || a?.detail || a?.text || '').trim()
            if (desc && (name === targetName || (targetId && name.includes(targetId)) || targetName.includes(name))) {
              matchedLines.push(desc)
            }
          })
        }
      })
    }
  })

  if (matchedLines.length) {
    const linesStr = Array.from(new Set(matchedLines)).join('；')
    if (asset?.subCategory === 'voice' || targetId.startsWith('aud_vo_')) {
      let charAsset = null
      const candidates = (assets.value || []).filter(a => a.category === 'role')
      for (const c of candidates) {
        const cName = String(c.name || '').toLowerCase()
        if (targetName.includes(cName) || targetId.includes(String(c.id || '').toLowerCase())) {
          charAsset = c
          break
        }
      }
      const profile = extractCharacterVoiceProfile(charAsset, targetName)
      const vocalPieces = [
        profile.identity,
        profile.gender,
        profile.age,
        profile.pitch,
        profile.texture,
        profile.feature,
      ].filter(Boolean)
      return `${vocalPieces.join('，')}：“${linesStr}”`
    }
    return linesStr
  }

  return String(asset.name || '语音或音效提示词')
}

function requestDeleteVideoProject(project) {
  if (!project?.id || deletingProjectId.value) return
  projectToDelete.value = project
  projectError.value = ''
}

function cancelDeleteVideoProject() {
  if (deletingProjectId.value) return
  projectToDelete.value = null
}

async function confirmDeleteVideoProject() {
  const project = projectToDelete.value
  if (!project?.id || deletingProjectId.value) return
  deletingProjectId.value = String(project.id)
  projectError.value = ''
  try {
    await videoProjectRequest('DELETE', `/video-project/${encodeURIComponent(project.id)}`)
    videoProjects.value = videoProjects.value.filter(item => String(item.id) !== String(project.id))
    projectToDelete.value = null
  } catch (err) {
    projectError.value = cleanError(err)
  } finally {
    deletingProjectId.value = ''
  }
}

function roleGenerationPrompt(value, style = DEFAULT_PROJECT_STYLE) {
  return buildRoleReferencePrompt(value, getProjectStylePrefix(style))
}

function normalizeAssetGroup(items, category, promptMap = new Map(), style = DEFAULT_PROJECT_STYLE) {
  const stylePrefix = getProjectStylePrefix(style)
  return (Array.isArray(items) ? items : []).map((item, index) => {
    const source = item && typeof item === 'object' ? item : { name: String(item || '') }
    const sourceId = String(source.id || `${category}-${Date.now()}-${index}`)
    const referencePrompt = promptMap.get(sourceId) || promptMap.get(sourceId.toLowerCase())
    const mergedSource = referencePrompt ? { ...source, prompt: referencePrompt.prompt || referencePrompt } : source
    const media = assetMediaValue(source)
    let rawPrompt = assetPromptFor(mergedSource, category)
    if (category !== 'audio' && rawPrompt) {
      if (!rawPrompt.includes('3D') && !rawPrompt.includes('国漫') && !rawPrompt.includes('写实') && !rawPrompt.includes('二次元') && !rawPrompt.includes('Q版') && !rawPrompt.includes('渲染') && !rawPrompt.includes('建模')) {
        rawPrompt = `${stylePrefix}。${rawPrompt}`
      }
    }
    const description = String(source.description || source.summary || source.style || source.desc || source.sound || '').trim()
    const audioText = String(
      (source.prompt && !String(source.prompt).includes('你好，很高兴认识你'))
        ? source.prompt
        : (source.text || source.dialogue || source.lines || source.content || source.style || source.desc || source.description || source.sound || rawPrompt || source.name || '')
    ).trim()
    return {
      ...mergedSource,
      id: sourceId,
      name: String(source.name || source.character || source.title || source.id || `未命名${categories.find(entry => entry.key === category)?.label || '资产'}`),
      category,
      type: ['role', 'layout'].includes(category) ? 'image' : category,
      description,
      useDefaultRoleLayout: category === 'role' ? source.useDefaultRoleLayout !== false : undefined,
      prompt: category === 'audio'
        ? audioText
        : category === 'role'
          ? rolePromptWithoutDefaultLayout(rawPrompt)
          : rawPrompt,
      cover: media ? absoluteMediaUrl(media) : '',
      fileId: String(source.fileId || source.coverId || fileIdFromUrl(media) || ''),
      generating: false,
      generationError: '',
    }
  })
}

function buildReferencePromptMap(referencePrompts) {
  const map = new Map()
  Object.values(referencePrompts && typeof referencePrompts === 'object' ? referencePrompts : {}).forEach(group => {
    ;(Array.isArray(group) ? group : []).forEach(item => {
      if (!item?.id) return
      map.set(String(item.id), item)
      map.set(String(item.id).toLowerCase(), item)
    })
  })
  return map
}

function shotPromptFor(shot) {
  const authored = String(shot?.video_prompt || shot?.prompt || '').trim()
  if (authored && /^(?:对白|台词|旁白|画外音|内心独白)[：:]/m.test(authored)
    && /^(?:【(?:本镜动作|连续性条件|表演基调)】|画面[：:])/m.test(authored)) return authored
  if (Array.isArray(shot?.acts) && shot.acts.length) {
    const acts = shot.acts.map(act => {
      const audio = (Array.isArray(act?.audio) ? act.audio : [])
        .filter(item => !['none', '无'].includes(String(item?.type || '').toLowerCase()))
        .map(item => [item.type, item.desc, item.description, item.detail, item.text].filter(Boolean).join('：'))
        .filter(Boolean)
        .join('；')
      return [
        [act?.time ? `【${act.time}】` : '', act?.name].filter(Boolean).join(' '),
        act?.visual ? `画面：${act.visual}` : '',
        act?.camera ? `运镜：${act.camera}` : '',
        audio ? `音频：${audio}` : '',
      ].filter(Boolean).join('\n')
    }).filter(Boolean)
    return [shot?.title, ...acts].filter(Boolean).join('\n')
  }

  const lines = []
  if (shot?.title) lines.push(shot.title)

  let timeCode = ''
  if (shot?.time) {
    timeCode = `【${shot.time}】`
  } else if (shot?.duration_s || shot?.duration) {
    const sec = Number(shot.duration_s || shot.duration || 5)
    const m = String(Math.floor(sec / 60)).padStart(2, '0')
    const s = String(sec % 60).padStart(2, '0')
    timeCode = `【00:00-${m}:${s}】`
  }
  if (timeCode) lines.push(timeCode)

  if (shot?.visual || shot?.description) {
    lines.push(`画面：${shot.visual || shot.description}`)
  }
  if (shot?.camera) {
    lines.push(`运镜：${shot.camera}`)
  }
  if (shot?.dialogue) {
    if (Array.isArray(shot.dialogue)) {
      const diagStr = shot.dialogue.map(d => {
        if (typeof d === 'string') return d
        const role = d?.role || d?.character || d?.speaker || ''
        const text = d?.lines || d?.line || d?.text || d?.content || ''
        return role ? `${role}：“${text}”` : text
      }).filter(Boolean).join('；')
      if (diagStr) lines.push(`对白：${diagStr}`)
    } else if (typeof shot.dialogue === 'string' && shot.dialogue.trim()) {
      lines.push(`对白：${shot.dialogue.trim()}`)
    }
  }
  if (!lines.some(l => /^(?:对白|台词|旁白|画外音|内心独白)[：:]/.test(l))) lines.push('对白：无。')
  const explicitAudio = shot?.audio_prompt || shot?.audioPrompt
  if (explicitAudio && typeof explicitAudio === 'string' && explicitAudio.trim()) {
    lines.push(`音频提示词：${explicitAudio.trim()}`)
  } else if (shot?.audio) {
    if (Array.isArray(shot.audio)) {
      const audStr = shot.audio.map(a => typeof a === 'string' ? a : (a?.prompt || a?.desc || a?.description || a?.name || a?.style || a?.text || '')).filter(Boolean).join('；')
      if (audStr) lines.push(`音频提示词：${audStr}`)
    } else if (typeof shot.audio === 'string' && shot.audio.trim()) {
      lines.push(`音频提示词：${shot.audio.trim()}`)
    }
  }
  if (Array.isArray(shot?.wirelist) && shot.wirelist.length) {
    const wireStr = shot.wirelist.map(w => `${w.slot || '图'}: ${w.name || w.asset_id || ''}${w.action ? `（${w.action}）` : ''}`).filter(Boolean).join('，')
    if (wireStr) lines.push(`接线单：${wireStr}`)
  }
  if (shot?.video_prompt && shot.video_prompt !== shot.visual) {
    lines.push(`提示词：${shot.video_prompt}`)
  } else if (shot?.prompt && shot.prompt !== shot.visual) {
    lines.push(`提示词：${shot.prompt}`)
  }

  return lines.filter(Boolean).join('\n')
}

function inferredShotDuration(source) {
  const explicitDuration = Number(source?.duration_s ?? source?.duration)
  if (Number.isFinite(explicitDuration) && explicitDuration > 0) return explicitDuration

  const timelineTexts = [
    source?.time,
    source?.timeline,
    source?.prompt,
    source?.description,
    ...(Array.isArray(source?.acts) ? source.acts.map(act => act?.time) : []),
  ].filter(value => value !== undefined && value !== null).map(String)
  const endSeconds = []
  const timecodeRange = /(\d{1,2}):([0-5]\d)(?:\.\d+)?\s*(?:-|–|—|~|～|至)\s*(\d{1,2}):([0-5]\d)(?:\.(\d+))?/g
  const secondRange = /(?:^|[^\d])(\d{1,2}(?:\.\d+)?)\s*(?:-|–|—|~|～|至)\s*(\d{1,2}(?:\.\d+)?)\s*秒/g
  timelineTexts.forEach((text) => {
    for (const match of text.matchAll(timecodeRange)) {
      const fraction = match[5] ? Number(`0.${match[5]}`) : 0
      endSeconds.push(Number(match[3]) * 60 + Number(match[4]) + fraction)
    }
    for (const match of text.matchAll(secondRange)) endSeconds.push(Number(match[2]))
  })
  return endSeconds.length ? Math.ceil(Math.max(...endSeconds)) : defaultVideoSettings.duration
}


function normalizeImportedShots(items, assetIndex) {
  return (Array.isArray(items) ? items : []).map((source, index) => {
    const shot = createStoryboard(index + 1)
    if (isGeneral.value) { shot.inheritPrevTail = false; shot.narrativeTransition = null }
    const rawDuration = inferredShotDuration(source)
    const duration = Math.min(15, Math.max(1, Math.ceil(Number.isFinite(rawDuration) ? rawDuration : defaultVideoSettings.duration)))
    shot.id = `json-shot-${String(source?.id || index + 1)}`
    shot.sceneId = String(source?.scene_id || '')
    if (source?.time_of_day || source?.weather || source?.temporal_break) shot.environmentContinuity={timeOfDay:String(source.time_of_day || ''),weather:String(source.weather || ''),reset:Boolean(source.temporal_break)}
    if (source?.transition && typeof source.transition === 'object') {
      const plan = source.transition
      shot.narrativeTransition = {
        version: 1, source: 'script', enabled: plan.enabled !== false,
        strategy: TRANSITION_OPTIONS.some(option => option.value === plan.strategy) ? plan.strategy : 'match',
        outgoing: String(plan.outgoing || ''), incoming: String(plan.incoming || ''), cue: String(plan.cue || ''),
      }
      shot.inheritPrevTail = false
    }
    shot.title = String(source?.title || source?.name || source?.id || shot.title)
    const inherit = source?.inheritPrevTail ?? source?.inherit_prev_tail
    if (typeof inherit === 'boolean') shot.inheritPrevTail = inherit
    const handoff = source?.continuityHandoff || source?.continuity_handoff
    if (handoff && typeof handoff === 'object') shot.continuityHandoff = JSON.parse(JSON.stringify(handoff))
    const mode = source?.continuityMode || source?.continuity_mode
    if (['exact', 'matchCut'].includes(mode)) shot.continuityMode = mode
    const continuityPlan = source?.continuityPlan || source?.continuity_plan
    if (continuityPlan && typeof continuityPlan === 'object') shot.continuityPlan = JSON.parse(JSON.stringify(continuityPlan))
    const continuityState = source?.continuityState || source?.continuity_state
    if (continuityState && typeof continuityState === 'object') shot.continuityState = JSON.parse(JSON.stringify(continuityState))
    const actionChain = source?.actionChain || source?.action_chain
    if (actionChain && typeof actionChain === 'object') shot.actionChain = {
      ...JSON.parse(JSON.stringify(actionChain)),
      requiredActions: actionChain.requiredActions || actionChain.required_actions || [],
      persistentFacts: actionChain.persistentFacts || actionChain.persistent_facts || [],
    }
    const performance = source?.performanceProfile || source?.performance_profile
    if (performance && typeof performance === 'object') shot.performanceProfile = JSON.parse(JSON.stringify(performance))

    const rawRefs = Array.isArray(source?.references) ? [...source.references] : []
    if (source?.scene_id && !rawRefs.some(r => (typeof r === 'object' ? r?.id : r) === source.scene_id)) {
      rawRefs.unshift(source.scene_id)
    }

    const refIds = rawRefs.map(r => typeof r === 'object' && r ? String(r.id || '') : String(r || '')).filter(Boolean)

    shot.references = refIds
      .map(id => assetIndex.get(id) || assetIndex.get(id.toLowerCase()))
      .filter(Boolean)
    const startFrame = source?.continuityStartFrame || source?.continuity_start_frame
    if (startFrame?.isComposedStartFrame && startFrame.fileId && startFrame.id === shot.continuityPlan?.sceneReferenceId) {
      shot.references = [...shot.references.filter(a => a.id !== startFrame.id), JSON.parse(JSON.stringify(startFrame))]
    }

    shot.referenceLabels = Object.fromEntries(
      rawRefs.map(r => {
        const id = typeof r === 'object' && r ? String(r.id || '') : String(r || '')
        const asset = assetIndex.get(id) || assetIndex.get(id.toLowerCase())
        const label = typeof r === 'object' && r ? String(r.label || asset?.name || '') : (asset?.name || '')
        return [id, label]
      }).filter(([id]) => id)
    )

    const consistencyItems = refIds.map(id => {
      const asset = assetIndex.get(id) || assetIndex.get(id.toLowerCase())
      const name = asset?.name || shot.referenceLabels[id] || id
      return `${name} {{${id}}}`
    })
    const consistencyText = consistencyItems.length ? `一致性引用：${consistencyItems.join('，')}` : ''

    const promptBody = shotPromptFor(source)
    shot.prompt = cleanShotAudioPrompt([consistencyText, promptBody].filter(Boolean).join('\n'))
    shot.dialogueBaseline = dialogueContract(shot.prompt)
    shot.duration = duration
    shot.sound = source?.sound ?? source?.output_sound ?? true
    alignAuthoredContinuity(shot)
    return shot
  })
}

function applyImportedDocument(document, sourceName, preserveExisting = true) {
    document = removeAudioAssets(document)
    if (!document || typeof document !== 'object') throw new Error('JSON 顶层必须是创作任务对象')
    const importedProfile = { ...(document.project && typeof document.project === 'object' ? document.project : {}), ...Object.fromEntries(['style', 'storyGenres', 'styleNotes'].filter(key => document[key] !== undefined).map(key => [key, document[key]])) }
    // A separately imported style must not inherit unrelated notes or genres.
    const docProfile = projectStyleFields(importedProfile.style ? importedProfile : { ...activeVideoProject.value, ...importedProfile })
    if (activeVideoProject.value) Object.assign(activeVideoProject.value, docProfile)
    const performancePolicy = document.performancePolicy || document.performance_policy
    if (activeVideoProject.value && performancePolicy && typeof performancePolicy === 'object') activeVideoProject.value.performancePolicy = JSON.parse(JSON.stringify(performancePolicy))
    const root = document.consistency && typeof document.consistency === 'object'
      ? document.consistency
      : document.assets && typeof document.assets === 'object'
        ? document.assets
        : document
    const promptMap = buildReferencePromptMap(root.reference_prompts)
    const nextAssets = [
      ...normalizeAssetGroup(root.characters || root.roles || root.people, 'role', promptMap, docProfile),
      ...normalizeAssetGroup(root.scenes, 'scene', promptMap, docProfile),
      ...normalizeAssetGroup(root.props || root.items, 'prop', promptMap, docProfile),
      ...normalizeAssetGroup(root.layouts || root.white_models || root.whiteModels || root.blockings, 'layout', promptMap, docProfile),
    ]
    if (!isGeneral.value && !nextAssets.length && !assets.value.length) throw new Error('没有找到 characters、scenes、props 或 layouts 数据')
    if (nextAssets.length) assets.value = preserveExisting ? mergePushedItems(assets.value, nextAssets) : nextAssets
    const assetIndex = new Map()
    assets.value.forEach(asset => {
      if (asset.id) {
        assetIndex.set(String(asset.id), asset)
        assetIndex.set(String(asset.id).toLowerCase(), asset)
      }
      if (asset.name) {
        assetIndex.set(String(asset.name), asset)
        assetIndex.set(String(asset.name).toLowerCase(), asset)
      }
    })
    const importedShots = maintainTransitions(normalizeImportedShots(document.shots || root.shots, assetIndex))
    if (importedShots.length) {
      pollTimers.forEach(timer => window.clearTimeout(timer))
      pollTimers.clear()
      storyboards.value = preserveExisting ? mergePushedItems(storyboards.value, importedShots) : importedShots
      activeShotId.value = importedShots[0].id
    }
    importedFileName.value = sourceName || '已导入 JSON'
    importedProjectTitle.value = String(document.title || document.project?.name || document.project || '')
    if (activeVideoProject.value && importedProjectTitle.value && !preserveExisting) activeVideoProject.value.name = importedProjectTitle.value
    importedSchemaVersion.value = String(document.schema_version || '')
    activeCategory.value = 'all'
}

function openImportDialog() {
  importError.value = ''
  importDialogOpen.value = true
  nextTick(() => document.querySelector('.json-import-textarea')?.focus())
}

function closeImportDialog() {
  importDialogOpen.value = false
  importError.value = ''
}

function importJsonText() {
  importError.value = ''
  try {
    const raw = jsonText.value.replace(/^\uFEFF/, '').trim()
    if (!raw) throw new Error('请粘贴完整 JSON 内容')
    applyImportedDocument(JSON.parse(raw), '粘贴的 JSON')
    jsonText.value = ''
    importDialogOpen.value = false
  } catch (err) {
    importError.value = err instanceof SyntaxError ? `JSON 格式错误：${err.message}` : cleanError(err)
  }
}

async function importAssetJson() {
  importError.value = ''
  if (!window.pywebview?.api) {
    importError.value = '请从桌面客户端选择 JSON 文件'
    return
  }
  try {
    const selected = await window.pywebview.api.select_json_data()
    if (!selected) return
    applyImportedDocument(selected.data, selected.name)
    importDialogOpen.value = false
  } catch (err) {
    importError.value = cleanError(err)
  }
}

function openCreationAiDialog() {
  creationAiError.value = ''
  creationAiOpen.value = true
  nextTick(() => document.querySelector('.creation-ai-prompt')?.focus())
}

function closeCreationAiDialog() {
  if (creationAiGenerating.value) return
  creationAiOpen.value = false
  creationAiError.value = ''
}

function creationScopeLabel(scope) {
  return ({ full: '完整创作数据', assets: '只生成资产设定', shots: '重点生成分镜' })[scope] || '完整创作数据'
}

async function generateCreationData() {
  creationAiError.value = ''
  const prompt = creationAiPrompt.value.trim()
  if (!prompt) {
    creationAiError.value = '请先输入小说、故事或创作需求'
    return
  }
  if (!selectedTextModel.value) {
    creationAiError.value = '还没有可用的文本模型，请先到「设置 → 模型管理 → 文本模型」添加并启用一个自定义 API'
    return
  }
  if (!window.pywebview?.api) {
    creationAiError.value = '请从桌面客户端打开视频生成工作台'
    return
  }
  creationAiGenerating.value = true
  try {
    const result = await window.pywebview.api.backend_request('POST', '/ai/creation-data', props.token, {
      model: selectedTextModel.value,
      scope: creationAiScope.value,
      title: creationAiTitle.value.trim(),
      projectType: project.value?.type || 'drama',
      genre: project.value?.storyGenres?.[0] || '',
      storyGenres: project.value?.storyGenres || [],
      prompt,
    })
    const document = result?.document
    if (!document || typeof document !== 'object') throw new Error('文本模型没有返回可导入的创作数据')
    creationAiPreview.value = String(result.text || JSON.stringify(document, null, 2))
  } catch (err) {
    creationAiError.value = cleanError(err)
  } finally {
    creationAiGenerating.value = false
  }
}

function importCreationAiPreview() {
  creationAiError.value = ''
  try {
    const raw = creationAiPreview.value.replace(/^\uFEFF/, '').trim()
    if (!raw) throw new Error('请先生成创作数据')
    applyImportedDocument(JSON.parse(raw), `AI 生成 · ${creationScopeLabel(creationAiScope.value)}`)
    creationAiOpen.value = false
    creationAiPreview.value = ''
  } catch (err) {
    creationAiError.value = err instanceof SyntaxError ? `JSON 格式错误：${err.message}` : cleanError(err)
  }
}

function baseAssetGenerationPrompt(asset) {
  const source = String(asset.prompt || asset.description || asset.name || '').trim()
  if (asset.category !== 'role') return source
  return asset.useDefaultRoleLayout === false ? rolePromptWithoutDefaultLayout(source) : roleGenerationPrompt(source, activeVideoProject.value || { style: DEFAULT_PROJECT_STYLE })
}

const assetImagePromptPreview = computed(() => {
  if (!assetDetailTarget.value || assetDetailTarget.value.category === 'audio') return ''
  const asset = { ...assetDetailTarget.value, ...assetDraft.value }
  const source = String(asset.prompt || asset.description || asset.name || '').trim()
  let prompt = baseAssetGenerationPrompt(asset)
  const dependencies = layoutDependencies(asset)
  if (dependencies.resolved.length && !dependencies.unresolved.length) prompt = referenceEditPrompt(asset, dependencies.resolved, source)
  try { return withImageTextPolicy(prompt, asset, isGeneral.value) } catch (err) { return cleanError(err) }
})

async function generateAsset(asset) {
  const isAudio = asset.category === 'audio'
  const isLayout = asset.category === 'layout'
  const sourcePrompt = String(asset.prompt || asset.description || asset.name || '').trim()
  let prompt = isAudio ? sourcePrompt : baseAssetGenerationPrompt(asset)
  let editImages = []
  let resolvedReferences = []
  asset.generationError = ''
  if (!prompt) {
    asset.generationError = '该资产缺少可用于生成的描述字段'
    return
  }
  if (!window.pywebview?.api) {
    asset.generationError = '请从桌面客户端启动后再生成'
    return
  }
  if (asset.category !== 'audio' && !selectedImageModel.value) {
    asset.generationError = '没有可用的图片模型，请先配置'
    return
  }
  if (asset.category === 'audio' && !selectedAudioModel.value && !audioModels.value.length) {
    asset.generationError = '没有可用的音频模型，请先在模型管理中添加并启用语音模型'
    return
  }
  const referenceState = isAudio ? null : assetReferenceState(asset)
  if (isLayout || referenceState?.total) {
    const { resolved, unresolved } = layoutDependencies(asset)
    if (unresolved.length) {
      asset.generationError = `${isLayout ? '白模依赖' : '参考图'}不存在：${unresolved.join('、')}`
      return
    }
    if (!resolved.length) {
      asset.generationError = isLayout ? '白模缺少人物或道具图片依赖' : '资产缺少可用参考图'
      return
    }
    const missing = resolved.filter(dependency => !assetUrl(dependency))
    if (missing.length) {
      asset.generationError = `请先生成${isLayout ? '白模依赖图片' : '参考图'}：${missing.map(item => item.name || item.id).join('、')}`
      return
    }
    resolvedReferences = resolved
    prompt = referenceEditPrompt(asset, resolved, sourcePrompt)
  }
  if (!isAudio) {
    try { prompt = withImageTextPolicy(prompt, asset, isGeneral.value) }
    catch (err) { asset.generationError = cleanError(err); return }
  }
  delete asset.previewFailed
  const resolvedRef = resolveAssetReference(asset)
  if (resolvedRef) delete resolvedRef.previewFailed
  asset.generating = true
  asset.generatingStartedAt = Date.now()
  await saveActiveVideoProject()
  await nextTick()
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
  try {
    if (resolvedReferences.length) editImages = await Promise.all(resolvedReferences.map(imageEditDataUrl))
    // 提交为后台任务：立即返回 taskId，生成在后台线程执行，
    // 完成后由后端 _apply_task_result 回写到当前资产，切页面/切客户端都不会丢。
    const body = isAudio
      ? {
          model: selectedAudioModel.value || undefined,
          prompt: sourcePrompt,
          preview_text: sourcePrompt,
          text: sourcePrompt,
          input: sourcePrompt,
          voice: asset.voice || undefined,
          voice_style: asset.description || undefined,
          name: asset.name,
          category: 'audio',
          subCategory: getAudioSubType(asset),
        }
      : { model: selectedImageModel.value, prompt, ...(editImages.length ? { image: editImages } : {}), n: 1, size: '1024x1024' }
    const submitted = await window.pywebview.api.start_asset_image_generation({
      path: isAudio ? '/ai/audio' : '/ai/image',
      body,
      token: props.token,
      ownerType: 'imageAsset',
      ownerId: String(asset.id || ''),
      projectId: String(activeVideoProject.value?.id || ''),
      taskName: asset.name || (isAudio ? '资产音频' : '资产图片'),
    })
    asset.taskId = String(submitted?.taskId || '')
    asset.pendingGenerationPrompt = prompt
    await saveActiveVideoProject()
    refreshTasks(String(activeVideoProject.value?.id || ''))
    // 返回的 Promise 在任务进入终态时 resolve：单点生成可忽略，批量生成需要
    // await 它以保证"参考图→白模"这类依赖顺序。
    return await pollAssetTask(asset)
  } catch (err) {
    asset.generationError = cleanError(err)
    asset.generating = false
    delete asset.generatingStartedAt
    await saveActiveVideoProject()
  }
}

function pollAssetTask(asset) {
  return new Promise(resolve => {
    const tick = async () => {
      try {
        const latest = await window.pywebview.api.get_task(asset.taskId)
        if (latest && latest.status === 'succeeded') {
          const rawUrl = String(latest.resultUrl || '')
          asset.cover = absoluteMediaUrl(rawUrl)
          asset.fileId = String(latest.resultFileId || fileIdFromUrl(rawUrl) || '')
          asset.generatedPrompt = asset.pendingGenerationPrompt || asset.prompt
          if (asset.category === 'scene') asset.referenceEnvironment = environmentHints(asset.generatedPrompt)
          if (asset.category === 'audio') asset.duration = '已生成'
          asset.generationError = ''
          asset.generating = false
          delete asset.generatingStartedAt
          reconcileAllShotsAssetConsistency()
          await saveActiveVideoProject()
          refreshTasks(String(activeVideoProject.value?.id || ''))
          resolve()
          return
        }
        if (latest && ['failed', 'cancelled', 'canceled'].includes(latest.status)) {
          asset.generationError = latest.statusText || '生成失败'
          asset.generating = false
          delete asset.generatingStartedAt
          reconcileAllShotsAssetConsistency()
          await saveActiveVideoProject()
          refreshTasks(String(activeVideoProject.value?.id || ''))
          resolve()
          return
        }
        pollTimers.set(`asset:${asset.id}`, window.setTimeout(tick, 1200))
      } catch (err) {
        asset.generationError = cleanError(err)
        asset.generating = false
        delete asset.generatingStartedAt
        await saveActiveVideoProject()
        resolve()
      }
    }
    tick()
  })
}

const bulkCancelled = ref(false)

async function cancelAsset(asset) {
  if (!asset) return
  const timer = pollTimers.get(`asset:${asset.id}`)
  if (timer) window.clearTimeout(timer)
  pollTimers.delete(`asset:${asset.id}`)
  const taskId = String(asset.taskId || '')
  if (taskId && window.pywebview?.api?.cancel_task) {
    try {
      await window.pywebview.api.cancel_task(taskId)
    } catch (err) {
      console.warn('cancel asset task error:', err)
    }
  }
  asset.generating = false
  delete asset.generatingStartedAt
  asset.generationError = '已手动终止'
  await saveActiveVideoProject()
  refreshTasks(String(activeVideoProject.value?.id || ''))
}

function cancelBulkGeneration() {
  bulkCancelled.value = true
  bulkGenerating.value = false
  bulkGenerationStatus.value = '已手动终止批量生成'
  assets.value.forEach((asset) => {
    if (asset.generating) cancelAsset(asset)
  })
}

function positionAssetActions(event) {
  if (!props.embedded || !event?.currentTarget) return
  const rect = event.currentTarget.getBoundingClientRect()
  const width = Math.min(340, window.innerWidth - 32)
  const left = Math.max(16, Math.min(rect.right + 10, window.innerWidth - width - 16))
  const top = Math.max(16, Math.min(rect.top, window.innerHeight - 430))
  assetActionsStyle.value = { position:'fixed', left:`${left}px`, right:'auto', top:`${top}px`, width:`${width}px`, maxHeight:`${window.innerHeight-top-16}px` }
}
function showAssetActions(event) {
  positionAssetActions(event)
  assetActionsOpen.value = true
}

function hideAssetActions() {
  if (!assetActionsPinned.value && !bulkGenerating.value && !assetLibrarySyncing.value) assetActionsOpen.value = false
}

function toggleAssetActions(event) {
  positionAssetActions(event)
  assetActionsPinned.value = !assetActionsPinned.value
  assetActionsOpen.value = assetActionsPinned.value
}

async function generateAllMissingAssets() {
  if (bulkGenerating.value) return
  const scope = [...displayedAssets.value]
  const scopeLabel = categories.find(category => category.key === activeCategory.value)?.label || '当前分类'
  const pending = scope.filter(asset => !assetUrl(asset) || asset.previewFailed)
  if (!pending.length) {
    bulkGenerationStatus.value = scope.length ? `${scopeLabel}资产均已生成` : `${scopeLabel}下没有资产`
    return
  }
  if (pending.some(asset => asset.category !== 'audio') && !selectedImageModel.value) {
    bulkGenerationStatus.value = '请先选择图片模型'
    return
  }
  bulkCancelled.value = false
  bulkGenerating.value = true
  assetActionsOpen.value = true
  assetActionsPinned.value = true
  let completed = 0
  try {
    bulkGenerationStatus.value = `正在生成${scopeLabel} 0/${pending.length}`
    const generateStage = stage => Promise.all(stage.map(async (asset) => {
      if (bulkCancelled.value) return
      await generateAsset(asset)
      completed += 1
      bulkGenerationStatus.value = `正在生成 ${completed}/${pending.length}`
    }))
    let remaining = [...pending]
    while (remaining.length) {
      if (bulkCancelled.value) break
      const remainingIds = new Set(remaining.map(asset => String(asset.id || '').toLowerCase()))
      const blocked = remaining.filter((asset) => {
        const { resolved } = layoutDependencies(asset)
        return resolved.some(dependency => !assetUrl(dependency) && !remainingIds.has(String(dependency.id || '').toLowerCase()))
      })
      if (blocked.length) {
        blocked.forEach((asset) => {
          const missing = layoutDependencies(asset).resolved.filter(dependency => !assetUrl(dependency))
          asset.generationError = `参考图生成失败或缺失，未执行：${missing.map(item => item.name || item.id).join('、')}`
          completed += 1
        })
        const blockedIds = new Set(blocked.map(asset => asset.id))
        remaining = remaining.filter(asset => !blockedIds.has(asset.id))
        bulkGenerationStatus.value = `正在生成 ${completed}/${pending.length}`
        continue
      }

      const stage = remaining.filter((asset) => {
        const { resolved, unresolved } = layoutDependencies(asset)
        return unresolved.length > 0 || resolved.every(dependency => Boolean(assetUrl(dependency)))
      })
      if (!stage.length) {
        remaining.forEach((asset) => {
          asset.generationError = '参考图依赖循环或无法满足，未执行生成'
          completed += 1
        })
        remaining = []
        break
      }
      bulkGenerationStatus.value = `正在生成第 ${completed + 1}-${completed + stage.length} 项，共 ${pending.length} 项`
      await generateStage(stage)
      if (bulkCancelled.value) break
      const stageIds = new Set(stage.map(asset => asset.id))
      remaining = remaining.filter(asset => !stageIds.has(asset.id))
    }
    if (!bulkCancelled.value) {
      const succeeded = pending.filter(asset => assetUrl(asset)).length
      const failed = pending.length - succeeded
      bulkGenerationStatus.value = `${scopeLabel}已生成 ${succeeded} 项${failed ? `，${failed} 项因依赖或生成失败未完成` : ''}，跳过 ${scope.length - pending.length} 项已有资产`
    }
  } finally {
    bulkGenerating.value = false
  }
}

function libraryTypeForAsset(asset) {
  if (['role', 'layout'].includes(asset.category)) return 'image'
  return ['scene', 'prop', 'audio'].includes(asset.category) ? asset.category : (asset.type || 'image')
}

function assetMatchKey(name, type) {
  return `${String(name || '').trim().toLocaleLowerCase()}::${String(type || '').trim().toLocaleLowerCase()}`
}

function libraryDescriptionForAsset(asset) {
  const description = String(asset.description || '').trim()
  const prompt = String(asset.prompt || '').trim()
  if (!prompt || description.includes(prompt)) return description
  return [description, `提示词：${prompt}`].filter(Boolean).join('\n')
}

async function syncAssetsToLibrary() {
  if (assetLibrarySyncing.value) return
  if (!window.pywebview?.api) {
    assetLibraryStatus.value = '请从桌面客户端同步资产'
    return
  }
  const linkedProjectId = activeLinkedProjectId()
  if (!linkedProjectId) {
    assetLibraryStatus.value = '请先在任务详情顶部选择关联项目'
    return
  }
  const syncable = assets.value.filter(asset => assetUrl(asset) && (asset.fileId || fileIdFromUrl(assetUrl(asset))))
  if (!syncable.length) {
    assetLibraryStatus.value = '没有可同步的已生成资产'
    return
  }
  assetLibrarySyncing.value = true
  assetLibraryStatus.value = `正在同步 0/${syncable.length}`
  try {
    const libraryAssets = await window.pywebview.api.backend_request('GET', '/asset/list', props.token, null) || []
    const libraryMap = new Map(libraryAssets
      .filter(item => (Array.isArray(item.boundProjectIds) ? item.boundProjectIds : []).map(String).includes(linkedProjectId))
      .map(item => [assetMatchKey(item.name, item.type), item]))
    let completed = 0
    await Promise.all(syncable.map(async (asset) => {
      const type = libraryTypeForAsset(asset)
      const payload = {
        name: String(asset.name || ''),
        type,
        coverId: String(asset.fileId || fileIdFromUrl(assetUrl(asset)) || ''),
        description: libraryDescriptionForAsset(asset),
        tags: type,
        duration: String(asset.duration || ''),
        boundProjectIds: [linkedProjectId],
      }
      const existing = libraryMap.get(assetMatchKey(payload.name, type))
      if (existing) {
        payload.boundProjectIds = [...new Set([...(existing.boundProjectIds || []).map(String), linkedProjectId])]
      }
      const result = await window.pywebview.api.backend_request(existing ? 'PUT' : 'POST', existing ? `/asset/${encodeURIComponent(existing.id)}` : '/asset', props.token, payload)
      if (!existing && result) libraryMap.set(assetMatchKey(payload.name, type), result)
      completed += 1
      assetLibraryStatus.value = `正在同步 ${completed}/${syncable.length}`
    }))
    assetLibraryStatus.value = `已同步 ${syncable.length} 项，并绑定项目“${linkedProjectName()}”`
  } catch (err) {
    assetLibraryStatus.value = `同步失败：${cleanError(err)}`
  } finally {
    assetLibrarySyncing.value = false
  }
}

async function syncFromLinkedChapter() {
  const linkedId = activeLinkedProjectId()
  if (!linkedId) {
    assetLibraryStatus.value = '请先在顶部关联母剧本项目'
    return
  }
  assetLibrarySyncing.value = true
  assetLibraryStatus.value = '正在从剧本章节读取最新分镜与资产…'
  try {
    const chapterList = await videoProjectRequest('GET', `/project/${encodeURIComponent(linkedId)}/chapter/list`)
    const matchingChapter = (Array.isArray(chapterList) ? chapterList : []).find(ch =>
      (activeVideoProject.value?.description && activeVideoProject.value.description.includes(`章节 ID ${ch.id}`)) ||
      (activeVideoProject.value?.name && activeVideoProject.value.name.includes(ch.title || '---'))
    ) || (Array.isArray(chapterList) ? chapterList[0] : null)

    const cd = matchingChapter?.workflow?.creationData
    if (!cd || typeof cd !== 'object') {
      throw new Error(`剧本章节「${matchingChapter?.title || '未命名'}」中尚未提取创作数据，请先在剧本助手中提取`)
    }
    applyImportedDocument(cd, `从剧本「${matchingChapter.title}」重新同步`, true)
    await saveActiveVideoProject()
    assetLibraryStatus.value = `已成功从「${matchingChapter.title}」同步 ${storyboards.value.length} 个分镜与 ${assets.value.length} 项资产`
  } catch (err) {
    assetLibraryStatus.value = `同步失败：${cleanError(err)}`
  } finally {
    assetLibrarySyncing.value = false
  }
}

function getChapterShotCount(chapterId) {
  const key = String(chapterId)
  if (currentChapterId.value === key) return storyboards.value.length
  const epData = activeVideoProject.value?.episodes?.[key]
  if (epData && Array.isArray(epData.storyboards)) return epData.storyboards.length
  const ch = dramaChapters.value.find(c => String(c.id) === key)
  if (ch?.workflow?.creationData?.shots?.length) return ch.workflow.creationData.shots.length
  return 0
}

async function switchChapter(chapterId) {
  if (!chapterId || currentChapterId.value === String(chapterId)) return
  
  // 1. 保存当前集的镜头到 episodes
  if (currentChapterId.value && activeVideoProject.value) {
    activeVideoProject.value.episodes ||= {}
    activeVideoProject.value.episodes[currentChapterId.value] = {
      id: currentChapterId.value,
      title: dramaChapters.value.find(c => String(c.id) === currentChapterId.value)?.title || '未命名集',
      storyboards: storyboards.value.map(shot => ({ ...shot }))
    }
  }

  // 2. 切换当前集
  currentChapterId.value = String(chapterId)
  if (activeVideoProject.value) {
    activeVideoProject.value.currentEpisodeId = currentChapterId.value
  }

  // 3. 载入目标集的镜头数据
  const epData = activeVideoProject.value?.episodes?.[currentChapterId.value]
  if (epData && Array.isArray(epData.storyboards) && epData.storyboards.length > 0) {
    storyboards.value = epData.storyboards.map((stored, index) => {
      const shot = { ...createStoryboard(index + 1), ...stored }
      shot.prompt = cleanShotAudioPrompt(shot.prompt)
      ensureStoryboardDefaults(shot)
      synchronizeShotAssets(shot)
      return shot
    })
    activeShotId.value = storyboards.value[0]?.id || ''
  } else {
    // 检查剧本章节是否有 creationData
    const targetChapter = dramaChapters.value.find(c => String(c.id) === currentChapterId.value)
    let cd = targetChapter?.workflow?.creationData
    if (!cd) {
      try {
        const fullChapter = await videoProjectRequest('GET', `/chapter/${encodeURIComponent(currentChapterId.value)}`)
        cd = fullChapter?.workflow?.creationData
      } catch {}
    }
    if (cd && Array.isArray(cd.shots) && cd.shots.length > 0) {
      applyImportedDocument(cd, `载入「${targetChapter?.title || '新集数'}」分镜`, false)
    } else {
      storyboards.value = [createStoryboard(1)]
      activeShotId.value = storyboards.value[0].id
    }
    if (activeVideoProject.value) {
      activeVideoProject.value.episodes ||= {}
      activeVideoProject.value.episodes[currentChapterId.value] = {
        id: currentChapterId.value,
        title: targetChapter?.title || '未命名集',
        storyboards: storyboards.value.map(shot => ({ ...shot }))
      }
    }
  }

  await saveActiveVideoProject()
}

async function syncCurrentChapterFromScript() {
  const linkedId = activeLinkedProjectId()
  if (!linkedId) {
    showWorkspaceToast('请先在任务顶部关联母剧本项目', 'warning')
    return
  }
  const targetChapter = dramaChapters.value.find(c => String(c.id) === currentChapterId.value)
  if (!targetChapter) {
    showWorkspaceToast('请先选择需要同步的集数', 'warning')
    return
  }
  assetLibrarySyncing.value = true
  assetLibraryStatus.value = `正在从短剧助手同步「${targetChapter.title}」…`
  try {
    const fullChapter = await videoProjectRequest('GET', `/chapter/${encodeURIComponent(targetChapter.id)}`)
    const cd = fullChapter?.workflow?.creationData
    if (!cd || typeof cd !== 'object' || !Array.isArray(cd.shots) || !cd.shots.length) {
      showWorkspaceToast(`剧本「${targetChapter.title}」尚未提取资产与分镜，请先在短剧助手中完成第3步提取`, 'warning', 4500)
      return
    }
    applyImportedDocument(cd, `从短剧助手同步「${targetChapter.title}」`, false)
    if (activeVideoProject.value) {
      activeVideoProject.value.episodes ||= {}
      activeVideoProject.value.episodes[currentChapterId.value] = {
        id: currentChapterId.value,
        title: targetChapter.title,
        storyboards: storyboards.value.map(shot => ({ ...shot }))
      }
    }
    await saveActiveVideoProject()
    showWorkspaceToast(`已成功同步「${targetChapter.title}」的 ${storyboards.value.length} 个分镜与资产！`, 'success')
  } catch (err) {
    showWorkspaceToast(`同步失败：${cleanError(err)}`, 'error')
  } finally {
    assetLibrarySyncing.value = false
  }
}

async function restoreAssetsFromLibrary() {
  if (assetLibrarySyncing.value) return
  if (!window.pywebview?.api) {
    assetLibraryStatus.value = '请从桌面客户端回显资产'
    return
  }
  const linkedProjectId = activeLinkedProjectId()
  if (!linkedProjectId) {
    assetLibraryStatus.value = '请先在任务详情顶部选择关联项目'
    return
  }
  assetLibrarySyncing.value = true
  assetLibraryStatus.value = `正在从项目“${linkedProjectName()}”匹配资产…`
  try {
    const libraryAssets = await window.pywebview.api.backend_request('GET', '/asset/list', props.token, null) || []
    const libraryMap = new Map(libraryAssets
      .filter(item => (Array.isArray(item.boundProjectIds) ? item.boundProjectIds : []).map(String).includes(linkedProjectId))
      .map(item => [assetMatchKey(item.name, item.type), item]))
    let restored = 0
    assets.value.forEach((asset) => {
      const match = libraryMap.get(assetMatchKey(asset.name, libraryTypeForAsset(asset)))
      const coverId = String(match?.coverId || '')
      if (!match || (!coverId && !match.cover)) return
      asset.cover = match.cover || absoluteMediaUrl(`/file/${encodeURIComponent(coverId)}/download`)
      asset.fileId = coverId || fileIdFromUrl(match.cover)
      if (asset.category === 'audio' && match.duration) asset.duration = match.duration
      asset.generationError = ''
      restored += 1
    })
    assetLibraryStatus.value = `已从项目“${linkedProjectName()}”回显 ${restored} 项资产`
  } catch (err) {
    assetLibraryStatus.value = `回显失败：${cleanError(err)}`
  } finally {
    assetLibrarySyncing.value = false
  }
}

function openAssetDetail(asset) {
  const isAudio = asset.category === 'audio'
  const isRole = asset.category === 'role'
  if (isAudio) {
    if (!asset.subCategory) asset.subCategory = getAudioSubType(asset)
    if (!asset.description && (asset.style || asset.desc || asset.sound)) {
      asset.description = String(asset.style || asset.desc || asset.sound || '').trim()
    }
    if (!asset.voice && asset.subCategory === 'voice') {
      const name = String(asset.name || '')
      const desc = String(asset.description || asset.style || '')
      if (/男|大叔|苍凉|雄浑|厚重|天道|开篇|序幕|旁白|老者|老祖|师尊|帝尊|神明|沉稳/.test(name + desc)) {
        asset.voice = 'longshu_v2'
      } else if (/评书|霸气|说书|热血/.test(name + desc)) {
        asset.voice = 'longfeiyan_v2'
      } else if (/少年|青年|男主|少侠/.test(name + desc)) {
        asset.voice = 'longyuan_v2'
      } else if (/萝莉|可爱|女童|灵宠/.test(name + desc)) {
        asset.voice = 'longmiao_v2'
      } else if (/御姐|师姐|女尊|仙子|女帝|知性/.test(name + desc)) {
        asset.voice = 'longyue_v2'
      } else if (/女|女主|甜美/.test(name + desc)) {
        asset.voice = 'longtian_v2'
      } else {
        asset.voice = 'longshu_v2'
      }
    }
    if (!asset.prompt || String(asset.prompt).includes('你好，很高兴认识你')) {
      asset.prompt = inferAudioPromptFromProject(asset)
    }
  }
  if (isRole) asset.prompt = rolePromptWithoutDefaultLayout(asset.prompt)
  assetDetailTarget.value = asset
  assetReferencesCopied.value = false
  assetDraft.value = {
    name: String(asset.name || ''),
    description: String(asset.description || ''),
    prompt: String(asset.prompt || ''),
    subCategory: isAudio ? (asset.subCategory || getAudioSubType(asset)) : '',
    voice: isAudio ? String(asset.voice || '') : '',
    useDefaultRoleLayout: isRole ? asset.useDefaultRoleLayout !== false : true,
    imageTextMode: asset.imageTextMode || 'specified',
    imageText: String(asset.imageText || ''),
  }
  audioPreviewPlaying.value = false
  audioPreviewCurrent.value = 0
  audioPreviewDuration.value = 0
  assetDetailOpen.value = true
}

function closeAssetDetail() {
  if (audioPreview.value) audioPreview.value.pause()
  assetDetailOpen.value = false
  assetDetailTarget.value = null
  audioPreviewPlaying.value = false
  audioPreviewCurrent.value = 0
  audioPreviewDuration.value = 0
}

function formatAudioTime(value) {
  const seconds = Number.isFinite(Number(value)) ? Math.max(0, Math.floor(Number(value))) : 0
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function syncAudioPreviewMetadata(event) {
  audioPreviewDuration.value = Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0
}

function syncAudioPreviewTime(event) {
  audioPreviewCurrent.value = Number.isFinite(event.currentTarget.currentTime) ? event.currentTarget.currentTime : 0
}

async function toggleAudioPreview() {
  const player = audioPreview.value
  if (!player) return
  if (player.paused) {
    try { await player.play() } catch (err) { assetDetailTarget.value.generationError = cleanError(err) }
  } else {
    player.pause()
  }
}

function seekAudioPreview(event) {
  const player = audioPreview.value
  if (!player) return
  player.currentTime = Number(event.target.value) || 0
  audioPreviewCurrent.value = player.currentTime
}

function saveAssetDetail() {
  if (!assetDetailTarget.value) return
  const isRole = assetDetailTarget.value.category === 'role'
  const isAudio = assetDetailTarget.value.category === 'audio'
  Object.assign(assetDetailTarget.value, {
    name: assetDraft.value.name.trim() || assetDetailTarget.value.name,
    description: assetDraft.value.description.trim(),
    prompt: assetDraft.value.prompt.trim(),
    ...(isRole ? { useDefaultRoleLayout: assetDraft.value.useDefaultRoleLayout } : {}),
    ...(isAudio ? { subCategory: assetDraft.value.subCategory, voice: assetDraft.value.voice } : {}),
    ...(!isAudio && isGeneral.value ? { imageTextMode: assetDraft.value.imageTextMode, imageText: assetDraft.value.imageText.trim() } : {}),
  })
  reconcileAllShotsAssetConsistency()
  closeAssetDetail()
  scheduleProjectSave()
}

async function generateAssetFromDetail() {
  if (!assetDetailTarget.value) return
  const isRole = assetDetailTarget.value.category === 'role'
  const isAudio = assetDetailTarget.value.category === 'audio'
  Object.assign(assetDetailTarget.value, {
    name: assetDraft.value.name.trim() || assetDetailTarget.value.name,
    description: assetDraft.value.description.trim(),
    prompt: assetDraft.value.prompt.trim(),
    ...(isRole ? { useDefaultRoleLayout: assetDraft.value.useDefaultRoleLayout } : {}),
    ...(isAudio ? { subCategory: assetDraft.value.subCategory, voice: assetDraft.value.voice } : {}),
    ...(!isAudio && isGeneral.value ? { imageTextMode: assetDraft.value.imageTextMode, imageText: assetDraft.value.imageText.trim() } : {}),
  })
  await generateAsset(assetDetailTarget.value)
}

async function copyAssetReferences(asset) {
  if (!asset || assetReferencesCopying.value) return
  const state = assetReferenceState(asset)
  asset.generationError = ''
  assetReferencesCopied.value = false
  if (!state.total) {
    asset.generationError = '当前资产没有参考图'
    return
  }
  if (state.ready !== state.total) {
    asset.generationError = '请先生成或补齐全部参考图后再复制'
    return
  }
  const api = window.pywebview?.api
  if (!api?.prepare_generation_asset || !api?.copy_files_to_clipboard) {
    asset.generationError = '桌面客户端缺少参考图复制能力，请重启客户端后重试'
    return
  }

  assetReferencesCopying.value = true
  try {
    const paths = []
    for (const reference of state.items) {
      const prepared = await api.prepare_generation_asset(reference, props.token)
      const path = String(prepared?.path || '')
      if (!path) throw new Error(`无法准备参考图：${reference.name || reference.id}`)
      paths.push(path)
    }
    const copied = await api.copy_files_to_clipboard(paths)
    if (Number(copied?.count || 0) !== paths.length) throw new Error('参考图未能完整写入剪贴板')
    assetReferencesCopied.value = true
    window.setTimeout(() => { assetReferencesCopied.value = false }, 1600)
  } catch (err) {
    asset.generationError = cleanError(err)
  } finally {
    assetReferencesCopying.value = false
  }
}

async function selectLocalImageForAsset(asset) {
  if (!window.pywebview?.api) {
    asset.generationError = asset.category === 'audio' ? '请从桌面客户端选择本地音频' : '请从桌面客户端选择本地图片'
    return
  }
  try {
    const isAudio = asset.category === 'audio'
    const selected = await window.pywebview.api.select_and_upload_asset(props.token, {
      name: asset.name || (isAudio ? '音频资产' : '任务资产'),
      description: asset.description || '',
      tags: asset.category || 'image',
      type: isAudio ? 'audio' : 'image',
      audioName: isAudio ? asset.name : undefined,
      boundProjectIds: activeLinkedProjectId() ? [activeLinkedProjectId()] : [],
    })
    if (!selected) return
    asset.fileId = String(selected.coverId || selected.id || '')
    asset.coverId = asset.fileId
    asset.cover = fileDownloadUrl(asset.fileId)
    delete asset.path
    asset.generationError = ''
    if (isAudio) asset.duration = '已上传'
    scheduleProjectSave()
  } catch (err) {
    asset.generationError = cleanError(err)
  }
}

function clearAssetMedia(asset) {
  if (!asset) return
  const currentUrl = assetUrl(asset)
  ;['cover', 'fileId', 'coverId', 'content', 'image', 'imageUrl', 'image_url', 'url'].forEach((key) => {
    asset[key] = ''
  })
  delete asset.path
  delete asset.previewFailed
  if (asset.category === 'audio') delete asset.duration
  asset.generationError = ''
  if (currentUrl && mediaPreviewSrc.value === currentUrl) {
    mediaPreviewVisible.value = false
    mediaPreviewSrc.value = ''
  }
  scheduleProjectSave()
}
function clearAssetImage(asset) { clearAssetMedia(asset) }

const downloadingAssetMedia = ref(false)

async function downloadAssetMedia(asset) {
  const url = assetUrl(asset)
  if (!url || downloadingAssetMedia.value) return
  downloadingAssetMedia.value = true
  try {
    const isAudio = isAudioAsset(asset)
    const ext = isAudio ? 'mp3' : 'png'
    const rawName = String(asset?.name || assetDraft.value?.name || asset?.id || (isAudio ? '音频' : '图片')).trim()
    const cleanName = rawName.replace(/[\\/:*?"<>|]/g, '_') || 'asset'
    const suggestedName = `${cleanName}.${ext}`

    const fileId = String(asset?.fileId || asset?.coverId || fileIdFromUrl(url) || '').trim()
    if (fileId && window.pywebview?.api?.save_server_file_as) {
      const res = await window.pywebview.api.save_server_file_as(props.token, fileId, suggestedName)
      if (res === null || res?.saved) return
    }

    const response = await fetch(url)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const blob = await response.blob()
    if (!blob.size) throw new Error('文件内容为空')
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = suggestedName
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  } catch (err) {
    console.error('下载资产媒体失败:', err)
    const link = document.createElement('a')
    link.href = url
    link.download = `${String(asset?.name || 'asset')}.png`
    link.target = '_blank'
    link.click()
  } finally {
    downloadingAssetMedia.value = false
  }
}

function assetUrl(asset) {
  const resolvedAsset = resolveAssetReference(asset)
  if (resolvedAsset?.cover) return absoluteMediaUrl(resolvedAsset.cover)
  const id = resolvedAsset?.coverId || resolvedAsset?.fileId
  if (id) return fileDownloadUrl(id)
  return ''
}

function isAudioAsset(asset) {
  const hints = [asset?.mediaType, asset?.type, asset?.category, asset?.mimeType, asset?.contentType, asset?.tags]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  if (/audio|音频/.test(hints) || asset?.audioUrl || asset?.audio_url) return true
  const pathHint = String(asset?.path || asset?.originalFileName || '').toLowerCase()
  if (/\.(?:mp3|wav|m4a|aac|ogg|flac)(?:$|[?#])/.test(pathHint)) return true
  return false
}

function handleReferencePreviewError(asset) {
  if (!asset) return
  const resolved = resolveAssetReference(asset)
  if (!resolved?.fileId && !resolved?.coverId && !resolved?.cover) {
    asset.previewFailed = true
    if (resolved) resolved.previewFailed = true
  }
}

const currentActiveShot = computed(() => {
  return storyboards.value.find(item => item.id === activeShotId.value) || storyboards.value[0] || null
})

function isAssetInActiveShot(asset) {
  if (!asset) return false
  const shot = currentActiveShot.value
  if (!shot || !Array.isArray(shot.references)) return false
  const targetId = String(asset.id || '')
  return shot.references.some(r => String(r.id) === targetId)
}

function shotAttachedAudios(shot) {
  if (!shot || !Array.isArray(shot.references)) return []
  return shot.references.filter(asset => isAudioAsset(asset) && getAudioSubType(asset) === 'sfx')
}

const playingAudioId = ref('')
let activeAudioElement = null

function togglePlayAudio(asset) {
  const url = assetUrl(asset)
  if (!url) return
  const idStr = String(asset.id || '')
  if (playingAudioId.value === idStr) {
    if (activeAudioElement) {
      activeAudioElement.pause()
      activeAudioElement = null
    }
    playingAudioId.value = ''
    return
  }
  if (activeAudioElement) {
    activeAudioElement.pause()
    activeAudioElement = null
  }
  const el = new Audio(url)
  if (asset.mode === 'voice-conversion' && asset.timeline?.length) {
    el.addEventListener('loadedmetadata', () => { el.currentTime = Number(asset.timeline[0].start || 0) }, { once: true })
  }
  activeAudioElement = el
  playingAudioId.value = idStr
  el.onended = () => {
    if (playingAudioId.value === idStr) {
      playingAudioId.value = ''
      activeAudioElement = null
    }
  }
  el.onerror = () => {
    playingAudioId.value = ''
    activeAudioElement = null
  }
  el.play().catch(() => {
    playingAudioId.value = ''
    activeAudioElement = null
  })
}

function toggleAudioReference(asset, targetShot = null) {
  const shot = targetShot || currentActiveShot.value
  if (!shot || !asset) return
  if (!assetUrl(asset)) {
    asset.generationError = '请先生成或导入音频后再添加到分镜'
    return
  }
  const isAdded = shot.references.some(r => String(r.id) === String(asset.id))
  if (isAdded) {
    removeReference(shot, asset.id)
  } else {
    addAudioReferenceToShot(shot, asset)
  }
}

function addAudioReferenceToShot(shot, asset) {
  if (!shot || !asset) return
  if (!shot.references.some(r => String(r.id) === String(asset.id))) {
    shot.references.push(asset)
  }
  shot.referenceLabels[String(asset.id)] = asset.name || '音频'
  shot.referencesExpanded = false
  scheduleProjectSave()
}

const muxingShotId = ref('')
const breezeConnection = ref({})
const breezeConnecting = ref(false)
const breezeProgress = ref(null)
const breezeBusy = computed(() => breezeProgress.value?.status === 'running')
const breezeQuickShotId = ref('')
const breezeRoot = computed(() => activeVideoProject.value?.breezeRoot || '')
const breezeBindings = computed(() => activeVideoProject.value?.breezeVoices || {})
function setBreezeRoot(value) {
  activeVideoProject.value.breezeRoot = value.trim()
  breezeConnection.value = {}
  scheduleProjectSave()
}
function setBreezeBinding({ role, field, value }) {
  // Preserve the settings used by legacy takes before changing a shared role.
  for (const shot of storyboards.value) {
    const audio = breezeAudio(shot)
    if (audio && !audio.voiceSignature) audio.voiceSignature = voiceSignature(shot.breezeAudioContract, breezeBindings.value)
  }
  const bindings = { ...breezeBindings.value }
  bindings[role] = { ...bindings[role], [field]: value, ...(field === 'instruction' ? { auto: false } : {}) }
  activeVideoProject.value.breezeVoices = bindings
  scheduleProjectSave()
}
async function connectBreeze(start = false) {
  if (breezeConnecting.value) return
  breezeConnecting.value = true
  try {
    const api = window.pywebview?.api
    if (!api?.breeze_status) throw new Error('本地配音组件尚未同步，请重启最新版客户端')
    if (start) await api.breeze_start(breezeRoot.value)
    const deadline = Date.now() + (start ? 180000 : 0)
    let elapsed = 0
    do {
      breezeConnection.value = await api.breeze_status(breezeRoot.value)
      if (breezeConnection.value.ready || !start) break
      elapsed += 2
      breezeConnection.value.message = `Breeze 正在加载 4.3G 本地模型（冷启动首次加载需约 1 分钟，已等待 ${elapsed}s）…`
      await new Promise(resolve => setTimeout(resolve, 2000))
    } while (Date.now() < deadline)
    if (start && !breezeConnection.value.ready) breezeConnection.value.message = '模型尚未就绪，请查看 Breeze 窗口后刷新连接'
  } catch (err) {
    breezeConnection.value = { ready: false, message: cleanError(err) }
  } finally {
    breezeConnecting.value = false
  }
}
function voiceBindingForRole(role, existing = null, deliveryHint = '', prompt = '') {
  if (existing?.instruction || existing?.voiceId) {
    return existing
  }
  const fromPrompt = extractRoleVoiceInstruction(prompt, role, deliveryHint)
  if (fromPrompt) {
    return { voiceId: existing?.voiceId || '', auto: false, instruction: fromPrompt }
  }
  const character = assets.value.find(a => a.category === 'role' && a.name === role)
  if (character) {
    return { voiceId: existing?.voiceId || '', auto: false, instruction: automaticVoiceInstruction(character) }
  }
  if (role === '旁白' || role === '画外音' || role === '内心独白' || role === '解说') {
    const hint = deliveryHint || '低沉浑厚，沉稳沧桑，富有叙事感染力'
    const desc = `${hint}，普通话，清晰自然，语速适中`
    return { voiceId: existing?.voiceId || '', auto: false, instruction: desc }
  }
  return existing
}
function shouldRefreshVoiceBinding(binding) {
  if (!binding) return true
  if (!binding.instruction && !binding.voiceId) return true
  return isLegacyVoiceInstruction(binding.instruction)
}
function refreshLegacyVoiceBindings() {
  const current = activeVideoProject.value?.breezeVoices || {}
  const bindings = { ...current }
  let changed = false
  for (const role of Object.keys(bindings)) {
    if (!shouldRefreshVoiceBinding(bindings[role])) continue
    const next = voiceBindingForRole(role, bindings[role])
    if (!next || JSON.stringify(bindings[role]) === JSON.stringify(next)) continue
    bindings[role] = next
    changed = true
  }
  if (changed) activeVideoProject.value.breezeVoices = bindings
  return changed
}
function toggleBreezePanel(shot) {
  shot.breezeOpen = true
  if (shot.breezeOpen) {
    const bindings = { ...breezeBindings.value }
    const contract = dialogueContract(shot.prompt)
    contract.roles.forEach((role, i) => {
      role ||= '未标注角色'
      if (!shouldRefreshVoiceBinding(bindings[role])) return
      const delivery = contract.deliveries?.[i] || ''
      const next = voiceBindingForRole(role, bindings[role], delivery, shot.prompt)
      if (next) bindings[role] = next
    })
    activeVideoProject.value.breezeVoices = bindings
    scheduleProjectSave()
    connectBreeze()
  }
}
function selectShotTab(shot, tab) {
  shot.workspaceTab = tab
  if (tab === 'audio') toggleBreezePanel(shot)
}
function breezeAudio(shot) {
  return shot.dubbingAudio || shot.references?.find(a => String(a.id) === String(shot.breezeAudioAssetId)) || null
}
function breezeAudioStale(shot) {
  const current = dialogueContract(shot.prompt)
  const previous = shot.breezeAudioContract
  const audio = breezeAudio(shot)
  if (!audio) return false
  const audioContract = audio.dialogueContract || audio.voiceReferenceContract
  const contractMismatch = audioContract ? !sameDialogue(audioContract, current) : !sameDialogue(previous, current)
  return Boolean((audio.voiceSignature && audio.voiceSignature !== voiceSignature(current, breezeBindings.value))
    || contractMismatch
    || !sameDialogue(previous, current)
    || (previous?.deliveries && JSON.stringify(previous.deliveries) !== JSON.stringify(current.deliveries)))
}
async function generateBreezeForShot(shot, mode = 'text', quick = false) {
  if (breezeBusy.value) return
  const contract = dialogueContract(shot.prompt)
  if (!contract.explicit || !contract.lines.length) return
  rememberAppliedDubbing(shot, breezeAudio(shot), contract)
  const projectId = String(activeVideoProject.value.id)
  const projectKey = activeLinkedProjectId() || projectId
  breezeProgress.value = { status: 'running', shotId: shot.id, completed: 0, total: contract.lines.length, message: '正在准备配音…' }
  try {
    const api = window.pywebview.api
    const bindingsSnapshot = { ...breezeBindings.value }
    for (let i = 0; i < contract.roles.length; i++) {
      const r = contract.roles[i] || '未标注角色'
      if (!bindingsSnapshot[r]?.instruction) {
        const extracted = extractRoleVoiceInstruction(shot.prompt, r, contract.deliveries?.[i] || '')
        if (extracted) {
          bindingsSnapshot[r] = { ...(bindingsSnapshot[r] || {}), instruction: extracted }
        }
      }
    }
    const request = JSON.parse(JSON.stringify({ projectKey, contract, bindings: bindingsSnapshot, delivery: quick ? 'natural-dialogue' : '' }))
    if (mode === 'voice-conversion') {
      const reference = breezeAudio(shot)
      if (!reference || breezeAudioStale(shot) || !breezeSourceVideoId(shot)) throw new Error('请先生成当前台词的角色配音，再尝试原声换音色')
      Object.assign(request, JSON.parse(JSON.stringify({ mode, videoFileId: breezeSourceVideoId(shot), referenceAudioFileId: reference.voiceReferenceFileId || reference.fileId || reference.coverId,
        referenceContract: reference.voiceReferenceContract || reference.dialogueContract, referenceTimeline: reference.voiceReferenceTimeline || reference.timeline })))
    }
    const job = await api.breeze_generate(props.token, request)
    breezeProgress.value.id = job.id
    let result
    do {
      await new Promise(resolve => setTimeout(resolve, 800))
      result = await api.breeze_job(job.id)
      breezeProgress.value = { ...result, shotId: shot.id }
    } while (result.status === 'running')
    if (result.status !== 'completed') return
    const media = result.result
    const id = `breeze_${job.id}`
    const asset = { id, category: 'audio', subCategory: 'voice', name: `${shot.title || '分镜'} · ${media.mode === 'voice-conversion' ? '原声换音色' : 'Breeze 配音'}`,
      fileId: media.fileId, coverId: media.fileId, cover: fileDownloadUrl(media.fileId),
      duration: media.duration, prompt: contract.text, description: '本机 Breeze 按分镜台词生成',
      provider: 'breeze-local', dialogueContract: contract, timeline: media.timeline, voiceSignature: voiceSignature(contract, request.bindings), loudnessVersion: media.loudnessVersion || 0,
      mode: media.mode || 'text', sourceVideoFileId: media.sourceVideoFileId || '', conversionReview: media.review || null, conversionReviewAccepted: false,
      voiceReferenceFileId: request.referenceAudioFileId || '', voiceReferenceContract: request.referenceContract || null, voiceReferenceTimeline: request.referenceTimeline || null }
    // Keep dubbing in this shot's sound panel, outside the visual asset library.
    const apply = (target) => {
      target.references = (target.references || []).filter(a => String(a.id) !== String(target.breezeAudioAssetId))
      target.dubbingAudio = asset
      target.referenceLabels ||= {}
      target.referenceLabels[id] = asset.name
      target.breezeAudioAssetId = id
      target.breezeAudioContract = contract
      target.breezeAlignment = media.alignment || alignmentForDubbing(target, asset, contract)
    }
    if (String(activeVideoProject.value?.id) === projectId) {
      const currentShot = storyboards.value.find(s => String(s.id) === String(shot.id))
      if (currentShot) apply(currentShot)
      const saved = await saveActiveVideoProject()
      if (!saved) throw new Error('配音已生成，但任务保存失败。请保留此页面并重试保存')
    } else {
      // A user may switch tasks during synthesis. Save back into the originating task.
      const detail = await videoProjectRequest('GET', `/video-project/${encodeURIComponent(projectId)}`)
      detail.assets = (detail.assets || []).filter(asset => !isAudioAsset(asset))
      const target = (detail.storyboards || []).find(s => String(s.id) === String(shot.id))
      if (target) apply(target)
      await videoProjectRequest('PUT', `/video-project/${encodeURIComponent(projectId)}`, detail)
    }
    breezeProgress.value.message = media.mode === 'voice-conversion' ? '原声换音色已完成，请试听并核对台词后合入' : `配音已保存，${media.duration.toFixed(1)} 秒，可试听或合入视频`
    return asset
  } catch (err) {
    breezeProgress.value = { ...breezeProgress.value, status: 'failed', message: cleanError(err) }
  }
}
async function cancelBreeze() {
  if (!breezeProgress.value?.id) return
  await window.pywebview.api.breeze_cancel(breezeProgress.value.id)
}
async function restoreBreezeVideo(shot) {
  if (!shot.originalVideoFileId) return
  shot.resultFileId = shot.originalVideoFileId
  shot.resultUrl = fileDownloadUrl(shot.resultFileId)
  shot.mixedAudioFileId = ''
  shot.mixedVideoFileId = ''
  shot.audioReview = null
  shot.previewOriginal = false
  shot.statusText = '已恢复原视频声音'
  await saveActiveVideoProject()
}
const breezeAlignProgress = ref(null)
function breezeSourceVideoId(shot) { return dubbingSourceVideoId(shot) }
function validBreezeAlignment(shot) {
  return alignmentForDubbing(shot, breezeAudio(shot), dialogueContract(shot.prompt))
}
async function alignShotAudio(shot, force = false) {
  const audio = breezeAudio(shot)
  if (!audio || breezeAudioStale(shot) || breezeAlignProgress.value?.status === 'running') return
  const existing = validBreezeAlignment(shot)
  if (!force && confirmedDubbingTiming(existing, dialogueContract(shot.prompt), breezeSourceVideoId(shot))) {
    shot.breezeAlignment = existing
    return existing
  }
  const projectId = String(activeVideoProject.value.id)
  const videoFileId = breezeSourceVideoId(shot)
  const audioFileId = String(audio.fileId || audio.coverId || '')
  const contract = JSON.parse(JSON.stringify(dialogueContract(shot.prompt)))
  breezeAlignProgress.value = { shotId: shot.id, status: 'running', message: '正在读取原视频台词…' }
  try {
    if (!window.pywebview.api.breeze_align) throw new Error('请同步最新版客户端并重启')
    const job = await window.pywebview.api.breeze_align(props.token, JSON.parse(JSON.stringify({ videoFileId, audioFileId, contract, timeline: audio.timeline })))
    let result
    do {
      await new Promise(resolve => setTimeout(resolve, 700))
      result = await window.pywebview.api.breeze_job(job.id)
      breezeAlignProgress.value = { ...result, shotId: shot.id }
    } while (result.status === 'running')
    if (result.status !== 'completed') return
    if (projectId !== String(activeVideoProject.value?.id)) return
    if (breezeSourceVideoId(shot) !== videoFileId || String(breezeAudio(shot)?.fileId || breezeAudio(shot)?.coverId || '') !== audioFileId || !sameDialogue(contract, dialogueContract(shot.prompt))) throw new Error('分镜或配音已改变，本次定位结果未应用')
    if (!confirmedDubbingTiming(result.result, contract, videoFileId) && confirmedDubbingTiming(existing, contract, videoFileId)) {
      shot.breezeAlignmentCandidate = result.result
      breezeAlignProgress.value = { shotId: shot.id, status: 'completed', message: '本次识别不完整，已保留确认过的说话时间，当前视频不变。' }
      await saveActiveVideoProject()
      return existing
    }
    shot.breezeAlignment = result.result
    if (confirmedDubbingTiming(result.result, contract, videoFileId)) shot.breezeTiming = JSON.parse(JSON.stringify(result.result))
    await saveActiveVideoProject()
    return result.result
  } catch (err) {
    breezeAlignProgress.value = { shotId: shot.id, status: 'failed', message: cleanError(err) }
  }
}
function updateBreezeTiming(shot, { index, field, value }) {
  if (breezeAudio(shot)?.mode === 'voice-conversion') return
  const alignment = validBreezeAlignment(shot)
  if (!alignment?.rows[index]) return
  shot.breezeAlignment = alignment
  shot.breezeTiming = null
  alignment.rows[index][field] = value
  if (field !== 'confirmed') {
    alignment.rows[index].confirmed = false
    alignment.rows[index].method = 'manual_required'
    delete alignment.rows[index].pieces
    delete alignment.rows[index].planStart
    delete alignment.rows[index].planEnd
  }
  scheduleProjectSave()
}
function acceptConversionReview(shot, value) {
  const audio = breezeAudio(shot)
  if (!audio) return
  audio.conversionReviewAccepted = Boolean(value)
  scheduleProjectSave()
}
async function previewBreezeOriginal(shot, row = null) {
  const id = breezeSourceVideoId(shot)
  if (!id) return
  shot.originalPreviewUrl = await compatibleVideoUrl(id, fileDownloadUrl(id))
  shot.previewOriginal = true
  shot.previewStopAt = row?.end ?? null
  await nextTick()
  const video = getVideo(shot)
  if (!video) return
  const seekAndPlay = () => {
    video.playbackRate = 1
    video.currentTime = Math.max(0, Number(row?.start || 0))
    video.muted = false
    video.play().catch(() => {})
  }
  if (video.readyState >= 1) seekAndPlay()
  else video.addEventListener('loadedmetadata', seekAndPlay, { once: true })
}
async function previewBreezeCurrent(shot) {
  shot.previewOriginal = false
  shot.previewStopAt = null
  if (shot.mixedVideoFileId && shot.resultFileId !== shot.mixedVideoFileId) {
    shot.resultFileId = shot.mixedVideoFileId
    shot.resultUrl = fileDownloadUrl(shot.mixedVideoFileId)
  }
  await nextTick()
  const video = getVideo(shot)
  if (!video) return
  const seekAndPlay = () => {
    video.playbackRate = 1
    video.currentTime = Math.max(0, Number(validBreezeAlignment(shot)?.rows?.[0]?.start || 0) - .35)
    video.muted = false
    video.play().catch(() => {})
  }
  if (video.readyState >= 1) seekAndPlay()
  else video.addEventListener('loadedmetadata', seekAndPlay, { once: true })
}
async function replaceShotDubbing(shot) {
  if (breezeQuickShotId.value || breezeBusy.value || muxingShotId.value) return
  const projectId = String(activeVideoProject.value?.id)
  breezeQuickShotId.value = shot.id
  shot.generationError = ''
  try {
    const audio = await generateBreezeForShot(shot, 'text', true)
    if (!audio || projectId !== String(activeVideoProject.value?.id)) return
    let alignment = await alignShotAudio(shot)
    if (projectId !== String(activeVideoProject.value?.id)) return
    if (await mixAlignedBreeze(shot)) {
      await previewBreezeCurrent(shot)
      showWorkspaceToast('✅ 配音已成功生成并替换入视频！', 'success', 3000)
    }
  } catch (err) {
    console.error('replaceShotDubbing error:', err)
    shot.generationError = err.message || '配音替换失败'
  } finally {
    breezeQuickShotId.value = ''
  }
}
async function mixAlignedBreeze(shot) {
  const audio = breezeAudio(shot)
  if (!audio || muxingShotId.value || breezeAudioStale(shot)) return false
  const audioId = dubbingAudioId(audio)
  
  // ⚡ 智能即时应用：如果本镜已有对应当前配音的成片视频，直接恢复并应用，秒级生效
  if (shot.mixedVideoFileId && String(shot.mixedAudioFileId || '') === audioId) {
    shot.resultFileId = shot.mixedVideoFileId
    shot.resultUrl = fileDownloadUrl(shot.mixedVideoFileId)
    shot.previewOriginal = false
    shot.statusText = '已应用配音'
    showWorkspaceToast('✅ 配音已成功应用到当前视频！', 'success', 3000)
    await saveActiveVideoProject()
    await previewBreezeCurrent(shot)
    return true
  }

  let alignment = validBreezeAlignment(shot)
  const projectId = String(activeVideoProject.value?.id)
  const contract = dialogueContract(shot.prompt)
  let prevEnd = 0
  const hasValidTimes = alignment?.rows?.length && alignment.rows.every(row => {
    const s = Number(row.start), e = Number(row.end)
    const ok = Number.isFinite(s) && Number.isFinite(e) && e - s >= 0.12 && s >= prevEnd - 0.05
    if (ok) {
      row.confirmed = true
      prevEnd = e
    }
    return ok
  })
  if (!hasValidTimes) {
    alignment = await alignShotAudio(shot)
    let prev2 = 0
    const rechecked = alignment?.rows?.length && alignment.rows.every(row => {
      const s = Number(row.start), e = Number(row.end)
      const ok = Number.isFinite(s) && Number.isFinite(e) && e - s >= 0.12 && s >= prev2 - 0.05
      if (ok) {
        row.confirmed = true
        prev2 = e
      }
      return ok
    })
    if (!rechecked) {
      shot.generationError = '尚未替换：没有找到说话位置。请重新定位，或在高级设置核对时间。'
      return false
    }
  }

  // 始终以原片底片为混音输入，避免二次混音损坏音轨
  const baseVideoId = String(shot.originalVideoFileId || breezeSourceVideoId(shot) || shot.resultFileId)
  const request = JSON.parse(JSON.stringify({ 
    videoFileId: baseVideoId, 
    audioFileId: alignment.audioFileId || audioId, 
    contract: alignment.contract || contract, 
    rows: alignment.rows, 
    timeline: audio.timeline || [],
    mode: audio.mode || 'text', 
    sourceVideoFileId: audio.sourceVideoFileId || '' 
  }))
  muxingShotId.value = shot.id
  shot.generationError = ''
  try {
    const result = await window.pywebview.api.breeze_mix_aligned(props.token, request)
    if (projectId !== String(activeVideoProject.value?.id) || !sameDialogue(request.contract, dialogueContract(shot.prompt))) {
      throw new Error('分镜台词已改变，对齐结果尚未替换当前视频，请重新合入')
    }
    if (!result?.id) throw new Error('合入没有返回视频文件')
    if (!shot.originalVideoFileId) shot.originalVideoFileId = baseVideoId
    shot.resultFileId = String(result.id)
    shot.mixedVideoFileId = String(result.id)
    shot.mixedAudioFileId = request.audioFileId
    shot.breezeMixVersion = 3
    shot.breezeAlignment = { ...alignment, videoFileId: String(result.id) }
    shot.breezeTiming = JSON.parse(JSON.stringify(shot.breezeAlignment))
    rememberAppliedDubbing(shot, audio, contract)
    shot.resultUrl = fileDownloadUrl(result.id)
    shot.previewOriginal = false
    shot.audioReview = null
    shot.statusText = '已替换配音'
    showWorkspaceToast('✅ 配音已成功替换入当前视频！', 'success', 3000)
    if (!await saveActiveVideoProject()) throw new Error('对齐完成，但任务保存失败，请保留页面重试')
    await previewBreezeCurrent(shot)
    return true
  } catch (err) {
    shot.generationError = `对齐合入失败：${cleanError(err)}`
    showWorkspaceToast(`❌ 对齐合入失败: ${cleanError(err)}`, 'error', 4000)
    return false
  } finally { muxingShotId.value = '' }
}
async function muxShotAudio(shot, audioAsset) {
  if (!shot?.resultFileId || !audioAsset) return
  if (muxingShotId.value) return
  if (audioAsset.provider === 'breeze-local' && !sameDialogue(audioAsset.dialogueContract, dialogueContract(shot.prompt))) {
    shot.generationError = '台词已修改，请重新生成配音后再合入'
    return
  }
  if (audioAsset.provider === 'breeze-local') {
    selectShotTab(shot, 'audio')
    if (!validBreezeAlignment(shot)) await alignShotAudio(shot)
    const alignment = validBreezeAlignment(shot)
    await mixAlignedBreeze(shot)
    return
  }
  const audioFileId = String(audioAsset.fileId || audioAsset.coverId || fileIdFromUrl(assetUrl(audioAsset)) || '')
  if (!audioFileId) {
    shot.generationError = '音频尚未上传入库，无法执行合成'
    return
  }
  if (!window.pywebview?.api?.mux_video_audio) {
    shot.generationError = '当前客户端版本尚未包含视频音频合成接口'
    return
  }
  muxingShotId.value = shot.id
  shot.generationError = ''
  try {
    const result = await window.pywebview.api.mux_video_audio(props.token, String(shot.resultFileId), audioFileId)
    if (result?.id) {
      if (!shot.originalVideoFileId || String(shot.resultFileId) !== String(shot.mixedVideoFileId)) shot.originalVideoFileId = String(shot.resultFileId)
      shot.resultFileId = String(result.id)
      shot.mixedAudioFileId = audioFileId
      shot.mixedVideoFileId = String(result.id)
      shot.audioReview = null
      shot.resultUrl = fileDownloadUrl(shot.resultFileId)
      shot.statusText = `已将「${audioAsset.name}」合入视频并覆盖原声音效`
      await saveActiveVideoProject()
    }
  } catch (err) {
    shot.generationError = `配音合入失败：${cleanError(err)}`
  } finally {
    muxingShotId.value = ''
  }
}

function addReference(asset) {
  if (!assetUrl(asset)) {
    asset.generationError = asset.category === 'audio' ? '请先生成音频' : '请先生成图片'
    return
  }
  const shot = storyboards.value.find(item => item.id === activeShotId.value) || storyboards.value[0]
  if (!shot) return
  if (isAudioAsset(asset)) {
    toggleAudioReference(asset, shot)
    return
  }
  if (shot.references.some(item => String(item.id) === String(asset.id))) return
  shot.references.push(asset)
  shot.referenceLabels[String(asset.id)] = `${asset.name}参考`
  const referenceText = `${asset.name}参考 {{${asset.id}}}`
  if (!shot.prompt.includes(`{{${asset.id}}}`)) {
    const lines = shot.prompt.split('\n')
    const lineIndex = lines.findIndex(line => /^一致性引用[：:]/.test(line.trim()))
    if (lineIndex >= 0) lines[lineIndex] = `${lines[lineIndex].replace(/[，,\s]+$/, '')}，${referenceText}`
    else lines.unshift(`一致性引用：${referenceText}`)
    shot.prompt = lines.join('\n')
  }
  shot.referencesExpanded = true
  scheduleProjectSave()
}

function selectMentionAsset(shot, asset) {
  if (!shot || !asset || shot.references.some(item => String(item.id) === String(asset.id))) return
  if (assetUrl(asset)) shot.references.push(asset)
  shot.referenceLabels[String(asset.id)] = asset.name || String(asset.id)
  shot.referencesExpanded = true
}


function allAvailableAssetsForEditor(shot) {
  const map = new Map()
  ;(assets.value || []).forEach(a => {
    if (a?.id) map.set(String(a.id), a)
  })
  ;(Array.isArray(shot?.references) ? shot.references : []).forEach(r => {
    const a = resolveAssetReference(r)
    if (a?.id && !map.has(String(a.id))) map.set(String(a.id), a)
  })
  return Array.from(map.values())
}

function mentionAssets(shot) {
  return (Array.isArray(shot?.references) ? shot.references : [])
    .map(resolveAssetReference)
    .filter(asset => asset?.id && assetUrl(asset))
}

function sendAttachments(shot) {
  if (shot) synchronizeShotAssets(shot)
  const result = (Array.isArray(shot?.references) ? shot.references : [])
    .map(resolveAssetReference)
    .filter(asset => asset?.id)
  const seen = new Set(result.map(asset => String(asset.id).toLowerCase()))
  const prompt = String(shot?.prompt || '')
  const pattern = /[{｛]{1,2}\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*[}｝]{1,2}/g
  let match
  while ((match = pattern.exec(prompt))) {
    const id = String(match[1] || '')
    const key = id.toLowerCase()
    if (!id || seen.has(key)) continue
    const asset = canonicalAssetsById.value.get(id) || canonicalAssetsById.value.get(key)
    if (!asset) continue
    result.push(asset)
    seen.add(key)
  }
  return result
}

function synchronizeShotRoles(shot) {
  const report = missingShotRoles(shot, assets.value)
  shot.references ||= []
  shot.referenceLabels ||= {}
  for (const asset of report.missing) {
    shot.references.push({ ...asset })
    shot.referenceLabels[asset.id] = asset.name || asset.id
  }
  if (report.missing.length) shot.referenceRepairNotice = `已补齐画面人物参考：${report.missing.map(asset => asset.name || asset.id).join('、')}`
  return report
}

function synchronizeShotAssets(shot) {
  if (!shot) return { missing: [], ambiguous: [] }
  const roleReport = synchronizeShotRoles(shot)
  shot.references ||= []
  shot.referenceLabels ||= {}
  const prompt = `${shot.title || ''}\n${shot.prompt || ''}`
  const existingIds = new Set(shot.references.map(a => String(a.id || '').toLowerCase()))
  const candidateAssets = (assets.value || []).filter(a => {
    const cat = String(a?.category || a?.type || '').toLowerCase()
    return cat === 'scene' || cat === 'environment' || cat === 'prop' || cat === 'item'
  })
  const addedAssets = []
  for (const asset of candidateAssets) {
    const name = String(asset?.name || '').trim()
    if (!name || name.length < 2) continue
    if (existingIds.has(String(asset.id || '').toLowerCase())) continue
    if (prompt.includes(name)) {
      shot.references.push({ ...asset })
      shot.referenceLabels[asset.id] = asset.name || asset.id
      existingIds.add(String(asset.id).toLowerCase())
      addedAssets.push(asset)
    }
  }
  if (addedAssets.length) {
    const label = addedAssets.map(a => a.name || a.id).join('、')
    if (shot.referenceRepairNotice) {
      shot.referenceRepairNotice += `；已自动关联场景/道具：${label}`
    } else {
      shot.referenceRepairNotice = `已自动关联场景/道具参考：${label}`
    }
  }
  return roleReport
}

const ORIGINAL_DOUBAO_MATERIAL_PLEDGE = '本次视频生成使用的参考图片均为 AI 生成的原创虚构角色，不对应现实人物，仅用于虚构剧情创作。'

function promptForOriginalDoubao(prompt, references, omittedReferences = []) {
  const attachmentNames = new Map()
  const omittedNames = new Map(omittedReferences.map(asset => [
    String(asset?.id || '').toLowerCase(),
    asset?.name || asset?.title || '音频参考',
  ]))
  const imageNames = []
  const audioNames = []
  references.forEach((asset, index) => {
    const audio = isAudioAsset(asset)
    const attachmentName = `${audio ? '文件' : '图'}${index + 1}`
    attachmentNames.set(String(asset.id).toLowerCase(), attachmentName)
    if (audio) audioNames.push(attachmentName)
    else imageNames.push(attachmentName)
  })
  const source = String(prompt || '')
  const tokenPattern = /[{｛]{1,2}\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*[}｝]{1,2}/g
  const directlyUsed = new Set([...source.matchAll(tokenPattern)]
    .map(match => attachmentNames.get(String(match[1] || '').toLowerCase()))
    .filter(Boolean))
  const availableAudioNames = audioNames.filter(name => !directlyUsed.has(name))
  const availableImageNames = imageNames.filter(name => !directlyUsed.has(name))
  const fallbackNames = new Map()
  const mappedPrompt = source.replace(tokenPattern, (token, id) => {
    const key = String(id).toLowerCase()
    const directName = attachmentNames.get(key)
    if (directName) return directName
    if (omittedNames.has(key)) return omittedNames.get(key)
    if (fallbackNames.has(key)) return fallbackNames.get(key)
    const isAudioToken = /^(?:audio|voice|sound)[-_.:]/i.test(String(id))
    const isImageToken = /^(?:char|character|role|scene|prop|image|img)[-_.:]/i.test(String(id))
    if (!isAudioToken && !isImageToken) return token
    const fallbackName = isAudioToken ? availableAudioNames.shift() : availableImageNames.shift()
    if (!fallbackName) return token
    fallbackNames.set(key, fallbackName)
    return fallbackName
  }).trim()
  return mappedPrompt.endsWith(ORIGINAL_DOUBAO_MATERIAL_PLEDGE)
    ? mappedPrompt
    : `${mappedPrompt}\n\n${ORIGINAL_DOUBAO_MATERIAL_PLEDGE}`
}

function layoutDependencyIds(asset) {
  const values = [
    ...(asset?.category === 'layout' && Array.isArray(asset?.characters) ? asset.characters : []),
    ...(asset?.category === 'layout' && Array.isArray(asset?.character_instances) ? asset.character_instances.map(item => item?.character_id || item?.id) : []),
    ...(asset?.category === 'layout' && Array.isArray(asset?.props) ? asset.props : []),
    ...(Array.isArray(asset?.dependencies) ? asset.dependencies : []),
    ...(Array.isArray(asset?.references) ? asset.references : []),
    ...(Array.isArray(asset?.reference_ids) ? asset.reference_ids : []),
    ...(Array.isArray(asset?.referenceIds) ? asset.referenceIds : []),
  ]
  const seen = new Set()
  return values.flatMap((value) => {
    const id = String(value?.id || value || '').trim()
    const key = id.toLowerCase()
    if (!id || key === String(asset?.id || '').toLowerCase() || seen.has(key)) return []
    seen.add(key)
    return [id]
  })
}

function layoutDependencies(asset) {
  const resolved = []
  const unresolved = []
  const excluded = []
  layoutDependencyIds(asset).forEach((id) => {
    const dependency = canonicalAssetsById.value.get(id) || canonicalAssetsById.value.get(id.toLowerCase())
    if (asset?.category === 'scene' && dependency?.category === 'role') excluded.push(dependency)
    else if (!dependency || dependency.category === 'audio' || dependency.category === 'layout') unresolved.push(id)
    else resolved.push(dependency)
  })
  return { resolved, unresolved, excluded }
}

function assetReferenceState(asset) {
  const { resolved, unresolved, excluded } = layoutDependencies(asset)
  const readyItems = resolved.filter(item => Boolean(assetUrl(item)))
  return {
    items: resolved,
    readyItems,
    unresolved,
    excluded,
    ready: readyItems.length,
    total: resolved.length + unresolved.length,
  }
}

function referenceEditPrompt(asset, dependencies, sourcePrompt) {
  const imageMap = dependencies.map((dependency, index) => `图${index + 1}=${dependency.name || dependency.id}`).join('，')
  const targetPrompt = asset.category === 'role'
    ? buildRoleReferencePrompt(sourcePrompt, getProjectStylePrefix(activeVideoProject.value || { style: DEFAULT_PROJECT_STYLE }), asset.useDefaultRoleLayout !== false)
    : sourcePrompt
  return [
    `参考图对应关系（严格按上传顺序）：${imageMap}。`,
    '请使用以上全部参考图片进行图片编辑生成，严格保持各图主体的身份、造型、身体比例和关键道具外形一致；不要重新设计主体。',
    targetPrompt,
  ].filter(Boolean).join('\n')
}

async function imageEditDataUrl(asset) {
  const media = assetUrl(asset)
  if (media.startsWith('data:')) return media
  const api = window.pywebview?.api
  if (!api?.prepare_generation_asset || !api?.read_local_media_data_url) throw new Error('桌面客户端缺少参考图读取能力，请重启客户端后重试')
  const prepared = await api.prepare_generation_asset(asset, props.token)
  const encoded = await api.read_local_media_data_url(prepared?.path)
  const dataUrl = String(encoded?.url || encoded?.dataUrl || encoded?.data_url || '')
  if (!dataUrl.startsWith('data:')) throw new Error(`无法读取参考图片：${asset.name || asset.id}`)
  return dataUrl
}

function sceneAnchorOf(shot, references, isFirstShot = false) {
  if (!needsSceneAnchor(shot, isFirstShot)) return null
  const available = references.filter(asset => assetUrl(asset) && !isAudioAsset(asset))
  const selected = shot.continuityPlan?.sceneReferenceId
  return selected ? available.find(asset => asset.id === selected) || null : pickSceneReference(available)
}

function sceneAnchorAsset(shot) {
  const isFirstShot = storyboards.value[0]?.id === shot?.id
  return sceneAnchorOf(shot, sendAttachments(shot), isFirstShot)
}

function orderSceneAnchorFirst(references, anchor) {
  if (!anchor) return references
  const anchorId = String(anchor.id || '').toLowerCase()
  return [anchor, ...references.filter(asset => String(asset.id || '').toLowerCase() !== anchorId)]
}

function gazeHandoffBeatFor(shot) {
  if (shot?.inheritPrevTail !== false) return ''
  return gazeHandoffBeat(storyboards.value, shot)
}

function gazeHandoffFrameOf(shot) {
  if (shot?.gazeHandoff === false || !gazeHandoffBeatFor(shot)) return null
  const frame = shot.gazeHandoffFrame
  const index = storyboards.value.findIndex(item => item.id === shot.id)
  const prev = index > 0 ? storyboards.value[index - 1] : null
  const prevVideoId = String(prev?.resultFileId || prev?.fileId || prev?.mixedVideoFileId || prev?.originalVideoFileId || '')
  if (frame?.sourceVideoId && prevVideoId && frame.sourceVideoId !== prevVideoId) return null
  const url = storedProjectMediaUrl(frame, 'url', 'cover')
  return url ? { ...frame, url, cover: url } : null
}

function toggleGazeHandoff(shot) {
  shot.gazeHandoff = shot.gazeHandoff === false
  showWorkspaceToast(shot.gazeHandoff === false
    ? '⏸️ 已关闭接镜点视角，本镜按定场图直接开场'
    : '👁 已开启接镜点视角，生成时复用上一镜真实尾帧作为第0秒', 'info', 2200)
  scheduleProjectSave()
}

function seedanceReferenceDescriptors(shot, references) {
  let imageIndex = 0
  let audioIndex = 0
  const descriptors = []
  const sceneAnchorId = String(sceneAnchorOf(shot, references)?.id || '').toLowerCase()
  const hasGazeHandoff = references.some(asset => asset?.isGazeHandoff)

  for (const [sourceIndex, asset] of references.entries()) {
    if (isAudioAsset(asset)) {
      audioIndex += 1
      descriptors.push({
        asset,
        sourceIndex,
        type: 'audio_url',
        urlField: 'audio_url',
        role: 'reference_audio',
        marker: `[Audio ${audioIndex}]`,
      })
    } else {
      imageIndex += 1
      const isGazeHandoff = Boolean(asset.isGazeHandoff)
      const isSceneAnchor = !isGazeHandoff && Boolean(sceneAnchorId) && String(asset.id || '').toLowerCase() === sceneAnchorId
      const isContinuity = !isGazeHandoff && !isSceneAnchor && (Boolean(asset.isContinuityFrame) || (sourceIndex === 0 && shot.inheritPrevTail !== false && storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover')))
      // A gaze handoff owns the first frame; the scene plate stays as environment reference.
      const role = isGazeHandoff || (isSceneAnchor && !hasGazeHandoff) || isContinuity ? 'first_frame' : 'reference_image'
      descriptors.push({
        asset,
        sourceIndex,
        type: 'image_url',
        urlField: 'image_url',
        role,
        marker: `[Image ${imageIndex}]`,
        isContinuityFrame: isContinuity,
        isSceneAnchor,
        isGazeHandoff,
        isCutReference: Boolean(asset.isCutReference),
      })
    }
  }

  return descriptors
}

function promptForSeedance(prompt, descriptors) {
  const markers = new Map(descriptors.map(item => [String(item.asset?.id || '').toLowerCase(), item.marker]))
  const tokenPattern = /[{｛]{1,2}\s*([A-Za-z0-9][A-Za-z0-9_.:-]*)\s*[}｝]{1,2}/g
  return String(prompt || '').replace(tokenPattern, (token, id) => markers.get(String(id).toLowerCase()) || '')
}

function composedGenerationPrompt(shot) {
  if (isGeneral.value && !shot.continuityTailFrame?.fileId) return stripTransitionBlock(shot.prompt)
  const composed = promptWithTransition(storyboards.value, shot)
  if (shot.inheritPrevTail !== false) return composed
  // Cross-scene cuts: keep the direction, but let the shot body lead so the model
  // treats the transition notes as the ending plan rather than the request itself.
  const direction = transitionBlockOf(composed)
  return direction ? `${stripTransitionBlock(composed)}\n\n${direction}` : composed
}

function storyStateInstruction(shot) {
  const state = shot?.continuityState
  const facts = Array.isArray(state?.persistentFacts) ? state.persistentFacts.filter(fact => typeof fact === 'string' && fact.trim()) : Array.isArray(state?.facts) ? state.facts.filter(fact => typeof fact === 'string' && fact.trim()) : []
  if (!facts.length) return ''
  return `【剧情持续事实】${state.phase || '延续已发生的事实'}。以下事实在本镜开头、过程中和结尾持续有效；门扇、持物等临时状态按动作链变化。\n${facts.map(fact => `· ${fact}`).join('\n')}`
}

function actionChainInstruction(shot) {
  const chain = shot?.actionChain
  const rawActions = chain?.requiredActions || chain?.required_actions
  const actions = Array.isArray(rawActions) ? rawActions.filter(x => typeof x === 'string' && x.trim()) : []
  if (!actions.length) return ''
  const rawFacts = chain?.persistentFacts || chain?.persistent_facts
  const facts = Array.isArray(rawFacts) ? rawFacts.filter(x => typeof x === 'string' && x.trim()) : []
  return `【本镜必须拍出的动作链】第0秒：${chain.start || '按起始图' }。按画面时间顺序完整呈现：${actions.map((a, i) => `${i + 1}. ${a}`).join('；')}。镜尾：${chain.end || '完成上述动作'}。起始图应处在动作开始前或起势状态，关键过程尚未完成，不用已完成动作的画面代替过程。${facts.length ? `持续事实：${facts.join('；')}。` : ''}`
}

function strictContinuityPrompt(shot, descriptors) {
  if (isGeneral.value && !(shot.inheritPrevTail !== false && shot.continuityTailFrame?.fileId)) {
    const text = promptForSeedance(stripTransitionBlock(shot.prompt), descriptors)
    return `【通用视频镜头】生成本段${Number(shot.duration || 5)}秒画面，按正文的信息顺序、构图与节奏表现。产品、图示、录屏或实拍的表达服从本段要求。素材引用只绑定被选中的图片；旁白和字幕只使用正文明确提供的内容。\n${text}`
  }
  const actorHandoff = roleHandoffPlan(storyboards.value, shot)
  const chaseText = `${shot.title || ''} ${stripTransitionBlock(shot.prompt)}`
  // "步行追赶" reads as an idle walk to the model and kills the chase; keep
  // deliberately slow pursuits (缓步/踱步) untouched.
  const chase = /追赶|追兵|追逐|追捕|逃命|奔逃|逃跑|拔腿/.test(chaseText)
    && !/缓步|慢步|踱步|不紧不慢|闲庭信步/.test(chaseText)
  let generationPrompt = composedGenerationPrompt(shot)
  if (chase) generationPrompt = generationPrompt.replace(/步行追赶|徒步追赶|步行追来|徒步追来/g, '全速奔跑追赶')
  const imageDescriptors = descriptors.filter(item => item.type === 'image_url')
  const cutReference = imageDescriptors.find(item => item.isCutReference)
  const gazeHandoff = imageDescriptors.find(item => item.isGazeHandoff)
  const sceneAnchor = imageDescriptors.find(item => item.isSceneAnchor)
  const pinnedHandoff = Boolean(gazeHandoff) && isMuseShot(shot)
  const mapped = promptForSeedance(generationPrompt, descriptors)
    .split('\n')
    .filter(line => !/^\s*接线单[：:]/.test(line))
    .filter(line => !(pinnedHandoff && /^\s*一致性引用[：:]/.test(line)))
    .join('\n').trim()
  const referenceMap = imageDescriptors.map(item => {
    const name = item.asset.name || item.asset.id
    if (item.isCutReference) return `${item.marker}=上一镜方位参考【${name}】`
    if (item.isGazeHandoff) return `${item.marker}=上一镜真实尾帧【${name}】（第0秒动作起始帧）`
    if (item.isContinuityFrame) return `${item.marker}=上一镜真实尾帧【${name}】（第0秒动作承接点）`
    if (item.isSceneAnchor) return `${item.marker}=场景环境基准【${name}】`
    const cat = String(item.asset.category || item.asset.type || '').toLowerCase()
    if (cat === 'role' || cat === 'character' || cat === 'actor') {
      const desc = item.asset.appearance || item.asset.prompt || ''
      return `${item.marker}=出场角色【${name}】（人物面貌长相、发型、体态与服装严格以此图为准${desc ? `；外观：${desc.slice(0, 50)}` : ''}）`
    }
    if (cat === 'scene' || cat === 'environment' || cat === 'env') {
      const desc = item.asset.environment || item.asset.prompt || ''
      return `${item.marker}=场景环境【${name}】（背景建筑与环境风貌严格以此图为准${desc ? `；环境特征：${desc.slice(0, 50)}` : ''}）`
    }
    if (cat === 'prop' || cat === 'item' || cat === 'object') {
      return `${item.marker}=关键道具【${name}】（道具外形细节参考）`
    }
    return `${item.marker}=${name}`
  }).join('；\n')
  const scope = `【当前单镜】仅生成当前分镜一个独立的${Number(shot.duration || 5)}秒视频，不拼接旧镜头、不输出合集。${referenceMap ? `图片对应关系：${referenceMap}。人物设定图仅用于身份与服装，不把三视图或拼图照搬进视频。` : ''}`
  // Muse treats extra pictures as mood references; a single handoff picture plus an
  // explicit frame-0 lock is what makes its in-scene continuations line up.
  const pinnedHandoffRule = pinnedHandoff
    ? '【最高优先级·严格首帧锁定】第一张图就是本视频第0秒的精确画面，不是风格参考图：第0秒必须同构图、同景别、同机位、同人物姿态与朝向、同服装与道具、同背景与光线，禁止换角度、禁止重新设计门口、禁止空镜开场；从第0秒起只执行本镜正文规定的动作，不自行追加追赶、出门或切换场景；推进镜头按正文执行，人物身份与服装按正文描述保持一致。'
    : ''
  // Muse sometimes narrates the whole scene instead of one shot; state the shape
  // of the clip as direction so it does not recap what happened before the cut.
  const shotScopeRule = '【单镜连续】本片是一个连续长镜头：从第0秒直接进入正文动作，事件按时间顺序连续发生到结尾；机位与运镜严格按本镜正文执行，全片保持在同一场景与同一条动作线上。'
  const handoffRule = gazeHandoff ? [
    `【接镜点·视线交接】${gazeHandoff.marker} 是上一镜的真实最后一帧，也是本视频第0秒的画面基准。第0秒必须复现该图：同一站位、人物朝向、视线方向与整体构图；随后按正文的运镜执行：正文要求越过人物视线拍向门外/远处时，在0.4~0.8秒内完成推进，人物可留在前景或随运镜出画，不把接镜点停成空镜；正文未要求推进时，保持原机位执行本镜动作。不得从侧面另起构图、不得跳到无关地点、不得重新设计入口。`,
    sceneAnchor ? `接镜点之后的环境（建筑、地形、光照、影调）以 ${sceneAnchor.marker} 定场图为准，人物身份服装以人物设定图为准。` : '',
  ].filter(Boolean).join('\n') : ''
  // The model otherwise treats multiple running people as a crowd walking in from
  // side lanes, so the chase axis has to be stated explicitly.
  const chaseRule = chase && !actorHandoff
    ? '【追逐方向锁定】本镜是连贯追逐：被追者沿本段既定逃跑方向持续奔跑（朝既定目标方向或画面纵深），不得左右改道或掉头；追赶者只从被追者身后同一条路线追来并持续逼近；所有追赶者从同一后方进入画面，禁止从左右岔路/侧巷分头包抄，禁止与被追者横向交错，禁止双方迎面跑。追赶者与被追者都保持奔跑速度，不得改为步行、停下张望或原地喊话（喊话不打断奔跑）。被追者每2~3秒回头确认一次追兵位置，回头不超过0.5秒且脚下不停。'
    : ''
  const sceneAnchorRule = sceneAnchor && !gazeHandoff ? [
    `【新场景定场锚】${sceneAnchor.marker} 是本镜所在场景的定场图，也是本视频第0秒的画面基准。第0秒必须直接落在该图的空间结构、建筑与地形布局、光照时段、色彩影调上：不延续、不重放上一镜的环境，不另造一套村落/街景/室内布局。`,
    '本镜人物按人物设定图的身份、发型与服装出现在这个环境里（可站在前景或中景），背景必须与该定场图同源；景别与运镜按正文执行，不要照搬定场图的空镜构图。全片美术风格与渲染质感以该定场图为准，不切换风格。',
  ].join('\n') : ''
  const composedStartRule = pinSceneStart(shot) ? '【已核对的镜头起始图】第一张图已包含本镜人物、道具与原场景布局，是本镜第0秒的精确画面。保持图中门窗、家具、照片、人物数量、衣服和持物，从已有姿态演下去；不重新安排人物或重建房间。这是本镜的起始图，不是上一镜尾帧；与前镜的关系是剪辑切镜。' : ''
  const cutNote = shot.inheritPrevTail === false
    ? (shot.continuityPlan?.kind === 'scene-start'
      ? '【起始镜】从本镜指定环境和人物开始，不承接不存在的上一镜，不添加额外片头或回放。'
      : shot.continuityPlan?.kind === 'camera-cut'
      ? '【同场景换机位】直接从本镜指定起始图开始，仍在上一镜的同一地点与同一时段；只切换拍摄机位，不重建空间，不重放前镜画面。'
      : gazeHandoff
      ? '【新场景转场】本镜从上一镜结尾的门口视线剪入新场景；接镜点之后才交代本场全貌，不重放上一镜整段画面。'
      : '【新场景转场】直接从本镜指定环境与人物开始；与前镜通过剪辑衔接，不重放前镜画面。')
    : ''
  const cutReferenceRule = cutReference ? `【视线切镜】${cutReference.marker} 只锁定上一镜的门窗、门框、贴纸、光色与朝外视线；不复现上一镜人物或构图，不从室内推镜。第0秒已经在该出入口外侧，按同一出入口朝外看见本镜正文指定的人物与背景；空间路线与门框方位相容。场景图提供外部布局，上一镜门口参考只决定入口地标；天气服从本镜明确的时空约束。` : ''
  // A structured cut already has one authored shooting prompt covering its action
  // chain and persistent facts. Repeating the planning metadata here encourages
  // duplicated props/text. Keep the established tail/handoff path unchanged.
  const cutActions = shot.actionChain?.requiredActions || shot.actionChain?.required_actions
  const structuredCut = shot.inheritPrevTail === false && !gazeHandoff && !cutReference && !actorHandoff && Array.isArray(cutActions) && cutActions.length
  const structuredStartRule = pinSceneStart(shot)
    ? '【起始参考】第一张图为本镜入场起势，保持图中人物身份、人数、空间与道具关系，沿正文连续演下去。'
    : sceneAnchorRule
  const doorwayRule = doorwayMovementInstruction(storyboards.value, shot)
  const base = structuredCut
    ? [scope, structuredStartRule, cutNote, doorwayRule, mapped].filter(Boolean).join('\n')
    : [storyStateInstruction(shot), actionChainInstruction(shot), roleHandoffInstruction(actorHandoff, descriptors), doorwayRule, environmentInstruction(storyboards.value, shot), cutReferenceRule, pinnedHandoffRule, scope, shotScopeRule, handoffRule, chaseRule, composedStartRule || sceneAnchorRule, cutNote, mapped].filter(Boolean).join('\n')
  const exact = resolvedContinuityMode(shot) === 'exact'
    && shot.inheritPrevTail !== false
    && storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover')
  if (exact) {
    return [
      '【最高优先级·严格首帧动作续接】输入的第一张图片就是本视频第0秒的精确画面，不是风格参考图。第0秒必须复现该图：保持同一构图、景别、机位、人物姿态、朝向、服装、道具位置和环境光线；禁止空镜开场、禁止重新构图、禁止先切换景别、禁止人物瞬移。开场前1秒只从该姿态连续启动动作。正文若出现中景、全景、特写、推拉摇移等机位要求，一律延后到1秒以后渐进执行，不得改变第0秒画面。新增HUD、光效或物体必须叠加在原构图中，不能先重建场景。',
      base,
      actorHandoff ? (actorHandoff.phase === 'scripted' ? '【人物复核】各人只执行本镜正文分配的动作，保持不同身份和服装，不套用其他剧情的进场路线。' : '【人物复核】只由正文指定的角色完成进场动作，其他人物停在原位、保持各自外貌和服装，不新增人物。') : '',
      '【首帧锁定复核】以上正文不得覆盖首帧约束：视频第一帧必须与输入图片同构图、同人物、同姿态、同道具、同背景；先接住上一镜动作，再渐进执行新镜头内容。',
    ].filter(Boolean).join('\n')
  }

  const isTransition = resolvedContinuityMode(shot) === 'transition'
    && shot.inheritPrevTail !== false
    && storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover')
  if (isTransition) {
    return [
      '【最高优先级·尾帧转场过渡（两者兼得）】第一张图片为上一镜真实尾帧，全片第0秒必须从上一镜画面起势开场，承接上一镜的光影与氛围；随后镜头自然运镜推进、后拉、环绕或光影融变，平滑过渡并展开本镜的新场景、新人物与新动作。两镜时空与光影有机融合，过渡流畅自然，严禁突兀硬切或黑屏断档。后续各图为本镜人物与场景资产参考，请在转场展开后准确呈现对应形象细节。',
      base,
    ].filter(Boolean).join('\n')
  }

  return base
}

function orderSeedanceContent(shot, mediaContent, textContent) {
  return shot.mode === 'firstLast' ? [textContent, ...mediaContent] : [...mediaContent, textContent]
}

function originalDoubaoSendPreview(shot) {
  const allReferences = sendAttachments(shot).filter(asset => assetUrl(asset))
  const references = allReferences.filter(asset => !isAudioAsset(asset))
  const omittedAudio = allReferences.filter(asset => isAudioAsset(asset))
  const attachments = references.map((asset, index) => {
    const name = `${isAudioAsset(asset) ? '文件' : '图'}${index + 1}`
    return `${name} ← ${asset.name || asset.id || '未命名素材'}`
  })
  return [
    `【发送方式】${generationEngineLabel(shot)} 桌面会话`,
    `【附件】${attachments.length ? `\n${attachments.join('\n')}` : '无'}`,
    `【过滤规则】音频附件不发送${omittedAudio.length ? `（已过滤 ${omittedAudio.length} 个）` : ''}`,
    `【实际文本】\n${promptForOriginalDoubao(promptWithTransition(storyboards.value, shot), references, omittedAudio).trim()}`,
    `【生成设置】\n模型：${props.videoModel || '默认'}\n比例：${shot.ratio === '智能' ? '16:9' : shot.ratio}\n时长：${shot.duration}s\n清晰度：${shot.quality}\n声音：${shot.sound ? '开启' : '关闭'}`,
  ].join('\n\n')
}

function seedancePreviewReferences(shot) {
  const continuity = shot.continuityTailFrame
  const continuityUrl = storedProjectMediaUrl(continuity, 'url', 'cover')
  const plan = roleHandoffPlan(storyboards.value, shot)
  const rawResolved = sendAttachments(shot).filter(asset => assetUrl(asset) && !isAudioAsset(asset))
  if (isMuseShot(shot) && plan && continuityUrl) {
    const tail = { id: continuity.fileId || 'continuity-first-frame', name: '上一镜真实尾帧·观察者原位', cover: continuityUrl, fileId: continuity.fileId, mediaType: 'image', isContinuityFrame: true }
    return handoffReferences(plan, rawResolved, tail)
  }
  if (shot.inheritPrevTail !== false && continuityUrl) {
    const tailAsset = {
      id: continuity.fileId || 'continuity-first-frame',
      name: `第${Number(continuity.sourceShotIndex ?? 0) + 1}镜真实尾帧`,
      cover: continuityUrl,
      fileId: continuity.fileId,
      mediaType: 'image',
      isContinuityFrame: true,
    }
    const validRefs = rawResolved.filter(asset => asset.id !== tailAsset.id)
    const roleRefs = validRefs.filter(a => {
      const cat = String(a.category || a.type || '').toLowerCase()
      return cat === 'role' || cat === 'character' || cat === 'actor'
    })
    const sceneRefs = validRefs.filter(a => {
      const cat = String(a.category || a.type || '').toLowerCase()
      return cat === 'scene' || cat === 'environment' || cat === 'env'
    })
    const propRefs = validRefs.filter(a => {
      const cat = String(a.category || a.type || '').toLowerCase()
      return cat === 'prop' || cat === 'item' || cat === 'object'
    })
    const otherRefs = validRefs.filter(a => !roleRefs.includes(a) && !sceneRefs.includes(a) && !propRefs.includes(a))
    return [
      tailAsset,
      ...roleRefs.slice(0, 2),
      ...sceneRefs.slice(0, 1),
      ...propRefs.slice(0, 1),
      ...otherRefs.slice(0, 1),
    ].slice(0, 5)
  }
  const references = rawResolved
  const gaze = gazeHandoffFrameOf(shot)
  if (gaze) {
    const handoff = {
      id: gaze.fileId || 'gaze-handoff',
      name: `第${Number(gaze.sourceShotIndex ?? 0) + 1}镜接镜点视角`,
      cover: gaze.cover,
      mediaType: 'image',
      isGazeHandoff: true,
    }
    if (isMuseShot(shot)) return [handoff]
    return [
      handoff,
      ...orderSceneAnchorFirst(references, sceneAnchorOf(shot, references)),
    ]
  }
  return sceneCutReferences(shot, references, sceneAnchorOf(shot, references))
}

function seedanceSendPreview(shot) {
  const references = seedancePreviewReferences(shot)
  const descriptors = seedanceReferenceDescriptors(shot, references)
  const mediaContent = descriptors.map((item) => ({
    type: item.type,
    [item.urlField]: { url: `data:${item.type === 'audio_url' ? 'audio' : 'image'}/*;base64,<${item.asset.name || item.asset.id || '本地素材'} 内容已省略>` },
    role: item.role,
  }))
  const textContent = { type: 'text', text: strictContinuityPrompt(shot, descriptors) }
  return JSON.stringify({
    model: shot.seedanceModel || defaultSeedanceModel.value || '',
    content: orderSeedanceContent(shot, mediaContent, textContent),
    continuity_mode: resolvedContinuityMode(shot),
    role_handoff: roleHandoffPlan(storyboards.value, shot),
    first_frame_pin: pinSceneStart(shot) || references.some(asset => asset.isGazeHandoff),
    continuity_state: shot.continuityState || null,
    action_chain: shot.actionChain || null,
    generate_audio: Boolean(shot.sound),
    ratio: shot.ratio === '智能' ? '16:9' : shot.ratio,
    resolution: String(shot.quality || defaultVideoSettings.quality).toLowerCase(),
    duration: Math.min(10, Math.max(3, Number(shot.duration || 5))),
    return_last_frame: true,
    watermark: false,
  }, null, 2)
}

function sendPreviewText(shot) {
  return shot.generationEngine === 'seedance' ? seedanceSendPreview(shot) : originalDoubaoSendPreview(shot)
}

function sendPreviewSummary(shot) {
  const references = sendAttachments(shot).filter(asset => assetUrl(asset))
  if (shot.generationEngine === 'seedance') {
    const images = seedancePreviewReferences(shot)
    const strict = isMuseShot(shot) && resolvedContinuityMode(shot) === 'exact' && images.length === 1 && images[0].isContinuityFrame
    if (roleHandoffPlan(storyboards.value, shot)) return `${images.length} 张图片 · 真实尾帧与人物身份参考；动作按本镜安排` 
    if (resolvedContinuityMode(shot) === 'transition') return `${images.length} 张图片 · 尾帧转场过渡（两者兼得：尾帧起势 · 融变到新景）`
    if (strict) return '1 张真实尾帧 · Muse 严格动作续接'
    if (isMuseShot(shot) && images.length === 1 && images[0].isGazeHandoff) return '1 张接镜点视角 · Muse 锁第0秒'
    if (pinSceneStart(shot)) return '1 张已核对起始图 · 包含场景、人物与道具；按剪辑衔接'
    return `${images.length} 张图片${images[0]?.isGazeHandoff ? ' · 含接镜点视角' : ''} · 音频不上传，需另行合入成片`
  }
  const imageCount = references.filter(asset => !isAudioAsset(asset)).length
  const audioCount = references.length - imageCount
  return `${imageCount} 个图片附件${audioCount ? ` · 已过滤 ${audioCount} 个音频` : ''}`
}

function referenceCardTooltip(asset) {
  const resolved = resolveAssetReference(asset)
  const cat = String(resolved?.category || resolved?.type || '').toLowerCase()
  let catLabel = '资产'
  if (cat === 'role' || cat === 'character') catLabel = '人物'
  else if (cat === 'scene' || cat === 'environment') catLabel = '场景'
  else if (cat === 'prop' || cat === 'item') catLabel = '道具'
  else if (cat === 'audio') catLabel = '音频'
  const status = assetUrl(resolved) ? '已就绪' : '待生成图片'
  return `【${catLabel}】${resolved?.name || asset?.name || '素材'}（${status}）`
}

function shotReferenceManifestText(shot) {
  const preview = seedancePreviewReferences(shot)
  if (preview.length > 0) {
    const details = preview.map((asset, idx) => {
      const marker = `图${idx + 1}`
      const name = asset.name || asset.id
      let tag = '参考图'
      if (asset.isContinuityFrame) tag = '上一镜真实尾帧'
      else if (asset.isGazeHandoff) tag = '接镜点视角'
      else {
        const cat = String(asset.category || asset.type || '').toLowerCase()
        if (cat === 'role' || cat === 'character') tag = '人物'
        else if (cat === 'scene' || cat === 'environment') tag = '场景'
        else if (cat === 'prop' || cat === 'item') tag = '道具'
      }
      return `${marker}:${name}【${tag}】`
    }).join('、')
    return `实际图片输入：已智能打包 ${preview.length} 张关键图发送至上游模型（${details}）。上游将严格结合尾帧起点与各角色/场景/道具资产图进行连续生成。`
  }
  const currentShotIdx = storyboards.value.findIndex(s => s.id === shot.id)
  const hints = []
  if (currentShotIdx === 0) {
    hints.push('首镜无需上一镜尾帧')
  } else {
    const prevShot = storyboards.value[currentShotIdx - 1]
    if (!prevShot?.resultUrl && !prevShot?.resultFileId) {
      hints.push('上一镜生成视频后将自动提取真实尾帧')
    }
  }
  const unready = (shot.references || []).filter(a => !isAudioAsset(a) && !assetUrl(a)).map(a => a.name || a.id)
  if (unready.length > 0) {
    hints.push(`关联资产【${unready.join('、')}】尚未生图或上传`)
  } else {
    hints.push('左侧资产生成/上传图片后将自动关联打包')
  }
  return `实际图片输入：暂无图片（${hints.join('；')}）。只要资产图或前镜尾帧就绪，系统均会自动完整打包发送至上游模型！`
}

async function toggleSendPreview(shot) {
  if (shot.sendPreview) {
    shot.sendPreview = false
    return
  }
  shot.sendPreview = true
  if (shot.generationEngine !== 'seedance' || shot.gazeHandoff === false) return
  if (!gazeHandoffBeatFor(shot) || gazeHandoffFrameOf(shot) || shot.extractingLastFrame) return
  const index = storyboards.value.findIndex(item => item.id === shot.id)
  const prev = index > 0 ? storyboards.value[index - 1] : null
  const prevHasVideo = Boolean(prev && (prev.resultUrl || prev.resultFileId || prev.mixedVideoFileId || prev.originalVideoFileId))
  if (!prevHasVideo) return
  await extractLastFrameForShot(prev, index - 1, shot, { activate: false, silent: true, store: 'gazeHandoff' })
}

async function uploadLocalReference(shot) {
  if (!window.pywebview?.api) {
    shot.generationError = '请从桌面客户端选择本地图片'
    return
  }
  try {
    const selected = await window.pywebview.api.select_local_reference_file()
    if (!selected) return
    const mediaType = String(selected.mediaType || selected.type || '').toLowerCase() === 'audio' ? 'audio' : 'image'
    const imageIndex = shot.references.filter(asset => !isAudioAsset(asset)).length + 1
    const audioIndex = shot.references.filter(isAudioAsset).length + 1
    const id = `LOCAL-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const asset = {
      id,
      name: mediaType === 'audio' ? `音${audioIndex}` : `图${imageIndex}`,
      category: mediaType === 'audio' ? 'audio' : 'local',
      type: mediaType,
      path: selected.path,
      cover: selected.preview || '',
      uploading: true,
      generationError: '',
    }
    shot.references.push(asset)
    shot.referenceLabels[id] = asset.name
    shot.referencesExpanded = true
    try {
      // 加 60 秒超时兜底：防止 Python 端卡死导致 uploading 永远为 true
      const uploadPromise = window.pywebview.api.upload_local_reference_file(props.token, selected.path, {
        imageName: `图${imageIndex}`,
        audioName: `音${audioIndex}`,
        description: '视频生成任务本地上传参考素材',
        tags: 'video-reference',
        boundProjectIds: activeLinkedProjectId() ? [activeLinkedProjectId()] : [],
      })
      const timeoutPromise = new Promise((_, reject) =>
        window.setTimeout(() => reject(new Error('上传超时（60秒），请检查网络或后端服务')), 60000)
      )
      const uploaded = await Promise.race([uploadPromise, timeoutPromise])
      const uploadedId = String(uploaded?.id || id)
      const fileId = String(uploaded?.coverId || uploaded?.fileId || '')
      if (uploadedId !== id) {
        delete shot.referenceLabels[id]
        asset.id = uploadedId
        shot.referenceLabels[uploadedId] = asset.name
      }
      asset.coverId = fileId
      asset.fileId = fileId
      asset.generationError = ''
    } catch (uploadError) {
      asset.generationError = cleanError(uploadError)
      shot.generationError = `“${asset.name}”上传失败：${asset.generationError}`
    } finally {
      // finally 确保 uploading 必定清除，无论成功/失败/超时
      asset.uploading = false
    }
  } catch (err) {
    shot.generationError = cleanError(err)
  }
}

function removeReference(shot, assetId) {
  shot.references = shot.references.filter(item => String(item.id) !== String(assetId))
  delete shot.referenceLabels[String(assetId)]
  const lines = shot.prompt.split('\n')
  const lineIndex = lines.findIndex(line => /^一致性引用[：:]/.test(line.trim()))
  if (lineIndex >= 0) {
    const references = lines[lineIndex]
      .replace(/^一致性引用[：:]\s*/, '')
      .split(/[，,]/)
      .map(item => item.trim())
      .filter(item => item && !item.includes(`{{${assetId}}}`))
    if (references.length) lines[lineIndex] = `一致性引用：${references.join('，')}`
    else lines.splice(lineIndex, 1)
    shot.prompt = lines.join('\n').replace(/^\n+/, '')
  }
}

function stackSlot(index, total) {
  return Math.max(0, Math.min(2, index + 3 - total))
}

function modeLabel(shot) {
  return generationModes.find(item => item.value === shot.mode)?.label || '参考生成'
}

function toggleModeMenu(shot) {
  storyboards.value.forEach(item => { if (item.id !== shot.id) { item.modeOpen = false; item.settingsOpen = false } })
  shot.modeOpen = !shot.modeOpen
  shot.settingsOpen = false
}

async function toggleSettings(shot, event) {
  storyboards.value.forEach(item => { if (item.id !== shot.id) { item.modeOpen = false; item.settingsOpen = false } })
  shot.settingsOpen = !shot.settingsOpen
  shot.modeOpen = false
  if (!shot.settingsOpen) {
    shot.settingsPopoverStyle = null
    return
  }
  const trigger = event?.currentTarget
  await nextTick()
  const popover = document.querySelector(`[data-settings-shot="${CSS.escape(String(shot.id))}"]`)
  if (!trigger || !popover) return
  const margin = 12
  const triggerRect = trigger.getBoundingClientRect()
  const contentRect = trigger.closest('.shot-content')?.getBoundingClientRect() || triggerRect
  const width = Math.max(280, Math.min(520, contentRect.width - 24, window.innerWidth - margin * 2))
  const spaceAbove = triggerRect.top - margin
  const spaceBelow = window.innerHeight - triggerRect.bottom - margin
  const openAbove = spaceAbove >= Math.min(320, popover.scrollHeight) || spaceAbove >= spaceBelow
  const availableHeight = Math.max(160, Math.min(420, (openAbove ? spaceAbove : spaceBelow) - 8))
  const renderedHeight = Math.min(popover.scrollHeight, availableHeight)
  const left = Math.max(margin, Math.min(contentRect.left + 12, window.innerWidth - width - margin))
  const top = openAbove
    ? Math.max(margin, triggerRect.top - renderedHeight - 8)
    : Math.min(window.innerHeight - renderedHeight - margin, triggerRect.bottom + 8)
  shot.settingsPopoverStyle = {
    position: 'fixed',
    top: `${Math.round(top)}px`,
    bottom: 'auto',
    left: `${Math.round(left)}px`,
    width: `${Math.round(width)}px`,
    maxHeight: `${Math.round(availableHeight)}px`,
  }
}

function selectMode(shot, mode) {
  shot.mode = mode
  shot.modeOpen = false
}

function closeAllPopovers() {
  assetActionsOpen.value = false
  assetActionsPinned.value = false
  storyboards.value.forEach(shot => {
    shot.modeOpen = false
    shot.settingsOpen = false
  })
}

function handlePopoverKeydown(event) {
  if (event.key === 'Escape') {
    closeAllPopovers()
    storyboards.value.forEach(shot => {
      shot.expanded = false
      shot.sendPreview = false
      shot.playerExpanded = false
    })
    if (importDialogOpen.value) closeImportDialog()
    if (assetDetailOpen.value) closeAssetDetail()
  }
}

function toggleShotExpanded(shot) {
  closeAllPopovers()
  storyboards.value.forEach(item => {
    if (item.id !== shot.id) {
      item.expanded = false
      item.sendPreview = false
    }
  })
  shot.expanded = !shot.expanded
  if (!shot.expanded) shot.sendPreview = false
}

async function togglePlayerExpanded(shot) {
  const player = document.querySelector(`[data-result-player="${shot.id}"]`)
  if (!player) return
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else if (player.requestFullscreen) await player.requestFullscreen()
  } catch (err) {
    error.value = `无法切换全屏播放：${cleanError(err)}`
  }
}

function resultVideoElement(shot) {
  return document.querySelector(`[data-result-video="${shot.id}"]`)
}

async function toggleResultVideo(shot) {
  const video = resultVideoElement(shot)
  if (!video) return
  if (video.paused) {
    try { await video.play() } catch (err) { error.value = `无法播放视频：${cleanError(err)}` }
  } else video.pause()
}

function syncResultVideoMetadata(shot, event) {
  shot.videoDuration = Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0
}

function syncResultVideoTime(shot, event) {
  shot.videoCurrent = Number.isFinite(event.currentTarget.currentTime) ? event.currentTarget.currentTime : 0
}

function seekResultVideo(shot, event) {
  const video = resultVideoElement(shot)
  if (!video) return
  video.currentTime = Number(event.currentTarget.value) || 0
  shot.videoCurrent = video.currentTime
}

function toggleResultVideoMute(shot) {
  const video = resultVideoElement(shot)
  if (!video) return
  video.muted = !video.muted
  shot.videoMuted = video.muted
}

function syncPlayerFullscreenState() {
  const activePlayerId = document.fullscreenElement?.dataset?.resultPlayer || ''
  storyboards.value.forEach(shot => {
    shot.playerExpanded = shot.id === activePlayerId
  })
}

async function adoptRejectedCandidate(shot) {
  const candidate = rejectedCandidate(shot)
  const candidateId = candidate?.fileId || shot.rejectedResultFileId
  if (!candidateId) return
  shot.resultFileId = candidateId
  shot.resultUrl = fileDownloadUrl(candidateId)
  shot.rejectedResultFileId = ''
  shot.rejectedResultUrl = ''
  shot.rejectedResultTaskId = ''
  shot.rejectedContinuityReview = null
  shot.showHistoricalResult = false
  shot.continuityReview = { status: 'manual_passed', fileId: candidateId, checkedAt: Date.now(), summary: '人工核验通过并采用' }
  finishGenerationAttempt(shot, 'succeeded')
  shot.generationProvenance = { sourceTask: shot.lastGenerationAttempt?.taskId || '', fileId: candidateId, submittedAt: shot.lastGenerationAttempt?.submittedAt }
  shot.status = 'succeeded'
  shot.statusText = '已人工核验并采用为成片'
  shot.generationError = ''
  const completedShotIndex = storyboards.value.findIndex(item => item.id === shot.id)
  const nextShot = storyboards.value[completedShotIndex + 1]
  if (nextShot?.inheritPrevTail !== false) nextShot.continuityOutdated = true
  showWorkspaceToast('✅ 已人工核验并成功采用该候选视频为成片！', 'success', 3500)
  await saveActiveVideoProject()
}

async function replaceShotVideo(shot) {
  if (shot.replacingVideo || shotRunning(shot)) return
  if (!window.pywebview?.api) {
    shot.videoReplaceError = '请从桌面客户端选择本地视频'
    return
  }
  shot.replacingVideo = true
  shot.videoReplaceError = ''
  try {
    const selected = await window.pywebview.api.select_local_video_file()
    if (!selected?.path) return
    const uploaded = await window.pywebview.api.upload_local_file(props.token, selected.path)
    const fileId = String(uploaded?.id || '')
    if (!fileId) throw new Error('视频入库没有返回文件 ID')

    stopPolling(shot.id)
    shot.taskId = ''
    shot.resultPath = ''
    shot.resultFileId = fileId
    shot.resultUrl = fileDownloadUrl(fileId)
    shot.resultWatermarked = false
    shot.status = 'succeeded'
    shot.statusText = `已使用本地视频替换：${selected.name || '本地视频'}`
    shot.progress = 100
    shot.generationError = ''
    shot.videoPlaying = false
    shot.videoCurrent = 0
    shot.videoDuration = 0
    await nextTick()
    await saveActiveVideoProject()
  } catch (err) {
    shot.videoReplaceError = cleanError(err)
  } finally {
    shot.replacingVideo = false
  }
}

function addStoryboard() {
  const shot = createStoryboard(storyboards.value.length + 1)
  storyboards.value.push(shot)
  activeShotId.value = shot.id
  nextTick(() => jumpToStoryboardAnchor(shot))
}

function removeStoryboard(shotId) {
  if (storyboards.value.length === 1) return
  stopPolling(shotId)
  storyboards.value = storyboards.value.filter(item => item.id !== shotId)
  if (activeShotId.value === shotId) activeShotId.value = storyboards.value[0].id
  nextTick(scheduleVisibleStoryboardAnchorUpdate)
}

function shotRunning(shot) {
  const status = String(shot.status || '').toLowerCase()
  const activeStatuses = ['preparing', 'submitting', 'queued', 'pending', 'generating', 'processing', 'running', 'cancelling']
  return Boolean(activeStatuses.includes(status) || (shot.taskId && !['succeeded', 'failed', 'cancelled', 'canceled'].includes(status)))
}

function stopPolling(shotId) {
  const timer = pollTimers.get(shotId)
  if (timer) window.clearTimeout(timer)
  pollTimers.delete(shotId)
}

const shotRequests = new WeakMap()
async function cancelShot(shot) {
  if (!shot) return
  const request = shotRequests.get(shot)
  if (request) request.cancelled = true
  stopPolling(shot.id)

  // 1. 若当前已处于 cancelling 状态，用户再次点击“终止”，代表强行立即重置，绝不静默忽略！
  if (shot.status === 'cancelling') {
    finishGenerationAttempt(shot, 'cancelled')
    shot.status = 'cancelled'
    shot.taskId = ''
    shot.seedanceTaskId = ''
    shot.seedanceTaskCreatedAt = 0
    restoreVideoResult(shot)
    shot.statusText = '已强制终止当前分镜生成'
    shot.generationError = ''
    shot.progress = 0
    await saveActiveVideoProject()
    refreshTasks(String(activeVideoProject.value?.id || ''))
    showWorkspaceToast('已强制终止当前分镜，可重新生成', 'info', 3000)
    return
  }

  shot.status = 'cancelling'
  shot.statusText = '正在通知服务端终止，请稍等…'
  await saveActiveVideoProject()

  try {
    // 2. 绝不盲目 await request.pending！最多等待 1.2 秒尝试拿取刚提交成功的 taskId
    let taskId = String(shot.taskId || shot.seedanceTaskId || '')
    if (!taskId && request?.pending) {
      try {
        const fastResult = await Promise.race([
          request.pending,
          new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 1200))
        ])
        taskId = String(fastResult?.taskId || fastResult?.id || fastResult?.task_id || '')
      } catch (_) {
        // 请求尚未返回或在后台挂起；由于已设置 request.cancelled = true，返回后会被自动丢弃
      }
    }

    if (taskId && shot.generationEngine === 'seedance') {
      shot.taskId = taskId
      shot.seedanceTaskId = taskId
      try {
        await videoProjectRequest('POST', '/ai/video/cancel', { taskId, model: shot.seedanceModel || defaultSeedanceModel.value })
      } catch (cancelErr) {
        console.warn('服务端取消请求警告:', cancelErr)
      }
    } else if (taskId && window.pywebview?.api?.cancel_task) {
      await window.pywebview.api.cancel_task(taskId)
    }
  } catch (err) {
    console.warn('cancelShot error:', err)
  }

  // 3. 无论服务端网络状态如何，前端立刻完成终止释放，确保用户界面可用
  finishGenerationAttempt(shot, 'cancelled')
  shot.status = 'cancelled'
  shot.taskId = ''
  shot.seedanceTaskId = ''
  shot.seedanceTaskCreatedAt = 0
  restoreVideoResult(shot)
  shot.statusText = '服务端任务已终止'
  shot.generationError = ''
  shot.progress = 0
  await saveActiveVideoProject()
  refreshTasks(String(activeVideoProject.value?.id || ''))
  showWorkspaceToast('分镜生成已终止', 'info', 3000)
}

async function pollShot(shot) {
  try {
    const latest = await window.pywebview.api.get_task(shot.taskId)
    if (latest) {
      shot.status = latest.status || ''
      shot.statusText = latest.statusText || ''
      shot.progress = Number(latest.progress || 0)
      shot.accountId = String(latest.accountId || shot.accountId || '')
      shot.conversationId = String(latest.conversationId || shot.conversationId || '')
      shot.conversationUrl = String(latest.conversationUrl || shot.conversationUrl || '')
      shot.generationSubmittedAt = Number(latest.generationSubmittedAt || shot.generationSubmittedAt || 0)
      shot.requiresManualVerification = Boolean(latest.requiresManualVerification)
      if (latest.resultFileId) {
        shot.resultFileId = String(latest.resultFileId)
        shot.resultUrl = fileDownloadUrl(shot.resultFileId)
      } else {
        shot.resultUrl = latest.resultUrl || ''
      }
      shot.resultPath = latest.resultPath || ''
      shot.resultWatermarked = Boolean(latest.resultWatermarked)
      if (latest.status === 'failed') shot.generationError = latest.statusText || '生成失败'
    }
    if (latest && ['succeeded', 'failed', 'cancelled', 'canceled'].includes(latest.status)) {
      if (latest.status === 'succeeded' && shot.resultFileId) {
        shot.statusText = latest.statusText || (shot.resultWatermarked
          ? '无水印解析失败，已将有水印视频保存到当前任务'
          : '视频已生成并保存到当前任务')
        await saveActiveVideoProject()
      } else if (latest.status === 'succeeded' && shot.resultPath) {
        // 兜底：worker 已生成但未入库时，由前端补一次上传。
        // 后端 _apply_task_result 会随后把结果回写到业务数据。
        shot.statusText = '视频生成完成，正在上传入库'
        try {
          const uploaded = await window.pywebview.api.upload_local_file(props.token, shot.resultPath)
          shot.resultFileId = String(uploaded?.id || '')
          if (!shot.resultFileId) throw new Error('视频入库没有返回文件 ID')
          shot.resultUrl = fileDownloadUrl(shot.resultFileId)
          shot.statusText = '视频已生成并保存到当前任务'
          reconcileAllShotsAssetConsistency()
          await saveActiveVideoProject()
        } catch (uploadError) {
          shot.generationError = `视频已生成，但入库失败：${cleanError(uploadError)}`
        }
      }
      stopPolling(shot.id)
      refreshTasks(String(activeVideoProject.value?.id || ''))
      return
    }
    const timer = window.setTimeout(() => pollShot(shot), 700)
    pollTimers.set(shot.id, timer)
  } catch (err) {
    shot.generationError = cleanError(err)
    shot.status = 'failed'
    stopPolling(shot.id)
    await saveActiveVideoProject()
  }
}

function generationEngineLabel(shot) {
  const matched = seedanceModelOptions.value.find(option => option.value === String(shot.seedanceModel || ''))
  return matched?.label || (shot.seedanceModel ? String(shot.seedanceModel) : 'API 视频模型')
}

function settingsSummaryLabel(shot) {
  const model = generationEngineLabel(shot)
  const dur = shot.durationMode === 'smart' ? '智能时长' : `${shot.duration || 5}s`
  return `${model} · ${shot.ratio || '16:9'} · ${shot.quality || '720P'} · ${dur} · ${shot.sound ? '有声' : '静音'}`
}

function ensureStoryboardDefaults(shot) {
  shot.generationEngine = 'seedance'
  if (!shot.seedanceModel && defaultSeedanceModel.value) {
    shot.seedanceModel = defaultSeedanceModel.value
  }
  if (!shot.duration) shot.duration = 5
  if (!shot.count) shot.count = 1
  if (!shot.durationMode) shot.durationMode = 'seconds'
  if (!shot.ratio || shot.ratio === '自动' || shot.ratio === '智能') shot.ratio = '16:9'
  if (!shot.quality) shot.quality = '720P'
}

function isOriginalDoubaoEngine(shot) {
  return false
}

function applyDefaultVideoModelToAll(modelValue) {
  defaultSeedanceModel.value = String(modelValue || '')
  storyboards.value.forEach(shot => {
    shot.seedanceModel = defaultSeedanceModel.value
  })
}

function selectGenerationEngine(shot, engine) {
  shot.generationEngine = engine
  if (engine === 'seedance' && !shot.seedanceModel) {
    shot.seedanceModel = defaultSeedanceModel.value
  } else if (engine === 'dola') {
    if (![5, 10, '5', '10'].includes(shot.duration)) {
      shot.duration = Number(shot.duration || 10) <= 7 ? 5 : 10
    }
    if (shot.ratio === '自动' || shot.ratio === '智能') {
      shot.ratio = '16:9'
    }
    if (!shot.webModel || !shot.webModel.includes('Dreamina')) {
      shot.webModel = 'Dreamina Seedance 2.0 Fast'
    }
  } else if (engine === 'doubao' || engine === 'do') {
    if (Number(shot.duration || 0) < 4) shot.duration = 6
    if (!shot.webModel || shot.webModel.includes('Dreamina')) {
      shot.webModel = 'Seedance 2.0 Mini'
    }
  }
  ensureStoryboardDefaults(shot)
}

function allStoryboardsUseEngine(engine) {
  return Boolean(storyboards.value.length && storyboards.value.every(shot => shot.generationEngine === engine))
}

function canSwitchAllStoryboardEngines() {
  return !storyboards.value.some(shot => shotRunning(shot))
}

function setAllStoryboardEngines(engine) {
  if (!canSwitchAllStoryboardEngines()) return
  storyboards.value.forEach(shot => selectGenerationEngine(shot, engine))
}

async function verifyShotContinuity(shot) {
  const mode = resolvedContinuityMode(shot)
  if (mode === 'transition') {
    shot.continuityReview = {
      status: 'passed',
      fileId: shot.resultFileId,
      taskId: shot.taskId || shot.lastGenerationAttempt?.taskId || '',
      summary: '尾帧转场过渡（两者兼得）· 尾帧起势与新景转场已顺畅过渡放行',
      checkedAt: Date.now(),
    }
    return shot.continuityReview
  }
  const submittedSeed=shot.lastGenerationAttempt?.references?.find(r=>r.role==='first_frame')
  const seed = submittedSeed?.fileId ? submittedSeed : shot.continuityTailFrame
  if (!isMuseShot(shot)
    || mode !== 'exact'
    || shot.inheritPrevTail === false
    || !seed?.fileId
    || !(shot.resultFileId || shot.resultUrl)) {
    shot.continuityReview = null
    return null
  }
  try {
    const data = await videoProjectRequest('POST', '/video/extract-custom-frame', {
      fileId: shot.resultFileId || '',
      url: shot.resultUrl || '',
      position: 'first',
      compareFileId: seed.fileId,
      continuityThreshold: 0.085,
    })
    const passed = data?.continuityPassed !== false
    shot.continuityReview = {
      status: passed ? 'passed' : 'failed',
      fileId: shot.resultFileId,
      taskId: shot.taskId || shot.lastGenerationAttempt?.taskId || '',
      expectedFirstFrameId:seed.fileId,
      mae: Number(data?.continuityMae || 0),
      generatedFirstFrameId: data?.fileId || '',
      generatedFirstFrameUrl: data?.url || '',
      checkedAt: Date.now(),
    }
    if (!passed) {
      shot.statusText = '视频已生成，首帧未通过接镜检查；请先查看候选与对照'
      showWorkspaceToast('视频已保存为未采用候选，请先查看首帧对照与完整视频。', 'warning', 6000)
    }
    return shot.continuityReview
  } catch (error) {
    shot.continuityReview = {
      status: 'unavailable',
      summary: cleanError(error),
      checkedAt: Date.now(),
    }
    return shot.continuityReview
  }
}

async function pollSeedanceShot(shot) {
  if (workspaceDisposed || seedancePollInFlight.has(shot) || !storyboards.value.includes(shot)) return
  seedancePollInFlight.add(shot)
  try {
    await pollSeedanceShotOnce(shot)
  } finally {
    seedancePollInFlight.delete(shot)
  }
}

async function pollSeedanceShotOnce(shot) {
  const taskId = String(shot.taskId || shot.seedanceTaskId || '')
  const modelId = String(shot.seedanceModel || '')
  if (!taskId || !modelId || shot.generationEngine !== 'seedance') return
  shot.taskId = taskId
  const projectId = String(activeVideoProject.value?.id || '')
  const navigation = workspaceNavigation
  const current = () => !workspaceDisposed && navigation === workspaceNavigation
    && projectId === String(activeVideoProject.value?.id || '') && storyboards.value.includes(shot)
    && String(shot.taskId || '') === taskId && !['cancelling', 'cancelled'].includes(shot.status)
    && !shotRequests.get(shot)?.cancelled
  stopPolling(shot.id)
  try {
    const data = await window.pywebview.api.backend_request(
      'GET',
      `/ai/video/${encodeURIComponent(taskId)}?model=${encodeURIComponent(modelId)}`,
      props.token,
      null,
    )
    if (!current()) return
    const status = String(data?.status || data?.state || '').toLowerCase()
    if (data?.validation) {
      shot.resultValidation = data.validation
      const effective = Number(data.validation.effectiveDuration || 0)
      if (data.validation.adjusted && effective > 0 && Number(shot.duration || 0) !== effective) {
        shot.duration = effective
        shot.statusText = String(data.validation.notice || `上游实际产出 ${effective} 秒，本镜已按 ${effective} 秒记录`)
        showWorkspaceToast(String(data.validation.notice || `上游实际产出 ${effective} 秒，本镜已按 ${effective} 秒记录`), 'info', 6000)
      }
    }
    if (['succeeded', 'completed', 'done', 'success'].includes(status)) {
      const videoUrl = String(data?.video_url || data?.content?.video_url || '')
      if (!videoUrl) throw new Error('Seedance 生成完成但没有返回视频地址')
      shot.resultFileId = fileIdFromUrl(videoUrl)
      shot.resultUrl = absoluteMediaUrl(videoUrl)
      shot.resultPath = ''
      shot.resultWatermarked = false
      shot.seedanceLastFrameUrl = absoluteMediaUrl(data?.last_frame_url || data?.content?.last_frame_url || '')
      shot.status = 'succeeded'
      shot.statusText = data?.validation?.adjusted && data?.validation?.notice
        ? `${generationEngineLabel(shot)} 视频已生成并保存到本地；${data.validation.notice}`
        : `${generationEngineLabel(shot)} 视频已生成并保存到本地`
      if (data?.validation?.trimmed) {
        showWorkspaceToast(`✂️ 上游返回 ${data.validation.originalDuration} 秒，已自动裁成 ${data.validation.expectedDuration} 秒单镜`, 'info', 4200)
      }
      shot.progress = 100
      shot.seedanceTaskId = ''
      shot.seedanceTaskCreatedAt = 0
      shot.generationError = ''
      stopPolling(shot.id)
      shot.resultValidation = data?.validation || null
      const continuity = await verifyShotContinuity(shot)
      if (!current()) return
      if (continuity?.status === 'failed') {
        shot.rejectedResultUrl = shot.resultUrl
        shot.rejectedResultFileId = shot.resultFileId
        shot.rejectedResultTaskId = taskId
        shot.resultVisualReview = null
        finishGenerationAttempt(shot, 'rejected', '新视频首帧未接上，未作为成片采用')
        shot.rejectedContinuityReview = continuity
        restoreVideoResult(shot)
        shot.statusText = '本次首帧未接上；当前显示历史版本，失败候选另存'
        await saveActiveVideoProject()
        return
      }
      finishGenerationAttempt(shot, 'succeeded')
      shot.generationProvenance = {sourceTask: taskId, fileId:shot.resultFileId, submittedAt: shot.lastGenerationAttempt?.submittedAt, references: shot.lastGenerationAttempt?.references || [], continuityMode:shot.lastGenerationAttempt?.continuityMode, continuityPlan:shot.lastGenerationAttempt?.continuityPlan, continuityState:shot.lastGenerationAttempt?.continuityState, actionChain:shot.lastGenerationAttempt?.actionChain}
      shot.referenceReview = {status:'pending', fileId:shot.resultFileId}
      if (isMuseShot(shot)) void reviewShotAudio(shot)
      const completedShotIndex = storyboards.value.findIndex(item => item.id === shot.id)
      const nextShot = storyboards.value[completedShotIndex + 1]
      if (nextShot?.inheritPrevTail !== false) nextShot.continuityOutdated = true
      await saveActiveVideoProject()
      return
    }
    if (['failed', 'error', 'cancelled', 'canceled', 'expired'].includes(status)) {
      if (data?.validation?.passed === false) shot.rejectedResultUrl = absoluteMediaUrl(data?.video_url || data?.content?.video_url || '')
      restoreVideoResult(shot)
      const message = videoTaskFailureMessage(data, generationEngineLabel(shot))
      finishGenerationAttempt(shot, status, String(message))
      shot.status = 'failed'
      shot.statusText = String(message)
      shot.generationError = String(message)
      shot.seedanceTaskId = ''
      shot.seedanceTaskCreatedAt = 0
      stopPolling(shot.id)
      await saveActiveVideoProject()
      return
    }
    shot.status = status || 'generating'
    shot.waitElapsedSeconds = Math.max(0, Math.floor((Date.now() - Number(shot.seedanceTaskCreatedAt || Date.now())) / 1000))
    shot.statusText = status === 'queued' ? '视频任务已提交，正在排队' : (isMuseShot(shot) ? (shot.waitElapsedSeconds >= 300 ? 'Muse 等待较久，尚未返回视频；可终止后重试' : '正在等待 Muse 返回视频') : 'Seedance 正在生成视频')
    const remoteProgress = Number(data?.progress || 0)
    shot.progress = Math.min(99, Math.max(0, remoteProgress))
  } catch (err) {
    if (!current()) return
    shot.statusText = `Seedance 状态查询失败，将自动重试：${cleanError(err)}`
  }
  if (!current()) return
  const timer = window.setTimeout(() => pollSeedanceShot(shot), 5_000)
  pollTimers.set(shot.id, timer)
}

function isMuseShot(shot) {
  if (shot.generationEngine !== 'seedance') return false
  const id = String(shot.seedanceModel || defaultSeedanceModel.value || '')
  const model = videoApiModels.value.find(m => String(m.id ?? m.modelName ?? '') === id)
  return /^muse[-_ ]?video/i.test(String(model?.modelName || id))
}

function confirmShotDialogue(shot) {
  const contract = dialogueContract(shot.prompt)
  if (!contract.explicit) { shot.generationError = contract.errors.join('；'); return }
  shot.dialogueBaseline = contract
  shot.generationError = ''
  shot.statusText = contract.lines.length ? `已确认本镜 ${contract.lines.length} 句台词` : '已确认本镜无对白'
  scheduleProjectSave()
}

async function reviewShotAudio(shot, force = false) {
  const fileId = String(shot.resultFileId || '')
  const projectId = activeVideoProject.value?.id
  if (!fileId || shot.audioReview?.status === 'checking') return
  if (!force && shot.audioReview?.fileId === fileId) return
  const contract = shot.generationAudioContract || shot.dialogueBaseline || dialogueContract(shot.prompt)
  const api = window.pywebview?.api
  if (!api?.review_video_audio) {
    shot.audioReview = { status: 'unavailable', summary: '请重启更新后的客户端启用本地台词检查' }
    return
  }
  shot.audioReview = { status: 'checking', summary: '正在本地识别并核对台词…' }
  try {
    const report = await api.review_video_audio(props.token, fileId, contract)
    if (shot.resultFileId === fileId) shot.audioReview = { ...report, fileId }
  } catch (err) {
    if (shot.resultFileId === fileId) shot.audioReview = { status: 'unavailable', summary: `台词尚未核验：${cleanError(err)}` }
  }
  if (activeVideoProject.value?.id === projectId) await saveActiveVideoProject()
}

async function submitSeedanceShot(shot, attachments, availableReferences, request) {
  const planProblems = continuityPlanProblems(shot, availableReferences)
  if (planProblems.length) throw new Error(`衔接安排冲突，已停止提交：${planProblems.join('；')}`)
  const modelId = String(shot.seedanceModel || defaultSeedanceModel.value || '')
  if (!modelId) throw new Error('请先选择 Seedance 视频模型')
  shot.seedanceModel = modelId
  const rawDur = Number(shot.duration || 5)
  const effectiveDur = Math.min(10, Math.max(3, rawDur))
  if (effectiveDur !== rawDur) {
    shot.duration = effectiveDur
    if (typeof shot.prompt === 'string') {
      shot.prompt = shot.prompt.replace(/【00:00-00:\d+】/g, `【00:00-00:${String(effectiveDur).padStart(2, '0')}】`)
    }
  }
  shot.status = 'submitting'
  shot.statusText = '正在向 Seedance 提交视频任务'
  shot.progress = 6

  // 过滤掉音频素材，Seedance 视频生成仅支持图片参考与首尾帧
  const imageAttachments = attachments.filter(a => a.type === 'image')
  const imageReferences = availableReferences.filter(asset => !isAudioAsset(asset))
  const descriptors = seedanceReferenceDescriptors(shot, imageReferences)
  const mediaContent = []
  for (const [index, attachment] of imageAttachments.entries()) {
    const descriptor = descriptors[index] || { type: 'image_url', urlField: 'image_url', role: 'reference_image' }
    const encoded = await window.pywebview.api.read_local_media_data_url(attachment.path)
    if (request?.cancelled) return
    mediaContent.push({
      type: descriptor.type,
      [descriptor.urlField]: { url: encoded.url },
      role: descriptor.role,
    })
  }
  const generationPrompt = strictContinuityPrompt(shot, descriptors)
  const textContent = { type: 'text', text: generationPrompt }
  const content = orderSeedanceContent(shot, mediaContent, textContent)

  if (request?.cancelled) return
  shot.lastGenerationAttempt = {status:'submitting', submittedAt:Date.now(), references:descriptors.map(d=>({id:d.asset?.id, fileId:d.asset?.fileId, name:d.asset?.name, role:d.role})), previousResultFileId:shot.previousVideoResult?.fileId || ''}
  request.pending = window.pywebview.api.backend_request('POST', '/ai/video', props.token, {
    model: modelId,
    shot_id: String(shot.id),
    project_id: String(activeVideoProject.value?.id || ''),
    continuity_enabled: shot.inheritPrevTail !== false,
    continuity_mode: resolvedContinuityMode(shot),
    role_handoff: roleHandoffPlan(storyboards.value, shot),
    continuity_state: shot.continuityState || null,
    action_chain: shot.actionChain || null,
    dialogue_contract: shot.dialogueBaseline || dialogueContract(shot.prompt),
    prompt: generationPrompt,
    content,
    first_frame_pin: pinSceneStart(shot) || availableReferences.some(asset => asset.isGazeHandoff),
    generate_audio: Boolean(shot.sound),
    ratio: shot.ratio === '智能' ? '16:9' : (shot.ratio || '16:9'),
    resolution: String(shot.quality || defaultVideoSettings.quality).toLowerCase(),
    duration: Number(shot.duration || 5),
    return_last_frame: true,
    watermark: false,
  })
  const result = await request.pending
  if (request.cancelled) return
  shot.generationAudioContract = result?.audio_contract || dialogueContract(shot.prompt)
  const taskId = String(result?.taskId || result?.id || result?.task_id || '')
  if (!taskId) throw new Error('Seedance 未返回任务 ID')
  shot.taskId = taskId
  shot.seedanceTaskId = taskId
  shot.seedanceTaskCreatedAt = Date.now()
  shot.lastGenerationAttempt = {taskId, status:String(result?.status || 'queued'), submittedAt:Date.now(), references:descriptors.map(d=>({id:d.asset?.id, fileId:d.asset?.fileId, name:d.asset?.name, role:d.role})), previousResultFileId:shot.previousVideoResult?.fileId || '', continuityMode:resolvedContinuityMode(shot), continuityPlan:shot.continuityPlan ? JSON.parse(JSON.stringify(shot.continuityPlan)) : null, continuityState:shot.continuityState ? JSON.parse(JSON.stringify(shot.continuityState)) : null, actionChain:shot.actionChain ? JSON.parse(JSON.stringify(shot.actionChain)) : null}
  shot.status = String(result?.status || 'queued')
  shot.statusText = 'Seedance 任务已提交，正在排队'
  shot.progress = 8
  if (result?.durationNotice) showWorkspaceToast(String(result.durationNotice), 'info', 6000)
  await saveActiveVideoProject()
  await pollSeedanceShot(shot)
}

async function generateShot(shot) {
  if (shotRunning(shot)) return
  try {
    if (alignAuthoredContinuity(shot)) {
      scheduleProjectSave()
      showWorkspaceToast('已按本镜剪辑安排使用场景图，取消冲突的尾帧续接要求', 'info', 3500)
    }
    const planProblems = continuityPlanProblems(shot, sendAttachments(shot).filter(asset => assetUrl(asset)))
    if (planProblems.length) {
      shot.generationError = `衔接安排冲突，已停止提交：${planProblems.join('；')}`
      showWorkspaceToast(shot.generationError, 'warning', 5000)
      return
    }
    maintainTransitions(storyboards.value)
    const cleanPromptText = typeof clean === 'function' ? clean(shot.prompt) : String(shot.prompt || '')
    const isTransitionShot = Boolean(
      shot.narrativeTransition ||
      shot.environmentContinuity?.reset ||
      (shot.references || []).filter(a => a.category === 'scene').length > 1 ||
      /时空|变迁|流转|重组|跨越|转场|跨场景|多年后|数十年后|现代|变焦|从.*到|由.*转为/.test(cleanPromptText) ||
      /时空|转场|变迁|变焦/.test(shot.title || '')
    )
    if (!isTransitionShot) {
      const authoredProblems = shotEnvironmentConflicts(storyboards.value, shot)
      if (authoredProblems.length) {
        shot.generationError = `时间或天气描述冲突，请先修正：${authoredProblems.join('；')}`
        showWorkspaceToast(shot.generationError, 'warning', 5000)
        return
      }
    }
    const lightingProblems = environmentConflicts(storyboards.value, shot)
    if (lightingProblems.length) {
      console.warn(`[CDTV] 场景参考图存在光照差异（${lightingProblems.join('；')}），以正文提示词光照描述为准生成。`)
    }
    if (shot.generationError && shot.generationError.includes('场景参考图的时间或天气冲突')) {
      shot.generationError = ''
    }
    const handoff = roleHandoffPlan(storyboards.value, shot)
    if (handoff) {
      if (handoff.sceneReferenceId) {
        const sceneRef = sendAttachments(shot).find(asset => asset.id === handoff.sceneReferenceId)
        if (!sceneRef || !assetUrl(sceneRef)) {
          shot.generationError = '本镜指定的场景参考图缺失，已停止提交；不会静默忽略场景图继续生成'
          showWorkspaceToast(shot.generationError, 'warning', 5000)
          return
        }
      }
      const actorRef = sendAttachments(shot).find(asset => asset.id === (handoff.actorReferenceId || handoff.actorId))
      if (!actorRef || !assetUrl(actorRef)) {
        shot.generationError = '人物交接缺少新入画人物的真实参考图，已停止提交，避免让观察者替代少年'
        showWorkspaceToast(shot.generationError, 'warning', 5000)
        return
      }
    }
    const roleReport = synchronizeShotAssets(shot)
    if (roleReport.ambiguous.length) {
      shot.generationError = `画面中的“${roleReport.ambiguous.join('、')}”对应多个角色，请先在参考图中选择具体人物再生成`
      showWorkspaceToast(shot.generationError, 'warning', 5000)
      return
    }
    const request = { cancelled: false, pending: null }
    shotRequests.set(shot, request)

    // 1. 自动首尾帧衔接检测：若开启衔接上一镜且上一镜有视频，自动提取最新尾帧
    const currentShotIdx = storyboards.value.findIndex(s => s.id === shot.id)
    if (currentShotIdx > 0 && shot.inheritPrevTail !== false) {
      const prevShot = storyboards.value[currentShotIdx - 1]
      if (hasRejectedReferences(prevShot)) {
        shot.generationError = '上一镜当前候选未通过人物或场景参考检查，请先修正上一镜，避免继续沿用错误画面'
        showWorkspaceToast(shot.generationError, 'warning', 5000)
        return
      }
      if (prevShot?.resultValidation?.passed === false) {
        shot.generationError = '上一镜视频未通过时长验收，请先重做上一镜，或关闭尾帧续接后制作新场景'
        showWorkspaceToast(shot.generationError, 'warning', 5000)
        return
      }
      if (prevShot && (prevShot.resultUrl || prevShot.resultFileId)) {
        const exactModeNeedsRawFrame = (resolvedContinuityMode(shot) === 'exact' || resolvedContinuityMode(shot) === 'transition') && shot.continuityTailFrame?.isMatrixCropped
        const strictMuseNeedsFreshTail = isMuseShot(shot) && (resolvedContinuityMode(shot) === 'exact' || resolvedContinuityMode(shot) === 'transition')
        if (strictMuseNeedsFreshTail || !storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover') || shot.continuityOutdated || exactModeNeedsRawFrame) {
          shot.status = 'preparing'
          shot.statusText = `正在提取第 ${currentShotIdx} 镜最新尾帧以保持动作接续...`
          const refreshedTail = await extractLastFrameForShot(prevShot, currentShotIdx - 1, shot)
          if (request.cancelled) return
          const existingTailOk = Boolean(shot.continuityTailFrame?.fileId && storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover'))
          if (strictMuseNeedsFreshTail && !refreshedTail && !existingTailOk) {
            shot.status = 'failed'
            shot.generationError = '未能读取上一镜真实尾帧，已停止生成，避免产生跳切视频'
            shot.statusText = shot.generationError
            showWorkspaceToast(shot.generationError, 'warning', 5000)
            return
          }
        }
      }
    }
    if (isMuseShot(shot)) {
      shot.prompt = cleanShotAudioPrompt(shot.prompt)
      const current = dialogueContract(shot.prompt)
      if (!current.explicit) {
        shot.generationError = current.errors.join('；')
        showWorkspaceToast(shot.generationError, 'warning', 5000)
        return
      }
      if (!shot.dialogueBaseline?.explicit) shot.dialogueBaseline = current
      if (!sameDialogue(shot.dialogueBaseline, current)) {
        shot.generationError = '当前台词与已确认基准不同，请核对后点击“确认当前台词”'
        showWorkspaceToast(shot.generationError, 'warning', 5000)
        return
      }
    }
    stopPolling(shot.id)
    shot.taskId = ''
    shot.seedanceTaskId = ''
    shot.seedanceTaskCreatedAt = 0
    shot.generationError = ''
    shot.showHistoricalResult = false
    if (shot.resultFileId) shot.previousVideoResult = snapshotVideoResult(shot)
    shot.lastGenerationAttempt = {status:'preparing', taskId:'', submittedAt:Date.now(), previousResultFileId:shot.previousVideoResult?.fileId || ''}
    shot.audioReview = null
    shot.referenceReview = null
    shot.generationProvenance = null
    shot.resultVisualReview = null
    shot.resultValidation = null
    shot.resultUrl = ''
    shot.resultPath = ''
    shot.resultFileId = ''
    shot.resultEnvironmentWarning = ''
    shot.resultWatermarked = false
    shot.conversationId = ''
    shot.conversationUrl = ''
    shot.generationSubmittedAt = 0
    shot.continuityReview = null
    if (!shot.prompt.trim()) {
      shot.generationError = '请先填写当前分镜的视频描述'
      showWorkspaceToast(shot.generationError, 'warning', 5000)
      return
    }
    if (shot.generationEngine === 'seedance' && !(shot.seedanceModel || defaultSeedanceModel.value)) {
      shot.generationError = '当前没有可用的 Seedance 视频模型，请先在后台配置模型'
      showWorkspaceToast(shot.generationError, 'warning', 5000)
      return
    }
    const rawResolved = sendAttachments(shot)
    const continuityUrl = storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover')
    const hasContinuity = shot.inheritPrevTail !== false && Boolean(continuityUrl)
    let resolvedReferences = []
    if (hasContinuity) {
      const tailAsset = {
        id: shot.continuityTailFrame.fileId,
        fileId: shot.continuityTailFrame.fileId,
        coverId: shot.continuityTailFrame.fileId,
        name: `第${shot.continuityTailFrame.sourceShotIndex !== undefined ? shot.continuityTailFrame.sourceShotIndex + 1 : '上'}镜尾帧`,
        url: continuityUrl,
        cover: continuityUrl,
        mediaType: 'image',
        isContinuityFrame: true,
      }
      if (isMuseShot(shot) && roleHandoffPlan(storyboards.value, shot)) {
        resolvedReferences = handoffReferences(roleHandoffPlan(storyboards.value, shot), rawResolved, tailAsset)
        if (resolvedReferences.length < 2) {
          shot.generationError='人物交接缺少少年参考图，已停止提交'
          showWorkspaceToast(shot.generationError, 'warning', 5000)
          return
        }
      } else {
        const validRefs = rawResolved.filter(asset => asset.id !== tailAsset.id)
        const roleRefs = validRefs.filter(a => {
          const cat = String(a.category || a.type || '').toLowerCase()
          return cat === 'role' || cat === 'character' || cat === 'actor'
        })
        const sceneRefs = validRefs.filter(a => {
          const cat = String(a.category || a.type || '').toLowerCase()
          return cat === 'scene' || cat === 'environment' || cat === 'env'
        })
        const propRefs = validRefs.filter(a => {
          const cat = String(a.category || a.type || '').toLowerCase()
          return cat === 'prop' || cat === 'item' || cat === 'object'
        })
        const otherRefs = validRefs.filter(a => !roleRefs.includes(a) && !sceneRefs.includes(a) && !propRefs.includes(a))
        resolvedReferences = [
          tailAsset,
          ...roleRefs.slice(0, 2),
          ...sceneRefs.slice(0, 1),
          ...propRefs.slice(0, 1),
          ...otherRefs.slice(0, 1),
        ].slice(0, 5)
      }

      shot.prompt = shot.prompt
        .replace(/运镜[：:\s]*全景[·\s]*环绕/g, '运镜：顺接首帧特写起步并迅速后拉升起展开为全景')
        .replace(/【镜\d+-\d+】\s*全景[·\s]*环绕/g, '【顺接首帧·运镜后拉至全景】')
    } else {
      let handoffAsset = null
      const gazeBeat = shot.gazeHandoff !== false ? gazeHandoffBeatFor(shot) : ''
      const cutReference = shot.narrativeTransition?.handoffMode === 'cut' && shot.narrativeTransition?.usePreviousViewReference === true
      const prevShot = currentShotIdx > 0 ? storyboards.value[currentShotIdx - 1] : null
      const prevHasVideo = Boolean(prevShot && (prevShot.resultUrl || prevShot.resultFileId || prevShot.mixedVideoFileId || prevShot.originalVideoFileId))
      if ((gazeBeat || cutReference) && prevHasVideo) {
        shot.status = 'preparing'
        shot.statusText = `正在提取第 ${currentShotIdx} 镜门口视角，接住上一镜视线...`
        const frame = await extractLastFrameForShot(prevShot, currentShotIdx - 1, shot, { activate: false, silent: true, store: 'gazeHandoff' })
        if (request.cancelled) return
        const frameUrl = storedProjectMediaUrl(frame, 'url', 'cover')
        if (frameUrl) {
          handoffAsset = {
            id: frame.fileId || 'gaze-handoff',
            fileId: frame.fileId,
            coverId: frame.fileId,
            name: `第${currentShotIdx}镜接镜点视角`,
            url: frameUrl,
            cover: frameUrl,
            mediaType: 'image',
            isGazeHandoff: !cutReference,
            isCutReference: cutReference,
          }
        }
      } else if (gazeBeat) {
        showWorkspaceToast('⚠️ 上一镜还没有视频，无法复用门口视角，本镜改按定场图开场', 'warning', 2600)
      }
      const isFirstShot = currentShotIdx === 0
      const anchor = sceneAnchorOf(shot, rawResolved, isFirstShot)
      resolvedReferences = cutReference
        ? [...orderSceneAnchorFirst([...rawResolved], anchor), handoffAsset].filter(Boolean)
        : isMuseShot(shot) && handoffAsset
          ? [handoffAsset]
          : [handoffAsset, ...sceneCutReferences(shot, [...rawResolved], anchor)].filter(Boolean)
    }

    const imageReferences = resolvedReferences.filter((asset) => {
      return !isAudioAsset(asset)
    })
    const audioReferences = resolvedReferences.filter((asset) => {
      return isAudioAsset(asset) && assetUrl(asset)
    })
    const unavailableImages = imageReferences.filter(asset => !assetUrl(asset))
    if (unavailableImages.length) {
      shot.generationError = `${unavailableImages.map(asset => asset.name || asset.id || '未命名图片').join('、')}还没有真实文件，请先上传或生成`
      showWorkspaceToast(shot.generationError, 'warning', 5000)
      return
    }
    if (!imageReferences.length) {
      shot.generationError = '请先从左侧添加人物、场景或道具图片'
      showWorkspaceToast(shot.generationError, 'warning', 5000)
      return
    }
    const imageAssets = imageReferences.map(resolveAssetReference)
    const audioAssets = audioReferences.map(resolveAssetReference)
    const missingAssets = imageAssets.filter(asset => !assetUrl(asset))
    if (missingAssets.length) {
      shot.generationError = `${missingAssets.map(asset => asset.name || asset.id || '未命名资产').join('、')}还没有图片，请先在左侧生成或上传`
      showWorkspaceToast(shot.generationError, 'warning', 5000)
      return
    }
    if (!window.pywebview?.api) {
      shot.generationError = '请从桌面客户端启动后再生成视频'
      showWorkspaceToast(shot.generationError, 'warning', 5000)
      return
    }

    shot.status = 'preparing'
    shot.statusText = `正在准备 ${imageAssets.length} 张参考图${audioAssets.length ? `和 ${audioAssets.length} 个音频文件` : ''}`
    shot.progress = 2
    const attachments = []
    const availableReferences = resolvedReferences.filter(asset => !isAudioAsset(asset) || assetUrl(asset))
    const generationReferences = shot.generationEngine === 'seedance'
      ? availableReferences
      : availableReferences.filter(asset => !isAudioAsset(asset))
    for (const [index, asset] of generationReferences.entries()) {
      const type = isAudioAsset(asset) ? 'audio' : 'image'
      const prepared = await window.pywebview.api.prepare_generation_asset(asset, props.token)
      if (request.cancelled) return
      attachments.push({ path: prepared.path, type, name: `${type === 'audio' ? '文件' : '图'}${index + 1}` })
    }
    const imagePaths = attachments.filter(item => item.type === 'image').map(item => item.path)
    const audioPaths = attachments.filter(item => item.type === 'audio').map(item => item.path)
    if (shot.generationEngine === 'seedance') {
      shot.accountId = ''
      await submitSeedanceShot(shot, attachments, generationReferences, request)
      return
    }
    const omittedAudioReferences = availableReferences.filter(asset => isAudioAsset(asset))
    ensureStoryboardDefaults(shot)
    const originalDoubaoPrompt = promptForOriginalDoubao(promptWithTransition(storyboards.value, shot), generationReferences, omittedAudioReferences)
    const result = await window.pywebview.api.start_generation({
      attachments,
      imagePaths,
      imagePath: imagePaths[0],
      audioPaths,
      prompt: originalDoubaoPrompt.trim(),
      ratio: shot.ratio === '智能' ? '16:9' : shot.ratio,
      duration: shot.duration,
      durationMode: shot.durationMode,
      quality: shot.quality,
      sound: shot.sound,
      count: shot.count,
      mode: shot.mode,
      model: isOriginalDoubaoEngine(shot) ? (shot.webModel || (shot.generationEngine === 'dola' ? 'Dreamina Seedance 2.0 Fast' : 'Seedance 2.0 Mini')) : props.videoModel,
      accountId: props.selectedAccountId,
      accountType: shot.generationEngine === 'do' ? 'auto' : shot.generationEngine === 'dola' ? 'dola' : 'doubao',
      autoAssignAccount: true,
      token: props.token,
      persistResult: true,
      ownerType: 'videoShot',
      ownerId: String(shot.id || ''),
      projectId: String(activeVideoProject.value?.id || ''),
      taskName: `分镜 ${storyboards.value.indexOf(shot) + 1} 视频`,
      generationEngine: String(shot.generationEngine || ''),
    })
    shot.taskId = result.taskId
    if (request.cancelled) { await window.pywebview.api.cancel_task(result.taskId); return }
    shot.accountId = String(result.accountId || props.selectedAccountId || '')
    await saveActiveVideoProject()
    await pollShot(shot)
  } catch (err) {
    if (shotRequests.get(shot)?.cancelled) return
    console.error('generateShot error:', err)
    shot.status = 'failed'
    shot.generationError = cleanError(err)
    showWorkspaceToast(`提交分镜失败: ${shot.generationError}`, 'error', 6000)
    finishGenerationAttempt(shot, 'failed', shot.generationError)
    restoreVideoResult(shot)
    await saveActiveVideoProject()
  }
}

// 字符串签名监听：Vue 只 diff 字符串（O(1)），不遍历对象图
// 只提取需要持久化的字段，排除 generating/progress/uploading 等瞬态属性
// 既不卡顿，又能捕获内容编辑（分镜文本、设置变更、资产重命名等）
const projectSignature = computed(() => JSON.stringify({
  name: activeVideoProject.value?.name,
  projectId: activeVideoProject.value?.projectId,
  description: activeVideoProject.value?.description,
  assets: assets.value.map(a => ({
    id: a.id, name: a.name, description: a.description, tags: a.tags,
    type: a.type, category: a.category, coverId: a.coverId, fileId: a.fileId,
    boundProjectIds: a.boundProjectIds, prompt: a.prompt,
    useDefaultRoleLayout: a.useDefaultRoleLayout,
    imageTextMode: a.imageTextMode, imageText: a.imageText,
  })),
  storyboards: storyboards.value.map(s => ({
    id: s.id, title: s.title, prompt: s.prompt, ratio: s.ratio,
    duration: s.duration, durationMode: s.durationMode, mode: s.mode,
    generationEngine: s.generationEngine, seedanceModel: s.seedanceModel,
    count: s.count, quality: s.quality, sound: s.sound,
    references: (s.references || []).map(r => ({ id: r.id, name: r.name })),
    referenceLabels: s.referenceLabels,
    sceneId: s.sceneId, inheritPrevTail: s.inheritPrevTail, gazeHandoff: s.gazeHandoff,
    narrativeTransition: s.narrativeTransition, environmentContinuity:s.environmentContinuity, continuityHandoff:s.continuityHandoff,
  })),
}))
watch(projectSignature, () => {
  if (!hydratingProject) {
    maintainTransitions(storyboards.value)
    scheduleProjectSave()
  }
})
watch(() => storyboards.value.map(shot => shot.id).join('|'), async () => {
  await nextTick()
  scheduleVisibleStoryboardAnchorUpdate()
})
watch(() => activeVideoProject.value?.name, scheduleProjectSave)
watch(() => activeVideoProject.value?.description, scheduleProjectSave)
watch(() => props.initialCreationData, (payload) => {
  if (!payload?.document || typeof payload.document !== 'object') return
  pendingInitialCreationData.value = payload
  consumeInitialCreationData()
}, { immediate: true })

async function consumeInitialCreationData() {
  const payload = pendingInitialCreationData.value
  // 组件首次挂载时 watcher 会先执行一次，此时工作台还没准备好，
  // 不能继续往下读 payload，否则会在 payload 为空时触发 projectName 空指针。
  if (
    !payload ||
    typeof payload !== 'object' ||
    !payload.document ||
    typeof payload.document !== 'object' ||
    !videoWorkspaceReady.value ||
    consumingInitialCreationData.value ||
    projectListLoading.value
  ) return
  consumingInitialCreationData.value = true
  try {
    const projectName = String(payload.projectName || payload.document?.project?.name || '项目')
    const chapterTitle = String(payload.chapterTitle || '第一集')
    const targetProjectName = isGeneral.value ? projectName : `${projectName} · ${chapterTitle}`
    const chapterId = String(payload.chapterId || '')
    const projectId = String(payload.projectId || '')

    // 智能匹配：同一短剧母项目 (projectId) 共享唯一的视频创作任务，避免每推一集重复创建新任务卡片
    let target = videoProjects.value.find(p => (payload.videoProjectId && String(p.id) === String(payload.videoProjectId)))
      || videoProjects.value.find(p => projectId && String(p.projectId || '') === projectId)
      || videoProjects.value.find(p => chapterId && String(p.description || '').includes(`章节 ID ${chapterId}`))

    let preserveExisting = false
    if (target) {
      await openVideoProject(target)
      target.episodes ||= {}
      if (chapterId && target.episodes[chapterId]?.storyboards?.length) {
        preserveExisting = true
      }
    } else {
      target = await videoProjectRequest('POST', '/video-project', {
        name: projectName,
        projectId,
        description: `由 AI 创作关联生成 · 包含 ${chapterTitle}`,
        assets: [],
        storyboards: [],
        episodes: {},
        currentEpisodeId: chapterId,
      })
      await loadVideoProjects()
      await openVideoProject(target)
    }

    if (projectId && chapterId) {
      try {
        const chapterList = await videoProjectRequest('GET', `/project/${encodeURIComponent(projectId)}/chapter/list`)
        const chapter = (Array.isArray(chapterList) ? chapterList : []).find(item => String(item.id) === chapterId)
        if (chapter) {
          payload.document = ensureScriptShotCoverage(payload.document, payload.script || chapter.script || chapter.workflow?.script || '', getProjectStylePrefix(activeVideoProject.value || {}))
          await videoProjectRequest('PUT', `/chapter/${encodeURIComponent(chapter.id)}`, {
            workflow: { ...(chapter.workflow || {}), creationData: payload.document, videoProjectId: target.id, videoProjectUpdatedAt: new Date().toISOString() },
          })
        }
      } catch {}
    }
    payload.document = ensureScriptShotCoverage(payload.document, payload.script || '', getProjectStylePrefix(activeVideoProject.value || {}))
    
    // 切换至推送的集数并载入分镜
    if (chapterId) {
      currentChapterId.value = chapterId
      if (activeVideoProject.value) {
        activeVideoProject.value.currentEpisodeId = chapterId
      }
    }

    applyImportedDocument(payload.document, `AI 创作 · ${chapterTitle} 推送`, preserveExisting)

    if (activeVideoProject.value && chapterId) {
      activeVideoProject.value.episodes ||= {}
      activeVideoProject.value.episodes[chapterId] = {
        id: chapterId,
        title: chapterTitle,
        storyboards: storyboards.value.map(shot => ({ ...shot }))
      }
      const importedTitles = Object.values(activeVideoProject.value.episodes).map(e => e.title || '').filter(Boolean)
      if (importedTitles.length) {
        activeVideoProject.value.description = `由 AI 创作关联生成 · 已导入：${importedTitles.join('、')}`
      }
    }

    await saveActiveVideoProject()
    projectError.value = ''
  } catch (err) {
    projectError.value = cleanError(err)
  } finally {
    pendingInitialCreationData.value = null
    consumingInitialCreationData.value = false
    useProductionView()
    emit('creation-data-consumed')
  }
}

watch(assetActionsOpen, (open) => {
  if (open) loadGenerators()
})

watch([materialDrawer, activeShotId], async () => {
  if (!props.embedded || isGeneral.value) return
  await nextTick()
  productionCanvasRef.value?.scrollTo({ top: 0, left: 0 })
})
watch(productionSummary, state => emit('production-state', state), { deep: true })
onMounted(async () => {
  await Promise.all([loadGenerators(), loadVideoProjects(), loadAvailableProjects()])
  videoWorkspaceReady.value = true
  await consumeInitialCreationData()
  await openScopedProduction()
  // 定时刷新任务表，驱动"生成中 N"计数；若配音面板已打开且尚未就绪，在后台自动探活
  taskRefreshTimer = window.setInterval(() => {
    refreshTasks(String(activeVideoProject.value?.id || ''))
    const hasAudioTab = storyboards.value.some(s => s.workspaceTab === 'audio')
    if (hasAudioTab && !breezeConnection.value?.ready && !breezeConnecting.value) {
      connectBreeze(false)
    }
  }, 2500)
  document.addEventListener('click', closeAllPopovers)
  document.addEventListener('keydown', handlePopoverKeydown)
  document.addEventListener('fullscreenchange', syncPlayerFullscreenState)
  window.addEventListener('resize', closeAllPopovers)
  window.addEventListener('cdtv:models-updated', loadGenerators)
  window.addEventListener('focus', loadGenerators)
})
onBeforeUnmount(() => {
  workspaceDisposed = true
  workspaceNavigation += 1
  pollTimers.forEach(timer => window.clearTimeout(timer))
  if (taskRefreshTimer) window.clearInterval(taskRefreshTimer)
  if (storyboardAnchorFrame) window.cancelAnimationFrame(storyboardAnchorFrame)
  if (projectSaveTimer) window.clearTimeout(projectSaveTimer)
  if (activeVideoProject.value?.id) saveActiveVideoProject()
  document.removeEventListener('click', closeAllPopovers)
  document.removeEventListener('keydown', handlePopoverKeydown)
  document.removeEventListener('fullscreenchange', syncPlayerFullscreenState)
  window.removeEventListener('resize', closeAllPopovers)
  window.removeEventListener('cdtv:models-updated', loadGenerators)
  window.removeEventListener('focus', loadGenerators)
})
</script>

<template>
  <section v-if="props.embedded && !activeVideoProject" class="embedded-production-empty">
    <p v-if="projectError" class="video-project-error" role="alert">{{ projectError }}</p>
    <BaseLoadingState v-if="!videoWorkspaceReady || projectDetailLoading || consumingInitialCreationData" panel text="正在打开制作台…" />
    <template v-else><span>▤</span><h2>{{ isGeneral ? '从内容开始，整理这支作品的镜头' : '在本剧内继续本集制作' }}</h2><p>完成脚本与镜头整理后，素材、视频、声音和版本会一直保留在这里。</p><button class="embedded-primary" @click="emit('request-plan')">{{ isGeneral ? '整理镜头并开始制作' : '载入本集分镜' }}</button></template>
  </section>
  <section v-else-if="!activeVideoProject" class="video-project-hub">
    <header class="video-project-workspace-head">
      <div class="video-project-head-copy"><span>资源与工具</span><div><h1>全部生成记录</h1><b>{{ videoProjects.length }} 个任务</b></div><p>查看历史任务、独立生成和后台进度；作品制作可直接在短剧或通用视频中完成。</p></div>
      <div class="video-project-head-art" aria-hidden="true"><span class="video-project-hero-script"><i></i><i></i><i></i></span><span class="video-project-hero-shot video-project-hero-shot-top"></span><span class="video-project-hero-shot video-project-hero-shot-bottom"></span><svg viewBox="0 0 250 130"><path d="M90 65 C125 65 122 32 164 32M90 68 C125 68 122 98 164 98"/></svg></div>
      <div class="video-project-head-actions">
        <div class="video-project-filter">
          <UiSelect v-model="videoProjectFilter" :options="projectFilterOptions" aria-label="按项目筛选任务" />
        </div>
        <label class="video-project-search">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.35-4.35"/></svg>
          <input v-model="videoProjectKeyword" type="search" placeholder="搜索任务" aria-label="搜索任务" />
        </label>
        <button class="video-project-new-button" type="button" @click="videoProjectCreateOpen = true"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>新建任务</button>
      </div>
    </header>
    <div v-if="projectDetailLoading" class="video-project-detail-overlay" role="status" aria-live="polite">
      <BaseLoadingState size="lg" panel text="正在打开任务…" description="加载资产与分镜数据" />
    </div>
    <p v-if="projectError" class="video-project-error">{{ projectError }}</p>
    <section class="video-project-library">
      <header><div><span>创作任务</span><h2>全部任务</h2></div><b>{{ videoProjects.length }}</b></header>
      <div v-if="projectListLoading" class="video-project-grid" role="status" aria-live="polite" aria-label="正在加载任务列表">
        <article v-for="n in 6" :key="`video-project-skeleton-${n}`" class="video-project-card video-project-card-skeleton" aria-hidden="true">
          <div class="video-project-card-body">
            <header class="video-project-skeleton-header"><i></i><i></i></header>
            <i class="video-project-skeleton-title"></i>
            <i class="video-project-skeleton-desc"></i>
            <div class="video-project-card-stats"><span><i></i><i></i></span><span><i></i><i></i></span><span><i></i><i></i></span></div>
            <footer><i class="video-project-skeleton-time"></i><i class="video-project-skeleton-cta"></i></footer>
          </div>
        </article>
      </div>
      <div v-else-if="videoProjects.length" class="video-project-grid">
        <article v-if="!videoProjectKeyword.trim()" class="video-project-create-card"><button type="button" @click="videoProjectCreateOpen = true"><span class="video-project-new-visual" aria-hidden="true"><span class="video-project-new-script"><i></i><i></i><i></i></span><span class="video-project-new-frame"><i></i><b></b></span><span class="video-project-new-plus"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></span></span><strong>开始创作</strong></button><div><svg viewBox="0 0 18 18"><path d="M3 6.5v5M6 4.5v9M9 7v4M12 5.5v7M15 3.5v11"/></svg><span>视频生成任务</span></div></article>
        <article v-for="project in filteredVideoProjectCards" :key="project.id" class="video-project-card" tabindex="0" @click="openVideoProject(project)" @keydown.enter.self="openVideoProject(project)">
          <div class="video-project-card-body">
            <header><span>视频创作任务</span><span class="video-project-card-head-actions"><button class="video-project-delete-button" type="button" :disabled="Boolean(deletingProjectId)" :aria-label="`删除任务 ${project.name || '未命名任务'}`" data-tooltip="删除任务" @click.stop="requestDeleteVideoProject(project)" @keydown.stop><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg></button><svg class="video-project-open-arrow" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 10h10m-4-4 4 4-4 4"/></svg></span></header>
            <h2>{{ project.name || '未命名任务' }}</h2>
            <p>{{ project.description || '暂未添加任务描述' }}</p>
            <span class="video-project-link-pill"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 12.5 12.5 7.5M6 9l-1.5 1.5a3 3 0 0 0 4.2 4.2l1.5-1.5M14 11l1.5-1.5a3 3 0 0 0-4.2-4.2L9.8 6.8"/></svg>{{ linkedProjectName(project.projectId) }}</span>
            <div class="video-project-card-stats">
              <div class="stat-pills">
                <span class="stat-pill stat-pill-asset"><i class="stat-dot"></i><b>{{ project.assetCount || 0 }}</b><small>资产</small></span>
                <span v-if="project.episodeCount && project.episodeCount > 1" class="stat-pill stat-pill-episode"><i class="stat-dot"></i><b>{{ project.episodeCount }}</b><small>集</small></span>
                <span class="stat-pill stat-pill-shot"><i class="stat-dot"></i><b>{{ project.storyboardCount || 0 }}</b><small>分镜</small></span>
                <span v-if="project.runningCount" class="stat-pill stat-pill-running"><i class="stat-dot"></i><b>{{ project.runningCount }}</b><small>生成中</small></span>
              </div>
              <button type="button" class="video-project-finished-stat" :aria-label="`查看 ${project.name || '任务'} 的 ${project.completedCount || 0} 个成片`" @click.stop="openProjectFinishedPreview(project)" @keydown.stop>
                <i class="video-project-finished-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 7 8 5-8 5z"/></svg></i>
                <span class="video-project-finished-copy"><small>{{ project.completedCount || 0 }} 视频</small></span>
                <svg class="video-project-finished-arrow" viewBox="0 0 20 20" aria-hidden="true"><path d="m8 6 4 4-4 4"/></svg>
              </button>
            </div>
            <footer><time>更新于 {{ project.updateTime ? String(project.updateTime).replace('T', ' ').slice(0, 16) : '--' }}</time><span>继续创作</span></footer>
          </div>
        </article>
      </div>
      <div v-else-if="videoProjectKeyword.trim() || videoProjectFilter !== 'all'" class="video-project-empty"><strong>没有匹配的任务</strong><span>试试调整项目筛选或关键词，或清空条件重新查看全部任务。</span></div>
      <div v-else class="video-project-empty"><strong>还没有创作任务</strong><span>点击“新建任务”，开始你的第一个故事。</span></div>
    </section>
    <div v-if="videoProjectCreateOpen" class="video-project-create-backdrop" @click.self="videoProjectCreateOpen = false">
      <form class="video-project-create" @submit.prevent="createVideoProject">
        <div class="video-project-create-head"><span>＋</span><div><strong>新建创作任务</strong><small>创建后可导入完整 JSON 资产与分镜</small></div><button type="button" aria-label="关闭" @click="videoProjectCreateOpen = false">×</button></div>
        <label><span>任务名称</span><input v-model="newProjectName" placeholder="例如：末日 Online" maxlength="256" autocomplete="off" /></label>
        <label class="video-project-link-field"><span>关联项目 <small>选填 · 可稍后在工作台绑定</small></span><UiSelect v-model="newProjectId" :options="projectLinkOptions" :placeholder="availableProjects.length ? '不关联项目' : '暂无项目'" badge="PROJECT" /></label>
        <label><span>任务描述 <small>选填</small></span><textarea v-model="newProjectDescription" placeholder="简单描述故事主题或创作方向" maxlength="512" rows="3"></textarea></label>
        <p v-if="projectError" class="video-project-form-error">{{ projectError }}</p>
        <footer><button type="button" @click="videoProjectCreateOpen = false">取消</button><button type="submit" :disabled="projectCreating">{{ projectCreating ? '正在创建…' : '创建并进入工作台' }}</button></footer>
      </form>
    </div>
    <div v-if="projectToDelete" class="video-project-create-backdrop" @click.self="cancelDeleteVideoProject">
      <section class="video-project-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="video-project-delete-title" aria-describedby="video-project-delete-description">
        <span class="video-project-delete-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg></span>
        <div><small>DELETE TASK</small><h2 id="video-project-delete-title">删除创作任务？</h2><p id="video-project-delete-description">任务 <strong>{{ projectToDelete.name || '未命名任务' }}</strong> 的资产配置和分镜记录将被删除，此操作不可撤销。</p></div>
        <footer><button type="button" :disabled="Boolean(deletingProjectId)" @click="cancelDeleteVideoProject">取消</button><button class="danger" type="button" :disabled="Boolean(deletingProjectId)" autofocus @click="confirmDeleteVideoProject">{{ deletingProjectId ? '正在删除…' : '确认删除' }}</button></footer>
      </section>
    </div>
  </section>

  <section v-else class="video-workbench" :class="{ 'embedded-production': props.embedded, 'general-production': isGeneral, 'drama-workbench': props.embedded && !isGeneral, 'materials-open': materialDrawer }">
    <header v-if="props.embedded && isGeneral" class="production-toolbar">
      <div><span class="production-kind">{{ isGeneral ? '通用视频制作台' : '本集制作台' }}</span><strong>{{ productionSummary.completed }} / {{ productionSummary.shots }} 镜头有视频</strong><small>{{ productionSummary.seconds }} 秒计划时长</small></div>
      <div><button :class="{active:materialDrawer}" :aria-expanded="materialDrawer" @click="materialDrawer=!materialDrawer">{{ materialDrawer ? '收起素材库' : isGeneral ? '参考图与生图' : '素材库' }} <b>{{ assets.length }}</b></button><button v-if="isGeneral && currentActiveShot && props.productionView!=='review'" class="production-video-settings" :aria-expanded="currentActiveShot.settingsOpen" @click.stop="toggleSettings(currentActiveShot,$event)">视频模型与参数</button><button v-if="isGeneral" @click="emit('request-model-settings')">模型配置</button><button @click="openProjectFinishedPreview(activeVideoProject)">连续预览与导出</button><button @click="syncEpisodeConsistency">统一声音与画面</button><button @click="addStoryboard">＋ 新增镜头</button><span class="workbench-save-status" :class="projectSaveTone">{{ projectSaveLabel }}</span></div>
    </header>
    <header v-if="props.embedded && !isGeneral" class="drama-studio-header">
      <div class="drama-studio-overview"><div><strong>本集制作台</strong><span>{{ productionSummary.completed }} / {{ productionSummary.shots }} 镜头有视频 · {{ productionSummary.seconds }} 秒</span></div><span class="workbench-save-status" :class="projectSaveTone">{{ projectSaveLabel }}</span></div>
      <nav class="drama-studio-navigation" aria-label="本集制作步骤">
        <button :class="{active:materialDrawer}" :aria-pressed="materialDrawer" @click="materialDrawer=true"><b>1</b><span>资产图片<small>人物、场景、道具 · {{ assets.length }} 项</small></span></button>
        <button :class="{active:!materialDrawer}" :aria-pressed="!materialDrawer" @click="materialDrawer=false"><b>2</b><span>分镜视频<small>选择镜头，编辑并生成</small></span></button>
        <button @click="openProjectFinishedPreview(activeVideoProject)"><b>3</b><span>连续预览与导出<small>检查衔接，制作成片</small></span></button>
      </nav>
    </header>
    <section v-if="props.embedded && props.productionView==='review'" class="production-review">
      <header><div><span>作品预览</span><h2>按镜头顺序检查整支作品</h2><p>逐段检查画面、文案和声音；已生成版本、历史候选和原视频都保留。</p></div><button class="embedded-primary" @click="openProjectFinishedPreview(activeVideoProject)">打开连续预览与导出</button></header>
      <div class="production-review-grid"><article v-for="(shot,index) in storyboards" :key="shot.id"><video v-if="shot.resultUrl" :src="shot.resultUrl" controls preload="metadata"></video><div v-else class="review-wait">尚未生成视频</div><h3>{{ String(index+1).padStart(2,'0') }} · {{ shot.title }}</h3><p>{{ shot.duration }} 秒 <span v-if="shot.resultValidation?.passed===false">· 时长待处理</span></p><small v-if="shot.generationError">{{ shot.generationError }}</small><button @click="activeShotId=shot.id;emit('request-plan','visual')">编辑这个镜头</button></article></div>
    </section>
    <header v-if="!props.embedded" class="video-workbench-head">
      <button class="workbench-back" type="button" @click="backToVideoProjects"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14.5 6-6 6 6 6"/></svg>返回</button>
      <div class="video-workbench-title">
        <input v-model="activeVideoProject.name" class="workbench-project-name" aria-label="任务名称" />
        <div class="workbench-meta">
          <span>{{ assets.length }} 项资产</span><span>{{ storyboards.length }} 个分镜</span>
          <label class="workbench-project-link" aria-label="关联项目" data-tooltip="关联所属母剧本，选择其他项目可快速切换"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 12.5 12.5 7.5M6 9l-1.5 1.5a3 3 0 0 0 4.2 4.2l1.5-1.5M14 11l1.5-1.5a3 3 0 0 0-4.2-4.2L9.8 6.8"/></svg><UiSelect :model-value="String(activeVideoProject.projectId || '')" :options="projectLinkOptions" :placeholder="availableProjects.length ? '关联项目' : '暂无项目'" :disabled="!availableProjects.length" @change="handleWorkbenchProjectChange" /></label>
          <label v-if="videoProjects.length > 1" class="workbench-task-switcher" aria-label="切换视频任务" data-tooltip="快速切换至其他视频创作任务"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 5h14M3 10h14M3 15h14"/></svg><UiSelect :model-value="String(activeVideoProject.id)" :options="videoTaskSwitchOptions" placeholder="切换其他视频任务" @change="switchActiveVideoTask" /></label>
          <input v-model="activeVideoProject.description" class="video-project-description" aria-label="任务描述" placeholder="添加任务描述…" />
          <span>Do / Seedance</span>
        </div>
      </div>
      <div class="workbench-head-actions">
        <span class="workbench-save-status" :class="projectSaveTone" :data-tooltip="projectSaveStatus || '任务修改会自动保存到数据库'"><i></i>{{ projectSaveLabel }}</span>
        <button class="workbench-sync-voices" type="button" data-tooltip="整理稳定声线文字与视觉指纹；Muse 不支持参考音频锁音色" @click="syncEpisodeConsistency"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><circle cx="18" cy="18" r="3"/></svg><span>整理声线与画面</span></button>
        <button class="workbench-sync-voices" style="border-color:#b45309;color:#b45309;background:#fffbeb;font-weight:600" type="button" data-tooltip="打开专门的视频剪辑与衔接工坊" @click="$emit('open-video-editor', activeVideoProject)">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>
          <span>视频剪辑与衔接</span>
        </button>
        <button class="workbench-sync-voices" type="button" @click="openProjectFinishedPreview(activeVideoProject)">连续预览与导出</button>
        <button class="workbench-add-shot" type="button" @click="addStoryboard"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><span>新增分镜</span></button>
      </div>
    </header>


    <div v-show="props.productionView!=='review'" class="video-workbench-layout" ref="productionCanvasRef">
      <aside v-show="!props.embedded || materialDrawer" class="asset-rail">
        <div class="asset-rail-head">
          <div><h2>{{ isGeneral ? '作品素材' : props.embedded ? '资产图片 · 在这里生成' : '资产数据' }}</h2><span>JSON ASSETS</span></div>
          <div class="asset-rail-head-actions">
            <b>{{ displayedAssets.length }}</b>
            <button v-if="props.embedded" class="production-material-close" aria-label="关闭素材库" @click="materialDrawer=false">×</button>
            <div class="asset-actions-wrap" @mouseenter="showAssetActions" @mouseleave="hideAssetActions">
              <button type="button" class="asset-actions-trigger" :class="{ active: assetActionsOpen }" :aria-expanded="assetActionsOpen" aria-label="操作" data-tooltip="操作" @click.stop="toggleAssetActions">
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/></svg>
              </button>
              <section v-if="assetActionsOpen" class="asset-actions-popover" :style="props.embedded ? assetActionsStyle : null" aria-label="操作菜单" @click.stop>
                <header><div><strong>操作</strong><small>导入、模型与批量任务</small></div><span>{{ displayedAssets.filter(asset => !assetUrl(asset)).length }} 项待生成</span></header>
                <button class="asset-action-import" type="button" @click="openImportDialog">
                  <span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 15v4h14v-4"/></svg></span>
                  <div><strong>{{ importedFileName ? '重新导入创作数据' : '导入创作数据 JSON' }}</strong><small>{{ importedSummary }}</small></div>
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
                </button>
                <button class="asset-action-ai" type="button" @click="openCreationAiDialog">
                  <span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3ZM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z"/></svg></span>
                  <div><strong>AI 生成创作数据</strong><small>{{ textModels.length ? '输入故事，自动整理成可导入 JSON' : '先在设置中添加文本模型 API' }}</small></div>
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
                </button>
                <label class="asset-action-model"><span>图片生成模型</span><UiSelect v-model="selectedImageModel" :options="imageModelOptions" :placeholder="loading ? '正在加载模型…' : '选择图片模型'" :disabled="loading || !imageModels.length" status badge="IMAGE" /></label>
                <label v-if="audioModels.length" class="asset-action-model"><span>音频生成模型</span><UiSelect v-model="selectedAudioModel" :options="audioModelOptions" :placeholder="loading ? '正在加载模型…' : '选择音频模型'" :disabled="loading || !audioModels.length" status badge="AUDIO" /></label>
                <label class="asset-action-model"><span>API 视频模型</span><UiSelect v-model="defaultSeedanceModel" :options="seedanceModelOptions" :placeholder="loading ? '正在加载模型…' : '选择视频模型'" :disabled="loading || !seedanceModelOptions.length" status badge="VIDEO" @update:model-value="applyDefaultVideoModelToAll" /></label>

                <button class="asset-action-generate-all" :class="{ 'is-generating': bulkGenerating }" type="button" :disabled="assetLibrarySyncing || (!bulkGenerating && !displayedAssets.length)" @click.stop="bulkGenerating ? cancelBulkGeneration() : generateAllMissingAssets">
                  <span v-if="bulkGenerating" class="asset-generate-spinner"></span>
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/><path d="m18 15 .8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15Z"/></svg>
                  <div><strong>{{ bulkGenerating ? '⏹ 终止批量生成' : '一键生成全部' }}</strong><small>{{ activeCategory === 'all' ? '生成全部分类，自动跳过已有资产' : `仅生成当前「${categories.find(item => item.key === activeCategory)?.label || '分类'}」` }}</small></div>
                  <b>{{ displayedAssets.filter(asset => !assetUrl(asset) || asset.previewFailed).length }}</b>
                </button>
                <button class="asset-action-sync-chapter" type="button" :disabled="assetLibrarySyncing || bulkGenerating || !activeLinkedProjectId()" @click="syncFromLinkedChapter">
                  <span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg></span>
                  <div><strong>从母剧本重新同步分镜</strong><small>{{ activeLinkedProjectId() ? `一键补齐 · ${linkedProjectName()}` : '请先关联母剧本项目' }}</small></div>
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
                </button>
                <div class="asset-action-library-grid">
                  <button type="button" :disabled="assetLibrarySyncing || bulkGenerating || !assets.length || !activeLinkedProjectId()" @click="syncAssetsToLibrary">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0-12L7.5 7.5M12 3l4.5 4.5M5 15v5h14v-5"/></svg>
                    <span><strong>同步到我的资产</strong><small>{{ activeLinkedProjectId() ? `自动绑定 · ${linkedProjectName()}` : '请先关联项目' }}</small></span>
                  </button>
                  <button type="button" :disabled="assetLibrarySyncing || bulkGenerating || !assets.length || !activeLinkedProjectId()" @click="restoreAssetsFromLibrary">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h11a5 5 0 0 1 0 10H9"/><path d="m8 4-4 4 4 4"/></svg>
                    <span><strong>从我的资产回显</strong><small>{{ activeLinkedProjectId() ? `仅匹配 · ${linkedProjectName()}` : '请先关联项目' }}</small></span>
                  </button>
                </div>
                <p v-if="assetLibraryStatus || bulkGenerationStatus || importError" :class="{ error: importError || bulkGenerationStatus === '请先选择图片模型' || assetLibraryStatus.includes('失败') }">{{ importError || assetLibraryStatus || bulkGenerationStatus }}</p>
              </section>
            </div>
          </div>
        </div>
        <section v-if="props.embedded" class="production-image-tools" aria-label="参考图生成">
          <label><span>生图模型</span><UiSelect v-model="selectedImageModel" :options="imageModelOptions" :placeholder="loading ? '正在加载模型…' : '请先配置生图模型'" :disabled="loading || !imageModels.length" aria-label="参考图生图模型" /></label>
          <button v-if="!isGeneral" class="drama-generate-missing" :disabled="assetLibrarySyncing || (!bulkGenerating && !displayedAssets.some(asset => !assetUrl(asset)))" @click="bulkGenerating ? cancelBulkGeneration() : generateAllMissingAssets()">{{ bulkGenerating ? '终止批量生成' : '生成当前分类缺失图片' }}</button>
          <p>点击素材的“生成图片”，生成后可加入当前镜头；也可点图片编辑提示词或上传本地图。</p>
          <button v-if="!loading && !imageModels.length" @click="emit('request-model-settings')">添加生图模型</button>
        </section>
        <nav class="asset-category-tabs" aria-label="资产分类">
          <button v-for="category in categories" :key="category.key" type="button" :class="{ active: activeCategory === category.key }" @click="activeCategory = category.key">
            <svg v-if="category.key === 'all'" viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/></svg>
            <svg v-else-if="category.key === 'role'" viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.5"/><path d="M5 20c.8-4.2 3.1-6.3 7-6.3s6.2 2.1 7 6.3"/></svg>
            <svg v-else-if="category.key === 'scene'" viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m5.5 17 4.3-4.2 3 3 2.5-2.5 3.2 3.7"/><circle cx="9" cy="9" r="1.4"/></svg>
            <svg v-else-if="category.key === 'prop'" viewBox="0 0 24 24"><path d="m7 17 10-10M14 5l5 5M5 14l5 5M4 20l3-3"/></svg>
            <svg v-else-if="category.key === 'layout'" viewBox="0 0 24 24"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></svg>
            <svg v-else viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg>
            <span>{{ category.label }}</span>
          </button>
        </nav>
        <div v-if="activeCategory === 'audio'" class="asset-audio-subtabs">
          <button
            type="button"
            class="asset-audio-subtab"
            :class="{ active: activeAudioSubCategory === 'all' }"
            @click="activeAudioSubCategory = 'all'"
          >
            全部 <b class="subtab-count">{{ audioCountAll }}</b>
          </button>
          <small>角色配音请在分镜“声音与配音”中制作</small>
          <button
            type="button"
            class="asset-audio-subtab sfx-subtab"
            :class="{ active: activeAudioSubCategory === 'sfx' }"
            @click="activeAudioSubCategory = 'sfx'"
          >
            🔊 音效 <b class="subtab-count">{{ audioCountSfx }}</b>
          </button>
        </div>
        <div class="asset-rail-scroll">
          <p v-if="error" class="asset-rail-state error">{{ error }}</p>
          <div v-if="displayedAssets.length" class="asset-rail-grid">
            <article v-for="asset in displayedAssets" :key="asset.id" class="asset-pick-card" :class="{ missing: !assetUrl(asset) || asset.previewFailed, generating: asset.generating }">
              <button v-if="assetUrl(asset) && !asset.previewFailed" type="button" class="asset-preview-button" :data-tooltip="`查看和编辑 ${asset.name}`" @click="openAssetDetail(asset)">
                <img v-if="asset.type !== 'audio'" :src="assetUrl(asset)" :alt="asset.name" @error="handleReferencePreviewError(asset)" />
                <span v-else :class="['asset-audio-placeholder', getAudioSubType(asset)]">
                  <svg viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg>
                </span>
              </button>
              <button v-else type="button" class="asset-missing-preview" :data-tooltip="`查看和编辑 ${asset.name}`" @click="openAssetDetail(asset)">
                <svg v-if="asset.category !== 'audio'" viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m6 17 4-4 3 3 2.5-2.5L19 17"/></svg>
                <div v-else :class="['asset-audio-placeholder', getAudioSubType(asset), 'missing']">
                  <svg v-if="getAudioSubType(asset) === 'voice'" viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3M8 22h8"/></svg>
                  <svg v-else viewBox="0 0 24 24"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
                </div>
                <span v-if="asset.category !== 'audio'">{{ asset.previewFailed ? '图片失效·点击补生' : '暂无图片' }}</span>
              </button>
              <span v-if="assetReferenceState(asset).total" class="asset-reference-count" :class="{ incomplete: assetReferenceState(asset).ready < assetReferenceState(asset).total }" :title="`${assetReferenceState(asset).ready}/${assetReferenceState(asset).total} 张参考图已就绪`"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="6" width="13" height="12" rx="2"/><path d="m7 15 3-3 2.5 2.5 2-2 2.5 2.5M8 6V4h12v11h-3"/></svg>{{ assetReferenceState(asset).ready }}/{{ assetReferenceState(asset).total }}</span>
              <div v-if="asset.generating && asset.category !== 'audio'" class="asset-image-generating" aria-live="polite" aria-label="正在生成图片"><i></i></div>
              <button type="button" class="asset-pick-copy" @click="openAssetDetail(asset)">
                <div class="asset-pick-title-row">
                  <strong :title="asset.name">{{ asset.name }}</strong>
                  <span v-if="asset.category === 'audio'" :class="['asset-audio-tag', getAudioSubType(asset)]">
                    {{ getAudioSubType(asset) === 'voice' ? '🎙️ 语音' : '🔊 音效' }}
                  </span>
                </div>
                <small v-if="asset.category === 'audio'">
                  <template v-if="getAudioSubType(asset) === 'voice'">
                    {{ assetUrl(asset) ? `已生成 · ${asset.duration || '音频就绪'}` : (getVoiceShortName(asset.voice) ? `待生成 (${getVoiceShortName(asset.voice)})` : '待生成语音') }}
                  </template>
                  <template v-else>
                    {{ assetUrl(asset) ? `已导入 · ${asset.duration || '音效就绪'}` : '待导入本地 MP3' }}
                  </template>
                </small>
                <small v-else>{{ assetUrl(asset) ? (asset.duration || categories.find(item => item.key === asset.category)?.label || '资产') : `${categories.find(item => item.key === asset.category)?.label || '资产'} · 待生成` }}</small>
              </button>
              <template v-if="!assetUrl(asset)">
                <button
                  v-if="asset.category === 'audio' && getAudioSubType(asset) === 'sfx'"
                  type="button"
                  class="asset-card-generate sfx-direct-import"
                  aria-label="从电脑导入本地 MP3/WAV 音效"
                  data-tooltip="从电脑导入本地 MP3/WAV 音效"
                  @click.stop="selectLocalImageForAsset(asset)"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5"/></svg>
                  <em>导入音效</em>
                </button>
                <button
                  v-else
                  type="button"
                  class="asset-card-generate"
                  :class="{ 'is-generating': asset.generating }"
                  :aria-label="asset.generating ? '终止生成' : asset.category === 'audio' ? '生成语音' : '生成图片'"
                  :data-tooltip="asset.generating ? '终止生成' : asset.category === 'audio' ? '生成语音' : '生成图片'"
                  @click.stop="asset.generating ? cancelAsset(asset) : generateAsset(asset)"
                >
                  <span v-if="asset.generating" class="asset-generate-spinner"></span>
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/></svg>
                  <em>{{ asset.generating ? '终止' : asset.category === 'audio' ? '生成语音' : '生成图片' }}</em>
                </button>
              </template>
              <template v-else-if="asset.category === 'audio'">
                <button
                  type="button"
                  class="asset-card-add audio-toggle-btn"
                  :class="{ 'is-attached': isAssetInActiveShot(asset) }"
                  :aria-label="isAssetInActiveShot(asset) ? `从当前分镜撤回/移出 ${asset.name}` : `添加 ${asset.name} 到当前分镜`"
                  :data-tooltip="isAssetInActiveShot(asset) ? '已关联到当前分镜（点击撤回/移出）' : '点击添加到当前分镜'"
                  @click.stop="toggleAudioReference(asset)"
                >
                  <svg v-if="!isAssetInActiveShot(asset)" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>
                  <em>{{ isAssetInActiveShot(asset) ? '已添加(撤回)' : '添加到分镜' }}</em>
                </button>
              </template>
              <button v-else type="button" class="asset-card-add" :aria-label="`添加 ${asset.name} 到当前分镜`" data-tooltip="添加到分镜" @click.stop="addReference(asset)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg><em>添加到分镜</em></button>
              <p v-if="asset.generationError" class="asset-card-error" :data-tooltip="asset.generationError">{{ asset.generationError }}</p>
            </article>
          </div>
          <div v-else class="asset-rail-empty">
            <span class="asset-rail-empty-icon"><svg viewBox="0 0 64 48" aria-hidden="true"><path d="M7 40 23.4 17.5a3 3 0 0 1 4.9.1l8.1 11 5-6.4a3 3 0 0 1 4.8.1L57 40H7Z" /><circle cx="43" cy="14" r="5" /></svg></span>
            <strong>还没有资产数据</strong>
            <small>导入 JSON 文件或点击上方「上传资产」开始</small>
          </div>
        </div>
      </aside>

      <div v-show="!(props.embedded && !isGeneral && materialDrawer)" class="storyboard-column-shell">
        <div class="storyboard-column-head">
          <nav v-if="props.embedded && isGeneral" class="production-rail-tabs" aria-label="制作素材导航">
            <button type="button" :class="{active:!materialDrawer}" :aria-pressed="!materialDrawer" @click="materialDrawer=false">镜头 <b>{{ storyboards.length }}</b></button>
            <button type="button" :class="{active:materialDrawer}" :aria-pressed="materialDrawer" @click="materialDrawer=true">素材与生图 <b>{{ assets.length }}</b></button>
          </nav>
          <template v-else><div><h2>{{ isGeneral ? '镜头编排' : '分镜' }}</h2><span>STORYBOARDS</span></div><b>{{ storyboards.length }} 个镜头</b></template>
          <label v-if="props.embedded && !isGeneral && storyboards.length > 6" class="drama-shot-picker">当前镜头<select aria-label="选择制作镜头" v-model="activeShotId"><option v-for="(shot,index) in storyboards" :key="shot.id" :value="shot.id">{{ String(index+1).padStart(2,'0') }} · {{ shot.title }} · {{ shot.duration }}秒</option></select></label>
          <div v-if="props.embedded && !isGeneral" class="drama-shot-tools"><button @click="syncEpisodeConsistency">统一声音与画面</button><button @click="addStoryboard">＋ 新增镜头</button></div>
        </div>

        <!-- 短剧多集分镜切换与导入栏 -->
        <div v-if="dramaChapters.length > 0 && !isGeneral" class="workbench-episode-bar">
          <div class="workbench-episode-chips">
            <button
              v-for="chapter in dramaChapters"
              :key="chapter.id"
              type="button"
              class="workbench-episode-chip"
              :class="{
                active: currentChapterId === String(chapter.id),
                'has-shots': getChapterShotCount(chapter.id) > 0
              }"
              @click="switchChapter(chapter.id)"
            >
              <span class="episode-chip-tag">📑</span>
              <strong class="episode-chip-title">{{ chapter.title || '未命名集' }}</strong>
              <small class="episode-chip-count">{{ getChapterShotCount(chapter.id) }} 镜</small>
            </button>
          </div>
          <div class="workbench-episode-tools">
            <button
              type="button"
              class="workbench-episode-sync-btn"
              :disabled="assetLibrarySyncing"
              data-tooltip="从短剧助手重新同步当前集的分镜与资产"
              @click="syncCurrentChapterFromScript"
            >
              <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              <span>{{ assetLibrarySyncing ? '同步中…' : '从剧本同步当前集分镜' }}</span>
            </button>
          </div>
        </div>

        <nav v-if="storyboards.length > 1 || props.embedded" v-show="!(props.embedded && isGeneral && materialDrawer) && !(props.embedded && !isGeneral && storyboards.length > 6)" class="storyboard-shot-tabs" aria-label="选择要编辑的分镜">
          <button
            v-for="(shot, shotIndex) in storyboards"
            :key="`storyboard-tab-${shot.id}`"
            type="button"
            :class="{
              active: activeShotId === shot.id,
              running: shotRunning(shot),
              complete: Boolean(shot.resultUrl) && shot.resultValidation?.passed !== false && !shot.generationError && !hasRejectedReferences(shot) && !hasFailedAttempt(shot) && !(shot.referenceReview?.status === 'pending' && shot.referenceReview?.fileId === shot.resultFileId),
              error: Boolean(shot.generationError) || shot.resultValidation?.passed === false || hasRejectedReferences(shot) || ['failed', 'error', 'rejected', 'expired'].includes(shot.lastGenerationAttempt?.status),
            }"
            :aria-current="activeShotId === shot.id ? 'page' : undefined"
            :title="`${String(shotIndex + 1).padStart(2, '0')} · ${shot.title || '未命名分镜'}`"
            @click.stop="activeShotId = shot.id; visibleStoryboardAnchorId = shot.id"
          >
            <span>{{ String(shotIndex + 1).padStart(2, '0') }}</span>
            <strong>{{ shot.title || `分镜 ${shotIndex + 1}` }}</strong>
            <small v-if="props.embedded">{{ shot.duration }}s · {{ shot.resultUrl ? '有视频' : '待制作' }}</small><i aria-hidden="true"></i>
          </button>
        </nav>
      <section ref="storyboardColumnRef" class="storyboard-column" :class="{ 'single-shot': storyboards.length === 1 }" @scroll.passive="scheduleVisibleStoryboardAnchorUpdate">

        <article v-for="(shot, shotIndex) in storyboards" v-show="activeShotId === shot.id" :key="shot.id" :ref="element => setStoryboardCardRef(element, shot.id)" class="storyboard-card" :class="{ active: activeShotId === shot.id }" tabindex="0" @click="activeShotId = shot.id" @focusin="activeShotId = shot.id">
          <div class="shot-body-grid">
            <div class="shot-content" :class="{ expanded: shot.expanded }">
              <header class="storyboard-card-head">
                <span class="shot-number">{{ String(shotIndex + 1).padStart(2, '0') }}</span>
                <input v-model="shot.title" aria-label="分镜名称" />
                <nav v-if="props.embedded && isGeneral" class="production-shot-stepper" aria-label="切换当前镜头">
                  <button type="button" aria-label="上一个镜头" :disabled="shotIndex===0" @click.stop="activeShotId=storyboards[shotIndex-1].id">‹</button>
                  <small>{{ shotIndex+1 }} / {{ storyboards.length }}</small>
                  <button type="button" aria-label="下一个镜头" :disabled="shotIndex===storyboards.length-1" @click.stop="activeShotId=storyboards[shotIndex+1].id">›</button>
                </nav>
                <button type="button" :disabled="storyboards.length === 1" aria-label="删除分镜" @click.stop="removeStoryboard(shot.id)">×</button>
              </header>

              <section v-if="assemblyRepairGuidance?.projectId===String(activeVideoProject?.id)&&assemblyRepairGuidance?.shotId===String(shot.id)" class="assembly-repair-guidance shot-validation-banner" role="status" style="display:block;white-space:normal">
                <strong>组片接点修复建议</strong><p style="white-space:pre-wrap">{{assemblyRepairGuidance.action}}</p><p>先核对本镜开头与前镜结尾的持物、视线和动作阶段，再按原流程生成候选。原视频保留；此建议不代表画面已通过检查。</p><button type="button" @click="assemblyRepairGuidance=null">收起建议</button>
              </section>
              <div v-if="shot.resultValidation?.passed === false" class="shot-validation-banner" role="alert">
                <strong>时长不符</strong><span>{{ shot.resultValidation.reason }}。请重新生成本镜。</span>
              </div>
              <p v-if="shot.referenceRepairNotice" class="shot-reference-notice">{{ shot.referenceRepairNotice }}</p>
              <nav class="shot-workspace-tabs" aria-label="分镜工作区">
                <button type="button" :class="{ active: shot.workspaceTab !== 'audio' }" :aria-pressed="shot.workspaceTab !== 'audio'" @click.stop="selectShotTab(shot, 'visual')">{{ isGeneral ? '画面与文案' : '画面与提示词' }}</button>
                <button type="button" :class="{ active: shot.workspaceTab === 'audio' }" :aria-pressed="shot.workspaceTab === 'audio'" @click.stop="selectShotTab(shot, 'audio')">{{ isGeneral ? '旁白与声音' : '声音与配音' }} <span>{{ shotAttachedAudios(shot).length || '' }}</span></button>
              </nav>
              <div v-if="props.embedded && !isGeneral && shot.workspaceTab !== 'audio'" class="drama-reference-heading"><strong>参考图片与画面描述</strong><button type="button" @click.stop="materialDrawer=true">去生成 / 选择资产图 →</button></div>
            <p v-if="shot.generationEngine === 'seedance'" class="shot-reference-manifest" :class="{ 'has-images': seedancePreviewReferences(shot).length > 0 }">{{ shotReferenceManifestText(shot) }}</p>
              <div v-show="shot.workspaceTab !== 'audio' || shot.expanded" class="storyboard-compose">
            <div class="reference-stack" :class="{ expanded: props.embedded || shot.referencesExpanded, 'has-references': shot.references.length }" :style="{ '--reference-expanded-width': `${Math.min(520, 78 + shot.references.length * 85)}px` }" @mouseenter="!props.embedded && shot.references.length && (shot.referencesExpanded = true)" @mouseleave="!props.embedded && (shot.referencesExpanded = false)">
              <button type="button" class="reference-add" data-tooltip="从本地上传图片或音频" @click.stop="uploadLocalReference(shot)"><span>＋</span><small>本地上传</small></button>
              <div
                v-for="(asset, index) in shot.references"
                :key="asset.id"
                class="reference-card"
                :class="{ 'stack-hidden': index < shot.references.length - 3 }"
                :style="{
                  '--stack-index': index,
                  '--stack-x': `${stackSlot(index, shot.references.length) * 9}px`,
                  '--stack-y': `${(2 - stackSlot(index, shot.references.length)) * -2}px`,
                  '--stack-angle': `${(stackSlot(index, shot.references.length) - 2) * 4}deg`
                }"
                :data-tooltip="referenceCardTooltip(asset)"
                data-tooltip-pos="top"
              >
                <img v-if="assetUrl(asset) && !isAudioAsset(asset) && !asset.previewFailed" :src="assetUrl(asset)" :alt="asset.name" data-tooltip="点击放大查看" @error="handleReferencePreviewError(asset)" @click.stop="openReferencePreview(asset)" />
                <span v-else><svg v-if="isAudioAsset(asset)" viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg><svg v-else viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m6 17 4-4 3 3 2.5-2.5L19 17"/></svg></span>
                <small>{{ asset.name }}</small>
                <em v-if="asset.uploading" class="reference-upload-state"><i></i>上传中</em>
                <em v-else-if="asset.generationError" class="reference-upload-state error" :data-tooltip="asset.generationError">上传失败</em>
                <button type="button" aria-label="移除参考资产" @click.stop="removeReference(shot, asset.id)">×</button>
              </div>
              <span v-if="!props.embedded && shot.references.length && !shot.referencesExpanded" class="reference-stack-add">＋</span>
            </div>

            <StoryboardMentionEditor v-if="!shot.sendPreview" v-model="shot.prompt" class="storyboard-prompt-editor" :assets="allAvailableAssetsForEditor(shot)" :labels="shot.referenceLabels" placeholder="描述分镜内容，输入 @ 选择已上传素材…" @select-asset="selectMentionAsset(shot, $event)" />
            <div v-else class="storyboard-send-preview" :class="`engine-${shot.generationEngine || 'doubao'}`" role="region" :aria-label="`实际发送给 ${generationEngineLabel(shot)} 的内容`"><header><svg viewBox="0 0 24 24"><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/></svg><strong>实际发送内容 · {{ generationEngineLabel(shot) }}</strong><span>{{ sendPreviewSummary(shot) }}</span></header><pre>{{ sendPreviewText(shot) }}</pre></div>
            <div class="shot-editor-actions">
              <button
                class="shot-prompt-optimize"
                :class="{ 'has-error': Boolean(shot.lastGenerationAttempt?.error || shot.generationError) }"
                type="button"
                :disabled="shot.optimizingPrompt"
                :aria-label="shot.lastGenerationAttempt?.error || shot.generationError ? '根据报错优化提示词' : '优化提示词'"
                :data-tooltip="shot.optimizingPrompt ? '正在针对报错与上下文动态优化提示词…' : ((shot.lastGenerationAttempt?.error || shot.generationError) ? '⚠️ 检测到生成异常：点击根据报错原因自动纠偏润色提示词' : '智能润色优化分镜提示词（剔除违规敏感词与冲突表述）')"
                @click.stop="optimizeShotPrompt(shot)"
              >
                <span v-if="shot.optimizingPrompt" class="asset-generate-spinner"></span>
                <svg v-else viewBox="0 0 24 24"><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><circle cx="5" cy="6" r="1.5"/><circle cx="18" cy="18" r="1.5"/></svg>
              </button>
              <button class="shot-audio-boost" type="button" aria-label="整理声音描述" data-tooltip="声线与逐句语气分开，去重并保留原台词；不自动添加喘息" @click.stop="applySixDimAudioFormulaToShot(shot)"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg></button>
              <button class="shot-visual-boost" type="button" aria-label="视觉指纹与空间锚点锁定" data-tooltip="注入出场角色的常驻外貌特征与场景光影空间锚点，锁定面部与环境杜绝换脸跳轴" @click.stop="applyVisualFingerprintToShot(shot)"><svg viewBox="0 0 24 24"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg></button>
              <button v-if="shot.expanded" class="shot-send-preview-toggle" :class="{ active: shot.sendPreview }" type="button" :aria-pressed="shot.sendPreview" :aria-label="shot.sendPreview ? '返回编辑内容' : '查看实际发送内容'" :data-tooltip="shot.sendPreview ? '返回编辑内容' : '查看实际发送内容'" @click.stop="toggleSendPreview(shot)"><svg v-if="!shot.sendPreview" viewBox="0 0 24 24"><path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/></svg><svg v-else viewBox="0 0 24 24"><path d="m4 4 16 16M10.7 6.2A8 8 0 0 1 12 6c5.5 0 9 6 9 6a14 14 0 0 1-2.1 2.8M6.3 6.3C4.2 7.8 3 10 3 12c0 0 3.5 6 9 6a8 8 0 0 0 3.3-.7"/></svg></button>
              <button class="shot-expand" type="button" :aria-label="shot.expanded ? '退出分镜放大' : '放大分镜内容'" :data-tooltip="shot.expanded ? '退出放大' : '放大分镜内容'" @click.stop="toggleShotExpanded(shot)"><svg v-if="!shot.expanded" viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg><svg v-else viewBox="0 0 24 24"><path d="M3 8h5V3M21 8h-5V3M3 16h5v5M21 16h-5v5"/></svg></button>
            </div>
          </div>

              <component :is="props.embedded && !isGeneral ? 'details' : 'div'" class="shot-advanced-section">
                <summary v-if="props.embedded && !isGeneral">动作、场景与接镜设置 <small>展开查看与调整</small></summary>
              <p v-if="performanceReviewMessage(shot)" class="performance-update-note" role="status">{{ performanceReviewMessage(shot) }}</p>
              <details v-if="shot.continuityState?.persistentFacts?.length || shot.continuityState?.facts?.length" class="performance-update-note">
                <summary>剧情状态 · {{ shot.continuityState.phase || '延续前镜事实' }}</summary>
                <p v-for="(fact, factIndex) in (shot.continuityState.persistentFacts || shot.continuityState.facts)" :key="factIndex">{{ fact }}</p>
              </details>
              <details v-if="shot.actionChain?.requiredActions?.length" class="performance-update-note">
                <summary>动作顺序 · {{ shot.actionChain.requiredActions.length }} 步</summary>
                <p>起点：{{ shot.actionChain.start }}</p>
                <p v-for="(action, actionIndex) in shot.actionChain.requiredActions" :key="actionIndex">{{ actionIndex + 1 }}. {{ action }}</p>
                <p>终点：{{ shot.actionChain.end }}</p>
              </details>
                        <!-- 专属上一镜尾帧衔接卡 (Tail Frame Continuity) -->
              <button v-if="isGeneral && shot.workspaceTab!=='audio'" class="production-advanced-toggle" @click="shot.generalAdvanced=!shot.generalAdvanced">{{ shot.generalAdvanced ? '收起高级场景与衔接' : '高级场景与衔接' }}</button>
              <!-- 第1镜专属：向下一镜衔接过渡规划 -->
              <div v-else-if="shotIndex === 0 && storyboards.length > 1 && (!isGeneral || shot.generalAdvanced)" class="shot-continuity-slot is-first-shot" style="border:1px dashed #d97706;background:#fffaf0;border-radius:8px;padding:6px 10px;margin:6px 0">
                <div class="continuity-bar-top" style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
                  <div class="continuity-tag-group" style="display:flex;align-items:center;gap:8px">
                    <span class="continuity-badge" style="background:#fef3c7;color:#92400e;padding:3px 8px;border-radius:4px;font-weight:600;font-size:11px">🎬 首镜出场</span>
                    <strong style="color:#78350f;font-size:13px">下镜衔接规划 · 第 1 ➔ 2 镜过渡</strong>
                  </div>
                  <div class="continuity-actions" style="display:flex;gap:8px">
                    <button type="button" class="continuity-btn-tool" style="background:#b45309;color:#fff;border-color:#b45309;font-weight:600;padding:5px 12px;border-radius:6px;cursor:pointer" @click.stop="$emit('open-video-editor', activeVideoProject)">
                      ✂️ 打开视频剪辑与衔接工坊
                    </button>
                    <button type="button" class="continuity-btn-tool" :class="{ active: shot.showOcclusionPanel }" style="padding:5px 10px;border-radius:6px;cursor:pointer;border:1px solid #d4c5b3;background:#fff" @click.stop="toggleOcclusionPanel(shot, shotIndex)">
                      🛡️ 本镜遮挡收尾设计
                    </button>
                  </div>
                </div>
                <div v-if="shot.showOcclusionPanel" class="continuity-occlusion-drawer" style="margin-top:10px">
                  <div class="occlusion-drawer-head">
                    <div class="occlusion-drawer-title">
                      <strong>🛡️ 第 1 镜收尾遮挡设计（让下一镜顺畅出遮挡）</strong>
                      <span>设计本镜末尾2秒遮挡物进入并覆盖视野，为第 2 镜出遮挡奠定基础</span>
                    </div>
                    <button type="button" class="occlusion-btn-apply-both" @click.stop="injectOcclusionToPrevShot(storyboards[1], 1)">
                      ⚡ 注入本镜末尾遮挡提示词
                    </button>
                  </div>
                  <p class="occlusion-step-formula">{{ prevShotOcclusionFormula(storyboards[1], 1) }}</p>
                </div>
              </div>

              <div v-if="shotIndex > 0 && (!isGeneral || shot.generalAdvanced)" class="shot-continuity-slot" :class="{ 'is-active': shot.inheritPrevTail !== false, 'is-disabled': shot.inheritPrevTail === false }">
                <div class="continuity-bar-top">
                  <div class="continuity-tag-group">
                    <span class="continuity-badge">🔗 尾帧接续</span>
                    <strong>衔接上一镜最新尾帧</strong>
                    <span class="continuity-scope-pill">{{ hasAuthoredCut(shot) ? '按剧本切镜 · 场景图' : shot.inheritPrevTail !== false ? '同场景连续动作' : '换场景/转场切镜' }}</span>
                  </div>
                  <label class="continuity-toggle-btn" :data-tooltip="shot.inheritPrevTail === false ? '点击开启（同场景连续动作自动继承上一镜尾帧）' : '点击关闭（适用于换场景或刻意切镜）'">
                    <input type="checkbox" :checked="shot.inheritPrevTail !== false" @change="toggleShotContinuity(shot, shotIndex, $event)" />
                    <span class="continuity-toggle-track"></span>
                    <em>{{ shot.inheritPrevTail === false ? '已关闭' : '已开启' }}</em>
                  </label>
                </div>

                <div v-if="sceneAnchorAsset(shot)" class="scene-anchor-hint">
                  <span v-if="gazeHandoffBeatFor(shot) && shot.gazeHandoff !== false">🎬 <strong>新场景定场锚</strong>：「{{ sceneAnchorAsset(shot).name }}」作为本场环境参考，第0秒由接镜点视角锁定。</span>
                  <span v-else>🎬 <strong>场景图基准</strong>：本镜按剪辑安排开始，使用「{{ sceneAnchorAsset(shot).name }}」约束空间和光线，人物按设定图入场，不同时锁定上一镜尾帧。</span>
                </div>

                <div v-if="gazeHandoffBeatFor(shot)" class="gaze-handoff-hint" :class="{ 'is-off': shot.gazeHandoff === false }">
                  <span>👁 <strong>接镜点视角</strong>：上一镜以「{{ gazeHandoffBeatFor(shot) }}」结束，{{ shot.gazeHandoff === false ? '已关闭，本镜按定场图开场。' : '生成时复用上一镜真实尾帧作为第0秒，沿视线切入本场。' }}</span>
                  <button type="button" @click.stop="toggleGazeHandoff(shot)">{{ shot.gazeHandoff === false ? '开启接镜点' : '关闭接镜点' }}</button>
                </div>

                <div v-if="shot.inheritPrevTail !== false" class="continuity-bar-content">
                  <div class="continuity-mode-switch">
                    <button type="button" :class="{ active: resolvedContinuityMode(shot) === 'exact' }" @click.stop="setContinuityMode(shot, shotIndex, 'exact')">
                      <strong>动作无缝续接</strong>
                      <small>{{ roleHandoffPlan(storyboards,shot) ? '真实尾帧 + 新入画人物参考' : '真实尾帧 + 角色道具参考' }}</small>
                    </button>
                    <button type="button" :class="{ active: resolvedContinuityMode(shot) === 'transition' }" @click.stop="setContinuityMode(shot, shotIndex, 'transition')">
                      <strong>尾帧转场过渡</strong>
                      <small>尾帧起势 · 运镜融变（两者兼得）</small>
                    </button>
                    <button type="button" :class="{ active: resolvedContinuityMode(shot) === 'matchCut' }" @click.stop="setContinuityMode(shot, shotIndex, 'matchCut')">
                      <strong>换机位剪辑</strong>
                      <small>九宫格换景别 · 属于切镜</small>
                    </button>
                  </div>
                  <div v-if="storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover')" class="continuity-frame-card">
                    <div class="continuity-thumb-box" @click.stop="openReferencePreview({ cover: storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover'), name: `第 ${shotIndex} 镜尾帧` })">
                      <img :src="storedProjectMediaUrl(shot.continuityTailFrame, 'url', 'cover')" alt="上一镜尾帧" />
                      <span class="continuity-zoom-overlay">点击预览大图</span>
                    </div>
                    <div class="continuity-info-box">
                      <div class="continuity-info-head">
                        <span class="continuity-origin-label">来源: 第 {{ shotIndex }} 镜最新视频尾帧</span>
                        <span v-if="shot.continuityOutdated" class="continuity-pill-warning">⚠️ 上一镜已重新生成</span>
                        <span v-else class="continuity-pill-synced">✅ 已绑定为起步首帧</span>
                      </div>
                      <p v-if="roleHandoffPlan(storyboards,shot)" class="continuity-info-desc"><template v-if="roleHandoffPlan(storyboards,shot).phase === 'scripted'"><strong>按本镜剧本交接人物</strong>：保留{{ roleHandoffPlan(storyboards,shot).observerName }}与{{ roleHandoffPlan(storyboards,shot).actorName }}的身份，进场方式、持物和站位按下方画面描述执行。</template><template v-else-if="roleHandoffPlan(storyboards,shot).phase === 'inside'"><strong>屋内两人身份分别锁定</strong>：{{ roleHandoffPlan(storyboards,shot).observerName }}与{{ roleHandoffPlan(storyboards,shot).actorName }}分别继续各自的动作，不重新入屋。</template><template v-else><strong>{{ roleHandoffPlan(storyboards,shot).observerName }}留在原屋门口</strong>；{{ roleHandoffPlan(storyboards,shot).actorName }}从外面跑来，进入同一间屋。尾帧与少年参考一起发送，不能把观察者变成逃跑者。</template></p>
                      <p v-else-if="resolvedContinuityMode(shot) === 'exact'" class="continuity-info-desc">当前使用<strong>真实尾帧（首帧起点）+ 角色道具参考图</strong>：锁定第0秒起始构图，同时保持出场人物面貌与服装一致。</p>
                      <p v-else-if="resolvedContinuityMode(shot) === 'transition'" class="continuity-info-desc">当前使用<strong>尾帧转场过渡（两者兼得）</strong>：保留上一镜真实尾帧作为第0秒起势开场，运镜推进/后拉/环绕或光影融变到本镜新场景，衔接检查自动放行。</p>
                      <p v-else class="continuity-info-desc">当前使用<strong>换机位参考图</strong>：适合景别切换与匹配剪辑，不代表上一镜动作的逐帧延长。</p>
                      <div v-if="isSceneTransition(shot, shotIndex) && shot.inheritPrevTail !== false && !roleHandoffPlan(storyboards,shot)" class="scene-transition-hint">
                        <div class="scene-transition-title">
                          <span>💡 <strong>检测到换场景转场</strong>：既想接上上一镜尾帧、又想转入新场景？推荐以下【两者兼得】方案：</span>
                        </div>
                        <div class="scene-transition-actions">
                          <button type="button" class="btn-both-motion" title="保留尾帧首帧起点，让镜头在视频内极速后拉/穿云转入新场景" @click.stop="injectCameraTransition(shot, shotIndex)">
                            ⚡ 方案一：注入动态运镜转场（AI 镜头内融变）
                          </button>
                          <button type="button" class="btn-both-dissolve" title="采用新场景最高画质，两镜交接自动开启0.8秒电影叠化转场，且自动放行成片" @click.stop="setDissolveTransition(shot, shotIndex)">
                            🎬 方案二：剪辑叠化转场（两者兼得·最稳画质）
                          </button>
                          <button type="button" class="btn-both-cut" @click.stop="disableContinuityForShot(shot)">
                            ✂️ 直接硬切
                          </button>
                        </div>
                      </div>
                      <div v-if="hasFailedAttempt(shot) && shot.continuityReview?.status === 'passed'" class="continuity-review-alert is-historical" role="note">
                        <strong>历史视频的首帧检查记录</strong>
                        <span>此前版本曾通过首帧检查，与本次失败请求无关；本次没有新视频可检查。</span>
                      </div>
                      <div v-else-if="currentContinuityReview(shot)?.status === 'failed'" class="continuity-review-alert is-failed">
                        <div>
                          <strong>⚠️ 自动检查：这一镜没有接住尾帧</strong>
                          <span>生成结果首帧偏差过大（{{ Math.round(Number(shot.continuityReview.mae || 0) * 100) }}%）。候选结果已保留，请核对原片与裁切情况后重试。</span>
                          <small v-if="isSceneTransition(shot, shotIndex)" style="display:block;margin-top:4px;color:var(--theme-accent);">💡 本镜是换场景转场：若画面满意，可直接点击右侧「采纳为转场成片」，将自动配置剪辑叠化过渡并放行！</small>
                          <small v-else style="display:block;margin-top:4px;opacity:0.85;">同一场景的新人物入画仍应保留尾帧续接；只有确实要切换场景或机位时，才使用“转场切镜”。</small>
                        </div>
                        <div class="continuity-review-actions">
                          <button type="button" class="continuity-accept-transition-btn" style="background:#0284c7;color:#fff;font-weight:600" @click.stop="setContinuityMode(shot, shotIndex, 'transition')">🎬 转为尾帧转场（两者兼得·立即采用）</button>
                          <button v-if="isSceneTransition(shot, shotIndex)" type="button" class="continuity-accept-transition-btn" @click.stop="setDissolveTransition(shot, shotIndex)">🎬 采纳为叠化成片</button>
                          <button v-if="shot.continuityReview.generatedFirstFrameUrl" type="button" @click.stop="openReferencePreview({ cover: absoluteMediaUrl(shot.continuityReview.generatedFirstFrameUrl), name: 'Muse 实际生成首帧' })">查看实际首帧</button>
                          <button type="button" class="continuity-switch-cut-btn" @click.stop="disableContinuityForShot(shot)">转场切镜（关闭尾帧）</button>
                          <button type="button" class="is-primary" :disabled="shotRunning(shot)" @click.stop="generateShot(shot)">严格重试本镜</button>
                        </div>
                      </div>
                      <div v-else-if="currentContinuityReview(shot)?.status === 'passed'" class="continuity-review-alert is-passed">
                        <strong>✅ 自动检查：生成首帧已接住上一镜</strong>
                        <span>首帧偏差 {{ Math.round(Number(shot.continuityReview.mae || 0) * 100) }}%</span>
                      </div>
                      <div class="continuity-btn-row">
                        <button type="button" class="continuity-btn-refresh" :disabled="shot.extractingLastFrame" @click.stop="refreshShotContinuityFrame(shot, shotIndex)">
                          <span v-if="shot.extractingLastFrame" class="asset-generate-spinner"></span>
                          <span v-else>🔄 重新提取最新尾帧</span>
                        </button>
                        <button type="button" class="continuity-btn-tool" :class="{ active: shot.showMatrixPanel }" @click.stop="toggleMatrixPanel(shot, shotIndex)">
                          🎬 变焦九宫格
                        </button>
                        <button type="button" class="continuity-btn-tool" :class="{ active: shot.showTimelineScrubber }" @click.stop="toggleTimelineScrubber(shot, shotIndex)">
                          ⏱️ 动作断点截帧
                        </button>
                        <button type="button" class="continuity-btn-tool" :class="{ active: shot.showOcclusionPanel }" @click.stop="toggleOcclusionPanel(shot, shotIndex)">
                          🛡️ 遮挡过渡与运镜连续
                        </button>
                        <button type="button" class="continuity-btn-clear" @click.stop="clearShotContinuityFrame(shot)">
                          清除尾帧
                        </button>
                      </div>

                      <!-- 🎬 变焦九宫格抽屉面板 -->
                      <div v-if="shot.showMatrixPanel" class="continuity-matrix-drawer">
                        <div class="matrix-drawer-head">
                          <div class="matrix-drawer-title">
                            <strong>🎬 电影多机位索引矩阵 (3×3)</strong>
                            <span>从同光影、同人物的9个景别中，点选下镜所需机位作为首帧，彻底消除跳切</span>
                          </div>
                          <button v-if="!shot.cameraMatrixImage" type="button" class="matrix-btn-gen" :disabled="shot.generatingMatrix" @click.stop="generateCameraMatrix(shot, shotIndex)">
                            <span v-if="shot.generatingMatrix" class="btn-spinner"></span>
                            <span>{{ shot.generatingMatrix ? '正在生成 3×3 矩阵...' : '✨ 一键生成 3×3 镜头索引矩阵' }}</span>
                          </button>
                          <div v-else class="matrix-drawer-actions">
                            <button type="button" class="matrix-btn-preview" @click.stop="openReferencePreview({ cover: fileDownloadUrl(shot.cameraMatrixImage.fileId) || absoluteMediaUrl(shot.cameraMatrixImage.url), name: '3×3 镜头索引矩阵' })">
                              <span>🔍 查看总图</span>
                            </button>
                            <button type="button" class="matrix-btn-split" :disabled="shot.croppingMatrix || shot.generatingMatrix" @click.stop="extractAllMatrixCells(shot, shotIndex)">
                              <span v-if="shot.croppingMatrix" class="btn-spinner"></span>
                              <span>{{ shot.croppingMatrix ? '正在拆分…' : ((shot.cameraMatrixCells?.length || 0) >= 9 ? '✂️ 重新拆分九张' : '✂️ 拆出九张单图') }}</span>
                            </button>
                            <button type="button" class="matrix-btn-regen" :disabled="shot.generatingMatrix || shot.croppingMatrix" @click.stop="generateCameraMatrix(shot, shotIndex)">
                              <span>🔄 重新生成矩阵</span>
                            </button>
                          </div>
                        </div>

                        <div v-if="shot.cameraMatrixImage?.fileId || shot.cameraMatrixImage?.url" class="matrix-drawer-body">
                          <div class="matrix-preview-card" @click.stop="openReferencePreview({ cover: fileDownloadUrl(shot.cameraMatrixImage.fileId) || absoluteMediaUrl(shot.cameraMatrixImage.url), name: '3×3 镜头索引矩阵' })">
                            <img :src="fileDownloadUrl(shot.cameraMatrixImage.fileId) || absoluteMediaUrl(shot.cameraMatrixImage.url)" alt="3×3 矩阵" />
                            <span class="matrix-preview-tip">点击查看大图</span>
                          </div>
                          <div class="matrix-grid-picker">
                            <div class="matrix-grid-tip">
                              <span>👇 点击下方任意景别，系统自动无损切片并设置为本镜首帧：</span>
                            </div>
                            <div class="matrix-cells-grid">
                              <button
                                v-for="cell in CAMERA_MATRIX_CELLS"
                                :key="cell.index"
                                type="button"
                                class="matrix-cell-btn"
                                :class="{
                                  'is-recommended': getRecommendedMatrixCell(shot) === cell.index,
                                  'is-selected': shot.selectedMatrixCell === cell.index,
                                }"
                                :disabled="shot.croppingMatrix"
                                @click.stop="selectMatrixCell(shot, shotIndex, cell.index)"
                              >
                                <span v-if="getRecommendedMatrixCell(shot) === cell.index" class="cell-rec-tag">🎯 推荐机位</span>
                                <img v-if="matrixCellImage(shot, cell.index)" :src="matrixCellImage(shot, cell.index)" :alt="`${cell.name}单图`" />
                                <span v-else class="matrix-cell-placeholder"><i v-if="shot.croppingMatrix" class="btn-spinner"></i><b>{{ shot.croppingMatrix ? '拆分中' : String(cell.index + 1).padStart(2, '0') }}</b></span>
                                <span class="matrix-cell-copy"><strong>{{ cell.index + 1 }}. {{ cell.name }} ({{ cell.code }})</strong><small>{{ matrixCellImage(shot, cell.index) ? '点击设为首帧' : cell.desc }}</small></span>
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>

                      <!-- ⏱️ 动作断点截帧抽屉面板 -->
                      <div v-if="shot.showTimelineScrubber" class="continuity-scrubber-drawer">
                        <div class="scrubber-head">
                          <strong>⏱️ 动作断点时间轴截取</strong>
                          <span>解决上一镜动作未演完就截断（如刚摸到杯子还没喝）。截取动作发生那一瞬，下一镜续演完整动作！</span>
                        </div>
                        <div class="scrubber-controls">
                          <div class="scrubber-slider-row">
                            <label>截取位置: <b>{{ Math.round((shot.scrubFraction || 0.85) * 100) }}%</b> 处动作瞬间</label>
                            <input
                              type="range"
                              min="0.5"
                              max="1.0"
                              step="0.05"
                              :value="shot.scrubFraction || 0.85"
                              @input="shot.scrubFraction = parseFloat($event.target.value)"
                            />
                          </div>
                          <div class="scrubber-presets">
                            <button type="button" :class="{ active: shot.scrubFraction === 0.7 }" @click.stop="extractActionFrameAt(shot, shotIndex, 0.7)">70% (发力起势)</button>
                            <button type="button" :class="{ active: shot.scrubFraction === 0.8 }" @click.stop="extractActionFrameAt(shot, shotIndex, 0.8)">80% (动作半程)</button>
                            <button type="button" :class="{ active: shot.scrubFraction === 0.9 }" @click.stop="extractActionFrameAt(shot, shotIndex, 0.9)">90% (收势前瞬)</button>
                            <button type="button" :class="{ active: shot.scrubFraction === 0.98 }" @click.stop="extractActionFrameAt(shot, shotIndex, 0.98)">100% (末尾)</button>
                            <button type="button" class="btn-custom-scrub" :disabled="shot.extractingLastFrame" @click.stop="extractActionFrameAt(shot, shotIndex, shot.scrubFraction || 0.85)">
                              📌 截取选定时刻动作帧
                            </button>
                            <button type="button" class="btn-inject-relay" @click.stop="injectActionRelayPrompt(shot)">
                              ⚡ 注入动作顺接模板
                            </button>
                          </div>
                        </div>
                      </div>

                      <!-- 🛡️ 遮挡过渡与运镜动能连续抽屉面板 -->
                      <div v-if="shot.showOcclusionPanel" class="continuity-occlusion-drawer">
                        <div class="occlusion-drawer-head">
                          <div class="occlusion-drawer-title">
                            <strong>🛡️ 遮挡过渡与运镜动能连续（消顿防穿帮）</strong>
                            <span>运用【A段进入遮挡 · B段退出遮挡 · 动能守恒】技巧，把接缝藏在遮挡中，消除跳帧与刹车顿挫！</span>
                          </div>
                          <div class="occlusion-drawer-actions">
                            <button type="button" class="occlusion-btn-apply-both" @click.stop="applyOcclusionContinuityToShots(shot, shotIndex)">
                              ✨ 两镜联动一键注入（A进遮挡+B出遮挡）
                            </button>
                          </div>
                        </div>

                        <div class="occlusion-config-grid">
                          <div class="occlusion-config-col">
                            <label><strong>1. 运镜惯性方向（两镜同向同速连续）：</strong></label>
                            <div class="occlusion-pills-row">
                              <button
                                v-for="dir in CAMERA_MOMENTUM_DIRECTIONS"
                                :key="dir.id"
                                type="button"
                                class="occlusion-pill-btn"
                                :class="{ active: (shot.occlusionDirection || 'pan_right') === dir.id }"
                                @click.stop="shot.occlusionDirection = dir.id"
                              >
                                {{ dir.label }}
                              </button>
                            </div>
                          </div>

                          <div class="occlusion-config-col">
                            <label><strong>2. 遮挡物类型（符合当前场景，剪点处充分遮挡）：</strong></label>
                            <div class="occlusion-pills-row">
                              <button
                                v-for="occ in OCCLUSION_OBJECT_PRESETS"
                                :key="occ.id"
                                type="button"
                                class="occlusion-pill-btn"
                                :class="{ active: (shot.occlusionObject || 'smoke_fog') === occ.id }"
                                @click.stop="shot.occlusionObject = occ.id"
                              >
                                {{ occ.label }}
                              </button>
                            </div>
                          </div>
                        </div>

                        <div class="occlusion-preview-cards">
                          <div class="occlusion-step-card">
                            <header>
                              <strong>上一镜（第 {{ shotIndex }} 镜）收尾：最后约2秒进入遮挡</strong>
                              <button type="button" class="btn-step-inject" @click.stop="injectOcclusionToPrevShot(shot, shotIndex)">⚡ 注入上一镜末尾</button>
                            </header>
                            <p class="occlusion-step-formula">{{ prevShotOcclusionFormula(shot, shotIndex) }}</p>
                          </div>
                          <div class="occlusion-step-card">
                            <header>
                              <strong>本镜（第 {{ shotIndex + 1 }} 镜）开场：首帧顺滑退出遮挡</strong>
                              <button type="button" class="btn-step-inject is-primary" @click.stop="injectOcclusionToCurrentShot(shot, shotIndex)">⚡ 注入本镜开头</button>
                            </header>
                            <p class="occlusion-step-formula">{{ currentShotOcclusionFormula(shot, shotIndex) }}</p>
                          </div>
                        </div>

                        <div class="occlusion-checklist-box">
                          <div class="checklist-title"><strong>📋 镜头衔接六维验收标准：</strong></div>
                          <div class="checklist-grid">
                            <span>☑ 遮挡物符合剧情场景，出入移动自然</span>
                            <span>☑ 剪点处充分遮挡，可辨认细节已挡住</span>
                            <span>☑ 两段运镜方向严格一致，无突然折返</span>
                            <span>☑ 前后速度连续惯性，无停顿后重新起步</span>
                            <span>☑ 连接帧可辨认纹理极少，杜绝跳帧割裂</span>
                            <span>☑ 遮挡退出后人物、服装道具及动作符合剧情</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div v-else class="continuity-pending-box">
                    <svg viewBox="0 0 24 24"><path d="M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/></svg>
                    <span v-if="storyboards[shotIndex - 1]?.resultUrl || storyboards[shotIndex - 1]?.resultFileId || storyboards[shotIndex - 1]?.mixedVideoFileId">上一镜（第 {{ shotIndex }} 镜）视频已就绪，可立即提取动作尾帧作为本镜首帧起步参考。</span>
                    <span v-else>上一镜（第 {{ shotIndex }} 镜）尚未生成视频。开启后，将在上一镜视频生成完成后<strong>自动提取尾帧</strong>载入本镜。</span>
                    <button
                      v-if="storyboards[shotIndex - 1]?.resultUrl || storyboards[shotIndex - 1]?.resultFileId || storyboards[shotIndex - 1]?.mixedVideoFileId"
                      type="button"
                      class="continuity-btn-fetch"
                      :disabled="shot.extractingLastFrame"
                      @click.stop="refreshShotContinuityFrame(shot, shotIndex)"
                    >
                      <span v-if="shot.extractingLastFrame" class="btn-spinner"></span>
                      <span>{{ shot.extractingLastFrame ? '正在截取尾帧...' : '⚡ 立即提取上一镜尾帧' }}</span>
                    </button>
                  </div>
                </div>
              </div>

              <details v-show="!isGeneral || shot.generalAdvanced" class="narrative-transition" @toggle="$event.target.open && initialiseShotEnvironment(shot)">
                <summary>时间与天气 · {{ environmentAt(storyboards,shotIndex).timeOfDay || '沿用前镜' }} <small>{{ environmentAt(storyboards,shotIndex).weather }}</small></summary>
                <div class="transition-fields">
                  <p>{{ environmentInstruction(storyboards,shot) }}</p>
                  <template v-if="shot.environmentContinuity">
                    <label v-if="shotIndex>0"><span><input v-model="shot.environmentContinuity.reset" type="checkbox" />剧情明确跨时段或异地，重新设定环境</span></label>
                    <label>时间<input v-model="shot.environmentContinuity.timeOfDay" :disabled="shotIndex>0 && !shot.environmentContinuity.reset" placeholder="白天 / 黄昏 / 夜晚" /></label>
                    <label>天气<input v-model="shot.environmentContinuity.weather" :disabled="shotIndex>0 && !shot.environmentContinuity.reset" placeholder="晴天 / 雨天 / 雪天" /></label>
                  </template>
                  <p v-if="environmentConflicts(storyboards,shot).length" class="breeze-warning">{{ environmentConflicts(storyboards,shot).join('；') }}（提示：画面将按本镜正文描述光照生成）。</p>
                  <p v-if="shot.resultEnvironmentWarning" class="breeze-warning">{{ shot.resultEnvironmentWarning }}</p>
                  <small>连续剧情自动继承前镜；室内阴影不能当作夜晚。这里的约束会写入提示词顶部，已有视频需重新生成才会改变。</small>
                </div>
              </details>
              <details v-if="shot.narrativeTransition && shot.inheritPrevTail === false && (!isGeneral || shot.generalAdvanced)" class="narrative-transition">
                <summary>跨场景衔接 · 第 {{ shotIndex }} → {{ shotIndex + 1 }} 镜 <small>{{ shot.narrativeTransition.enabled === false || shot.narrativeTransition.strategy === 'none' ? '直接切镜' : '已写入提示词' }}</small></summary>
                <div class="transition-fields">
                  <label>衔接方式<UiSelect :model-value="shot.narrativeTransition.strategy" :options="TRANSITION_OPTIONS" @update:model-value="setTransitionStrategy(shot, $event)" /></label>
                  <label>上一镜怎么收尾<textarea v-model="shot.narrativeTransition.outgoing" rows="3" @change="scheduleProjectSave"></textarea></label>
                  <label>本镜怎么接入<textarea v-model="shot.narrativeTransition.incoming" rows="3" @change="scheduleProjectSave"></textarea></label>
                  <label>声音线索<textarea v-model="shot.narrativeTransition.cue" rows="2" @change="scheduleProjectSave"></textarea></label>
                  <small>安排会同步显示在相邻两镜提示词顶部；请在此调整。修改后需重新生成两镜，已有视频保持原样。新增对白请同时写入相应分镜台词。</small>
                </div>
              </details>
              <details v-if="storyboards[shotIndex + 1]?.narrativeTransition && storyboards[shotIndex + 1]?.inheritPrevTail === false && (!isGeneral || shot.generalAdvanced)" class="narrative-transition">
                <summary>下一场引子 · 第 {{ shotIndex + 1 }} → {{ shotIndex + 2 }} 镜</summary>
                <p>{{ storyboards[shotIndex + 1].narrativeTransition.outgoing }}</p>
                <small>在下一镜的「跨场景衔接」中统一调整。重新生成本镜时会带上这段收尾安排。</small>
              </details>
              </component>
          <BreezeDubbingPanel v-if="shot.workspaceTab === 'audio'" :prompt="shot.prompt" :quick="breezeQuickShotId === shot.id" :has-applied-audio="hasAppliedDubbing(shot)" :audio-applied="Boolean(shot.mixedVideoFileId === shot.resultFileId && shot.mixedAudioFileId && shot.mixedAudioFileId === String(breezeAudio(shot)?.fileId || breezeAudio(shot)?.coverId || ''))" :legacy-mix="Boolean(shot.mixedVideoFileId === shot.resultFileId && shot.mixedVideoFileId && !shot.breezeMixVersion)" :general="isGeneral" :contract="dialogueContract(shot.prompt)" :bindings="breezeBindings" :root="breezeRoot" :connection="breezeConnection" :connecting="breezeConnecting" :busy="breezeBusy || Boolean(breezeQuickShotId)" :progress="breezeProgress?.shotId === shot.id ? breezeProgress : null" :audio="breezeAudio(shot)" :stale="breezeAudioStale(shot)" :has-video="Boolean(shot.resultFileId)" :mixing="muxingShotId === shot.id" :mixed="Boolean(shot.originalVideoFileId && shot.mixedVideoFileId === shot.resultFileId)" :alignment="validBreezeAlignment(shot)" :aligning="breezeAlignProgress?.shotId === shot.id && breezeAlignProgress?.status === 'running'" :alignment-message="breezeAlignProgress?.shotId === shot.id ? breezeAlignProgress.message : ''" @binding="setBreezeBinding" @root="setBreezeRoot" @connect="connectBreeze()" @start="connectBreeze(true)" @quick="replaceShotDubbing(shot)" @play-current="previewBreezeCurrent(shot)" @generate="generateBreezeForShot(shot)" @convert="generateBreezeForShot(shot, 'voice-conversion')" @accept-review="acceptConversionReview(shot, $event)" @cancel="cancelBreeze" @play="togglePlayAudio(breezeAudio(shot))" @align="alignShotAudio(shot, true)" @mix="mixAlignedBreeze(shot)" @timing="updateBreezeTiming(shot, $event)" @preview="previewBreezeOriginal(shot, $event)" @restore="restoreBreezeVideo(shot)" />
          <details v-if="shot.workspaceTab === 'audio' && (!isGeneral || dialogueContract(shot.prompt).lines.length)" class="dialogue-extra"><summary>台词基准与核验</summary><div class="dialogue-controls">
              <span v-if="shot.dialogueBaseline?.explicit" style="color:var(--theme-accent-text);font-size:12px">{{ sameDialogue(shot.dialogueBaseline, dialogueContract(shot.prompt)) ? '台词基准已确认' : '台词已变动，请重新确认' }}</span>
              <button type="button" class="dialogue-confirm-btn" @click.stop="confirmShotDialogue(shot)" title="修改台词后确认新基准；未填写台词时按无对白生成">确认当前台词</button>
              <button v-if="shot.resultFileId" type="button" class="dialogue-review-btn" :disabled="shot.audioReview?.status === 'checking'" @click.stop="reviewShotAudio(shot, true)">{{ shot.audioReview?.status === 'checking' ? '本地台词核验中…' : '核验视频台词' }}</button>
          </div></details>
              <!-- 关联音频/配音专属条带 -->
              <details v-if="shotAttachedAudios(shot).length && shot.workspaceTab === 'audio'" class="storyboard-audio-track">
                <summary>关联声音素材 <span>{{ shotAttachedAudios(shot).length }} 项 · 试听、合入与移除</span></summary>
                <div v-for="aud in shotAttachedAudios(shot)" :key="aud.id" class="storyboard-audio-pill" :class="getAudioSubType(aud)">
                  <span class="audio-pill-icon">
                    <svg v-if="getAudioSubType(aud) === 'voice'" viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3M8 22h8"/></svg>
                    <svg v-else viewBox="0 0 24 24"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
                  </span>
                  <span class="audio-pill-label">
                    <strong>{{ !assetUrl(aud) ? '声音文字设定' : (getAudioSubType(aud) === 'voice' ? '配音文件' : '音效文件') }}：</strong>
                    <span class="audio-pill-name" :title="aud.name">{{ aud.name }}</span>
                    <small v-if="aud.duration && aud.duration !== '已生成' && aud.duration !== '已上传'">({{ aud.duration }})</small>
                  </span>
                  <span class="audio-pill-tip" :data-tooltip="assetUrl(aud) ? '该音频不会自动覆盖成片；需点击合入视频' : '没有音频文件，仅作文字描述，未绑定音色'">{{ shot.mixedAudioFileId && shot.mixedAudioFileId === String(aud.fileId || '') && shot.mixedVideoFileId === shot.resultFileId ? '已合入成片' : (assetUrl(aud) ? '未合入成片' : '未生成音频') }}</span>
                  <button
                    type="button"
                    class="audio-pill-btn audio-pill-play"
                    :class="{ 'is-playing': playingAudioId === String(aud.id) }"
                    :aria-label="playingAudioId === String(aud.id) ? '暂停音频' : '试听音频'"
                    :disabled="!assetUrl(aud)"
                    data-tooltip="试听音频（需先生成真实文件）"
                    @click.stop="togglePlayAudio(aud)"
                  >
                    <svg v-if="playingAudioId !== String(aud.id)" viewBox="0 0 24 24"><path d="m9 7 8 5-8 5V7Z"/></svg>
                    <svg v-else viewBox="0 0 24 24"><path d="M8 7h3v10H8zM14 7h3v10h-3z"/></svg>
                    <span>{{ playingAudioId === String(aud.id) ? '暂停' : '试听' }}</span>
                  </button>
                  <button
                    v-if="shot.resultFileId"
                    type="button"
                    class="audio-pill-btn audio-pill-mux"
                    :disabled="muxingShotId === shot.id || !assetUrl(aud)"
                    data-tooltip="将此音频直接合入当前视频文件并覆盖原音"
                    @click.stop="muxShotAudio(shot, aud)"
                  >
                    <span v-if="muxingShotId === shot.id" class="asset-generate-spinner"></span>
                    <svg v-else viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg>
                    <span>{{ muxingShotId === shot.id ? '合入中…' : aud.provider === 'breeze-local' ? '对齐配音' : '合入视频' }}</span>
                  </button>
                  <button
                    type="button"
                    class="audio-pill-btn audio-pill-remove"
                    aria-label="从当前分镜撤回/移出此音频"
                    data-tooltip="从当前分镜撤回音频"
                    @click.stop="removeReference(shot, aud.id)"
                  >
                    <svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>
                    <span>撤回</span>
                  </button>
                </div>
              </details>

          <div v-if="shot.generationError && shot.resultFileId" class="shot-audio-review needs_review" role="alert">{{ shot.generationError }}</div>
          <div v-if="shot.audioReview && (!isGeneral || dialogueContract(shot.prompt).lines.length)" v-show="shot.workspaceTab === 'audio'" class="shot-audio-review" :class="shot.audioReview.status" aria-live="polite">
            <strong>{{ shot.audioReview.summary }}</strong>
            <span v-if="shot.audioReview.transcript">识别：{{ shot.audioReview.transcript }}</span>
            <small>{{ shot.audioReview.limitation || '本地识别只核对台词文字；自然度、音色与口型仍需试听。' }}</small>
          </div>
          <footer class="storyboard-toolbar">
            <div class="toolbar-popover-wrap">
              <button type="button" :aria-expanded="shot.modeOpen" @click.stop="toggleModeMenu(shot)"><svg viewBox="0 0 24 24"><path d="M5 7h14v12H5zM8 4h8v3"/></svg>{{ modeLabel(shot) }}</button>
              <div v-if="shot.modeOpen" class="mode-popover" @click.stop>
                <label>选择模式</label>
                <button v-for="mode in generationModes" :key="mode.value" type="button" :class="{ active: shot.mode === mode.value }" @click="selectMode(shot, mode.value)">
                  <svg v-if="mode.value === 'reference'" viewBox="0 0 24 24"><path d="M5 7h14v12H5zM8 4h8v3"/></svg>
                  <svg v-else viewBox="0 0 24 24"><rect x="4" y="5" width="6" height="14"/><rect x="14" y="5" width="6" height="14"/></svg>
                  <span>{{ mode.label }}</span><b v-if="shot.mode === mode.value">✓</b>
                </button>
              </div>
            </div>
            <div class="toolbar-popover-wrap settings-wrap">
              <button type="button" class="settings-summary-btn" :aria-expanded="shot.settingsOpen" :aria-label="isGeneral ? '当前镜头视频模型与参数' : '视频设置'" data-tooltip="视频设置" @click.stop="toggleSettings(shot, $event)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h18M3 12h18M3 17h18"/></svg><span>{{ isGeneral ? '视频模型 · ' : '' }}{{ settingsSummaryLabel(shot) }}</span></button>
              <div v-if="shot.settingsOpen" class="settings-popover" :style="shot.settingsPopoverStyle" :data-settings-shot="shot.id" @click.stop>
                <fieldset class="settings-field-wide generation-model-field">
                  <legend>API 视频生成模型</legend>
                  <label class="seedance-model-select">
                    <UiSelect v-model="shot.seedanceModel" :options="seedanceModelOptions" :disabled="!seedanceModelOptions.length" :placeholder="seedanceModelOptions.length ? '选择已配置的视频模型' : '暂无可用视频模型，请在模型管理中添加'" status badge="VIDEO" />
                  </label>
                </fieldset>

                <!-- API 自定义模型配置 -->
                <template v-if="true">
                  <fieldset class="settings-field-wide">
                    <legend>视频比例</legend>
                    <div class="ratio-options">
                      <button v-for="ratioOption in videoRatios" :key="ratioOption" type="button" :class="{ active: shot.ratio === ratioOption }" @click="shot.ratio = ratioOption">
                        <svg viewBox="0 0 24 24"><rect :x="ratioOption === '9:16' || ratioOption === '3:4' ? 8 : 5" :y="ratioOption === '9:16' || ratioOption === '3:4' ? 4 : 7" :width="ratioOption === '9:16' || ratioOption === '3:4' ? 8 : 14" :height="ratioOption === '9:16' || ratioOption === '3:4' ? 16 : 10" rx="1"/></svg>
                        <span>{{ ratioOption }}</span>
                      </button>
                    </div>
                  </fieldset>
                  <fieldset>
                    <legend>分辨率</legend>
                    <div class="segmented-options four">
                      <button v-for="qualityOption in videoQualities" :key="qualityOption" type="button" :class="{ active: shot.quality === qualityOption }" @click="shot.quality = qualityOption">
                        {{ qualityOption }}
                      </button>
                    </div>
                  </fieldset>
                  <fieldset>
                    <legend>输出声音</legend>
                    <div class="segmented-options">
                      <button type="button" :class="{ active: shot.sound }" @click="shot.sound = true">开</button>
                      <button type="button" :class="{ active: !shot.sound }" @click="shot.sound = false">关</button>
                    </div>
                  </fieldset>
                  <fieldset class="settings-field-wide">
                    <legend>视频时长</legend>
                    <div class="segmented-options">
                      <button type="button" :class="{ active: shot.durationMode === 'seconds' }" @click="shot.durationMode = 'seconds'">按秒数</button>
                      <button type="button" :class="{ active: shot.durationMode === 'smart' }" @click="shot.durationMode = 'smart'">智能时长</button>
                    </div>
                    <div v-if="shot.durationMode === 'seconds'" class="duration-options">
                      <button v-for="durationOption in videoDurations" :key="durationOption" type="button" :class="{ active: Number(shot.duration) === durationOption }" @click="shot.duration = durationOption">
                        {{ durationOption }}s
                      </button>
                    </div>
                  </fieldset>
                  <fieldset class="settings-field-wide">
                    <legend>选择生成数量</legend>
                    <div class="count-options">
                      <button v-for="countOption in generationCounts" :key="countOption" type="button" :class="{ active: shot.count === countOption }" @click="shot.count = countOption">
                        {{ countOption }}
                      </button>
                    </div>
                  </fieldset>
                </template>
              </div>
            </div>
            <button class="shot-clear" type="button" @click="shot.references = []; shot.prompt = ''">清空内容</button>
            <button class="shot-submit" :class="{ 'is-running': shotRunning(shot) }" type="button" :aria-label="shotRunning(shot) ? '终止当前分镜生成' : '生成当前分镜'" @click.stop="shotRunning(shot) ? cancelShot(shot) : generateShot(shot)"><span v-if="shotRunning(shot)" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24"><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/></svg><strong>{{ shotRunning(shot) ? '终止' : '生成视频' }}</strong></button>
          </footer>
            </div>

          <section class="shot-result" :class="{ 'has-player': Boolean(shot.resultUrl) }" aria-label="分镜生成结果">
            <p v-if="resultSourceMessage(shot)" class="shot-result-provenance" role="status">{{ resultSourceMessage(shot) }} <button v-if="hasFailedAttempt(shot) && shot.showHistoricalResult" type="button" @click="shot.showHistoricalResult = false">收起历史版本</button></p>
            <p v-if="shot.videoReplaceError" class="shot-result-replace-error">{{ shot.videoReplaceError }}</p>
            <div v-if="shot.resultUrl && (!hasFailedAttempt(shot) || shot.showHistoricalResult)" class="shot-result-player" :data-result-player="shot.id">
              <video :key="(shot.previewOriginal ? 'orig_' + (shot.originalVideoFileId || '') : 'res_' + (shot.resultFileId || '')) + '_' + (shot.mixedVideoFileId || '')" :ref="el => setVideoRef(shot, el)" :src="shot.previewOriginal ? shot.originalPreviewUrl : shot.resultUrl" playsinline preload="auto" @click.stop="toggleVideo(shot)" @play="shot.videoPlaying = true; verifyShotVideoFrame(shot, $event)" @pause="shot.videoPlaying = false" @ended="shot.videoPlaying = false; shot.videoCurrent = 0" @loadedmetadata="syncVideoMeta(shot, $event)" @loadeddata="ensureShotVideoRenderable(shot, $event)" @timeupdate="syncVideoTime(shot, $event)" @volumechange="shot.videoMuted = $event.currentTarget.muted" @error="handleShotVideoError(shot)"></video>
              <div v-if="shot.workspaceTab === 'audio'" class="shot-preview-switch"><button type="button" :class="{ active: !shot.previewOriginal }" @click.stop="shot.previewOriginal = false; shot.previewStopAt = null">当前成片</button><button type="button" :class="{ active: shot.previewOriginal }" @click.stop="previewBreezeOriginal(shot)">原片原声</button></div>
              <span v-if="shot.resultWatermarked" class="shot-result-watermark-badge">有水印</span>
              <button v-if="!shot.videoPlaying" type="button" class="shot-result-center-play" aria-label="播放" @click.stop="toggleVideo(shot)"><svg viewBox="0 0 24 24"><path d="m9 6 9 6-9 6V6Z"/></svg></button>
              <div class="shot-result-controls" @click.stop>
                <input type="range" min="0" :max="shot.videoDuration || 0" step="0.01" :value="shot.videoCurrent" :style="{ '--video-progress': `${shot.videoDuration ? (shot.videoCurrent / shot.videoDuration) * 100 : 0}%` }" aria-label="视频进度" @input="seekVideo(shot, $event)" />
                <div>
                  <button type="button" :aria-label="shot.videoPlaying ? '暂停' : '播放'" @click="toggleVideo(shot)"><svg v-if="shot.videoPlaying" viewBox="0 0 24 24"><path d="M8 6v12M16 6v12"/></svg><svg v-else viewBox="0 0 24 24"><path d="m9 6 9 6-9 6V6Z"/></svg></button>
                  <time>{{ fmtTime(shot.videoCurrent) }} <span>/ {{ fmtTime(shot.videoDuration) }}</span></time>
                  <button type="button" :aria-label="shot.videoMuted ? '开启声音' : '静音'" @click="toggleMute(shot)"><svg v-if="shot.videoMuted" viewBox="0 0 24 24"><path d="M5 10v4h3l4 3V7l-4 3H5M16 9l5 6M21 9l-5 6"/></svg><svg v-else viewBox="0 0 24 24"><path d="M5 10v4h3l4 3V7l-4 3H5M16 9.5a4 4 0 0 1 0 5M18.5 7a7 7 0 0 1 0 10"/></svg></button>
                  <button type="button" class="shot-result-replace-control" :disabled="shot.replacingVideo" :aria-label="shot.replacingVideo ? '正在替换视频' : '使用本地视频替换'" data-tooltip="本地替换视频" data-tooltip-pos="top" @click="replaceShotVideo(shot)"><span v-if="shot.replacingVideo" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24"><path d="M4 7h10M11 4l3 3-3 3M20 17H10m3-3-3 3 3 3"/><rect x="4" y="12" width="4" height="8" rx="1"/><rect x="16" y="4" width="4" height="8" rx="1"/></svg></button>
                  <button v-if="shotIndex < storyboards.length - 1" type="button" class="shot-result-cascade-control" :disabled="shot.extractingLastFrame" :aria-label="'设为下镜首帧'" title="提取当前尾帧并直接设为下一分镜首帧（首尾帧级联衔接）" data-tooltip="设为下镜首帧" data-tooltip-pos="top" @click.stop.prevent="setShotLastFrameAsNextFirstFrame(shot, shotIndex)"><span v-if="shot.extractingLastFrame" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24"><path d="m13 5 7 7-7 7M5 5l7 7-7 7"/></svg></button>
                  <button type="button" class="shot-result-download-control" :disabled="shot.downloadingVideo" :aria-label="shot.downloadingVideo ? '正在下载视频' : '下载当前视频'" title="下载当前视频" data-tooltip="下载视频" data-tooltip-pos="top" @click.stop.prevent="downloadShotVideo(shot)"><span v-if="shot.downloadingVideo" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14"/></svg></button>
                  <button type="button" aria-label="放大播放" @click="openVideoPreview(shot)"><svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg></button>
                </div>
              </div>
            </div>
            <section v-else-if="!shotRunning(shot)&&rejectedCandidate(shot)" class="rejected-candidate" aria-label="本次未采用的视频候选" style="width:100%;padding:16px;box-sizing:border-box;overflow:auto;align-self:stretch">
              <strong style="color:#b42318">视频已生成 · 衔接检查未通过，尚未采用</strong>
              <p>{{shot.lastGenerationAttempt?.error}}。请先连看候选和首帧对照，不必立即重复生成。原成片仍保留。</p>
              <video :src="fileDownloadUrl(rejectedCandidate(shot).fileId)" :data-candidate-id="rejectedCandidate(shot).fileId" controls playsinline preload="metadata" style="width:100%;max-height:52vh;object-fit:contain;background:#111"></video>
              <div class="rejected-frame-comparison" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
                <figure v-if="rejectedCandidate(shot).expectedFrameId" style="margin:0"><img :src="fileDownloadUrl(rejectedCandidate(shot).expectedFrameId)" alt="本次实际提交的起始参考" style="width:100%"/><figcaption>本次提交的起始参考</figcaption></figure>
                <figure v-if="rejectedCandidate(shot).actualFrameId" style="margin:0"><img :src="fileDownloadUrl(rejectedCandidate(shot).actualFrameId)" alt="候选视频实际首帧" style="width:100%"/><figcaption>候选视频实际首帧</figcaption></figure>
              </div>
              <p>首帧差异只用于筛查，不能代替人物、持物、空间方向、动作与声音的完整检查。当前未改变原成片，也没有自动放行。</p>
              <div class="rejected-candidate-actions" style="display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;align-items:center">
                <button type="button" class="shot-adopt-transition-btn" style="background:#0284c7;color:#fff;padding:8px 16px;border-radius:6px;border:none;cursor:pointer;font-weight:600" @click="setContinuityMode(shot, shotIndex, 'transition')">🎬 设为尾帧转场（两者兼得·立即采用）</button>
                <button type="button" class="primary" style="background:var(--theme-accent);color:var(--theme-text-on-accent);padding:8px 16px;border-radius:6px;border:none;cursor:pointer;font-weight:600" @click="adoptRejectedCandidate(shot)">人工核验通过，采用为成片</button>
                <button v-if="shot.resultUrl" type="button" @click="shot.showHistoricalResult=true">查看保留的历史版本</button>
                <button
                  v-if="hasContinuityConflictOrDurationError(shot)"
                  type="button"
                  class="shot-adopt-candidate-btn"
                  style="background: #2563eb; color: #fff; font-weight: bold; border-color: #2563eb;"
                  @click.stop="resolveShotConflictAndRegenerate(shot)"
                >⚡ 自动修正冲突 (10秒+姿态对齐)</button>
                <button type="button" @click.stop="generateShot(shot)">重新生成</button>
              </div>
            </section>
            <div v-else-if="hasFailedAttempt(shot) && !shotRunning(shot)" class="shot-result-error">
              <strong>本次没有新成片</strong><span>{{ shot.lastGenerationAttempt?.error || '任务已终止，未采用新视频。' }}</span>
              <div class="shot-result-error-actions">
                <button v-if="shot.resultUrl" type="button" @click="shot.showHistoricalResult = true">查看历史版本</button>
                <button type="button" class="shot-optimize-err-btn" :disabled="shot.optimizingPrompt" @click.stop="optimizeShotPrompt(shot)">
                  <span v-if="shot.optimizingPrompt" class="asset-generate-spinner"></span>
                  <span v-else>✨ 优化提示词</span>
                </button>
                <button type="button" @click.stop="generateShot(shot)">重新生成</button>
              </div>
            </div>
            <div v-else-if="shotRunning(shot)" class="shot-result-progress">
              <span class="result-spinner"></span>
              <div><strong>{{ shot.statusText || '正在生成视频' }}</strong><small>{{ shot.requiresManualVerification ? `请切换到 ${generationEngineLabel(shot)} 浏览器手动点击确认` : '完成后将在这里直接显示并播放' }}</small></div>
              <b v-if="isMuseShot(shot)">等待 {{ Math.floor((shot.waitElapsedSeconds || 0) / 60) }}分{{ (shot.waitElapsedSeconds || 0) % 60 }}秒</b>
              <b v-else>{{ shot.progress }}%</b>
              <i v-if="!isMuseShot(shot)"><em :style="{ width: `${shot.progress}%` }"></em></i>
            </div>
            <div v-else-if="shot.generationError" class="shot-result-error">
              <strong>生成未完成</strong><span>{{ shot.generationError }}</span>
              <div class="shot-result-error-actions">
                <button type="button" @click.stop="generateShot(shot)">重新生成</button>
                <button type="button" :disabled="shot.replacingVideo" @click.stop="replaceShotVideo(shot)">{{ shot.replacingVideo ? '正在上传…' : '上传本地视频' }}</button>
              </div>
            </div>
            <div v-else-if="shot.status === 'succeeded'" class="shot-result-complete">
              <strong>视频生成完成</strong><span>{{ shot.statusText || '自动下载已关闭，暂时没有本地播放文件。' }}</span>
              <button class="shot-result-upload" type="button" :disabled="shot.replacingVideo" @click.stop="replaceShotVideo(shot)">{{ shot.replacingVideo ? '正在上传…' : '上传本地视频' }}</button>
            </div>
            <div v-else class="shot-result-empty">
              <span><svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="2.5"/><path d="m10 9 5 3-5 3V9Z"/></svg></span>
              <div><strong>视频将在这里显示</strong><small>点击“生成视频”制作当前镜头，完成后可在这里播放</small></div>
              <button class="shot-result-upload" type="button" :disabled="shot.replacingVideo" aria-label="上传本地视频到当前分镜" @click.stop="replaceShotVideo(shot)">{{ shot.replacingVideo ? '正在上传…' : '上传本地视频' }}</button>
            </div>
          </section>
          </div>
        </article>
      </section>
      </div>
    </div>

    <div v-if="creationAiOpen" class="creation-ai-backdrop" role="presentation" @mousedown.self="closeCreationAiDialog">
      <section class="creation-ai-dialog" role="dialog" aria-modal="true" aria-labelledby="creation-ai-title" @mousedown.stop>
        <header>
          <div><span>AI 创作数据</span><h2 id="creation-ai-title">AI 生成创作数据</h2><p>接入你在模型管理里配置的文本模型，把小说、故事或剧本整理成 CDTV 可导入 JSON。</p></div>
          <button type="button" aria-label="关闭 AI 生成窗口" @click="closeCreationAiDialog">×</button>
        </header>
        <div class="creation-ai-form">
          <label><span>文本模型</span><UiSelect v-model="selectedTextModel" :options="textModelOptions" :placeholder="textModels.length ? '选择文本模型' : '暂无已启用的文本模型'" :disabled="creationAiGenerating || !textModels.length" status badge="文本" /></label>
          <label><span>生成范围</span><select v-model="creationAiScope" :disabled="creationAiGenerating"><option value="full">完整创作数据</option><option value="assets">只生成资产设定</option><option value="shots">重点生成分镜</option></select></label>
          <label class="creation-ai-title-field"><span>项目标题（可选）</span><input v-model="creationAiTitle" :disabled="creationAiGenerating" maxlength="120" placeholder="例如：雨夜重生" /></label>
          <label class="creation-ai-prompt-field"><span>故事 / 小说 / 剧本 / 创作要求</span><textarea v-model="creationAiPrompt" class="creation-ai-prompt" :disabled="creationAiGenerating" maxlength="30000" placeholder="把故事梗概、人物关系、风格、集数或你想要的分镜要求粘贴到这里…"></textarea></label>
        </div>
        <p v-if="creationAiError" class="creation-ai-error">{{ creationAiError }}</p>
        <label v-if="creationAiPreview" class="creation-ai-preview"><span>生成结果（可修改后再导入）</span><textarea v-model="creationAiPreview" spellcheck="false"></textarea></label>
        <footer>
          <small>不会自动覆盖当前任务；确认“解析并导入”后才会写入当前编辑区。</small>
          <button class="json-cancel-button" type="button" @click="closeCreationAiDialog">取消</button>
          <button class="creation-ai-generate-button" type="button" :disabled="creationAiGenerating || !creationAiPrompt.trim() || !textModels.length" @click="generateCreationData"><span v-if="creationAiGenerating" class="asset-generate-spinner"></span>{{ creationAiGenerating ? '正在生成…' : '生成 JSON' }}</button>
          <button v-if="creationAiPreview" class="json-confirm-button" type="button" :disabled="creationAiGenerating" @click="importCreationAiPreview">解析并导入</button>
        </footer>
      </section>
    </div>

    <div v-if="importDialogOpen" class="json-import-backdrop" role="presentation" @mousedown.self="closeImportDialog">
      <section class="json-import-dialog" role="dialog" aria-modal="true" aria-labelledby="json-import-title" @mousedown.stop>
        <header>
          <div><span>IMPORT CREATION DATA</span><h2 id="json-import-title">导入创作数据 JSON</h2><p>粘贴 JSON 文本，或直接选择本地 .json 文件。</p></div>
          <button type="button" aria-label="关闭导入窗口" @click="closeImportDialog">×</button>
        </header>
        <label class="json-import-editor">
          <span>JSON 文本</span>
          <textarea v-model="jsonText" class="json-import-textarea" spellcheck="false" placeholder="在这里粘贴完整 JSON 内容…"></textarea>
        </label>
        <p v-if="importError" class="json-import-error">{{ importError }}</p>
        <footer>
          <button class="json-file-button" type="button" @click="importAssetJson"><span>⇧</span><div><strong>选择 JSON 文件</strong><small>从电脑中选择 .json 文件</small></div></button>
          <button class="json-cancel-button" type="button" @click="closeImportDialog">取消</button>
          <button class="json-confirm-button" type="button" :disabled="!jsonText.trim()" @click="importJsonText">解析并导入</button>
        </footer>
      </section>
    </div>

    <div v-if="assetDetailOpen && assetDetailTarget" class="asset-detail-backdrop" role="presentation" @mousedown.self="closeAssetDetail">
      <section class="asset-detail-dialog" :class="{ 'drama-asset-dialog': props.embedded && !isGeneral }" role="dialog" aria-modal="true" aria-labelledby="asset-detail-title" @mousedown.stop>
        <header>
          <div>
            <span>ASSET DETAILS</span>
            <h2 id="asset-detail-title">资产详情与编辑</h2>
            <p>{{ assetDetailTarget.id }} · {{ assetDetailTarget.category === 'audio' ? (assetDraft.subCategory === 'voice' ? '🎙️ 语音配音 (TTS)' : '🔊 拟声音效 (SFX)') : (categories.find(item => item.key === assetDetailTarget.category)?.label || '本地资产') }}</p>
          </div>
          <button type="button" aria-label="关闭资产详情" @click="closeAssetDetail">×</button>
        </header>
        <div class="asset-detail-body">
          <div class="asset-detail-preview">
            <button v-if="assetUrl(assetDetailTarget) && assetDetailTarget.type !== 'audio'" class="asset-detail-image-preview" :class="{ 'is-generating': assetDetailTarget.generating }" type="button" :aria-label="`放大查看 ${assetDetailTarget.name || '资产图片'}`" @click="openReferencePreview(assetDetailTarget)">
              <img :src="assetUrl(assetDetailTarget)" :alt="assetDetailTarget.name" />
              <span class="asset-detail-zoom-hint" aria-hidden="true"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4M11 8v6M8 11h6"/></svg>点击放大</span>
            </button>
            <div v-else-if="assetUrl(assetDetailTarget)" class="asset-detail-audio-player">
              <audio ref="audioPreview" :src="assetUrl(assetDetailTarget)" preload="metadata" @loadedmetadata="syncAudioPreviewMetadata" @durationchange="syncAudioPreviewMetadata" @timeupdate="syncAudioPreviewTime" @play="audioPreviewPlaying = true" @pause="audioPreviewPlaying = false" @ended="audioPreviewPlaying = false"></audio>
              <button type="button" class="asset-detail-audio-toggle" :aria-label="audioPreviewPlaying ? '暂停音频' : '播放音频'" @click="toggleAudioPreview">
                <svg v-if="!audioPreviewPlaying" viewBox="0 0 24 24"><path d="m9 7 8 5-8 5V7Z"/></svg>
                <svg v-else viewBox="0 0 24 24"><path d="M8 7h3v10H8zM14 7h3v10h-3z"/></svg>
              </button>
              <div class="asset-detail-audio-copy">
                <div><strong>音频预览</strong><span>{{ audioPreviewPlaying ? '正在播放' : '准备就绪' }}</span></div>
                <input type="range" min="0" :max="audioPreviewDuration || 0" step="0.01" :value="audioPreviewCurrent" :style="{ '--audio-progress': `${audioPreviewDuration ? (audioPreviewCurrent / audioPreviewDuration) * 100 : 0}%` }" aria-label="音频播放进度" @input="seekAudioPreview" />
              </div>
              <time>{{ formatAudioTime(audioPreviewCurrent) }} / {{ formatAudioTime(audioPreviewDuration) }}</time>
              <svg class="asset-detail-audio-volume" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 10v4h3l4 3V7l-4 3H5Z"/><path d="M15 9.5a4 4 0 0 1 0 5M17.5 7a7 7 0 0 1 0 10"/></svg>
            </div>
            <div v-else class="asset-detail-empty" :class="{ 'is-generating': assetDetailTarget.generating && assetDetailTarget.category !== 'audio' }"><svg v-if="assetDetailTarget.category !== 'audio'" viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m6 17 4-4 3 3 2.5-2.5L19 17"/></svg><svg v-else viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6" cy="18" r="3"/><circle cx="16" cy="16" r="3"/></svg><span>{{ assetDetailTarget.generating && assetDetailTarget.category !== 'audio' ? '正在生成图片' : assetDetailTarget.category === 'audio' ? '尚未生成或上传音频' : '尚未上传或生成图片' }}</span></div>
            <section v-if="assetReferenceState(assetDetailTarget).total" class="asset-detail-references">
              <header><strong>参考图</strong><div><span>{{ assetReferenceState(assetDetailTarget).ready }}/{{ assetReferenceState(assetDetailTarget).total }} 张已就绪</span><button class="asset-detail-reference-copy" type="button" :disabled="assetReferencesCopying || assetReferenceState(assetDetailTarget).ready !== assetReferenceState(assetDetailTarget).total" @click="copyAssetReferences(assetDetailTarget)">{{ assetReferencesCopying ? '复制中…' : assetReferencesCopied ? '已复制' : '复制' }}</button></div></header>
              <div>
                <button v-for="(reference, index) in assetReferenceState(assetDetailTarget).items" :key="reference.id" type="button" :disabled="!assetUrl(reference)" :aria-label="assetUrl(reference) ? `放大查看图${index + 1} ${reference.name}` : `图${index + 1} ${reference.name} 尚未生成`" @click="openReferencePreview(reference, assetDetailTarget)">
                  <img v-if="assetUrl(reference)" :src="assetUrl(reference)" :alt="reference.name" />
                  <span v-else>待生成</span>
                  <small>图{{ index + 1 }} · {{ reference.name || reference.id }}</small>
                </button>
                <span v-for="id in assetReferenceState(assetDetailTarget).unresolved" :key="id" class="asset-detail-reference-missing"><i>缺失</i><small>{{ id }}</small></span>
              </div>
            </section>
            <div class="asset-detail-media-actions">
              <button v-if="assetDetailTarget.category !== 'audio'" type="button" aria-label="从本地上传图片" data-tooltip="从本地上传图片" data-tooltip-pos="top" @click="selectLocalImageForAsset(assetDetailTarget)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5"/></svg><span v-if="props.embedded && !isGeneral">上传图片</span></button>
              <button v-else type="button" aria-label="从本地上传音频 (MP3/WAV)" data-tooltip="从本地上传音频 (MP3/WAV)" data-tooltip-pos="top" @click="selectLocalImageForAsset(assetDetailTarget)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5"/></svg></button>
              <button v-if="assetDetailTarget.category === 'role' && assetUrl(assetDetailTarget)" class="asset-detail-crop-portrait" type="button" :disabled="croppingPortrait" aria-label="提取纯净单人特写剧照" data-tooltip="智能裁剪单人正面特写（剔除多视角干扰，极大提升视频生成人脸一致性）" data-tooltip-pos="top" @click="cropRolePortrait(assetDetailTarget)"><span v-if="croppingPortrait" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/></svg></button>
              <button v-if="assetUrl(assetDetailTarget)" class="asset-detail-download-media" type="button" :disabled="downloadingAssetMedia" :aria-label="assetDetailTarget.category === 'audio' ? '下载音频' : '下载图片'" :data-tooltip="assetDetailTarget.category === 'audio' ? '下载音频' : '下载图片'" data-tooltip-pos="top" @click="downloadAssetMedia(assetDetailTarget)"><span v-if="downloadingAssetMedia" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 19h14"/></svg></button>
              <button v-if="assetUrl(assetDetailTarget)" class="asset-detail-clear-image" type="button" :aria-label="assetDetailTarget.category === 'audio' ? '清空音频' : '清空图片'" :data-tooltip="assetDetailTarget.category === 'audio' ? '清空音频' : '清空图片'" data-tooltip-pos="top" @click="clearAssetMedia(assetDetailTarget)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg></button>
              <button class="asset-detail-generate-media" :class="{ 'is-generating': assetDetailTarget.generating }" type="button" :aria-label="assetDetailTarget.generating ? '终止生成' : assetDetailTarget.category === 'audio' ? (assetDraft.subCategory === 'voice' ? '生成语音' : '生成音效') : '重新生成图片'" :data-tooltip="assetDetailTarget.generating ? '终止生成' : assetDetailTarget.category === 'audio' ? (assetDraft.subCategory === 'voice' ? '生成语音' : '生成音效') : '重新生成图片'" data-tooltip-pos="top" @click.stop="assetDetailTarget.generating ? cancelAsset(assetDetailTarget) : generateAssetFromDetail()"><span v-if="assetDetailTarget.generating" class="asset-generate-spinner"></span><svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/><path d="m18.5 15 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z"/></svg><span v-if="props.embedded && !isGeneral">{{ assetDetailTarget.generating ? '终止生成' : assetDetailTarget.category === 'audio' ? '生成音频' : '生成图片' }}</span></button>
            </div>
          </div>
          <div class="asset-detail-fields">
            <label><span>资产名称</span><input v-model="assetDraft.name" /></label>
            <div v-if="assetDetailTarget.category === 'audio'" class="audio-type-selector">
              <span>音频类别</span>
              <div class="audio-type-tabs">
                <button
                  type="button"
                  class="audio-type-tab voice-tab"
                  :class="{ active: assetDraft.subCategory === 'voice' }"
                  @click="assetDraft.subCategory = 'voice'"
                >
                  🎙️ 语音配音 (旁白/台词/系统音)
                </button>
                <button
                  type="button"
                  class="audio-type-tab sfx-tab"
                  :class="{ active: assetDraft.subCategory === 'sfx' }"
                  @click="assetDraft.subCategory = 'sfx'"
                >
                  🔊 拟声音效 (环境音/打斗/BGM)
                </button>
              </div>
            </div>
            <label><span>描述</span><textarea v-model="assetDraft.description" rows="3" :placeholder="assetDetailTarget.category === 'audio' ? '声音特点、语调或音效用途说明' : '资产的外观、用途说明'"></textarea></label>
            <div v-if="assetDetailTarget.category === 'audio' && assetDraft.subCategory === 'voice'" class="voice-dual-action-card">
              <div class="voice-dual-action-info">
                <strong>🎙️ 配音支持两种方式</strong>
                <p><b>① API 在线合成：</b>选择下方音色并填写台词，点击右下角「生成语音」<br /><b>② 本地 MP3 导入：</b>自备录音或从 MiniMax 等下载的音频，点击右侧导入</p>
              </div>
              <button type="button" class="voice-upload-btn" @click="selectLocalImageForAsset(assetDetailTarget)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5"/></svg>
                <span>从电脑导入 MP3</span>
              </button>
            </div>
            <label v-if="assetDetailTarget.category === 'audio' && assetDraft.subCategory === 'voice'" class="asset-action-model">
              <span>音色预设 (CosyVoice / 语音模型)</span>
              <UiSelect v-model="assetDraft.voice" :options="VOICE_PRESET_OPTIONS" placeholder="选择音色预设" status badge="音色" />
            </label>
            <label>
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span>{{ assetDetailTarget.category === 'audio' ? (assetDraft.subCategory === 'voice' ? '语音台词 (TTS 朗读文本 / 视频音频提示词)' : '音效生成描述 / 提示词') : '生成提示词' }}</span>
                <button v-if="assetDetailTarget.category === 'audio' && assetDraft.subCategory === 'voice'" type="button" class="btn-audio-formula-mini" title="套用【职业身份+性别+年龄+音高+声音质地+发声特点】六维强感知音频公式" @click="formatAssetPromptToSixDim">🎙️ 套用6维音频公式</button>
              </div>
              <textarea v-model="assetDraft.prompt" rows="6" :placeholder="assetDetailTarget.category === 'audio' ? (assetDraft.subCategory === 'voice' ? '输入要朗读的纯文本台词（如：鸿蒙初降，诸天共尊…）' : '输入拟声音效描述（如：沉重老旧木门缓缓推开时发出的干涩摩擦声…）') : '用于生成图片或音频的完整提示词'"></textarea>
            </label>
            <div v-if="assetDetailTarget.category === 'audio' && assetDraft.subCategory === 'sfx'" class="sfx-upload-card">
              <div class="sfx-upload-info">
                <strong>💡 建议导入下载的 MP3 音效</strong>
                <p>大部分 AI 语音模型专精于人声对白。环境氛围和打斗拟声音效，建议直接从网上下载 MP3 资源并导入。</p>
              </div>
              <button type="button" class="sfx-upload-btn" @click="selectLocalImageForAsset(assetDetailTarget)">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M5 14v5h14v-5"/></svg>
                <span>从电脑选择音效导入</span>
              </button>
            </div>
            <label v-if="props.embedded && assetDetailTarget.category !== 'audio'" class="asset-action-model"><span>生图模型</span><UiSelect v-model="selectedImageModel" :options="imageModelOptions" :placeholder="imageModels.length ? '选择生图模型' : '请先配置生图模型'" :disabled="loading || !imageModels.length" aria-label="素材详情生图模型" /></label>
            <section v-if="isGeneral && assetDetailTarget.category !== 'audio'" class="asset-image-text-policy" aria-label="图片文字要求">
              <label><span>画面文字</span><UiSelect v-model="assetDraft.imageTextMode" :options="IMAGE_TEXT_OPTIONS" aria-label="画面文字策略" /></label>
              <label v-if="assetDraft.imageTextMode==='exact'"><span>需要显示的文字原文</span><textarea v-model="assetDraft.imageText" rows="3" placeholder="只填写图片中需要出现的文字，不写排版说明"></textarea></label>
              <small>未给出文字原文时保持留白；可选择无文字底图，后期再排字。生成模型仍需人工核对文字。</small>
              <details><summary>本次实际发送的生图提示词</summary><pre>{{ assetImagePromptPreview }}</pre></details>
              <details v-if="assetDetailTarget.generatedPrompt"><summary>上次生成使用的提示词</summary><pre>{{ assetDetailTarget.generatedPrompt }}</pre></details>
            </section>
            <label v-if="assetDetailTarget.category === 'audio' && audioModels.length" class="asset-action-model"><span>音频生成模型</span><UiSelect v-model="selectedAudioModel" :options="audioModelOptions" :placeholder="loading ? '正在加载模型…' : '选择音频模型'" :disabled="loading || !audioModels.length" status badge="AUDIO" /></label>
            <div v-if="assetDetailTarget.category === 'role'" class="asset-detail-default-prompt" :class="{ disabled: !assetDraft.useDefaultRoleLayout || hasCustomRoleLayout(assetDraft.prompt) }">
              <div class="asset-detail-default-prompt-head"><span>KSR 角色四宫格</span><button type="button" role="switch" :aria-checked="assetDraft.useDefaultRoleLayout" :aria-label="assetDraft.useDefaultRoleLayout ? '关闭默认角色构图' : '开启默认角色构图'" @click="assetDraft.useDefaultRoleLayout = !assetDraft.useDefaultRoleLayout"><i></i></button></div>
              <div v-if="assetDraft.useDefaultRoleLayout && !hasCustomRoleLayout(assetDraft.prompt)" class="role-panel-guide" aria-label="角色四宫格布局"><span>① 正面脸部特写</span><span>② 侧面脸部特写</span><span>③ 正面全身 · 不刻画五官</span><span>④ 背面全身</span></div>
              <small v-if="hasCustomRoleLayout(assetDraft.prompt)">你已填写自定义构图，保持原文；需要四宫格时，请先删除原构图说明。</small>
              <small v-else-if="assetDraft.useDefaultRoleLayout">冷灰棚拍背景，保留项目画风与服装本色。只影响后续生成，已有图片保留。</small>
              <small v-else>已关闭，生成时只发送你的原提示词。</small>
              <details class="role-prompt-preview"><summary>查看本次角色生图提示词 · {{ ROLE_REFERENCE_VERSION }}</summary><pre>{{ assetImagePromptPreview }}</pre></details>
            </div>
            <details><summary>查看 JSON 详细字段</summary><pre>{{ assetRawDetails }}</pre></details>
            <p v-if="assetDetailTarget.generationError" class="asset-detail-error">{{ assetDetailTarget.generationError }}</p>
          </div>
        </div>
        <footer>
          <button type="button" class="asset-detail-secondary" @click="closeAssetDetail">取消</button>
          <template v-if="assetDetailTarget.category === 'audio'">
            <button
              type="button"
              class="asset-detail-secondary audio-detail-toggle-btn"
              :class="{ 'is-attached': isAssetInActiveShot(assetDetailTarget) }"
              :disabled="!assetUrl(assetDetailTarget)"
              @click="toggleAudioReference(assetDetailTarget); closeAssetDetail()"
            >
              {{ isAssetInActiveShot(assetDetailTarget) ? '✕ 从当前分镜撤回/移出' : '＋ 添加到当前分镜' }}
            </button>
          </template>
          <button v-else type="button" class="asset-detail-secondary" :disabled="!assetUrl(assetDetailTarget)" @click="addReference(assetDetailTarget); closeAssetDetail()">添加到当前分镜</button>
          <button type="button" class="asset-detail-save" @click="saveAssetDetail">保存修改</button>
        </footer>
      </section>
    </div>

    <BaseMediaPreview
      v-model:visible="mediaPreviewVisible"
      :src="mediaPreviewSrc"
      :type="mediaPreviewType"
      :references="mediaPreviewReferences"
      @video-error="handleMediaPreviewVideoError"
    />
  </section>

  <FinishedVideoTrackPreview
    v-model:visible="finishedPreviewVisible"
    :project-title="finishedPreviewProjectTitle"
    :project-id="String(finishedPreviewOwner?.id || '')"
    :assembly-enabled="finishedPreviewAssemblyEnabled"
    :assembly-value="finishedPreviewOwner?.aiAssembly"
    :models="videoApiModels"
    :text-models="textModels"
    :text-model="selectedTextModel"
    :file-url="fileDownloadUrl"
    :save-assembly="saveShotAssembly"
    :videos="finishedPreviewVideos"
    :loading="finishedPreviewLoading"
    :error="finishedPreviewError"
    :token="props.token"
    @video-error="handleFinishedVideoError"
    @edit-shot="openAssemblyRepairShot"
  />
  <!-- 全局工作区浮动提示 -->
  <Transition name="workspace-toast-fade">
    <div v-if="workspaceToast.message" class="workspace-floating-toast" :class="workspaceToast.type">
      <span class="workspace-toast-icon">
        <template v-if="workspaceToast.type === 'success'">✅</template>
        <template v-else-if="workspaceToast.type === 'error'">❌</template>
        <template v-else-if="workspaceToast.type === 'warning'">⚠️</template>
        <template v-else>ℹ️</template>
      </span>
      <span class="workspace-toast-text">{{ workspaceToast.message }}</span>
    </div>
  </Transition>
</template>

<style scoped>
.performance-update-note { margin: 0 0 14px; padding: 12px 14px; border: 1px solid #c7d9ed; border-radius: 10px; background: #f2f7fd; color: #405e83; font-size: 13px; line-height: 1.65; }
.video-project-hub { position: relative; z-index: 1; width: min(1420px,100%); box-sizing: border-box; margin: 0 auto; padding: 32px 0 44px; }
.video-project-hero { display: grid; min-height: 330px; grid-template-columns: minmax(0,1fr) minmax(360px,460px); gap: clamp(36px,6vw,100px); align-items: center; padding: clamp(26px,4vw,54px); overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 28px; background: radial-gradient(circle at 12% 10%,var(--theme-bg-surface) 0,transparent 34%),linear-gradient(135deg,var(--theme-bg-surface) 0%,var(--theme-bg-elevated) 68%); box-shadow: 0 26px 70px var(--theme-shadow); }
.video-project-hub-head > span,.video-project-library > header span { color: var(--theme-text-secondary); font: 700 12px/1 monospace; letter-spacing: .2em; }.video-project-hub-head h1 { margin: 17px 0 0; color: var(--theme-text-primary); font-size: clamp(38px,4vw,58px); line-height: 1.06; letter-spacing: -.055em; }.video-project-hub-head h1 em { color: var(--theme-accent-text); font-style: normal; }.video-project-hub-head p { max-width: 510px; margin: 19px 0 0; color: var(--theme-text-secondary); font-size: 14px; line-height: 1.8; }.video-project-highlights { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 27px; }.video-project-highlights span { display: flex; align-items: center; gap: 7px; padding: 8px 11px; border: 1px solid var(--theme-border-subtle); border-radius: 999px; color: var(--theme-text-secondary); background: var(--theme-accent-soft); font-size: 13px; }.video-project-highlights i { width: 6px; height: 6px; border-radius: 50%; background: var(--theme-accent-soft); box-shadow: 0 0 10px var(--theme-shadow); }
.video-project-create { display: grid; gap: 17px; padding: 23px; border: 1px solid var(--theme-border-subtle); border-radius: 20px; background: var(--theme-bg-elevated); box-shadow: 0 22px 55px var(--theme-shadow); backdrop-filter: blur(16px); }.video-project-create-head { display: flex; align-items: center; gap: 12px; padding-bottom: 3px; }.video-project-create-head > span { display: grid; width: 38px; height: 38px; flex: 0 0 auto; place-items: center; border-radius: 11px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 20px; }.video-project-create-head > div { display: grid; gap: 4px; }.video-project-create strong { color: var(--theme-text-primary); font-size: 16px; }.video-project-create small { color: var(--theme-text-secondary); font-size: 13px; }.video-project-create label { display: grid; gap: 8px; color: var(--theme-text-secondary); font-size: 13px; }.video-project-create label > span { padding-left: 2px; }.video-project-create label small { float: right; margin-left: 5px; }.video-project-create input,.video-project-create textarea { width: 100%; box-sizing: border-box; padding: 0 13px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; outline: 0; color: var(--theme-text-primary); background: var(--theme-bg-input); font: inherit; transition: border-color .18s ease,box-shadow .18s ease; }.video-project-create input { height: 43px; }.video-project-create textarea { min-height: 72px; padding-top: 12px; resize: none; line-height: 1.5; }.video-project-create input::placeholder,.video-project-create textarea::placeholder { color: var(--theme-text-primary); }.video-project-create input:focus,.video-project-create textarea:focus { border-color: var(--theme-border-strong); box-shadow: 0 0 0 3px var(--theme-shadow); }.video-project-create > button { display: flex; height: 45px; align-items: center; justify-content: space-between; padding: 0 16px; border: 1px solid var(--theme-border-subtle); border-radius: 11px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); cursor: pointer; font-size: 14px; font-weight: 700; transition: transform .18s ease,background .18s ease; }.video-project-create > button b { font-size: 18px; font-weight: 400; }.video-project-create > button:hover:not(:disabled) { transform: translateY(-1px); background: var(--theme-bg-card-hover); }.video-project-create > button:disabled { cursor: wait; opacity: .5; }
.video-project-error { margin: 13px 0 0; padding: 11px 13px; border: 1px solid var(--theme-danger-border); border-radius: 10px; color: var(--theme-danger-text); background: var(--theme-bg-surface); font-size: 14px; }.video-project-detail-overlay { position: fixed; z-index: 80; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; place-items: center; padding: 24px; background: var(--theme-overlay); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); }.video-project-library { margin-top: 36px; }.video-project-library > header { display: flex; align-items: end; justify-content: space-between; padding: 0 3px 14px; border-bottom: 1px solid var(--theme-border-subtle); }.video-project-library > header h2 { margin: 7px 0 0; color: var(--theme-text-primary); font-size: 22px; letter-spacing: -.025em; }.video-project-library > header b { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 9px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); font-size: 13px; }.video-project-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(360px,1fr)); gap: 18px; margin-top: 20px; }.video-project-card { min-width: 0; overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 20px; outline: 0; background: var(--theme-bg-elevated); box-shadow: 0 14px 38px var(--theme-shadow); cursor: pointer; transition: border-color .2s ease,transform .2s ease,box-shadow .2s ease; }.video-project-card:hover,.video-project-card:focus-visible { border-color: var(--theme-border-strong); transform: translateY(-3px); box-shadow: 0 24px 55px var(--theme-shadow); }.video-project-card-cover { position: relative; height: 116px; overflow: hidden; border-bottom: 1px solid var(--theme-border-subtle); background: radial-gradient(circle at 72% 35%,var(--theme-accent-soft),transparent 25%),linear-gradient(115deg,var(--theme-bg-surface),var(--theme-bg-elevated) 58%); }.video-project-card-cover::before,.video-project-card-cover::after { position: absolute; width: 220px; height: 1px; content: ''; background: linear-gradient(90deg,transparent,var(--theme-accent-soft),transparent); transform: rotate(-25deg); }.video-project-card-cover::before { right: -25px; top: 43px; }.video-project-card-cover::after { right: 12px; top: 72px; }.video-project-card-cover > span { position: absolute; left: 17px; top: 15px; color: var(--theme-text-primary); font: 700 13px/1 monospace; letter-spacing: .15em; }.video-project-card-cover > button { position: absolute; right: 17px; bottom: 15px; display: grid; width: 38px; height: 38px; place-items: center; border: 1px solid var(--theme-border-subtle); border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 12px; }.video-project-card-mark { position: absolute; left: 18px; bottom: 20px; display: flex; align-items: end; gap: 4px; }.video-project-card-mark i { display: block; width: 4px; border-radius: 4px; background: var(--theme-accent-soft); }.video-project-card-mark i:nth-child(1) { height: 11px; opacity: .45; }.video-project-card-mark i:nth-child(2) { height: 23px; opacity: .7; }.video-project-card-mark i:nth-child(3) { height: 16px; }.video-project-card-body { padding: 18px; }.video-project-card-copy { min-width: 0; }.video-project-card-copy > span { color: var(--theme-text-secondary); font: 700 12px/1 monospace; letter-spacing: .15em; }.video-project-card-copy h2 { overflow: hidden; margin: 7px 0 0; color: var(--theme-text-primary); font-size: 19px; text-overflow: ellipsis; white-space: nowrap; }.video-project-card-copy p { overflow: hidden; min-height: 17px; margin: 7px 0 0; color: var(--theme-text-secondary); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.video-project-card dl { display: grid; grid-template-columns: repeat(3,1fr); margin: 17px 0 0; padding: 13px 0; border-top: 1px solid var(--theme-border-subtle); border-bottom: 1px solid var(--theme-border-subtle); }.video-project-card dl > div { display: flex; align-items: baseline; justify-content: center; gap: 6px; border-right: 1px solid var(--theme-border-subtle); }.video-project-card dl > div:first-child { justify-content: flex-start; }.video-project-card dl > div:last-child { justify-content: flex-end; border-right: 0; }.video-project-card dt { color: var(--theme-text-secondary); font-size: 12px; }.video-project-card dd { margin: 0; color: var(--theme-text-primary); font-size: 14px; font-weight: 700; }.video-project-card footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-top: 15px; }.video-project-card time { color: var(--theme-text-secondary); font-size: 12px; }.video-project-card footer button { padding: 0; border: 0; color: var(--theme-text-secondary); background: transparent; cursor: pointer; font-size: 13px; }.video-project-card footer button span { display: inline-block; margin-left: 3px; transition: transform .18s ease; }.video-project-card:hover footer button span { transform: translateX(3px); }.video-project-empty { display: grid; min-height: 240px; place-content: center; gap: 8px; margin-top: 20px; border: 1px dashed var(--theme-border-subtle); border-radius: 17px; color: var(--theme-text-secondary); background: var(--theme-bg-elevated); text-align: center; font-size: 13px; }.video-project-empty strong { color: var(--theme-text-secondary); font-size: 16px; }.video-project-empty span { font-size: 14px; }
.video-project-card-skeleton { pointer-events: none; }
.video-project-card-skeleton .video-project-card-body > header,
.video-project-card-skeleton .video-project-card-stats span,
.video-project-card-skeleton footer { gap: 0; }
.video-project-skeleton-header { display: flex; align-items: center; justify-content: space-between; }
.video-project-skeleton-header i:first-child { width: 90px; height: 12px; }
.video-project-skeleton-header i:last-child { width: 16px; height: 16px; border-radius: 50%; }
.video-project-skeleton-title,
.video-project-skeleton-desc,
.video-project-skeleton-time,
.video-project-skeleton-cta,
.video-project-skeleton-header i,
.video-project-card-skeleton .video-project-card-stats i { display: block; background: linear-gradient(90deg,var(--theme-bg-elevated) 25%,var(--theme-bg-surface) 50%,var(--theme-bg-elevated) 75%); background-size: 200% 100%; animation: video-project-skeleton-shimmer 1.4s ease-in-out infinite; border-radius: 4px; }
.video-project-skeleton-title { width: 70%; height: 19px; margin: 7px 0 0; }
.video-project-skeleton-desc { width: 88%; height: 13px; margin: 7px 0 0; }
.video-project-card-skeleton .video-project-card-stats i { height: 12px; margin: 0 auto; }
.video-project-card-skeleton .video-project-card-stats span i:first-child { width: 20px; margin-bottom: 4px; }
.video-project-card-skeleton .video-project-card-stats span i:last-child { width: 28px; }
.video-project-skeleton-time { width: 90px; height: 12px; }
.video-project-skeleton-cta { width: 56px; height: 13px; margin-left: auto; }
@keyframes video-project-skeleton-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .video-project-skeleton-title, .video-project-skeleton-desc, .video-project-skeleton-time, .video-project-skeleton-cta, .video-project-skeleton-header i, .video-project-card-skeleton .video-project-card-stats i { animation: none; } }
@media (max-width: 980px) { .video-project-hero { grid-template-columns: 1fr; }.video-project-hub-head h1 br { display: none; }.video-project-create { max-width: 620px; }.video-project-grid { grid-template-columns: repeat(auto-fill,minmax(300px,1fr)); } }
.video-workbench { position: relative; z-index: 1; box-sizing: border-box; width: 100%; max-width: none; margin: 0; padding: 22px 0 20px; }
.video-workbench-head { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.video-workbench-head > div > span,.asset-rail-head span,.storyboard-column-head span { color: var(--theme-text-secondary); font: 700 12px/1 monospace; letter-spacing: .18em; }
.video-workbench-head h1 { margin: 9px 0 0; color: var(--theme-text-primary); font-size: 34px; letter-spacing: -.04em; }
.video-workbench-title { display: grid; justify-items: start; }.video-workbench-title > button { margin: 0 0 10px; padding: 0; border: 0; color: var(--theme-text-secondary); background: transparent; cursor: pointer; font-size: 14px; }.video-workbench-title > button:hover { color: var(--theme-text-primary); }.video-workbench-title > input { width: min(560px,65vw); margin-top: 7px; padding: 0; border: 0; outline: 0; color: var(--theme-text-primary); background: transparent; font-size: 34px; font-weight: 800; letter-spacing: -.04em; }.video-workbench-title p small { margin-left: 10px; color: var(--theme-text-secondary); font-size: 12px; }
.video-workbench-title > .video-project-description { margin-top: 5px; color: var(--theme-text-secondary); font-size: 13px; font-weight: 400; letter-spacing: 0; }.video-workbench-title > .video-project-description::placeholder { color: var(--theme-text-secondary); }
.video-workbench-head p { margin: 9px 0 0; color: var(--theme-text-secondary); font-size: 14px; }
.video-workbench-head > button { display: flex; height: 38px; align-items: center; gap: 7px; padding: 0 14px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; color: var(--theme-text-primary); background: var(--theme-bg-surface); cursor: pointer; font-size: 13px; }
.video-workbench-head > button:hover { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); }
.video-workbench-layout { display: grid; width: 100%; min-height: calc(100vh - 185px); grid-template-columns: clamp(240px,18vw,300px) minmax(0,1fr); gap: 18px; align-items: start; }
.asset-rail,.storyboard-column { border: 1px solid var(--theme-border-subtle); border-radius: 18px; background: var(--theme-bg-elevated); box-shadow: 0 22px 55px var(--theme-shadow); }
.asset-rail { position: sticky; top: 70px; overflow: visible; }
.asset-rail-head,.storyboard-column-head { display: flex; align-items: center; justify-content: space-between; padding: 18px; }
.asset-rail-head h2,.storyboard-column-head h2 { margin: 5px 0 0; color: var(--theme-text-primary); font-size: 16px; }
.asset-rail-head b,.storyboard-column-head b { padding: 4px 8px; border-radius: 999px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); font-size: 12px; }
.asset-head-actions { display: flex; align-items: center; gap: 6px; }.asset-head-actions button { display: grid; width: 25px; height: 25px; place-items: center; padding: 0; border: 1px solid var(--theme-border-subtle); border-radius: 7px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); cursor: pointer; }.asset-head-actions button:hover:not(:disabled) { color: var(--theme-text-primary); border-color: var(--theme-border-subtle); }.asset-head-actions button:disabled { cursor: wait; opacity: .45; }
.asset-category-tabs { display: grid; grid-template-columns: repeat(6,1fr); gap: 3px; margin: 0 10px 12px; padding: 4px; border-radius: 10px; background: var(--theme-bg-elevated); }
.asset-category-tabs button { display: grid; min-width: 0; height: 49px; place-items: center; align-content: center; gap: 3px; padding: 0; border: 0; border-radius: 7px; color: var(--theme-text-secondary); background: transparent; cursor: pointer; font-size: 12px; }
.asset-category-tabs button:hover,.asset-category-tabs button.active { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-category-tabs svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.asset-generator { display: grid; gap: 8px; margin: 0 10px 12px; padding: 10px; border: 1px solid var(--theme-border-subtle); border-radius: 12px; background: var(--theme-bg-elevated); }
.asset-json-import { display: grid; min-width: 0; min-height: 48px; grid-template-columns: 28px minmax(0,1fr); align-items: center; gap: 8px; padding: 7px 9px; border: 1px dashed var(--theme-border-subtle); border-radius: 9px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); cursor: pointer; text-align: left; }.asset-json-import:hover { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); }.asset-json-import > span { display: grid; width: 27px; height: 27px; place-items: center; border-radius: 8px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 15px; }.asset-json-import > div { display: grid; min-width: 0; gap: 3px; }.asset-json-import strong { font-size: 12px; }.asset-json-import small { overflow: hidden; color: var(--theme-text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.asset-generator-error { margin: 0; color: var(--theme-danger-text); font-size: 11px; line-height: 1.4; }
.asset-generate-spinner { width: 12px; height: 12px; border: 2px solid var(--theme-border-subtle); border-top-color: var(--theme-border-subtle); border-radius: 50%; animation: result-spin .7s linear infinite; }
.asset-rail-scroll { max-height: calc(100vh - 415px); min-height: 180px; padding: 0 10px 12px; overflow-y: auto; }
.asset-rail-grid { display: grid; grid-template-columns: 1fr; gap: 8px; }
.asset-pick-card { position: relative; min-width: 0; overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 10px; padding: 0; color: var(--theme-text-primary); background: var(--theme-bg-surface); text-align: left; }
.asset-pick-card:hover { border-color: var(--theme-border-subtle); transform: translateY(-1px); }
.asset-preview-button { display: block; width: 100%; padding: 0; border: 0; background: var(--theme-bg-elevated); cursor: pointer; }.asset-preview-button > img,.asset-audio-placeholder { display: grid; width: 100%; aspect-ratio: 1/1; place-items: center; object-fit: cover; background: var(--theme-bg-elevated); }
.asset-reference-count { position: absolute; z-index: 3; top: 10px; left: 46px; display: inline-flex; height: 20px; align-items: center; gap: 3px; padding: 0 6px; border: 1px solid var(--theme-border-subtle); border-radius: 999px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 3px 10px var(--theme-shadow); font: 700 10px/1 monospace; pointer-events: none; }.asset-reference-count.incomplete { color: var(--theme-accent-text); }.asset-reference-count svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.asset-audio-placeholder svg { width: 25px; fill: none; stroke: var(--theme-text-secondary); stroke-width: 1.5; }
.asset-missing-preview { display: grid; width: 100%; aspect-ratio: 1/1; place-items: center; align-content: center; gap: 7px; padding: 0; border: 0; color: var(--theme-text-secondary); background: repeating-linear-gradient(135deg,var(--theme-bg-elevated),var(--theme-bg-elevated) 8px,var(--theme-bg-elevated) 8px,var(--theme-bg-elevated) 16px); cursor: pointer; }.asset-missing-preview:hover { color: var(--theme-text-secondary); }.asset-missing-preview svg { width: 25px; fill: none; stroke: currentColor; stroke-width: 1.4; }.asset-missing-preview span { font-size: 11px; }
.asset-pick-copy { display: grid; width: 100%; gap: 2px; padding: 8px; border: 0; color: var(--theme-text-primary); background: transparent; cursor: pointer; text-align: left; }
.asset-pick-copy strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.asset-pick-copy small { color: var(--theme-text-secondary); font-size: 11px; }
.asset-card-add { position: absolute; top: 6px; right: 6px; display: grid; width: 25px; height: 25px; place-items: center; padding: 0; border: 2px solid var(--theme-border-subtle); border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 5px 14px var(--theme-shadow); cursor: pointer; font-size: 16px; opacity: 0; }.asset-pick-card:hover .asset-card-add,.asset-card-add:focus-visible { opacity: 1; }.asset-card-add:hover { background: var(--theme-bg-card-hover); transform: scale(1.06); }
.asset-card-generate { display: flex; width: calc(100% - 12px); height: 29px; align-items: center; justify-content: center; gap: 5px; margin: 0 6px 7px; padding: 0 5px; border: 1px solid var(--theme-border-subtle); border-radius: 7px; color: var(--theme-text-primary); background: var(--theme-bg-surface); cursor: pointer; font-size: 11px; }
.asset-card-generate svg { width: 12px; height: 12px; flex: 0 0 12px; fill: currentColor; }
.asset-card-generate .asset-generate-spinner { flex: 0 0 12px; }.asset-card-generate:hover:not(:disabled) { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); }.asset-card-generate:disabled { cursor: wait; opacity: .6; }.asset-card-error { overflow: hidden; margin: 0 7px 7px; color: var(--theme-danger-text); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.asset-rail-state { padding: 35px 10px; color: var(--theme-text-secondary); font-size: 12px; text-align: center; }
.asset-rail-state.error { color: var(--theme-danger-text); }
.asset-rail-empty { display: grid; padding: 44px 20px; gap: 7px; justify-items: center; text-align: center; }
.asset-rail-empty-icon { display: grid; width: 56px; height: 42px; place-items: center; margin-bottom: 6px; opacity: .3; }
.asset-rail-empty-icon svg { width: 100%; height: 100%; fill: var(--theme-text-secondary); }
.asset-rail-empty strong { color: var(--theme-text-secondary); font-size: 14px; font-weight: 600; }
.asset-rail-empty small { color: var(--theme-text-primary); font-size: 12px; line-height: 1.6; max-width: 200px; }
.storyboard-column { min-width: 0; padding-bottom: 16px; background: var(--theme-bg-elevated); }
.storyboard-column-head { border-bottom: 1px solid var(--theme-border-subtle); }
.workbench-episode-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 14px; background: var(--theme-bg-surface); border-bottom: 1px solid var(--theme-border-subtle); overflow-x: auto; scrollbar-width: thin; }
.workbench-episode-chips { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.workbench-episode-chip { display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; background: var(--theme-bg-elevated); color: var(--theme-text-secondary); font-size: 12px; cursor: pointer; transition: all .2s cubic-bezier(.22,1,.36,1); }
.workbench-episode-chip:hover { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.workbench-episode-chip.active { background: #eef2ff; border-color: #6366f1; color: #4338ca; font-weight: 600; box-shadow: 0 1px 4px rgba(99,102,241,0.15); }
.episode-chip-tag { font-size: 12px; }
.episode-chip-count { font-size: 11px; padding: 1px 6px; border-radius: 999px; background: rgba(0,0,0,0.06); color: inherit; }
.workbench-episode-chip.active .episode-chip-count { background: rgba(99,102,241,0.15); }
.workbench-episode-tools { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.workbench-episode-sync-btn { display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border: 1px dashed var(--theme-border-subtle); border-radius: 7px; background: transparent; color: var(--theme-text-secondary); font-size: 11px; cursor: pointer; transition: all .18s ease; }
.workbench-episode-sync-btn:hover:not(:disabled) { border-color: #6366f1; color: #4338ca; background: var(--theme-bg-card-hover); }
.workbench-episode-sync-btn:disabled { opacity: .5; cursor: wait; }
.stat-pill.stat-pill-episode { color: #4338ca; background: #eef2ff; border: 1px solid #c7d2fe; }
.storyboard-card { --shot-card-radius: var(--theme-accent); position: relative; margin: 15px; border: 1px solid var(--theme-border-subtle); border-radius: 17px; outline: none; background: linear-gradient(145deg,var(--theme-bg-surface),var(--theme-bg-elevated)); box-shadow: 0 14px 34px var(--theme-shadow); transition: border-color .18s ease,box-shadow .18s ease; }
.storyboard-card:has(.mode-popover,.settings-popover) { z-index: 40; }
.storyboard-card.active,.storyboard-card:focus-visible { border-color: var(--theme-border-strong); box-shadow: 0 18px 46px var(--theme-shadow),0 0 0 3px var(--theme-shadow); }
.storyboard-card-head { display: flex; height: 42px; align-items: center; gap: 9px; padding: 0 13px; border-bottom: 1px solid var(--theme-border-subtle); }
.shot-number { color: var(--theme-text-secondary); font: 700 12px/1 monospace; }
.storyboard-card-head input { flex: 1; min-width: 0; border: 0; outline: 0; color: var(--theme-text-primary); background: transparent; font-size: 13px; font-weight: 700; text-overflow: ellipsis; }
.shot-reference-notice { margin:0; padding:7px 15px; color:var(--theme-text-secondary); background:var(--theme-bg-surface); border-bottom:1px solid var(--theme-border-subtle); font-size:11px; line-height:1.5; overflow-wrap:anywhere; }
.shot-result-provenance { flex:none; margin:0; padding:12px; color:#8a4805; background:#fff6df; border:1px solid #e5cf9f; border-radius:8px; font-size:13px; line-height:1.6; overflow-wrap:anywhere; }
.shot-reference-manifest { flex:none; margin:6px 12px; padding:6px 10px; border-radius:6px; background:rgba(0,0,0,0.03); color:var(--theme-text-secondary); font-size:12px; line-height:1.5; }
.shot-reference-manifest.has-images { color:#18794e; background:#f0fdf4; border:1px solid #bbf7d0; font-weight:500; }
.shot-validation-banner { display:flex; flex-wrap:wrap; align-items:baseline; gap:5px 9px; margin:10px 12px; padding:9px 11px; border:1px solid #efb5ba; border-radius:8px; background:#fff4f5; color:#8e3942; font-size:12px; line-height:1.5; }
.shot-validation-banner strong { flex:0 0 auto; }
.shot-validation-banner span { min-width:0; flex:1 1 180px; overflow-wrap:anywhere; }
.storyboard-card-head button,.shot-expand { display: grid; width: 27px; height: 27px; place-items: center; border: 0; border-radius: 7px; color: var(--theme-text-secondary); background: transparent; cursor: pointer; }
.storyboard-card-head button:hover:not(:disabled),.shot-expand:hover { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.storyboard-card-head button:disabled { opacity: .2; cursor: not-allowed; }
.shot-body-grid { display: grid; grid-template-columns: minmax(520px,1.15fr) minmax(360px,.85fr); align-items: stretch; }
.shot-content { display: flex; min-width: 0; flex-direction: column; border-right: 1px solid var(--theme-border-subtle); }
.shot-content.expanded { position: fixed; z-index: 45; top: 64px; right: 24px; bottom: 24px; left: calc(var(--sidebar-width,240px) + 24px); overflow: visible; border: 1px solid var(--theme-border-subtle); border-radius: 18px; background: linear-gradient(145deg,var(--theme-bg-surface),var(--theme-bg-elevated)); box-shadow: 0 32px 100px var(--theme-shadow),0 0 0 100vmax var(--theme-shadow); }
.shot-content.expanded .shot-content-head { min-height: 56px; padding-right: 20px; padding-left: 20px; }
.shot-content.expanded .storyboard-compose { min-height: 0; flex: 1; grid-template-columns: auto minmax(260px,1fr) 34px; align-items: stretch; padding: 20px; }
.shot-content.expanded .storyboard-compose textarea { width: 100%; height: 100%; min-height: 240px; box-sizing: border-box; padding: 8px 10px; font-size: 16px; }
.shot-content.expanded .shot-expand { align-self: start; width: 34px; height: 34px; color: var(--theme-text-primary); background: var(--theme-bg-surface); }
.shot-content.expanded .storyboard-toolbar { min-height: 58px; padding-right: 18px; padding-left: 18px; border-radius: 0 0 18px 18px; background: var(--theme-bg-elevated); }
.shot-content.expanded .mode-popover,.shot-content.expanded .settings-popover { top: auto; bottom: calc(100% + 10px); }
.shot-content-head { display: grid; min-height: 44px; box-sizing: border-box; align-content: center; gap: 4px; padding: 0 13px; border-bottom: 1px solid var(--theme-border-subtle); }.shot-content-head span { color: var(--theme-text-secondary); font: 700 11px/1 monospace; letter-spacing: .14em; }.shot-content-head strong { color: var(--theme-text-primary); font-size: 12px; }
.storyboard-compose { position: relative; display: grid; grid-template-columns: auto minmax(220px,1fr) 28px; gap: 12px; min-height: 112px; align-items: start; padding: 14px; }
.reference-stack { position: relative; display: flex; width: 104px; min-width: 104px; max-width: 520px; height: 82px; align-items: stretch; isolation: isolate; transition: width .34s cubic-bezier(.22,1,.36,1),max-width .34s cubic-bezier(.22,1,.36,1); }
.reference-stack.expanded { width: var(--reference-expanded-width,78px); min-width: 78px; }
.reference-add { display: grid; width: 78px; flex: 0 0 78px; place-items: center; align-content: center; gap: 4px; overflow: hidden; border: 1px dashed var(--theme-border-subtle); border-radius: 10px; color: var(--theme-text-secondary); background: var(--theme-bg-elevated); cursor: pointer; opacity: 1; transform: translateX(0) scale(1); transform-origin: left center; transition: width .28s cubic-bezier(.22,1,.36,1),flex-basis .28s cubic-bezier(.22,1,.36,1),opacity .18s ease,transform .28s cubic-bezier(.22,1,.36,1),border-color .18s ease,background .18s ease; }.reference-add:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.reference-stack.has-references:not(.expanded) .reference-add { width: 0; flex-basis: 0; border-color: transparent; opacity: 0; pointer-events: none; transform: translateX(-12px) scale(.82); }
.reference-add span { font-size: 20px; line-height: 1; }.reference-add small { font-size: 12px; }
.reference-card { position: relative; flex: 0 0 78px; width: 78px; height: 78px; margin-left: 7px; overflow: visible; border: 1px solid var(--theme-border-subtle); border-radius: 10px; background: var(--theme-bg-surface); box-shadow: -5px 5px 15px var(--theme-shadow); transform: none; transform-origin: 50% 90%; transition: margin .24s ease,transform .24s cubic-bezier(.2,.8,.2,1),opacity .18s ease; }
.reference-stack:not(.expanded) .reference-card { position: absolute; top: 2px; left: 0; z-index: calc(var(--stack-index) + 1); margin: 0; transform: translateX(var(--stack-x)) translateY(var(--stack-y)) rotate(var(--stack-angle)) scale(.86); transform-origin: 50% 88%; }
.reference-stack:not(.expanded) .reference-card.stack-hidden { visibility: hidden; opacity: 0; }
.reference-stack.expanded .reference-card { position: relative; top: auto; left: auto; z-index: auto; margin-left: 7px; transform: none; animation: reference-card-unfold .34s cubic-bezier(.22,1,.36,1) both; animation-delay: calc(var(--stack-index) * 35ms); }
.reference-card > img,.reference-card > span { display: grid; width: 100%; height: 100%; place-items: center; border-radius: 9px; object-fit: cover; background: var(--theme-bg-elevated); }
.reference-card > img { cursor: pointer; transition: transform .25s ease; }
.reference-card > img:hover { transform: scale(1.04); }
.reference-card > span svg { width: 24px; fill: none; stroke: var(--theme-text-secondary); stroke-width: 1.5; }
.reference-card > small { position: absolute; right: 4px; bottom: 4px; left: 4px; overflow: hidden; padding: 3px 4px; border-radius: 4px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 11px; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.reference-stack:not(.expanded) .reference-card > small { display: none; }.reference-stack:not(.expanded) .reference-card:last-of-type > small { display: block; }
.reference-card > button { position: absolute; z-index: 3; top: -6px; right: -6px; display: block; width: 18px; height: 18px; padding: 0; border: 0; border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-surface); cursor: pointer; font-size: 13px; opacity: 0; pointer-events: none; transform: scale(.55) rotate(-35deg); transition: opacity .18s ease .12s,transform .26s cubic-bezier(.22,1,.36,1) .1s; }
.reference-stack.expanded .reference-card > button { opacity: 1; pointer-events: auto; transform: scale(1) rotate(0); }
.reference-stack-add { position: absolute; z-index: 20; left: 71px; bottom: 4px; display: grid; width: 27px; height: 27px; place-items: center; border: 3px solid var(--theme-border-subtle); border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 5px 12px var(--theme-shadow); font-size: 16px; line-height: 1; transition: transform .18s ease,background .18s ease; }.reference-stack:not(.expanded):hover .reference-stack-add { transform: scale(1.08); background: var(--theme-bg-card-hover); }
@keyframes reference-card-unfold { from { opacity: .72; transform: translateX(calc(var(--stack-x) * -1)) translateY(var(--stack-y)) rotate(var(--stack-angle)) scale(.86); } to { opacity: 1; transform: translateX(0) translateY(0) rotate(0) scale(1); } }
@media (prefers-reduced-motion: reduce) { .reference-stack,.reference-add,.reference-card,.reference-card > button { transition-duration: 1ms !important; animation-duration: 1ms !important; animation-delay: 0ms !important; } }
.storyboard-compose textarea { min-height: 78px; padding: 5px 8px 5px 4px; overflow-y: auto; resize: none; border: 0; outline: 0; color: var(--theme-text-primary); background: transparent; font-size: 13px; line-height: 1.65; box-shadow: none; }
.storyboard-compose textarea::placeholder { color: var(--theme-text-secondary); }
.storyboard-compose textarea { scrollbar-width: thin; scrollbar-color: var(--theme-scrollbar-thumb) transparent; }
.storyboard-compose textarea::-webkit-scrollbar { width: 7px; }
.storyboard-compose textarea::-webkit-scrollbar-track { border-radius: 999px; background: transparent; }
.storyboard-compose textarea::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 999px; background: var(--theme-scrollbar-thumb); background-clip: padding-box; }
.storyboard-compose textarea::-webkit-scrollbar-thumb:hover { background: var(--theme-scrollbar-thumb-hover); background-clip: padding-box; }
.shot-expand svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.5; }
.shot-editor-actions { display: flex; align-self: start; flex-direction: column; gap: 7px; }
.shot-editor-actions > button { display: grid; width: 28px; height: 28px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 7px; color: var(--theme-text-secondary); background: transparent; cursor: pointer; }
.shot-editor-actions > button:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.shot-editor-actions > button svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.shot-editor-actions .shot-send-preview-toggle.active { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.shot-editor-actions .shot-audio-boost:hover { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.shot-editor-actions .shot-visual-boost:hover { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.shot-editor-actions .shot-prompt-optimize:hover { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.shot-editor-actions .shot-prompt-optimize.has-error { color: #d97706; border-color: rgba(217, 119, 6, 0.45); background: rgba(245, 158, 11, 0.12); box-shadow: 0 0 6px rgba(245, 158, 11, 0.25); }
.shot-result-error-actions .shot-optimize-err-btn { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-accent-soft); font-weight: 600; }
.shot-result-error-actions .shot-optimize-err-btn:hover { background: var(--theme-accent); color: var(--theme-text-on-accent); }

.shot-inherit-prev-frame-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
  padding: 2px 8px;
  border: 1px solid var(--theme-accent-border);
  border-radius: 6px;
  font-size: 11px;
  color: var(--theme-accent-text);
  background: var(--theme-accent-soft);
  cursor: pointer;
  transition: all .15s ease;
  white-space: nowrap;
}
.shot-inherit-prev-frame-btn:hover:not(:disabled) {
  background: var(--theme-accent-soft);
  border-color: var(--theme-accent-border);
  color: var(--theme-text-primary);
}
.shot-inherit-prev-frame-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.shot-inherit-prev-frame-btn svg {
  width: 12px;
  height: 12px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
}
.shot-result-cascade-control:hover {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-accent-text) !important;
}
.asset-detail-crop-portrait:hover {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-accent-text) !important;
}
.btn-audio-formula-mini { padding: 2px 8px; border: 1px solid var(--theme-accent-border); border-radius: 5px; font-size: 11px; color: var(--theme-accent-text); background: var(--theme-accent-soft); cursor: pointer; transition: all .15s ease; }
.btn-audio-formula-mini:hover { background: var(--theme-accent-soft); border-color: var(--theme-accent-border); }
.storyboard-toolbar { display: flex; width: 100%; min-width: 0; max-width: none; min-height: 42px; box-sizing: border-box; align-items: center; gap: 10px; margin: 0; padding: 8px 12px; border-top: 1px solid var(--theme-border-subtle); color: var(--theme-text-secondary); font-size: 12px; }
.storyboard-toolbar button { display: flex; align-items: center; gap: 5px; padding: 4px 5px; border: 0; color: var(--theme-text-secondary); background: transparent; cursor: pointer; font-size: 12px; white-space: nowrap; }
.storyboard-toolbar button:hover { color: var(--theme-text-primary); }.storyboard-toolbar button svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.6; }
.settings-summary-btn { padding: 4px 10px !important; border: 1px solid var(--theme-border-subtle) !important; border-radius: 8px !important; color: var(--theme-text-primary) !important; background: var(--theme-bg-elevated) !important; transition: border-color .18s ease,color .18s ease; }
.settings-summary-btn:hover { border-color: var(--theme-border-subtle) !important; color: var(--theme-text-primary) !important; }
.settings-summary-btn[aria-expanded="true"] { border-color: var(--theme-border-subtle) !important; color: var(--theme-text-primary) !important; }
.settings-summary-btn svg { width: 13px !important; stroke-width: 2; }
.storyboard-toolbar span { white-space: nowrap; }.storyboard-toolbar span i { display: inline-block; width: 11px; height: 6px; margin-right: 4px; border: 1px solid currentColor; border-radius: 2px; }
.storyboard-toolbar .shot-clear { margin-left: auto; color: var(--theme-text-secondary); }
.storyboard-toolbar .shot-submit { display: grid; width: 32px; height: 32px; place-items: center; padding: 0; border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-elevated); }
.storyboard-toolbar .shot-submit:hover { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.storyboard-toolbar .shot-submit:disabled { cursor: wait; opacity: .55; }
.toolbar-popover-wrap { position: relative; display: flex; flex: 0 0 auto; }
.mode-popover,.settings-popover { position: absolute; z-index: 60; top: auto; bottom: calc(100% + 8px); left: 0; border: 1px solid var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-surface); box-shadow: 0 18px 48px var(--theme-shadow); }
.mode-popover { width: 196px; padding: 10px; border-radius: 12px; }.mode-popover > label { display: block; padding: 2px 5px 9px; color: var(--theme-text-secondary); font-size: 13px; }.storyboard-toolbar .mode-popover > button { display: grid; width: 100%; height: 42px; grid-template-columns: 20px minmax(0,1fr) 18px; align-items: center; gap: 8px; padding: 0 10px; border-radius: 9px; color: var(--theme-text-secondary); font-size: 14px; text-align: left; }.storyboard-toolbar .mode-popover > button:hover,.storyboard-toolbar .mode-popover > button.active { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }.mode-popover > button b { font-size: 15px; text-align: center; }
.settings-popover { display: grid; width: min(460px,calc(100vw - 340px)); min-width: 400px; max-height: min(380px,calc(100vh - 80px)); box-sizing: border-box; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 12px; padding: 12px; overflow-y: auto; overscroll-behavior: contain; border-radius: 12px; scrollbar-width: thin; }
.settings-popover .settings-field-wide { grid-column: 1 / -1; }
.settings-popover fieldset { margin: 0; padding: 0; border: 0; }
.seedance-model-select { margin-top: 10px; display: block; width: 100%; }
.seedance-model-select :deep(.ui-select) { display: block; width: 100%; }
.seedance-model-select :deep(.ui-select-trigger) { min-height: 38px; border-radius: 9px; width: 100%; box-sizing: border-box; }
.seedance-model-select :deep(.ui-select-value) { flex: 1 1 auto; min-width: 0; }
.settings-popover legend { padding: 0; margin-bottom: 8px; color: var(--theme-text-secondary); font-size: 11px; font-weight: 700; letter-spacing: .04em; }.settings-popover::-webkit-scrollbar { width: 7px; }.settings-popover::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 99px; background: var(--theme-scrollbar-thumb); background-clip: padding-box; }.settings-popover fieldset { min-width: 0; margin: 0; padding: 0; border: 0; }.settings-popover fieldset:nth-child(1),.settings-popover fieldset:nth-child(3),.settings-popover fieldset:nth-child(5) { grid-column: 1 / -1; }.settings-popover legend { margin-bottom: 7px; color: var(--theme-text-secondary); font-size: 12px; }
.ratio-options { display: grid; grid-template-columns: repeat(7,minmax(0,1fr)); overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 9px; background: var(--theme-bg-elevated); }.storyboard-toolbar .ratio-options button { display: grid; height: 46px; place-items: center; align-content: center; gap: 3px; padding: 0; border-right: 1px solid var(--theme-border-subtle); border-radius: 0; color: var(--theme-text-secondary); font-size: 12px; }.ratio-options button:last-child { border-right: 0; }.storyboard-toolbar .ratio-options button:hover,.storyboard-toolbar .ratio-options button.active { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }.ratio-options svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.6; }
.segmented-options { display: grid; grid-template-columns: repeat(2,1fr); overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 9px; background: var(--theme-bg-elevated); }.segmented-options.four { grid-template-columns: repeat(4,1fr); }.storyboard-toolbar .segmented-options button { height: 38px; justify-content: center; border-right: 1px solid var(--theme-border-subtle); border-radius: 0; color: var(--theme-text-secondary); font-size: 14px; }.segmented-options button:last-child { border-right: 0; }.storyboard-toolbar .segmented-options button:hover,.storyboard-toolbar .segmented-options button.active { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.duration-options,.count-options { display: grid; grid-template-columns: repeat(8,1fr); gap: 4px; margin-top: 9px; padding: 4px; border-radius: 9px; background: var(--theme-bg-elevated); }.count-options { margin-top: 0; }.storyboard-toolbar .duration-options button,.storyboard-toolbar .count-options button { height: 32px; justify-content: center; padding: 0; border-radius: 7px; color: var(--theme-text-secondary); font-size: 13px; }.storyboard-toolbar .duration-options button:hover,.storyboard-toolbar .duration-options button.active,.storyboard-toolbar .count-options button:hover,.storyboard-toolbar .count-options button.active { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.shot-result { position: relative; display: flex; min-width: 0; margin: 12px; overflow: hidden; flex-direction: column; border: 1px solid var(--theme-border-subtle); border-radius: 13px; background: var(--theme-bg-elevated); box-shadow: inset 0 1px var(--theme-shadow); }
.shot-result-replace-control:disabled,.shot-result-download-control:disabled { cursor: wait; opacity: .55; }
.shot-result-replace-control .asset-generate-spinner,.shot-result-download-control .asset-generate-spinner { width: 14px; height: 14px; }
.shot-result-replace-error { position: absolute; z-index: 8; top: 10px; right: 10px; max-width: calc(100% - 20px); margin: 0; padding: 6px 9px; border: 1px solid var(--theme-danger-border); border-radius: 7px; color: var(--theme-danger-text); background: var(--theme-danger-soft); box-shadow: 0 6px 18px var(--theme-shadow); font-size: 11px; }
.shot-result > header { display: flex; min-height: 44px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 13px; border-bottom: 1px solid var(--theme-border-subtle); background: linear-gradient(100deg,var(--theme-bg-elevated),var(--theme-bg-elevated)); }
.shot-result > header > div { display: grid; gap: 4px; }.shot-result > header span { color: var(--theme-text-secondary); font: 700 11px/1 monospace; letter-spacing: .14em; }.shot-result > header strong { color: var(--theme-text-primary); font-size: 12px; }
.shot-result > header small { overflow: hidden; max-width: 180px; color: var(--theme-text-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.shot-result-player { position: relative; display: grid; min-height: 230px; overflow: hidden; flex: 1; place-items: center; isolation: isolate; background: radial-gradient(circle at 50% 35%,var(--theme-bg-surface) 0,var(--theme-bg-elevated) 52%,var(--theme-bg-elevated) 100%); border-radius: 11px; }
.shot-result-player::before { position: absolute; z-index: -1; inset: 0; content: ''; opacity: .5; background-image: linear-gradient(var(--theme-accent-soft) 1px,transparent 1px),linear-gradient(90deg,var(--theme-accent-soft) 1px,transparent 1px); background-size: 28px 28px; mask-image: linear-gradient(#000,transparent 80%); }
.shot-result-player video { display: block; width: 100%; height: 100%; min-height: 230px; max-height: 480px; object-fit: cover; background: var(--theme-bg-elevated); border-radius: 11px; cursor: pointer; }
.shot-result-watermark-badge { position: absolute; z-index: 6; top: 10px; left: 10px; padding: 5px 8px; border: 1px solid var(--theme-accent-border); border-radius: 7px; color: var(--theme-accent-text); background: var(--theme-accent-soft); box-shadow: 0 4px 14px var(--theme-shadow); font-size: 11px; font-weight: 700; }
.shot-result-center-play { position: absolute; z-index: 4; top: 50%; left: 50%; display: grid; width: 56px; height: 56px; place-items: center; padding: 0; border: 0; border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 6px 24px var(--theme-shadow); cursor: pointer; transform: translate(-50%,-50%); transition: transform .18s ease,background .18s ease; }
.shot-result-center-play:hover { background: var(--theme-bg-card-hover); transform: translate(-50%,-50%) scale(1.08); }
.shot-result-center-play svg { width: 26px; fill: currentColor; }
.shot-result-player .shot-result-expand { position: absolute; z-index: 5; top: 10px; right: 10px; display: inline-flex; width: 32px; height: 32px; align-items: center; justify-content: center; padding: 0; border: 0; border-radius: 8px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); cursor: pointer; opacity: 0; transition: opacity .18s ease,background .18s ease; }
.shot-result-player .shot-result-expand svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.7; }
.shot-result-player:hover .shot-result-expand { opacity: 1; }
.shot-result-player .shot-result-expand:hover { background: var(--theme-bg-card-hover); }
/* 底部控件栏：渐变遮罩 + 毛玻璃 */
.shot-result-controls { position: absolute; z-index: 4; right: 0; bottom: 0; left: 0; display: flex; align-items: center; gap: 8px; padding: 10px 12px 8px; background: linear-gradient(transparent,var(--theme-bg-elevated)); opacity: 0; transition: opacity .2s ease; }
.shot-result-player:hover .shot-result-controls,
.shot-result-controls:hover { opacity: 1; }
.shot-ctrl-btn { display: grid; width: 28px; height: 28px; flex: 0 0 28px; place-items: center; padding: 0; border: 0; border-radius: 6px; color: var(--theme-text-primary); background: transparent; cursor: pointer; transition: background .15s ease; }
.shot-ctrl-btn:hover { background: var(--theme-accent-soft); }
.shot-ctrl-btn svg { width: 16px; fill: currentColor; }
.shot-ctrl-time { color: var(--theme-text-primary); font: 600 11px/1 monospace; font-variant-numeric: tabular-nums; white-space: nowrap; user-select: none; }
/* 自定义进度条 */
.shot-ctrl-seek { flex: 1; min-width: 0; height: 4px; appearance: none; -webkit-appearance: none; background: var(--theme-accent-soft); border-radius: 2px; cursor: pointer; background-image: linear-gradient(var(--theme-accent-soft),var(--theme-accent-soft)); background-size: var(--p,0%) 100%; background-repeat: no-repeat; }
.shot-ctrl-seek::-webkit-slider-thumb { -webkit-appearance: none; width: 12px; height: 12px; border: 0; border-radius: 50%; background: var(--theme-accent-soft); box-shadow: 0 0 0 3px var(--theme-shadow); cursor: pointer; transition: transform .15s ease; }
.shot-ctrl-seek::-webkit-slider-thumb:hover { transform: scale(1.2); }
.shot-ctrl-seek::-moz-range-thumb { width: 12px; height: 12px; border: 0; border-radius: 50%; background: var(--theme-accent-soft); cursor: pointer; }
.shot-result-empty,.shot-result-progress,.shot-result-error,.shot-result-complete { min-height: 150px; box-sizing: border-box; padding: 20px; flex: 1; }
.shot-result-empty { display: flex; align-items: center; justify-content: center; gap: 12px; color: var(--theme-text-secondary); background: radial-gradient(circle at 50% 45%,var(--theme-bg-surface),var(--theme-bg-elevated) 65%); }
.shot-result-empty > span { display: grid; width: 40px; height: 40px; place-items: center; border: 1px solid var(--theme-border-subtle); border-radius: 12px; background: var(--theme-bg-elevated); }.shot-result-empty svg { width: 20px; fill: none; stroke: var(--theme-text-secondary); stroke-width: 1.5; }.shot-result-empty > div,.shot-result-progress > div { display: grid; gap: 5px; }.shot-result-empty strong,.shot-result-progress strong,.shot-result-error strong { color: var(--theme-text-secondary); font-size: 12px; }.shot-result-empty small,.shot-result-progress small { color: var(--theme-text-secondary); font-size: 12px; }
.shot-result-progress { position: relative; display: grid; grid-template-columns: 34px minmax(0,1fr) auto; align-items: center; gap: 12px; }.shot-result-progress b { color: var(--theme-text-secondary); font: 700 12px/1 monospace; }.shot-result-progress > i { position: absolute; right: 20px; bottom: 20px; left: 66px; height: 3px; overflow: hidden; border-radius: 3px; background: var(--theme-accent); color: var(--theme-text-on-accent); }.shot-result-progress > i em { display: block; height: 100%; border-radius: inherit; background: var(--theme-accent); transition: width .3s ease; color: var(--theme-text-on-accent); }
.result-spinner { width: 28px; height: 28px; border: 2px solid var(--theme-border-subtle); border-top-color: var(--theme-border-subtle); border-radius: 50%; animation: result-spin .8s linear infinite; }
.shot-result-error { display: grid; grid-template-columns: minmax(0,1fr) auto; align-content: center; align-items: center; gap: 7px 15px; }.shot-result-error strong { color: var(--theme-danger-text); }.shot-result-error > span { grid-column: 1; color: var(--theme-danger-text); font-size: 12px; }.shot-result-error-actions { display: flex; grid-column: 2; grid-row: 1 / 3; gap: 7px; }.shot-result-error-actions button,.shot-result-upload { padding: 7px 10px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; color: var(--theme-text-primary); background: var(--theme-bg-surface); cursor: pointer; font-size: 12px; transition: border-color .16s ease,background .16s ease,opacity .16s ease; }.shot-result-error-actions button:first-child { border-color: var(--theme-danger-border); color: var(--theme-danger-text); background: var(--theme-bg-surface); }.shot-result-error-actions button:hover,.shot-result-upload:hover { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); }.shot-result-error-actions button:disabled,.shot-result-upload:disabled { cursor: wait; opacity: .55; }
.shot-result-complete { display: grid; place-content: center; gap: 7px; text-align: center; }.shot-result-complete strong { color: var(--theme-text-secondary); font-size: 12px; }.shot-result-complete span { color: var(--theme-text-secondary); font-size: 12px; }.shot-result-complete .shot-result-upload { justify-self: center; margin-top: 4px; }
.shot-result-empty .shot-result-upload { margin-left: auto; white-space: nowrap; }

.json-import-backdrop { position: fixed; z-index: 200; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; box-sizing: border-box; place-items: center; padding: 28px; background: var(--theme-overlay); backdrop-filter: blur(8px); }
.json-import-dialog { width: min(680px,calc(100vw - 56px)); max-height: calc(100vh - 56px); box-sizing: border-box; overflow: auto; border: 1px solid var(--theme-border-subtle); border-radius: 20px; color: var(--theme-text-primary); background: linear-gradient(145deg,var(--theme-bg-surface),var(--theme-bg-elevated)); box-shadow: 0 32px 100px var(--theme-shadow); }
.json-import-dialog > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 24px 26px 18px; border-bottom: 1px solid var(--theme-border-subtle); }
.json-import-dialog > header span { color: var(--theme-text-secondary); font: 700 12px/1 monospace; letter-spacing: .16em; }.json-import-dialog > header h2 { margin: 9px 0 0; color: var(--theme-text-primary); font-size: 23px; }.json-import-dialog > header p { margin: 8px 0 0; color: var(--theme-text-secondary); font-size: 13px; }
.json-import-dialog > header button { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 9px; color: var(--theme-text-secondary); background: transparent; cursor: pointer; font-size: 22px; }.json-import-dialog > header button:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.json-import-editor { display: grid; gap: 9px; padding: 20px 26px 0; color: var(--theme-text-secondary); font-size: 13px; }.json-import-textarea { width: 100%; min-height: 290px; box-sizing: border-box; padding: 15px 16px; resize: vertical; border: 1px solid var(--theme-border-subtle); border-radius: 13px; outline: 0; color: var(--theme-text-primary); background: var(--theme-bg-input); font: 14px/1.65 Consolas,"Microsoft YaHei",monospace; tab-size: 2; }.json-import-textarea::placeholder { color: var(--theme-text-secondary); }.json-import-textarea:focus { border-color: var(--theme-border-strong); box-shadow: 0 0 0 3px var(--theme-shadow); }
.json-import-error { margin: 12px 26px 0; padding: 10px 12px; border: 1px solid var(--theme-danger-border); border-radius: 9px; color: var(--theme-danger-text); background: var(--theme-bg-surface); font-size: 14px; line-height: 1.5; }
.json-import-dialog > footer { display: grid; grid-template-columns: minmax(190px,1fr) auto auto; align-items: center; gap: 10px; padding: 18px 26px 24px; }
.json-import-dialog > footer button { height: 42px; box-sizing: border-box; border-radius: 10px; cursor: pointer; font-size: 14px; }.json-file-button { display: grid; min-width: 0; grid-template-columns: 28px minmax(0,1fr); align-items: center; gap: 9px; padding: 5px 10px; border: 1px dashed var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-surface); text-align: left; }.json-file-button:hover { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); }.json-file-button > span { display: grid; width: 27px; height: 27px; place-items: center; border-radius: 7px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 15px; }.json-file-button > div { display: grid; min-width: 0; gap: 2px; }.json-file-button strong { font-size: 14px; }.json-file-button small { color: var(--theme-text-secondary); font-size: 12px; }
.json-cancel-button { padding: 0 17px; border: 1px solid var(--theme-border-subtle); color: var(--theme-text-secondary); background: var(--theme-bg-surface); }.json-cancel-button:hover { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }.json-confirm-button { padding: 0 19px; border: 1px solid var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-weight: 700; }.json-confirm-button:hover:not(:disabled) { background: var(--theme-bg-card-hover); }.json-confirm-button:disabled { cursor: not-allowed; opacity: .35; }

.asset-detail-backdrop { position: fixed; z-index: 210; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; box-sizing: border-box; place-items: center; padding: 28px; background: var(--theme-overlay); backdrop-filter: blur(9px); }
.asset-detail-dialog { width: min(900px,calc(100vw - 56px)); max-height: calc(100vh - 56px); box-sizing: border-box; overflow: auto; border: 1px solid var(--theme-border-subtle); border-radius: 20px; color: var(--theme-text-primary); background: linear-gradient(145deg,var(--theme-bg-surface),var(--theme-bg-elevated)); box-shadow: 0 32px 110px var(--theme-shadow); scrollbar-width: thin; scrollbar-color: var(--theme-scrollbar-thumb) transparent; }
.asset-detail-dialog > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 22px 25px 17px; border-bottom: 1px solid var(--theme-border-subtle); }.asset-detail-dialog > header span { color: var(--theme-text-secondary); font: 700 12px/1 monospace; letter-spacing: .16em; }.asset-detail-dialog > header h2 { margin: 8px 0 0; color: var(--theme-text-primary); font-size: 23px; }.asset-detail-dialog > header p { margin: 7px 0 0; color: var(--theme-text-secondary); font-size: 14px; }.asset-detail-dialog > header button { display: grid; width: 34px; height: 34px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 9px; color: var(--theme-text-secondary); background: transparent; cursor: pointer; font-size: 22px; }.asset-detail-dialog > header button:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-detail-body { display: grid; grid-template-columns: minmax(280px,.8fr) minmax(340px,1.2fr); gap: 22px; padding: 22px 25px; }.asset-detail-preview { display: flex; min-width: 0; flex-direction: column; gap: 12px; }.asset-detail-image-preview,.asset-detail-empty { width: 100%; min-height: 330px; max-height: 520px; border: 1px solid var(--theme-border-subtle); border-radius: 14px; background: var(--theme-bg-elevated); }.asset-detail-image-preview { position: relative; display: grid; padding: 0; overflow: hidden; place-items: center; cursor: zoom-in; transition: border-color .18s ease,box-shadow .18s ease; }.asset-detail-image-preview:hover,.asset-detail-image-preview:focus-visible { border-color: var(--theme-border-strong); outline: 0; box-shadow: 0 0 0 3px var(--theme-shadow); }.asset-detail-image-preview > img { display: block; width: 100%; min-height: 330px; max-height: 520px; object-fit: contain; transition: transform .2s ease; }.asset-detail-image-preview:hover > img { transform: scale(1.015); }.asset-detail-zoom-hint { position: absolute; right: 11px; bottom: 11px; display: inline-flex; height: 28px; align-items: center; gap: 6px; padding: 0 10px; border: 1px solid var(--theme-border-subtle); border-radius: 999px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); backdrop-filter: blur(8px); font-size: 11px; }.asset-detail-zoom-hint svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }.asset-detail-empty { display: grid; place-items: center; align-content: center; gap: 10px; color: var(--theme-text-secondary); }.asset-detail-empty svg { width: 44px; fill: none; stroke: currentColor; stroke-width: 1.3; }.asset-detail-empty span { font-size: 14px; }
.asset-detail-references { display: grid; min-width: 0; gap: 9px; padding: 11px; border: 1px solid var(--theme-border-subtle); border-radius: 12px; background: var(--theme-bg-elevated); }.asset-detail-references > header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.asset-detail-references > header strong { color: var(--theme-text-primary); font-size: 12px; }.asset-detail-references > header > div { display: flex; align-items: center; gap: 8px; }.asset-detail-references > header span { color: var(--theme-text-secondary); font-size: 11px; }.asset-detail-reference-copy { min-width: 48px; height: 25px; padding: 0 10px; border: 1px solid var(--theme-border-subtle); border-radius: 7px; color: var(--theme-text-primary); background: var(--theme-bg-surface); cursor: pointer; font-size: 11px; }.asset-detail-reference-copy:hover:not(:disabled) { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }.asset-detail-reference-copy:disabled { cursor: not-allowed; opacity: .5; }.asset-detail-references > div { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 7px; }.asset-detail-references > div > button,.asset-detail-reference-missing { position: relative; display: grid; min-width: 0; aspect-ratio: 1/1; padding: 0; overflow: hidden; place-items: center; border: 1px solid var(--theme-border-subtle); border-radius: 9px; color: var(--theme-text-secondary); background: var(--theme-bg-elevated); }.asset-detail-references > div > button:not(:disabled) { cursor: zoom-in; }.asset-detail-references > div > button:not(:disabled):hover { border-color: var(--theme-border-subtle); }.asset-detail-references > div > button:disabled { cursor: not-allowed; opacity: .58; }.asset-detail-references img { width: 100%; height: 100%; object-fit: cover; }.asset-detail-references small { position: absolute; right: 4px; bottom: 4px; left: 4px; overflow: hidden; padding: 3px 5px; border-radius: 5px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.asset-detail-reference-missing i { color: var(--theme-danger-text); font: normal 11px/1 inherit; }
.asset-detail-image-preview.is-generating::after,.asset-detail-empty.is-generating::after { position: absolute; z-index: 1; top: -18%; bottom: -18%; left: 0; width: 24%; background: linear-gradient(90deg,transparent,var(--theme-bg-card),transparent); filter: blur(.25px); content: ''; pointer-events: none; animation: assetDetailImageGenerateSweep 1.55s ease-in-out infinite; }.asset-detail-empty.is-generating { position: relative; overflow: hidden; border-color: var(--theme-border-subtle); }.asset-detail-empty.is-generating > svg,.asset-detail-empty.is-generating > span { position: relative; z-index: 2; }.asset-detail-zoom-hint { z-index: 2; }
@keyframes assetDetailImageGenerateSweep { 0% { opacity: 0; transform: translateX(-140%) skewX(-12deg); } 18%,78% { opacity: .9; } 100% { opacity: 0; transform: translateX(440%) skewX(-12deg); } }
.asset-detail-audio-player { display: grid; width: 100%; min-height: 76px; box-sizing: border-box; grid-template-columns: 42px minmax(0,1fr) auto 18px; align-items: center; gap: 12px; margin: auto 0; padding: 14px 16px; border: 1px solid var(--theme-border-subtle); border-radius: 14px; background: linear-gradient(135deg,var(--theme-bg-surface),var(--theme-bg-elevated)); box-shadow: inset 0 1px var(--theme-shadow),0 12px 30px var(--theme-shadow); }
.asset-detail-audio-player > audio { display: none; }
.asset-detail-audio-toggle { display: grid; width: 42px; height: 42px; place-items: center; padding: 0; border: 1px solid var(--theme-border-subtle); border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-elevated); cursor: pointer; transition: background .16s ease,transform .16s ease; }
.asset-detail-audio-toggle:hover { background: var(--theme-bg-card-hover); transform: scale(1.04); }
.asset-detail-audio-toggle svg { width: 19px; height: 19px; fill: currentColor; stroke: none; }
.asset-detail-audio-copy { display: grid; min-width: 0; gap: 10px; }
.asset-detail-audio-copy > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.asset-detail-audio-copy strong { color: var(--theme-text-primary); font-size: 12px; }
.asset-detail-audio-copy span { color: var(--theme-text-secondary); font-size: 11px; }
.asset-detail-audio-copy input { width: 100%; height: 4px; margin: 0; appearance: none; border-radius: 999px; outline: 0; background: linear-gradient(90deg,var(--theme-bg-input) var(--audio-progress),var(--theme-bg-input) var(--audio-progress)); cursor: pointer; }
.asset-detail-audio-copy input::-webkit-slider-thumb { width: 12px; height: 12px; appearance: none; border: 2px solid var(--theme-border-subtle); border-radius: 50%; background: var(--theme-bg-input); box-shadow: 0 1px 5px var(--theme-shadow); }
.asset-detail-audio-copy input::-moz-range-thumb { width: 9px; height: 9px; border: 2px solid var(--theme-border-subtle); border-radius: 50%; background: var(--theme-bg-input); }
.asset-detail-audio-player time { color: var(--theme-text-secondary); font: 11px/1.2 Consolas,monospace; white-space: nowrap; }
.asset-detail-audio-volume { width: 18px; fill: none; stroke: var(--theme-text-secondary); stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.asset-detail-media-actions { display: flex; align-items: center; justify-content: center; gap: 8px; }.asset-detail-media-actions button { display: grid; width: 42px; height: 42px; padding: 0; place-items: center; border: 1px solid var(--theme-border-subtle); border-radius: 11px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); cursor: pointer; transition: border-color .16s ease,color .16s ease,background .16s ease,transform .16s ease; }.asset-detail-media-actions button:hover:not(:disabled) { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); transform: translateY(-1px); }.asset-detail-media-actions button:focus-visible { outline: 2px solid var(--theme-border-strong); outline-offset: 2px; }.asset-detail-media-actions button:disabled { cursor: wait; opacity: .5; }.asset-detail-media-actions svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }.asset-detail-media-actions .asset-detail-generate-media { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-elevated); }.asset-detail-media-actions .asset-detail-generate-media:hover:not(:disabled) { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }.asset-detail-media-actions .asset-detail-download-media:hover:not(:disabled) { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-bg-card-hover); }.asset-detail-media-actions .asset-detail-clear-image:hover:not(:disabled) { border-color: var(--theme-danger-border); color: var(--theme-danger-text); background: var(--theme-bg-card-hover); }
.asset-detail-fields { display: grid; min-width: 0; align-content: start; gap: 14px; }.asset-detail-fields > label { display: grid; gap: 7px; }.asset-detail-fields > label > span { color: var(--theme-text-secondary); font-size: 14px; }.asset-detail-fields input,.asset-detail-fields textarea { width: 100%; box-sizing: border-box; padding: 10px 11px; border: 1px solid var(--theme-border-subtle); border-radius: 9px; outline: 0; color: var(--theme-text-primary); background: var(--theme-bg-input); font: 14px/1.6 inherit; }.asset-detail-fields textarea { resize: vertical; scrollbar-width: thin; scrollbar-color: var(--theme-scrollbar-thumb) transparent; }.asset-detail-fields input:focus,.asset-detail-fields textarea:focus { border-color: var(--theme-border-strong); box-shadow: 0 0 0 3px var(--theme-shadow); }.asset-detail-fields details { overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 10px; background: var(--theme-bg-elevated); }.asset-detail-fields summary { padding: 10px 12px; color: var(--theme-text-secondary); cursor: pointer; font-size: 14px; }.asset-detail-fields pre { max-height: 210px; margin: 0; padding: 12px; overflow: auto; border-top: 1px solid var(--theme-border-subtle); color: var(--theme-text-secondary); font: 12px/1.6 Consolas,monospace; white-space: pre-wrap; word-break: break-word; }.asset-detail-error { margin: 0; color: var(--theme-danger-text); font-size: 13px; }
.asset-detail-fields textarea[readonly] { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-input); cursor: default; }
.asset-detail-default-prompt { display: grid; gap: 7px; }.asset-detail-default-prompt-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.asset-detail-default-prompt-head > span { color: var(--theme-text-secondary); font-size: 14px; }.asset-detail-default-prompt-head button { position: relative; width: 38px; height: 22px; flex: 0 0 38px; padding: 0; border: 1px solid var(--theme-border-subtle); border-radius: 999px; outline: 0; background: var(--theme-bg-surface); cursor: pointer; transition: border-color .18s ease,background .18s ease; }.asset-detail-default-prompt-head button i { position: absolute; top: 3px; left: 3px; width: 14px; height: 14px; border-radius: 50%; background: var(--theme-bg-elevated); transition: left .18s ease,background .18s ease; }.asset-detail-default-prompt-head button[aria-checked="true"] { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); }.asset-detail-default-prompt-head button[aria-checked="true"] i { left: 19px; background: var(--theme-bg-card-hover); }.asset-detail-default-prompt-head button:focus-visible { box-shadow: 0 0 0 3px var(--theme-shadow); }.asset-detail-default-prompt textarea { transition: opacity .18s ease,border-color .18s ease; }.asset-detail-default-prompt small { color: var(--theme-text-secondary); font-size: 12px; line-height: 1.5; }.asset-detail-default-prompt.disabled textarea { opacity: .42; }.asset-detail-default-prompt.disabled small { color: var(--theme-text-secondary); }
.asset-detail-dialog > footer { display: flex; justify-content: flex-end; gap: 9px; padding: 16px 25px 22px; border-top: 1px solid var(--theme-border-subtle); }.asset-detail-dialog > footer button { min-height: 40px; padding: 0 17px; border-radius: 9px; cursor: pointer; font-size: 14px; }.asset-detail-secondary { border: 1px solid var(--theme-border-subtle); color: var(--theme-text-secondary); background: var(--theme-bg-surface); }.asset-detail-secondary:hover:not(:disabled) { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }.asset-detail-secondary:disabled { cursor: not-allowed; opacity: .35; }.asset-detail-save { border: 1px solid var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-weight: 700; }.asset-detail-save:hover { background: var(--theme-bg-card-hover); }

/* Readability scale for the desktop workbench. */
.video-workbench-head > div > span,.asset-rail-head span,.storyboard-column-head span { font-size: 12px; }
.video-workbench-head p { font-size: 14px; }.video-workbench-head > button { height: 42px; font-size: 13px; }
.asset-rail-head h2,.storyboard-column-head h2 { font-size: 19px; }.asset-rail-head b,.storyboard-column-head b { font-size: 13px; }
.asset-category-tabs button { height: 56px; font-size: 14px; }.asset-category-tabs svg { width: 18px; height: 18px; }
.asset-json-import strong { font-size: 14px; }.asset-json-import small { font-size: 12px; }
.asset-generator-error,.asset-card-error { font-size: 12px; }.asset-rail-state { font-size: 14px; line-height: 1.7; }
.asset-missing-preview span { font-size: 13px; }.asset-pick-copy strong { font-size: 13px; }.asset-pick-copy small { font-size: 12px; }.asset-card-generate { height: 34px; font-size: 13px; }
.shot-number { font-size: 13px; }.storyboard-card-head input { font-size: 14px; }.shot-content-head span,.shot-result > header span { font-size: 12px; }.shot-content-head strong,.shot-result > header strong { font-size: 13px; }
.reference-add small,.reference-card > small { font-size: 12px; }.storyboard-compose textarea { font-size: 14px; line-height: 1.7; }
.storyboard-toolbar { position: relative; z-index: 8; gap: 12px; overflow: visible; font-size: 14px; }.storyboard-toolbar button { font-size: 14px; }.storyboard-toolbar .shot-submit { flex: 0 0 34px; }
.shot-result > header small { font-size: 12px; }.shot-result-empty strong,.shot-result-progress strong,.shot-result-error strong,.shot-result-complete strong { font-size: 13px; }.shot-result-empty small,.shot-result-progress small,.shot-result-error span,.shot-result-complete span { font-size: 13px; line-height: 1.5; }.shot-result-error button,.shot-result-player a { font-size: 13px; }
@keyframes result-spin { to { transform: rotate(360deg); } }
@media (max-width: 1450px) { .shot-body-grid { grid-template-columns: 1fr; }.shot-content { border-right: 0; border-bottom: 1px solid var(--theme-border-subtle); border-bottom-left-radius: 0; }.shot-content:not(.expanded) .storyboard-toolbar { border-bottom-left-radius: 0; }.shot-result { min-height: 250px; } }
@media (max-width: 1100px) { .video-workbench-layout { grid-template-columns: 220px minmax(0,1fr); }.storyboard-toolbar { gap: 6px; }.storyboard-toolbar span:nth-of-type(2) { display: none; } }
@media (max-width: 720px) { .json-import-backdrop { padding: 12px; }.json-import-dialog { width: calc(100vw - 24px); max-height: calc(100vh - 24px); }.json-import-dialog > header,.json-import-editor { padding-right: 18px; padding-left: 18px; }.json-import-dialog > footer { grid-template-columns: 1fr 1fr; padding-right: 18px; padding-left: 18px; }.json-file-button { grid-column: 1 / -1; }.json-import-textarea { min-height: 230px; } }
@media (max-width: 820px) { .asset-detail-backdrop { padding: 12px; }.asset-detail-dialog { width: calc(100vw - 24px); max-height: calc(100vh - 24px); }.asset-detail-body { grid-template-columns: 1fr; }.asset-detail-image-preview,.asset-detail-image-preview > img,.asset-detail-empty { min-height: 240px; max-height: 360px; } }

/* Cinematic production workspace redesign. */
.video-project-hub,.video-workbench {
  --studio-accent: var(--theme-accent);
  --studio-accent-rgb: 79,112,168;
  --studio-pink: var(--theme-accent);
  --studio-bg: var(--theme-bg-page);
  --studio-surface: var(--theme-bg-surface);
  --studio-surface-raised: var(--theme-bg-card);
  --studio-border: var(--theme-border-subtle);
  --studio-border-strong: var(--theme-border-strong);
  --studio-text: var(--theme-text-primary);
  --studio-muted: var(--theme-text-secondary);
  --studio-dim: var(--theme-text-secondary);
}
.video-project-hub { padding-top: 28px; }
.video-project-workspace-head { position: relative; display: flex; min-height: 176px; box-sizing: border-box; align-items: center; justify-content: space-between; gap: 38px; padding: 30px clamp(26px,4vw,50px); border: 1px solid var(--theme-border-subtle); border-radius: 22px; background: var(--theme-bg-elevated); box-shadow: 0 22px 60px var(--theme-shadow); }
.video-project-workspace-head::before { position: absolute; inset: 0; overflow: hidden; border-radius: inherit; opacity: .32; background-image: radial-gradient(circle,var(--theme-bg-surface) 1px,transparent 1px); background-size: 18px 18px; content: ''; mask-image: linear-gradient(90deg,transparent 22%,#000 54%,transparent 92%); }
.video-project-head-copy,.video-project-head-actions { position: relative; z-index: 3; }
.video-project-head-copy { min-width: 300px; }
.video-project-head-copy > span { color: var(--theme-accent-text); font: 800 12px/1 monospace; letter-spacing: .18em; }
.video-project-head-copy > div { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.video-project-head-copy h1 { margin: 0; color: var(--theme-text-primary); font-size: 30px; letter-spacing: -.04em; }
.video-project-head-copy b { padding: 3px 8px; border: 1px solid var(--theme-border-subtle); border-radius: 99px; color: var(--theme-text-secondary); font-size: 12px; }
.video-project-head-copy p { margin: 13px 0 0; color: var(--theme-text-secondary); font-size: 13px; line-height: 1.55; }
.video-project-head-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 10px; padding: 7px; border: 1px solid var(--theme-border-subtle); border-radius: 14px; background: var(--theme-bg-surface); box-shadow: 0 12px 30px var(--theme-shadow); backdrop-filter: blur(12px); }
.video-project-search { display: flex; width: clamp(130px,14vw,210px); min-width: 0; flex: 0 1 auto; height: 40px; align-items: center; gap: 10px; padding: 0 14px; border: 1px solid var(--theme-border-subtle); border-radius: 22px; background: var(--theme-bg-input); }
.video-project-filter { width: clamp(120px,13vw,180px); flex: 0 1 auto; }
.video-project-filter :deep(.ui-select-trigger) { min-height: 40px; border-radius: 22px; background: var(--theme-bg-input); }
.video-project-search:focus-within { border-color: var(--theme-border-strong); }
.video-project-search svg { width: 17px; flex: 0 0 auto; fill: none; stroke: var(--theme-text-secondary); stroke-width: 1.7; }
.video-project-search input { min-width: 0; flex: 1; border: 0; outline: 0; color: var(--theme-text-primary); background: transparent; font-size: 14px; }
.video-project-search input::placeholder { color: var(--theme-text-secondary); opacity: 1; }
.video-project-new-button { display: inline-flex; height: 40px; align-items: center; gap: 7px; padding: 0 14px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; color: var(--theme-text-primary); background: var(--theme-bg-surface); cursor: pointer; font-size: 13px; font-weight: 700; }
.video-project-new-button:hover,.video-project-new-button:focus-visible { border-color: var(--theme-accent-border); outline: 0; background: var(--theme-bg-card-hover); }
.video-project-new-button svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.video-project-head-art { position: absolute; z-index: 1; top: 24px; left: 40%; width: 250px; height: 130px; opacity: .46; transform: translateX(-50%); pointer-events: none; }
.video-project-head-art > svg { position: absolute; inset: 0; width: 100%; height: 100%; fill: none; stroke: var(--theme-accent-text); stroke-width: 1.4; }
.video-project-hero-script,.video-project-hero-shot { position: absolute; z-index: 2; display: block; border: 1px solid var(--theme-border-subtle); background: var(--theme-bg-surface); box-shadow: 0 7px 18px var(--theme-shadow); }
.video-project-hero-script { top: 27px; left: 18px; width: 72px; height: 78px; padding: 21px 11px 8px; border-radius: 8px; transform: rotate(-3deg); }
.video-project-hero-script::before { position: absolute; top: 10px; left: 11px; width: 26px; height: 4px; border-radius: 4px; background: var(--theme-accent-text); content: ''; }
.video-project-hero-script i { display: block; height: 3px; margin-top: 8px; border-radius: 3px; background: var(--theme-bg-surface); }.video-project-hero-script i:nth-child(2) { width: 78%; }.video-project-hero-script i:nth-child(3) { width: 57%; }
.video-project-hero-shot { right: 20px; width: 67px; height: 43px; }.video-project-hero-shot::before { position: absolute; inset: 6px; border-radius: 4px; background: var(--theme-accent); content: ''; color: var(--theme-text-on-accent); }.video-project-hero-shot-top { top: 10px; }.video-project-hero-shot-bottom { bottom: 9px; border-color: var(--theme-accent-border); }
.video-project-create-card { min-width: 0; overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 18px; background: var(--theme-bg-elevated); box-shadow: 0 8px 30px var(--theme-shadow); transition: border-color .2s ease,transform .2s ease; }
.video-project-create-card:hover { border-color: var(--theme-border-subtle); transform: translateY(-2px); }
.video-project-create-card > button { display: flex; width: 100%; aspect-ratio: 16/9; align-items: center; justify-content: center; flex-direction: column; gap: 12px; border: 0; border-bottom: 1px solid var(--theme-border-subtle); color: var(--theme-text-primary); background: radial-gradient(circle at 50% 45%,var(--theme-bg-surface),var(--theme-bg-elevated) 70%); cursor: pointer; }
.video-project-create-card > button > strong { font-size: 15px; }
.video-project-new-visual { position: relative; display: block; width: 132px; height: 65px; }
.video-project-new-script,.video-project-new-frame { position: absolute; display: block; border: 1px solid var(--theme-border-subtle); background: var(--theme-bg-surface); box-shadow: 0 7px 15px var(--theme-shadow); transition: .18s ease; }
.video-project-new-script { top: 10px; left: 2px; width: 50px; height: 54px; box-sizing: border-box; padding: 16px 9px 7px; border-radius: 7px; transform: rotate(-4deg); }.video-project-new-script::before { position: absolute; top: 8px; left: 9px; width: 14px; height: 3px; border-radius: 3px; background: var(--theme-accent); content: ''; color: var(--theme-text-on-accent); }.video-project-new-script i { display: block; width: 100%; height: 3px; margin-top: 5px; border-radius: 3px; background: var(--theme-bg-surface); }.video-project-new-script i:nth-child(2) { width: 80%; }.video-project-new-script i:nth-child(3) { width: 58%; }
.video-project-new-frame { top: 12px; right: 0; width: 66px; height: 45px; box-sizing: border-box; padding: 5px; border-radius: 7px; transform: rotate(3deg); }.video-project-new-frame i { display: block; width: 100%; height: 100%; border-radius: 4px; background: linear-gradient(145deg,var(--theme-bg-surface) 55%,var(--theme-accent-soft) 56%); }.video-project-new-frame b { position: absolute; top: 8px; right: 8px; width: 5px; height: 5px; border-radius: 50%; background: var(--theme-accent-soft); }
.video-project-new-plus { position: absolute; z-index: 3; top: 18px; left: 49px; display: grid; width: 39px; height: 39px; place-items: center; border: 3px solid var(--theme-border-subtle); border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 6px 16px var(--theme-shadow); transition: .18s ease; }.video-project-new-plus svg { width: 21px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }.video-project-create-card > button:hover .video-project-new-plus { transform: rotate(90deg) scale(1.05); }
.video-project-create-card > div { display: flex; height: 88px; align-items: center; justify-content: center; gap: 5px; color: var(--theme-text-primary); font-size: 14px; font-weight: 650; }.video-project-create-card > div svg { width: 14px; fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linecap: round; }
.video-project-create-backdrop { position: fixed; z-index: 220; top: 48px; right: 0; bottom: 0; left: var(--sidebar-width, 240px); display: grid; place-items: center; padding: 24px; background: var(--theme-overlay); backdrop-filter: blur(10px); }
.video-project-create-backdrop .video-project-create { width: min(520px,92vw); box-sizing: border-box; padding: 24px; border-color: var(--theme-accent-border); border-radius: 20px; background: var(--theme-overlay); box-shadow: 0 30px 90px var(--theme-shadow); }
.video-project-create-head > button { display: grid; width: 34px; height: 34px; margin-left: auto; place-items: center; border: 0; color: var(--theme-accent-text); background: transparent; cursor: pointer; font-size: 24px; }
.video-project-create-backdrop .video-project-create input,.video-project-create-backdrop .video-project-create textarea { border-color: var(--theme-accent-border); background: var(--theme-overlay); }
.video-project-create-backdrop .video-project-create footer { display: flex; justify-content: flex-end; gap: 8px; padding-top: 3px; }
.video-project-create-backdrop .video-project-create footer button { min-height: 38px; padding: 0 14px; border: 1px solid var(--theme-accent-border); border-radius: 9px; color: var(--theme-text-secondary); background: var(--theme-overlay); cursor: pointer; font-size: 12px; }
.video-project-create-backdrop .video-project-create footer button[type=submit] { border: 0; color: var(--theme-text-primary); background: linear-gradient(100deg,var(--theme-accent-soft),var(--theme-accent-soft) 48%,var(--theme-accent-soft) 120%); font-weight: 800; }
.video-project-hero { position: relative; isolation: isolate; border-color: var(--studio-border); background: radial-gradient(circle at 8% 0%,rgba(var(--studio-accent-rgb),.13),transparent 32%),radial-gradient(circle at 90% 100%,var(--theme-accent-soft),transparent 35%),linear-gradient(145deg,var(--theme-bg-elevated),var(--theme-bg-elevated) 72%); box-shadow: 0 30px 80px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.video-project-hero::before { position: absolute; z-index: -1; inset: 0; opacity: .25; background-image: linear-gradient(var(--theme-accent-soft) 1px,transparent 1px),linear-gradient(90deg,var(--theme-accent-soft) 1px,transparent 1px); background-size: 36px 36px; mask-image: linear-gradient(100deg,#000,transparent 68%); content: ''; }
.video-project-hub-head > span,.video-project-library > header span { color: var(--theme-accent-text); }
.video-project-hub-head h1 em { color: transparent; background: linear-gradient(92deg,var(--theme-accent-text),var(--theme-accent-text) 52%,var(--theme-accent-text)); background-clip: text; }
.video-project-highlights span { border-color: var(--studio-border); color: var(--theme-text-secondary); background: var(--theme-accent-soft); }
.video-project-highlights i { background: var(--studio-accent); box-shadow: 0 0 12px rgba(var(--studio-accent-rgb),.65); }
.video-project-create { border-color: var(--studio-border-strong); background: var(--theme-bg-elevated); box-shadow: 0 24px 64px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.video-project-create-head > span,.video-project-create > button { border-color: transparent; color: var(--theme-text-primary); background: linear-gradient(105deg,var(--studio-accent),var(--theme-accent-soft) 52%,var(--studio-pink)); box-shadow: 0 12px 30px rgba(var(--studio-accent-rgb),.16); }
.video-project-create input,.video-project-create textarea { border-color: var(--studio-border); background: var(--theme-bg-input); }
.video-project-create input:focus,.video-project-create textarea:focus { border-color: rgba(var(--studio-accent-rgb),.65); box-shadow: 0 0 0 3px rgba(var(--studio-accent-rgb),.1); }
.video-project-library > header { align-items: center; padding-bottom: 16px; border-color: var(--theme-border-subtle); }
.video-project-grid { grid-template-columns: repeat(4,minmax(0,1fr)); gap: 18px; margin-top: 24px; }
.video-project-card { min-width: 0; overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 18px; outline: 0; background: var(--theme-bg-elevated); box-shadow: 0 8px 30px var(--theme-shadow); transition: border-color .2s ease,transform .2s ease; }
.video-project-card:hover { border-color: var(--theme-border-subtle); box-shadow: 0 8px 30px var(--theme-shadow); transform: translateY(-2px); }
.video-project-card:focus-visible { border-color: var(--theme-accent-border); box-shadow: 0 0 0 3px var(--theme-shadow); }
.video-project-card-body { min-height: 106px; box-sizing: border-box; padding: 13px 14px 11px; background: var(--theme-bg-elevated); }
.video-project-card-body h2 { min-width: 0; margin: 0; overflow: hidden; color: var(--theme-text-primary); font-size: 15px; line-height: 22px; text-overflow: ellipsis; white-space: nowrap; }
.video-project-card-body > p { margin: 2px 0 0; overflow: hidden; color: var(--theme-text-secondary); font-size: 14px; line-height: 19px; text-overflow: ellipsis; white-space: nowrap; }
.video-project-card-body footer { display: flex; min-width: 0; min-height: 0; align-items: center; justify-content: space-between; gap: 8px; margin-top: 7px; padding-top: 7px; border-top: 1px solid var(--theme-border-subtle); }
.video-project-card-body time { flex: 0 0 auto; color: var(--theme-text-secondary); font-size: 13px; }
.video-project-card-body footer span { min-width: 0; height: 20px; padding: 0 7px; overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 5px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }

.video-workbench { padding: 18px 0 32px; color: var(--studio-text); }
.video-workbench-head { position: relative; align-items: center; margin-bottom: 16px; padding: 20px 22px; overflow: hidden; border: 1px solid var(--studio-border); border-radius: 22px; background: radial-gradient(circle at 8% 0%,rgba(var(--studio-accent-rgb),.1),transparent 34%),linear-gradient(110deg,var(--theme-bg-elevated),var(--theme-bg-elevated) 72%); box-shadow: 0 18px 48px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.video-workbench-head::after { position: absolute; top: 0; right: 12%; left: 12%; height: 1px; background: linear-gradient(90deg,transparent,var(--studio-accent),var(--studio-pink),transparent); content: ''; opacity: .65; }
.video-workbench-title { min-width: 0; gap: 0; }
.workbench-breadcrumb { display: flex; align-items: center; gap: 9px; color: var(--studio-dim); font: 700 12px/1 monospace; letter-spacing: .15em; }
.workbench-breadcrumb button { display: inline-flex; min-height: 30px; align-items: center; gap: 4px; margin: 0; padding: 0 7px; border: 0; border-radius: 7px; color: var(--theme-text-secondary); background: transparent; cursor: pointer; font: inherit; letter-spacing: 0; }
.workbench-breadcrumb button:hover,.workbench-breadcrumb button:focus-visible { color: var(--theme-text-primary); background: var(--theme-accent-soft); outline: 0; }
.workbench-breadcrumb svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.workbench-breadcrumb > i { width: 3px; height: 3px; border-radius: 50%; background: var(--theme-accent-soft); }
.workbench-breadcrumb > span { color: var(--theme-accent-text); }
.workbench-project-row { display: flex; min-width: 0; align-items: center; gap: 13px; margin-top: 9px; }
.workbench-project-mark { display: grid; width: 42px; height: 42px; flex: 0 0 auto; place-items: center; border: 1px solid rgba(var(--studio-accent-rgb),.22); border-radius: 13px; color: var(--theme-accent-text); background: rgba(var(--studio-accent-rgb),.08); box-shadow: inset 0 1px var(--theme-shadow); }
.workbench-project-mark svg { width: 22px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.workbench-project-row > div { display: grid; min-width: 0; gap: 2px; }
.video-workbench-title .workbench-project-row input { width: min(660px,62vw); margin: 0; padding: 0; border: 0; outline: 0; color: var(--studio-text); background: transparent; font: 750 26px/1.2 inherit; letter-spacing: -.035em; }
.video-workbench-title .workbench-project-row .video-project-description { color: var(--studio-muted); font-size: 14px; font-weight: 450; letter-spacing: 0; }
.workbench-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 11px; }
.workbench-meta > span { display: inline-flex; min-height: 24px; box-sizing: border-box; align-items: center; gap: 6px; padding: 0 8px; border: 1px solid var(--studio-border); border-radius: 999px; color: var(--theme-accent-text); background: var(--theme-accent-soft); font-size: 12px; }
.workbench-meta .save-state { color: var(--theme-success-text); }
.workbench-meta .save-state i { width: 6px; height: 6px; border-radius: 50%; background: var(--theme-success-soft); box-shadow: 0 0 9px var(--theme-shadow); }
.video-workbench-head .workbench-sync-voices { display: inline-flex; height: 32px; align-items: center; justify-content: center; gap: 6px; padding: 0 12px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; color: var(--theme-text-primary); font-size: 12.5px; font-weight: 600; background: var(--theme-bg-surface); cursor: pointer; white-space: nowrap; transition: all .15s ease; }
.video-workbench-head .workbench-sync-voices:hover { background: var(--theme-accent-soft); border-color: var(--theme-accent-border); transform: translateY(-1px); }
.video-workbench-head .workbench-sync-voices svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.video-workbench-head .workbench-add-shot { display: inline-flex; min-width: 128px; height: 44px; align-items: center; justify-content: center; gap: 8px; padding: 0 16px; border: 0; border-radius: 12px; color: var(--theme-text-primary); background: linear-gradient(105deg,var(--studio-accent),var(--theme-accent-soft) 55%,var(--studio-pink)); box-shadow: 0 13px 30px rgba(var(--studio-accent-rgb),.16); font-size: 14px; font-weight: 800; transition: filter .18s ease,transform .18s ease; }
.video-workbench-head .workbench-add-shot:hover { border-color: transparent; background: linear-gradient(105deg,var(--studio-accent),var(--theme-accent-soft) 55%,var(--studio-pink)); filter: brightness(1.08); transform: translateY(-1px); }
.workbench-add-shot svg { width: 17px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; }

.video-workbench-layout { min-height: calc(100vh - 176px); grid-template-columns: clamp(280px,20vw,330px) minmax(0,1fr); gap: 16px; }
.asset-rail,.storyboard-column { border-color: var(--studio-border); background: var(--studio-surface); box-shadow: 0 18px 48px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.asset-rail { top: 62px; max-height: calc(100vh - 82px); border-radius: 17px; }
.asset-rail-head,.storyboard-column-head { min-height: 62px; box-sizing: border-box; padding: 14px 16px; }
.asset-rail-head h2,.storyboard-column-head h2 { color: var(--studio-text); }
.asset-rail-head b,.storyboard-column-head b { color: var(--theme-text-secondary); background: var(--theme-accent-soft); }
.asset-rail-head span,.storyboard-column-head span { color: var(--theme-accent-text); }
.asset-category-tabs { gap: 4px; margin: 0 10px 10px; border: 1px solid var(--theme-border-subtle); background: var(--theme-bg-elevated); }
.asset-category-tabs button { position: relative; height: 52px; color: var(--theme-accent-text); transition: color .16s ease,background .16s ease; }
.asset-category-tabs button:hover { color: var(--theme-text-primary); background: var(--theme-accent-soft); }
.asset-category-tabs button.active { color: var(--theme-accent-text); background: rgba(var(--studio-accent-rgb),.1); box-shadow: inset 0 0 0 1px rgba(var(--studio-accent-rgb),.08); }
.asset-category-tabs button.active::after { position: absolute; right: 13px; bottom: 2px; left: 13px; height: 2px; border-radius: 2px; background: var(--studio-accent); content: ''; box-shadow: 0 0 8px rgba(var(--studio-accent-rgb),.55); }
.asset-generator { border-color: var(--studio-border); background: var(--theme-bg-elevated); }
.asset-json-import { min-height: 54px; border-color: rgba(var(--studio-accent-rgb),.24); color: var(--theme-text-primary); background: rgba(var(--studio-accent-rgb),.045); }
.asset-json-import:hover { border-color: rgba(var(--studio-accent-rgb),.55); background: rgba(var(--studio-accent-rgb),.08); }
.asset-json-import > span { color: var(--theme-accent-text); background: rgba(var(--studio-accent-rgb),.12); }
.asset-json-import > span svg { width: 16px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.asset-json-import small { color: var(--theme-accent-text); }
.asset-generator { --select-accent: var(--theme-accent-border); --select-border: var(--theme-border-subtle); --select-border-hover: var(--theme-border-subtle); --select-border-focus: var(--theme-accent-border); --select-bg: var(--theme-bg-input); --select-bg-hover: var(--theme-bg-card-hover); --select-bg-focus: var(--theme-bg-input); --select-menu-border: var(--theme-border-subtle); --select-menu-bg: var(--theme-bg-input); --select-focus-ring: var(--theme-accent-soft); }
.asset-rail-scroll { max-height: calc(100vh - 376px); }
.asset-pick-card { border-color: var(--studio-border); border-radius: 11px; background: var(--theme-bg-elevated); transition: border-color .18s ease,transform .18s ease,box-shadow .18s ease; }
.asset-pick-card:hover { border-color: rgba(var(--studio-accent-rgb),.38); box-shadow: 0 10px 24px var(--theme-shadow); }
.asset-preview-button,.asset-preview-button > img,.asset-audio-placeholder { background: var(--theme-bg-elevated); }
.asset-missing-preview { color: var(--theme-accent-text); background: repeating-linear-gradient(135deg,var(--theme-bg-elevated),var(--theme-bg-elevated) 8px,var(--theme-bg-elevated) 8px,var(--theme-bg-elevated) 16px); }
.asset-pick-copy strong { color: var(--theme-text-primary); }
.asset-card-add { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--studio-accent); }
.asset-card-generate { min-height: 34px; border-color: rgba(var(--studio-accent-rgb),.18); color: var(--theme-accent-text); background: rgba(var(--studio-accent-rgb),.08); }
.asset-card-generate:hover:not(:disabled) { border-color: rgba(var(--studio-accent-rgb),.42); background: rgba(var(--studio-accent-rgb),.14); }
.asset-card-generate > svg { width: 13px; fill: none; stroke: currentColor; stroke-width: 1.7; }

.storyboard-column { border: 0; background: transparent; box-shadow: none; }
.storyboard-column-head { margin-bottom: 10px; border: 1px solid var(--studio-border); border-radius: 15px; background: var(--studio-surface); box-shadow: inset 0 1px var(--theme-shadow); }
.storyboard-card { --shot-card-radius: var(--theme-accent); margin: 0 0 14px; overflow: visible; border-color: var(--studio-border); border-radius: 18px; background: linear-gradient(145deg,var(--theme-bg-elevated),var(--theme-bg-elevated)); box-shadow: 0 16px 42px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.storyboard-card.active,.storyboard-card:focus-visible { border-color: rgba(var(--studio-accent-rgb),.38); box-shadow: 0 18px 48px var(--theme-shadow),0 0 0 3px rgba(var(--studio-accent-rgb),.07); }
.storyboard-card-head { height: 48px; padding: 0 15px; border-color: var(--studio-border); background: linear-gradient(90deg,rgba(var(--studio-accent-rgb),.045),transparent 36%); border-radius: 18px 18px 0 0; }
.shot-number { display: grid; min-width: 28px; height: 24px; place-items: center; border: 1px solid rgba(var(--studio-accent-rgb),.18); border-radius: 7px; color: var(--theme-accent-text); background: rgba(var(--studio-accent-rgb),.07); }
.storyboard-card-head input { color: var(--theme-text-primary); }
.shot-content { border-color: var(--studio-border); }
.shot-content-head,.shot-result > header { border-color: var(--studio-border); background: var(--theme-bg-elevated); }
.shot-content-head span,.shot-result > header span { color: var(--theme-accent-text); }
.shot-content-head strong,.shot-result > header strong { color: var(--theme-text-primary); }
.storyboard-compose { min-height: 138px; padding: 16px; }
.reference-add { border-color: rgba(var(--studio-accent-rgb),.22); color: var(--theme-accent-text); background: rgba(var(--studio-accent-rgb),.035); }
.reference-add:hover { border-color: rgba(var(--studio-accent-rgb),.5); color: var(--theme-accent-text); background: rgba(var(--studio-accent-rgb),.08); }
.reference-card { border-color: var(--studio-border-strong); background: var(--theme-bg-elevated); }
.reference-stack-add { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--studio-accent); }
.storyboard-compose textarea { padding: 8px 10px; border: 1px solid transparent; border-radius: 10px; color: var(--theme-text-primary); background: var(--theme-bg-input); transition: border-color .18s ease,box-shadow .18s ease; }
.storyboard-compose textarea:focus { border-color: rgba(var(--studio-accent-rgb),.36); box-shadow: 0 0 0 3px rgba(var(--studio-accent-rgb),.06); }
.storyboard-toolbar { min-height: 52px; gap: 5px; padding: 8px 10px; border-color: var(--studio-border); background: var(--theme-bg-elevated); border-radius: 0 0 0 18px; }
.storyboard-toolbar > button,.storyboard-toolbar .toolbar-popover-wrap > button { min-height: 30px; padding: 0 8px; border: 1px solid transparent; border-radius: 8px; color: var(--theme-accent-text); }
.storyboard-toolbar > button:hover,.storyboard-toolbar .toolbar-popover-wrap > button:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-accent-soft); }
.storyboard-toolbar .shot-clear { margin-left: auto; color: var(--theme-accent-text); }
.storyboard-toolbar .shot-submit { display: inline-flex; width: auto; min-width: 108px; height: 36px; flex: 0 0 auto; align-items: center; justify-content: center; gap: 7px; padding: 0 13px; border: 0; border-radius: 10px; color: var(--theme-text-primary); background: linear-gradient(105deg,var(--studio-accent),var(--theme-accent-soft) 58%,var(--studio-pink)); box-shadow: 0 9px 24px rgba(var(--studio-accent-rgb),.14); }
.storyboard-toolbar .shot-submit:hover { color: var(--theme-text-primary); background: linear-gradient(105deg,var(--studio-accent),var(--theme-accent-soft) 58%,var(--studio-pink)); filter: brightness(1.05); }
.storyboard-toolbar .shot-submit strong { font-size: 13px; }
.storyboard-toolbar .shot-submit .asset-generate-spinner { border-color: var(--theme-border-subtle); border-top-color: var(--theme-border-subtle); }
.mode-popover,.settings-popover { border-color: var(--studio-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 22px 58px var(--theme-shadow),inset 0 1px var(--theme-shadow); backdrop-filter: blur(18px); }
.ratio-options,.segmented-options,.duration-options,.count-options { border-color: var(--studio-border); background: var(--theme-bg-elevated); }
.storyboard-toolbar .ratio-options button:hover,.storyboard-toolbar .ratio-options button.active,.storyboard-toolbar .segmented-options button:hover,.storyboard-toolbar .segmented-options button.active,.storyboard-toolbar .duration-options button:hover,.storyboard-toolbar .duration-options button.active,.storyboard-toolbar .count-options button:hover,.storyboard-toolbar .count-options button.active { color: var(--theme-text-primary); background: var(--studio-accent); }
.shot-result { margin: 14px; border-color: var(--studio-border); background: var(--theme-bg-elevated); }
.shot-result-player { background: radial-gradient(circle at 50% 32%,var(--theme-bg-surface),var(--theme-bg-elevated) 58%,var(--theme-bg-elevated) 100%); }
.shot-result-empty { color: var(--theme-accent-text); background: radial-gradient(circle at 50% 45%,var(--theme-bg-surface),var(--theme-bg-elevated) 68%); }
.shot-result-empty > span { border-color: rgba(var(--studio-accent-rgb),.16); color: var(--theme-accent-text); background: rgba(var(--studio-accent-rgb),.06); }
.shot-result-empty svg { stroke: currentColor; }
.shot-result-progress > i em { background: var(--studio-accent); box-shadow: 0 0 12px rgba(var(--studio-accent-rgb),.45); }
.result-spinner { border-color: var(--theme-accent-border); border-top-color: var(--studio-accent); }

@media (max-width: 1450px) { .video-project-grid { grid-template-columns: repeat(3,minmax(0,1fr)); } }
@media (max-width: 1180px) { .video-project-head-art { display: none; }.video-project-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 900px) { .video-project-workspace-head { align-items: flex-start; flex-direction: column; gap: 22px; }.video-project-head-actions { width: 100%; }.video-project-search { width: auto; flex: 1; }.video-project-new-button { justify-content: center; }.video-project-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } }
@media (max-width: 1280px) {
  .video-workbench-layout { grid-template-columns: 260px minmax(0,1fr); }
  .asset-rail-grid { grid-template-columns: 1fr; }
  .asset-preview-button > img,.asset-audio-placeholder,.asset-missing-preview { aspect-ratio: 16/10; }
  .storyboard-toolbar { flex-wrap: wrap; }
  .storyboard-toolbar .shot-clear { margin-left: 0; }
  .storyboard-toolbar .shot-submit { margin-left: auto; }
}
@media (max-width: 940px) {
  .video-workbench-head { align-items: stretch; flex-direction: column; }
  .video-workbench-head .workbench-add-shot { width: 100%; }
  .video-workbench-layout { grid-template-columns: 1fr; }
  .asset-rail { position: relative; top: auto; max-height: none; }
  .asset-rail-scroll { max-height: 360px; }
  .asset-rail-grid { grid-template-columns: 1fr; }
  .video-workbench-title .workbench-project-row input { width: min(100%,70vw); }
}
@media (max-width: 680px) {
  .video-project-grid { grid-template-columns: 1fr; }
  .video-workbench-head { padding: 16px; border-radius: 16px; }
  .workbench-project-mark { display: none; }
  .video-workbench-title .workbench-project-row input { width: 100%; font-size: 22px; }
  .asset-rail-grid { grid-template-columns: 1fr; }
  .shot-body-grid { grid-template-columns: 1fr; }
  .storyboard-toolbar .shot-submit { width: 100%; margin-left: 0; }
}

/* Match the established project list and project detail layouts. */
.video-project-grid { align-items: start; }
.video-project-create-card > button { height: 172px; aspect-ratio: auto; }
.video-project-create-card > div { height: 60px; }
.video-project-card { border-radius: 12px; background: var(--theme-bg-elevated); }
.video-project-card:hover { border-color: var(--theme-border-subtle); transform: translateY(-2px); }
.video-project-card-body { display: flex; min-height: 232px; padding: 20px 20px 16px; flex-direction: column; background: var(--theme-bg-elevated); }
.video-project-card-body > header { display: flex; align-items: center; justify-content: space-between; color: var(--theme-text-secondary); }
.video-project-card-body > header span { color: var(--theme-accent-text); font: 800 12px/1 monospace; letter-spacing: .14em; }
.video-project-card-body > header svg { width: 17px; fill: none; stroke: var(--theme-text-secondary); stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; transition: transform .18s ease,stroke .18s ease; }
.video-project-card:hover .video-project-card-body > header svg { stroke: var(--theme-accent-text); transform: translateX(2px); }
.video-project-card-body h2 { margin-top: 16px; font-size: 18px; line-height: 24px; }
.video-project-card-body > p { min-height: 44px; margin: 4px 0 0; color: var(--theme-text-secondary); line-height: 20px; white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.video-project-card-stats { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-top: 14px; padding: 11px 0; border-top: 1px solid var(--theme-border-subtle); border-bottom: 1px solid var(--theme-border-subtle); }
.stat-pills { display: flex; gap: 5px; min-width: 0; }
.stat-pill { display: inline-flex; align-items: center; gap: 4px; height: 26px; padding: 0 7px; border-radius: 6px; background: var(--theme-bg-surface); transition: background .18s ease; flex: 0 0 auto; }
.stat-pill-asset { --stat-rgb: 69,215,255; }
.stat-pill-shot { --stat-rgb: 184,167,255; }
.stat-pill-running { --stat-rgb: 90,224,138; }
.stat-pill:hover { background: var(--theme-bg-card-hover); }
.stat-dot { width: 5px; height: 5px; border-radius: 50%; background: rgba(var(--stat-rgb),.95); box-shadow: 0 0 5px rgba(var(--stat-rgb),.4); flex: 0 0 auto; }
.stat-pill b { color: var(--theme-text-primary); font-size: 12px; font-weight: 700; line-height: 1; }
.stat-pill small { color: var(--theme-text-secondary); font-size: 10px; line-height: 1; }
.video-project-finished-stat { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; height: 40px; padding: 0 10px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; color: var(--theme-text-primary); background: linear-gradient(135deg,var(--theme-accent-soft),var(--theme-accent-soft)); box-shadow: inset 0 1px 0 var(--theme-shadow); cursor: pointer; text-align: left; transition: border-color .18s ease,background .18s ease,box-shadow .18s ease,transform .18s ease; }
.video-project-finished-copy { white-space: nowrap; }
.video-project-finished-copy b { color: var(--theme-text-primary); font-size: 14px; font-weight: 800; line-height: 1; margin-right: 3px; }
.video-project-finished-copy small { color: var(--theme-text-secondary); font-size: 11px; line-height: 1; }
.video-project-finished-arrow { width: 13px; flex: 0 0 auto; fill: none; stroke: var(--theme-text-primary); stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; transition: transform .18s ease; }
.video-project-finished-stat:hover .video-project-finished-arrow,.video-project-finished-stat:focus-visible .video-project-finished-arrow { transform: translateX(2px); }
.video-project-finished-stat:hover,.video-project-finished-stat:focus-visible { border-color: var(--theme-border-strong); outline: 0; background: linear-gradient(135deg,var(--theme-accent-soft),var(--theme-accent-soft)); box-shadow: 0 7px 20px var(--theme-shadow),inset 0 1px 0 var(--theme-shadow); transform: translateY(-1px); }
.video-project-finished-stat:active { border-color: var(--theme-border-strong); background: var(--theme-accent-soft); transform: translateY(0); }
.video-project-finished-icon { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 6px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); flex: 0 0 auto; }
.video-project-finished-icon svg { width: 12px; fill: currentColor; stroke: none; }
.video-project-finished-copy { display: grid; min-width: 0; gap: 4px; }
.video-project-finished-copy small { overflow: hidden; color: var(--theme-text-primary); font-size: 12px; font-weight: 650; line-height: 1.05; text-overflow: ellipsis; white-space: nowrap; }
.video-project-finished-copy b { overflow: hidden; margin: 0; color: var(--theme-text-secondary); font: 10px/1.05 Consolas,monospace; text-overflow: ellipsis; white-space: nowrap; }
.video-project-finished-arrow { width: 15px; fill: none; stroke: var(--theme-text-primary); stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; transition: transform .18s ease; }
.video-project-finished-stat:hover .video-project-finished-arrow,.video-project-finished-stat:focus-visible .video-project-finished-arrow { transform: translateX(2px); }
.video-project-card-body footer { margin-top: auto; padding-top: 11px; border: 0; }
.video-project-card-body footer span { height: auto; padding: 0; border: 0; color: var(--theme-text-primary); background: transparent; font-size: 12px; }

.video-workbench {
  display: flex;
  width: 100%;
  height: 100%;
  max-height: 100%;
  min-height: 0;
  box-sizing: border-box;
  flex-direction: column;
  padding: 20px 28px 0;
  overflow: hidden;
  color: var(--theme-text-primary);
  background: transparent;
}
.video-workbench-head {
  position: static;
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  gap: 16px;
  margin: 0 0 18px;
  padding: 0;
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
.video-workbench-head::after { display: none; }
.workbench-back {
  display: inline-flex;
  height: 32px;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
  padding: 0 10px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 7px;
  color: var(--theme-text-secondary);
  background: var(--theme-bg-surface);
  cursor: pointer;
  font-size: 13px;
}
.workbench-back:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.workbench-back svg { width: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.video-workbench-title { display: grid; min-width: 0; flex: 1; gap: 7px; }
.video-workbench-title .workbench-project-name { width: min(680px,70vw); margin: 0; padding: 0; border: 0; outline: 0; color: var(--theme-text-primary); background: transparent; font: 750 25px/32px inherit; letter-spacing: -.035em; }
.workbench-meta { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 7px; margin: 0; }
.workbench-meta > span { min-height: 22px; padding: 0 7px; border-color: var(--theme-border-subtle); color: var(--theme-text-secondary); background: var(--theme-bg-surface); }
.workbench-meta .video-project-description { width: min(340px,30vw); min-width: 150px; height: 22px; padding: 0 7px; border: 1px solid transparent; border-radius: 5px; outline: 0; color: var(--theme-text-secondary); background: transparent; font-size: 12px; }
.workbench-meta .video-project-description:hover,.workbench-meta .video-project-description:focus { border-color: var(--theme-border-strong); background: var(--theme-bg-card-hover); }
.workbench-head-actions { display: flex; width: auto; flex: 0 0 auto; flex-direction: row; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.workbench-save-status { display: inline-flex; height: 30px; align-items: center; justify-content: center; gap: 5px; overflow: hidden; padding: 0 9px; border: 1px solid var(--theme-border-subtle); border-radius: 7px; color: var(--theme-text-secondary); font-size: 12px; line-height: 28px; text-overflow: ellipsis; white-space: nowrap; background: var(--theme-bg-surface); }
.workbench-save-status i { width: 6px; height: 6px; flex: 0 0 auto; border-radius: 50%; background: #10b981; }
.workbench-save-status.saved { color: var(--theme-text-secondary); }.workbench-save-status.saved i { background: #10b981; }
.workbench-save-status.saving { color: var(--theme-text-secondary); }.workbench-save-status.saving i { border: 1px solid var(--theme-border-subtle); border-top-color: transparent; background: transparent; animation: result-spin .8s linear infinite; }
.workbench-save-status.pending { color: var(--theme-text-secondary); }.workbench-save-status.pending i { background: #f59e0b; }
.workbench-save-status.error { color: var(--theme-danger-text); }.workbench-save-status.error i { background: var(--theme-danger-soft); }
.video-workbench-head .workbench-add-shot {
  display: inline-flex;
  min-width: 0;
  height: 32px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 0;
  padding: 0 13px;
  border: 1px solid #ea580c;
  border-radius: 8px;
  color: #ffffff;
  background: #ea580c;
  box-shadow: none;
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 700;
  white-space: nowrap;
}
.video-workbench-head .workbench-add-shot:hover { border-color: #c2410c; background: #c2410c; filter: none; transform: none; }
.video-workbench-layout { display: grid; flex: 1; min-height: 0; grid-template-columns: 280px minmax(0,1fr); grid-template-rows: minmax(0,1fr); align-items: stretch; gap: 18px; overflow: hidden; }
.asset-rail {
  position: relative;
  top: 0;
  z-index: 30;
  display: flex;
  height: 100%;
  min-height: 0;
  max-height: 100%;
  flex-direction: column;
  overflow: visible;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 9px;
  background: var(--theme-bg-elevated);
  box-shadow: none;
}
.asset-rail-head,.storyboard-column-head { height: 52px; min-height: 52px; box-sizing: border-box; flex: 0 0 52px; padding: 0 14px; border-color: var(--theme-border-subtle); }
.asset-rail-head > div:first-child,.storyboard-column-head > div { display: flex; min-width: 0; align-items: center; gap: 9px; }
.asset-rail-head > div:first-child > span,.storyboard-column-head > div > span { padding: 3px 6px; border: 1px solid var(--theme-border-subtle); border-radius: 999px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); font-size: 8px; letter-spacing: .12em; white-space: nowrap; }
.asset-rail-head h2,.storyboard-column-head h2 { margin: 0; color: var(--theme-text-primary); font-size: 17px; line-height: 1; }
.asset-rail-head > .asset-rail-head-actions > b,.storyboard-column-head > b { display: grid; min-width: 26px; height: 26px; box-sizing: border-box; place-items: center; padding: 0 7px; border-radius: 999px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); font-size: 11px; white-space: nowrap; }
.asset-rail-head-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; }
.asset-actions-wrap { position: relative; }
.asset-actions-wrap::after { position: absolute; top: 0; left: 100%; width: 12px; height: 44px; content: ''; }
.asset-actions-trigger { display: grid; width: 30px; height: 30px; place-items: center; padding: 0; border: 1px solid var(--theme-border-subtle); border-radius: 8px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); cursor: pointer; transition: border-color .16s ease,color .16s ease,background .16s ease; }
.asset-actions-trigger:hover,.asset-actions-trigger.active { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-actions-trigger svg { width: 17px; height: 17px; fill: currentColor; }
.asset-actions-popover { position: absolute; z-index: 80; top: -1px; right: auto; left: calc(100% + 12px); display: grid; width: 320px; max-height: calc(100vh - 110px); box-sizing: border-box; gap: 10px; padding: 13px; overflow-y: auto; overscroll-behavior: contain; border: 1px solid var(--theme-border-subtle); border-radius: 14px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 22px 60px var(--theme-shadow),inset 0 1px var(--theme-shadow); backdrop-filter: blur(14px); scrollbar-width: thin; scrollbar-color: var(--theme-scrollbar-thumb) transparent; }
.asset-actions-popover > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 1px 2px 3px; }
.asset-actions-popover > header > div { display: grid; gap: 3px; }
.asset-actions-popover > header strong { color: var(--theme-text-primary); font-size: 13px; }
.asset-actions-popover > header small { color: var(--theme-text-secondary); font-size: 11px; }
.asset-actions-popover > header > span { padding: 4px 7px; border: 1px solid var(--theme-border-subtle); border-radius: 999px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); font: 10px/1 inherit; white-space: nowrap; }
.asset-action-import, .asset-action-sync-chapter { display: grid; min-width: 0; min-height: 58px; grid-template-columns: 34px minmax(0,1fr) 16px; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; color: var(--theme-text-primary); background: var(--theme-bg-surface); cursor: pointer; text-align: left; }
.asset-action-import:hover { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); }
.asset-action-import > span { display: grid; width: 34px; height: 34px; place-items: center; padding: 0; border: 0; border-radius: 9px; color: var(--theme-text-primary); background: var(--theme-bg-surface); }
.asset-action-import > span svg { width: 17px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.asset-action-import > div { display: grid; min-width: 0; gap: 4px; }
.asset-action-import strong { font-size: 12px; }
.asset-action-import small { overflow: hidden; color: var(--theme-text-secondary); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.asset-action-import > svg { width: 15px; fill: none; stroke: var(--theme-text-secondary); stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.asset-action-model { display: grid; gap: 7px; padding: 10px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; background: var(--theme-bg-elevated); }
.asset-action-model > span { padding: 0; border: 0; color: var(--theme-text-secondary); background: transparent; font: 10px/1.2 inherit; letter-spacing: 0; }
.asset-action-model { --select-accent: var(--theme-accent-border); --select-border-hover: var(--theme-border-subtle); --select-border-focus: var(--theme-accent-border); --select-focus-ring: var(--theme-accent-soft); }
.asset-action-video-engine { display: grid; gap: 7px; margin: 0; padding: 10px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; background: var(--theme-bg-elevated); }
.asset-action-video-engine legend { padding: 0 4px; color: var(--theme-text-secondary); font-size: 10px; }
.asset-action-video-engine > small { color: var(--theme-text-secondary); font-size: 9px; }
.asset-action-video-engine > div { display: grid; grid-template-columns: repeat(2,1fr); gap: 5px; padding: 4px; border-radius: 8px; background: var(--theme-bg-elevated); }
.asset-action-video-engine button { height: 31px; padding: 0 8px; border: 1px solid transparent; border-radius: 6px; color: var(--theme-text-secondary); background: transparent; cursor: pointer; font-size: 11px; transition: border-color .16s ease,color .16s ease,background .16s ease; }
.asset-action-video-engine button:hover:not(:disabled) { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-action-video-engine button.active { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-action-video-engine button:disabled { cursor: not-allowed; opacity: .38; }
.asset-action-video-engine > em { color: var(--theme-accent-text); font-size: 9px; font-style: normal; }
.asset-action-generate-all { display: grid; min-height: 58px; grid-template-columns: 34px minmax(0,1fr) 28px; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); cursor: pointer; text-align: left; }
.asset-action-generate-all:hover:not(:disabled) { background: var(--theme-bg-card-hover); }
.asset-action-generate-all:disabled { cursor: wait; opacity: .45; }
.asset-action-generate-all > svg { width: 21px; fill: none; stroke: currentColor; stroke-width: 1.55; }
.asset-action-generate-all > div { display: grid; gap: 3px; }
.asset-action-generate-all strong { font-size: 12px; }
.asset-action-generate-all small { color: var(--theme-text-secondary); font-size: 9px; }
.asset-action-generate-all > b { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-surface); font-size: 11px; }
.asset-action-library-grid { display: grid; grid-template-columns: 1fr; gap: 7px; }
.asset-action-library-grid > button { display: grid; min-height: 50px; grid-template-columns: 30px minmax(0,1fr); align-items: center; gap: 10px; padding: 7px 10px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; color: var(--theme-text-primary); background: var(--theme-bg-surface); cursor: pointer; text-align: left; transition: border-color .16s ease,background .16s ease; }
.asset-action-library-grid > button:hover:not(:disabled) { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); }
.asset-action-library-grid > button:disabled { cursor: wait; opacity: .45; }
.asset-action-library-grid > button > svg { width: 19px; fill: none; stroke: var(--theme-text-secondary); stroke-width: 1.65; stroke-linecap: round; stroke-linejoin: round; }
.asset-action-library-grid > button > span { display: grid; gap: 3px; padding: 0; border: 0; color: inherit; background: transparent; font: inherit; letter-spacing: 0; }
.asset-action-library-grid strong { color: var(--theme-text-primary); font-size: 11px; }
.asset-action-library-grid small { color: var(--theme-text-secondary); font-size: 9px; }
.asset-actions-popover > p { margin: 0; padding: 2px 3px 0; color: var(--theme-text-secondary); font-size: 11px; line-height: 1.4; }
.asset-actions-popover > p.error { color: var(--theme-danger-text); }
.asset-category-tabs { flex: 0 0 auto; gap: 3px; margin: 0 10px 10px; padding: 4px; border: 0; border-radius: 10px; background: var(--theme-bg-elevated); box-shadow: inset 0 0 0 1px var(--theme-shadow); }
.asset-category-tabs button { height: 44px; gap: 4px; border: 1px solid transparent; border-radius: 7px; color: var(--theme-text-secondary); font-size: 11px; transition: color .16s ease,background .16s ease,border-color .16s ease; }
.asset-category-tabs button:hover { color: var(--theme-text-secondary); background: var(--theme-bg-card-hover); }
.asset-category-tabs svg,.asset-category-tabs button:first-child svg { width: 17px; height: 17px; stroke-width: 1.65; }
.asset-category-tabs button.active { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); box-shadow: inset 0 1px var(--theme-shadow); }
.asset-category-tabs button.active::after { display: none; }
.asset-generator { flex: 0 0 auto; border-color: var(--theme-border-subtle); background: var(--theme-bg-elevated); }
.asset-json-import { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-surface); }
.asset-json-import:hover { border-color: var(--theme-accent-border); background: var(--theme-bg-card-hover); }
.asset-json-import > span { color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.asset-rail-scroll {
  flex: 1;
  min-height: 0;
  max-height: none;
  overflow-x: hidden;
  overflow-y: scroll;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}
.asset-rail-scroll::-webkit-scrollbar { width: 10px; height: 10px; }
.asset-rail-scroll::-webkit-scrollbar-track { background: transparent; }
.asset-rail-scroll::-webkit-scrollbar-thumb {
  min-height: 44px;
  border: 3px solid transparent;
  border-radius: 999px;
  background: var(--theme-scrollbar-thumb);
  background-clip: padding-box;
}
.asset-rail-scroll::-webkit-scrollbar-thumb:hover { border-width: 2px; background: var(--theme-scrollbar-thumb-hover); background-clip: padding-box; }
.asset-rail-grid { grid-template-columns: 1fr; gap: 7px; }
.asset-pick-card {
  display: grid;
  height: 76px;
  min-height: 76px;
  box-sizing: border-box;
  grid-template-columns: 62px minmax(0,1fr) 34px;
  grid-template-rows: 1fr;
  align-items: center;
  gap: 10px;
  padding: 7px;
  overflow: visible;
  border-color: var(--theme-border-subtle);
  border-radius: 10px;
  background: var(--theme-bg-surface);
  box-shadow: none;
  transition: grid-template-columns .18s ease,gap .18s ease,border-color .16s ease,background .16s ease;
}
.asset-pick-card:has(.asset-card-add:hover),.asset-pick-card:has(.asset-card-generate:hover),.asset-pick-card:has(.asset-card-add:focus-visible),.asset-pick-card:has(.asset-card-generate:focus-visible) { grid-template-columns: 62px minmax(0,1fr) 96px; gap: 7px; }
.asset-pick-card:has([data-tooltip]:hover),.asset-pick-card:has([data-tooltip]:focus-visible) { z-index: 30; }
.asset-pick-card:hover { border-color: var(--theme-border-subtle); background: var(--theme-bg-card-hover); box-shadow: none; transform: none; }
.asset-pick-card .asset-preview-button,.asset-pick-card .asset-missing-preview {
  width: 62px;
  height: 60px;
  grid-column: 1;
  grid-row: 1;
  overflow: hidden;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
}
.asset-pick-card .asset-preview-button > img,.asset-pick-card .asset-audio-placeholder,.asset-pick-card .asset-missing-preview {
  width: 62px;
  height: 60px;
  aspect-ratio: auto;
  object-fit: cover;
}
.asset-pick-card .asset-missing-preview { color: var(--theme-text-secondary); background: var(--theme-bg-elevated); }
.asset-pick-card .asset-missing-preview span { display: none; }
.asset-pick-card .asset-missing-preview svg { width: 22px; }
.asset-pick-card .asset-pick-copy { grid-column: 2; grid-row: 1; align-self: center; gap: 4px; padding: 0; }
.asset-pick-card .asset-pick-copy strong { color: var(--theme-text-primary); font-size: 14px; line-height: 18px; }
.asset-pick-card .asset-pick-copy small { color: var(--theme-text-secondary); font-size: 11px; line-height: 15px; }
.asset-pick-card .asset-card-add {
  position: static;
  width: 34px;
  height: 34px;
  grid-column: 3;
  grid-row: 1;
  align-self: center;
  border-width: 1px;
  border-color: var(--theme-border-subtle);
  border-radius: 9px;
  color: var(--theme-text-primary);
  background: var(--theme-bg-surface);
  box-shadow: none;
  opacity: 1;
  transition: border-color .16s ease,color .16s ease,background .16s ease;
}
.asset-pick-card .asset-card-add:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); transform: none; }
.asset-pick-card .asset-card-generate {
  width: 34px;
  min-height: 34px;
  height: 34px;
  grid-column: 3;
  grid-row: 1;
  justify-self: center;
  margin: 0;
  padding: 0;
  border-color: var(--theme-border-subtle);
  border-radius: 9px;
  color: var(--theme-text-primary);
  background: var(--theme-bg-surface);
  font-size: 0;
}
.asset-pick-card .asset-card-generate svg { width: 16px; height: 16px; }
.asset-pick-card .asset-card-generate:hover:not(:disabled) { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-pick-card .asset-card-error { position: absolute; right: 8px; bottom: 3px; left: 80px; margin: 0; font-size: 9px; }
.asset-pick-card.generating { border-color: var(--theme-accent-border); box-shadow: inset 0 0 18px var(--theme-shadow); }
.asset-image-generating { position: absolute; z-index: 4; top: 7px; left: 7px; width: 62px; height: 60px; overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 8px; background: var(--theme-bg-elevated); pointer-events: none; contain: paint; }
.asset-image-generating i { position: absolute; top: -18%; bottom: -18%; left: 0; width: 38%; background: linear-gradient(90deg,transparent,var(--theme-bg-card),transparent); filter: blur(.2px); transform: skewX(-12deg); animation: assetImageGenerateSweep 1.55s ease-in-out infinite; }
.asset-pick-card .asset-card-add,.asset-pick-card .asset-card-generate { justify-self: end; overflow: hidden; white-space: nowrap; transition: width .18s ease,border-color .16s ease,color .16s ease,background .16s ease; }
.asset-pick-card .asset-card-add { display: flex; align-items: center; justify-content: center; gap: 0; font-size: 0; }
.asset-pick-card .asset-card-add svg { width: 16px; height: 16px; flex: 0 0 16px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.asset-pick-card .asset-card-add em,.asset-pick-card .asset-card-generate em { max-width: 0; overflow: hidden; opacity: 0; color: inherit; font-size: 11px; font-style: normal; transition: max-width .18s ease,opacity .14s ease; }
.asset-card-add:hover,.asset-card-generate:hover,.asset-card-add:focus-visible,.asset-card-generate:focus-visible { z-index: 6; width: 96px; gap: 6px; padding: 0 9px; background: var(--theme-bg-card-hover); }
.asset-card-add:hover em,.asset-card-generate:hover em,.asset-card-add:focus-visible em,.asset-card-generate:focus-visible em { max-width: 68px; opacity: 1; }
@keyframes assetImageGenerateSweep { 0% { opacity: 0; transform: translateX(-130%) skewX(-12deg); } 18%,78% { opacity: .9; } 100% { opacity: 0; transform: translateX(360%) skewX(-12deg); } }
@media (prefers-reduced-motion: reduce) { .asset-image-generating i,.asset-detail-image-preview.is-generating::after,.asset-detail-empty.is-generating::after { animation-duration: 1ms !important; } }
.storyboard-column-shell {
  position: relative;
  min-width: 0;
  min-height: 0;
  height: 100%;
  max-height: 100%;
}
.storyboard-column {
  height: 100%;
  min-height: 0;
  max-height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 9px;
  background: var(--theme-bg-elevated);
  box-shadow: none;
}
.storyboard-column::-webkit-scrollbar { width: 10px; height: 10px; }
.storyboard-column::-webkit-scrollbar-track { background: transparent; }
.storyboard-column::-webkit-scrollbar-thumb {
  min-height: 44px;
  border: 3px solid transparent;
  border-radius: 999px;
  background: var(--theme-scrollbar-thumb);
  background-clip: padding-box;
}
.storyboard-column::-webkit-scrollbar-thumb:hover { border-width: 2px; background: var(--theme-scrollbar-thumb-hover); background-clip: padding-box; }
.storyboard-anchor-nav {
  position: fixed;
  z-index: 40;
  top: 50%;
  right: 16px;
  display: flex;
  width: 30px;
  max-height: calc(100vh - 120px);
  box-sizing: border-box;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 8px 5px;
  overflow: hidden;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 11px;
  background: var(--theme-bg-elevated);
  box-shadow: 0 10px 28px var(--theme-shadow),inset 0 1px var(--theme-shadow);
  backdrop-filter: blur(10px);
  transform: translateY(-50%);
}
.storyboard-anchor-nav button {
  display: grid;
  width: 20px;
  height: 11px;
  flex: 0 0 11px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 4px;
  outline: 0;
  color: var(--theme-text-secondary);
  background: transparent;
  cursor: pointer;
}
.storyboard-anchor-nav button i {
  display: block;
  width: 7px;
  height: 1px;
  border-radius: 99px;
  background: currentColor;
  transition: width .18s ease,height .18s ease,color .18s ease,box-shadow .18s ease;
}
.storyboard-anchor-nav button:nth-child(3n + 2) i { width: 10px; }
.storyboard-anchor-nav button:nth-child(4n) i { width: 5px; }
.storyboard-anchor-nav button:hover,.storyboard-anchor-nav button:focus-visible { color: var(--theme-text-primary); background: var(--theme-accent-soft); }
.storyboard-anchor-nav button.active { color: var(--theme-accent-text); }
.storyboard-anchor-nav button.active i { width: 18px; height: 2px; box-shadow: 0 0 9px var(--theme-shadow); }
.asset-rail,.storyboard-column { align-self: stretch; height: 100%; min-height: 0; max-height: 100%; box-sizing: border-box; }
.storyboard-column-head { position: sticky; z-index: 12; top: 0; margin: 0; border: 0; border-bottom: 1px solid var(--theme-border-subtle); border-radius: 9px 9px 0 0; background: var(--theme-bg-elevated); box-shadow: none; }
.storyboard-card { --shot-card-radius: var(--theme-accent); margin: 14px; overflow: visible; border-color: var(--theme-border-subtle); border-radius: 9px; background: var(--theme-bg-elevated); box-shadow: none; }
.storyboard-card + .storyboard-card { margin-top: 0; }
.storyboard-column.single-shot .storyboard-card { display: flex; min-height: 0; box-sizing: border-box; flex-direction: column; }
.storyboard-column.single-shot .shot-body-grid { flex: 1; min-height: 0; }
.storyboard-column.single-shot .shot-content:not(.expanded),.storyboard-column.single-shot .shot-result { min-height: 0; }
.storyboard-card.active,.storyboard-card:focus-visible { border-color: var(--theme-border-strong); box-shadow: 0 0 0 2px var(--theme-shadow); }
.storyboard-card-head { border-radius: 9px 9px 0 0; background: var(--theme-bg-surface); }
.shot-number { border-color: var(--theme-border-subtle); border-radius: 5px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); }
.storyboard-card.active .shot-number,.storyboard-card:focus-visible .shot-number { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.shot-content:not(.expanded) { height: 100%; }
.shot-content:not(.expanded) .shot-content-head,.shot-content:not(.expanded) .storyboard-toolbar { flex: 0 0 auto; }
.shot-content:not(.expanded) .storyboard-compose { height: clamp(160px,23vh,200px); min-height: 160px; max-height: 200px; flex: 0 0 auto; grid-template-columns: 104px minmax(260px,1fr) 28px; align-items: stretch; }
.shot-content:not(.expanded) .storyboard-compose:has(.reference-stack.expanded) { grid-template-columns: minmax(104px,280px) minmax(260px,1fr) 28px; }
.shot-content:not(.expanded) .storyboard-compose .reference-stack,.shot-content:not(.expanded) .storyboard-compose .shot-expand { align-self: start; }
.shot-content:not(.expanded) .storyboard-compose .reference-stack { z-index: 4; }
.shot-content:not(.expanded) .storyboard-compose .storyboard-prompt-editor { position: relative; z-index: 1; min-width: 0; }
.shot-content:not(.expanded) .storyboard-compose textarea,.shot-content:not(.expanded) .storyboard-compose .storyboard-prompt-editor { height: 100%; min-height: 0; max-height: 100%; box-sizing: border-box; overflow-y: auto; overscroll-behavior: contain; }
.shot-content-head,.shot-result > header { background: var(--theme-bg-elevated); }
.shot-content-head,.shot-result > header > div { display: flex; align-items: center; gap: 8px; }
.shot-content-head span,.shot-result > header span { order: 2; padding: 3px 6px; border: 1px solid var(--theme-border-subtle); border-radius: 999px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); font-size: 8px; letter-spacing: .1em; white-space: nowrap; }
.shot-content-head strong,.shot-result > header strong { order: 1; color: var(--theme-text-primary); font-size: 13px; line-height: 1; }
.storyboard-compose textarea { color: var(--theme-text-primary); background: var(--theme-bg-input); }
.storyboard-compose .storyboard-prompt-editor { min-height: 78px; padding: 8px 10px; border: 1px solid transparent; border-radius: 10px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); transition: border-color .18s ease,box-shadow .18s ease; }
.storyboard-compose .storyboard-prompt-editor:focus,.storyboard-compose .storyboard-prompt-editor:focus-within { border-color: var(--theme-border-strong); box-shadow: 0 0 0 3px var(--theme-shadow); }
.shot-content.expanded .storyboard-compose .storyboard-prompt-editor { width: 100%; height: 100%; min-height: 240px; box-sizing: border-box; padding: 12px; font-size: 16px; }
.storyboard-toolbar { border-radius: 0; background: var(--theme-bg-elevated); }
.storyboard-toolbar .shot-submit { border-radius: 7px; color: var(--theme-text-primary); background: var(--theme-accent-soft); box-shadow: none; }
.storyboard-toolbar .shot-submit:hover { color: var(--theme-text-primary); background: var(--theme-accent-soft); filter: none; }
.storyboard-toolbar .ratio-options button.active,.storyboard-toolbar .segmented-options button.active,.storyboard-toolbar .duration-options button.active,.storyboard-toolbar .count-options button.active { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.shot-result { background: var(--theme-bg-elevated); }
.shot-result:has(.shot-result-player) { align-self: center; }
.shot-result:has(.shot-result-player) .shot-result-player { width: 100%; min-height: 0; aspect-ratio: 16 / 9; flex: 0 0 auto; }
.shot-result:has(.shot-result-player) .shot-result-player video { width: 100%; height: 100%; min-height: 0; max-height: none; object-fit: cover; }

/* Primary controls use the same neutral white interaction language. */
.video-project-new-button:hover,.video-project-new-button:focus-visible,.video-project-card:focus-visible { border-color: var(--theme-border-strong); box-shadow: 0 0 0 3px var(--theme-shadow); }
.video-project-new-plus { color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 6px 16px var(--theme-shadow); }
.video-project-create-backdrop .video-project-create footer button[type=submit] { border: 1px solid var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: none; }
.video-project-create-backdrop .video-project-create footer button[type=submit]:hover:not(:disabled) { background: var(--theme-bg-card-hover); }
.video-project-card-head-actions { display: inline-flex; align-items: center; gap: 7px; }
.video-project-delete-button { display: grid; width: 28px; height: 28px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 7px; color: var(--theme-text-secondary); background: transparent; cursor: pointer; transition: border-color .16s ease,color .16s ease,background .16s ease; }
.video-project-delete-button svg { width: 15px !important; fill: none; stroke: currentColor !important; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.video-project-delete-button:hover:not(:disabled),.video-project-delete-button:focus-visible { border-color: var(--theme-danger-border); outline: 0; color: var(--theme-danger-text); background: var(--theme-danger-soft); }
.video-project-delete-button:disabled { cursor: wait; opacity: .45; }
.video-project-card:hover .video-project-card-body > header .video-project-delete-button svg { stroke: currentColor; transform: none; }
.video-project-open-arrow { flex: 0 0 auto; }
.video-project-delete-dialog { display: grid; grid-template-columns: 50px minmax(0,1fr); gap: 16px; width: min(470px,92vw); box-sizing: border-box; padding: 24px; border: 1px solid var(--theme-border-subtle); border-radius: 20px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 30px 90px var(--theme-shadow); }
.video-project-delete-icon { display: grid; width: 48px; height: 48px; place-items: center; border: 1px solid var(--theme-danger-border); border-radius: 14px; color: var(--theme-danger-text); background: var(--theme-danger-soft); }
.video-project-delete-icon svg { width: 23px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.video-project-delete-dialog small { color: var(--theme-danger-text); font: 800 11px/1 monospace; letter-spacing: .15em; }
.video-project-delete-dialog h2 { margin: 8px 0 9px; color: var(--theme-text-primary); font-size: 20px; }
.video-project-delete-dialog p { margin: 0; color: var(--theme-text-secondary); font-size: 14px; line-height: 1.7; }
.video-project-delete-dialog p strong { color: var(--theme-text-primary); }
.video-project-delete-dialog footer { display: flex; grid-column: 1 / -1; justify-content: flex-end; gap: 8px; margin-top: 6px; }
.video-project-delete-dialog footer button { min-width: 90px; height: 38px; border: 1px solid var(--theme-border-subtle); border-radius: 9px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); cursor: pointer; }
.video-project-delete-dialog footer button.danger { border-color: var(--theme-danger-border); color: var(--theme-text-primary); background: var(--theme-danger-soft); }
.video-project-delete-dialog footer button:hover:not(:disabled) { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); }
.video-project-delete-dialog footer button.danger:hover:not(:disabled) { border-color: var(--theme-danger-border); background: var(--theme-danger-soft); }
.video-project-delete-dialog footer button:disabled { cursor: wait; opacity: .55; }
.video-workbench-head .workbench-add-shot,.storyboard-toolbar .shot-submit { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: none; }
.video-workbench-head .workbench-add-shot:hover,.storyboard-toolbar .shot-submit:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-card-add,.reference-stack-add { color: var(--theme-text-primary); background: var(--theme-bg-elevated); }
.asset-card-generate { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-surface); }
.asset-card-generate:hover:not(:disabled) { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-json-import:hover,.reference-add:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.asset-json-import > span { color: var(--theme-text-primary); background: var(--theme-accent-soft); }
.asset-generator { --select-accent: var(--theme-accent-border); --select-border-hover: var(--theme-border-subtle); --select-border-focus: var(--theme-accent-border); --select-focus-ring: var(--theme-accent-soft); }

/* Refined storyboard card hierarchy. */
.storyboard-card {
  --shot-accent: var(--theme-accent);
  --shot-card-radius: var(--theme-accent);
  border: 1px solid var(--theme-border-subtle);
  border-radius: 14px;
  background: var(--theme-bg-elevated);
  background-clip: padding-box;
  box-shadow: 0 12px 32px var(--theme-shadow),inset 0 1px var(--theme-shadow);
  transition: border-color .18s ease,box-shadow .18s ease,transform .18s ease;
}
.storyboard-card::before { display: none; content: none; }
.storyboard-card::after {
  position: absolute;
  z-index: 30;
  right: -1px;
  bottom: -1px;
  width: 14px;
  height: 14px;
  box-sizing: border-box;
  border-right: 1px solid var(--theme-border-subtle);
  border-bottom: 1px solid var(--theme-border-subtle);
  border-radius: 0 0 14px 0;
  content: '';
  pointer-events: none;
}
.storyboard-card:hover { border-color: var(--theme-border-subtle); box-shadow: 0 15px 38px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.storyboard-card.active,.storyboard-card:focus-visible { border-color: var(--theme-border-strong); box-shadow: 0 16px 40px var(--theme-shadow),0 0 0 1px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.storyboard-card-head { height: 48px; gap: 10px; padding: 0 14px; border-color: var(--theme-border-subtle); border-radius: 14px 14px 0 0; background: linear-gradient(180deg,var(--theme-bg-surface) 0%,var(--theme-bg-surface) 100%); }
.storyboard-card-head .shot-number { display: grid; width: 29px; height: 26px; flex: 0 0 29px; box-sizing: border-box; place-items: center; padding: 0; border: 1px solid var(--theme-border-subtle); border-radius: 7px; color: var(--theme-text-secondary); background: var(--theme-bg-elevated); font: 700 11px/1 ui-monospace,SFMono-Regular,Consolas,monospace; box-shadow: inset 0 1px var(--theme-shadow); }
.storyboard-card.active .shot-number,.storyboard-card:focus-visible .shot-number { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-bg-card-hover); box-shadow: inset 0 0 0 1px var(--theme-shadow); }
.storyboard-card-head input { color: var(--theme-text-primary); font-size: 14px; font-weight: 650; letter-spacing: .01em; }
.storyboard-card-head button { width: 28px; height: 28px; border-radius: 7px; color: var(--theme-text-secondary); }
.storyboard-card-head button:hover:not(:disabled) { color: var(--theme-text-primary); background: var(--theme-accent-soft); }
.shot-content { border-color: var(--theme-border-subtle); background: var(--theme-bg-elevated); }
.shot-content-head,.shot-result > header { min-height: 44px; padding: 0 16px; border-color: var(--theme-border-subtle); background: var(--theme-bg-elevated); }
.shot-content-head strong,.shot-result > header strong { color: var(--theme-text-primary); font-size: 13px; font-weight: 650; }
.shot-content-head span,.shot-result > header span { border-color: var(--theme-border-subtle); color: var(--theme-accent-text); background: var(--theme-bg-surface); }
.storyboard-compose { gap: 14px; padding: 15px; background: linear-gradient(135deg,var(--theme-bg-elevated),var(--theme-bg-elevated)); }
.storyboard-compose .storyboard-prompt-editor { border-color: var(--theme-border-subtle); border-radius: 11px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: inset 0 1px 0 var(--theme-shadow); }
.storyboard-compose .storyboard-prompt-editor:focus,.storyboard-compose .storyboard-prompt-editor:focus-within { border-color: var(--theme-border-strong); box-shadow: 0 0 0 3px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.reference-card { border-color: var(--theme-border-subtle); background: var(--theme-bg-elevated); box-shadow: 0 7px 18px var(--theme-shadow); }
.reference-card > small { right: 5px; bottom: 5px; left: 5px; padding: 4px 5px; border-radius: 5px; background: var(--theme-bg-elevated); }
.reference-upload-state { position: absolute; z-index: 4; top: 5px; left: 5px; display: flex; height: 20px; align-items: center; gap: 5px; padding: 0 7px; border-radius: 999px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 11px; font-style: normal; box-shadow: 0 3px 10px var(--theme-shadow); }
.reference-upload-state i { width: 8px; height: 8px; border: 1.5px solid var(--theme-border-subtle); border-top-color: var(--theme-border-subtle); border-radius: 50%; animation: result-spin .7s linear infinite; }
.reference-upload-state.error { color: var(--theme-danger-text); background: var(--theme-danger-soft); }
.reference-stack-add { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-elevated); }
.shot-content:not(.expanded) { border-bottom-left-radius: var(--shot-card-radius,14px); background-clip: padding-box; }
.storyboard-toolbar { min-height: 48px; gap: 7px; padding: 7px 10px; border-color: var(--theme-border-subtle); border-radius: 0 0 0 var(--shot-card-radius,14px); background: var(--theme-bg-elevated); background-clip: padding-box; }
.storyboard-toolbar > button,.storyboard-toolbar .toolbar-popover-wrap > button { min-height: 30px; padding: 0 8px; border: 1px solid transparent; border-radius: 7px; color: var(--theme-text-secondary); background: transparent; font-size: 12px; }
.storyboard-toolbar > button:hover,.storyboard-toolbar .toolbar-popover-wrap > button:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.storyboard-toolbar .shot-clear { color: var(--theme-text-secondary); }
.storyboard-toolbar .shot-submit { width: auto; min-width: 106px; height: 34px; flex: 0 0 auto; grid-auto-flow: column; gap: 7px; padding: 0 15px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 12px; box-shadow: 0 5px 16px var(--theme-shadow); }
.storyboard-toolbar .shot-submit:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); transform: translateY(-1px); }
.storyboard-toolbar .shot-submit svg { width: 13px; }
.shot-result { margin: 14px; overflow: hidden; border-color: var(--theme-border-subtle); border-radius: 12px; background: var(--theme-bg-elevated); box-shadow: 0 8px 24px var(--theme-shadow),inset 0 1px var(--theme-shadow); }
.shot-result > header { flex: 0 0 44px; border-radius: 12px 12px 0 0; background: linear-gradient(180deg,var(--theme-bg-surface),var(--theme-bg-elevated)); }
.shot-result-player { overflow: hidden; isolation: isolate; box-sizing: border-box; padding: 0; border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); background: var(--theme-bg-elevated); }
.shot-result-player::after { display: none; content: none; }
.shot-result-player video { width: 100%; height: 100%; min-height: 0; overflow: hidden; border: 0; border-radius: 0; background: var(--theme-bg-elevated); box-shadow: none; }
.shot-result-player:fullscreen { padding: 0; }
.shot-result-player:fullscreen,.shot-result-player:fullscreen video { contain: none; border: 0; border-radius: 0; clip-path: none; transform: none; -webkit-mask-image: none; }
.shot-result-player:fullscreen::after { display: none; }
.shot-result:has(.shot-result-player) { width: 100%; height: auto; align-self: center; margin: 0; border: 0; border-radius: 0 0 var(--shot-card-radius,14px) 0; background: var(--theme-bg-elevated); box-shadow: none; }
.shot-result:has(.shot-result-player) .shot-result-player { width: 100%; height: auto; min-height: 0; aspect-ratio: 16 / 9; flex: 0 0 auto; border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); }
/* 垂直布局（上下显示）：.shot-result 横跨卡片底部，两个底角都要圆角对齐卡片 */
@media (max-width: 1450px) {
  .storyboard-card .shot-result:has(.shot-result-player) { border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); }
}
.shot-result-player video { cursor: pointer; }
.shot-result-center-play { position: absolute; z-index: 5; top: 50%; left: 50%; display: grid; width: 54px; height: 54px; place-items: center; padding: 0; border: 1px solid var(--theme-border-subtle); border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-accent-soft); box-shadow: 0 8px 24px var(--theme-shadow),0 0 0 6px var(--theme-shadow); backdrop-filter: blur(5px); cursor: pointer; transform: translate(-50%,-50%); transition: transform .18s ease,background .18s ease,border-color .18s ease; }.shot-result-center-play:hover { border-color: var(--theme-border-subtle); background: var(--theme-accent-soft); transform: translate(-50%,-50%) scale(1.06); }.shot-result-center-play svg { width: 24px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; transform: translateX(1px); }
.shot-result-controls {
  position: absolute;
  z-index: 7;
  right: 0;
  bottom: 0;
  left: 0;
  display: grid;
  box-sizing: border-box;
  gap: 8px;
  padding: 46px 0 13px;
  overflow: hidden;
  border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px);
  color: var(--theme-text-primary);
  background: linear-gradient(to bottom,transparent,var(--theme-bg-elevated) 58%,var(--theme-bg-elevated));
  clip-path: inset(0 round 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px));
}
.shot-result-player:focus-within .shot-result-controls { opacity: 1; }
.shot-result-controls > input { width: 100%; height: 14px; margin: 0; cursor: pointer; appearance: none; background: transparent; }.shot-result-controls > input::-webkit-slider-runnable-track { height: 3px; border-radius: 99px; background: linear-gradient(90deg,var(--theme-bg-input) var(--video-progress),var(--theme-accent-soft) var(--video-progress)); }.shot-result-controls > input::-webkit-slider-thumb { width: 12px; height: 12px; margin-top: -4.5px; border: 2px solid var(--theme-border-subtle); border-radius: 50%; background: var(--theme-bg-input); box-shadow: 0 2px 8px var(--theme-shadow); appearance: none; opacity: 0; transition: opacity .15s ease; }.shot-result-controls:hover > input::-webkit-slider-thumb { opacity: 1; }.shot-result-controls > input::-moz-range-track { height: 3px; border-radius: 99px; background: var(--theme-accent-soft); }.shot-result-controls > input::-moz-range-progress { height: 3px; border-radius: 99px; background: var(--theme-bg-input); }.shot-result-controls > input::-moz-range-thumb { width: 10px; height: 10px; border: 2px solid var(--theme-border-subtle); border-radius: 50%; background: var(--theme-bg-input); }
.shot-result-controls > div { display: flex; align-items: center; gap: 7px; padding: 0 16px; }.shot-result-controls button { display: grid; width: 30px; height: 30px; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 7px; color: var(--theme-text-primary); background: transparent; cursor: pointer; }.shot-result-controls button:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-accent-soft); }.shot-result-controls button:first-child { margin-right: 2px; }.shot-result-controls .shot-result-replace-control { margin-left: auto; }.shot-result-controls svg { width: 17px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }.shot-result-controls time { color: var(--theme-text-primary); font: 650 11px/1 ui-monospace,SFMono-Regular,Consolas,monospace; }.shot-result-controls time span { color: var(--theme-text-secondary); }
.shot-result-player:fullscreen .shot-result-controls { right: 0; bottom: 0; left: 0; padding: 70px 24px 20px; border-radius: 0; clip-path: none; }.shot-result-player:fullscreen .shot-result-center-play { width: 66px; height: 66px; }
.shot-result-expand { border-color: var(--theme-border-subtle); border-radius: 7px; background: var(--theme-bg-elevated); }

/* Expanded storyboard editor must escape the card and scroll containers. */
.shot-content.expanded {
  position: fixed;
  z-index: 2147482000;
  top: 64px;
  right: 18px;
  bottom: 18px;
  left: calc(var(--sidebar-width,240px) + 18px);
  display: flex;
  min-width: 0;
  overflow: visible;
  flex-direction: column;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 16px;
  background: var(--theme-bg-elevated);
  box-shadow: 0 32px 100px var(--theme-shadow),0 0 0 100vmax var(--theme-shadow),inset 0 1px var(--theme-shadow);
}
.shot-content.expanded .shot-content-head { min-height: 56px; flex: 0 0 56px; padding: 0 20px; border-radius: 16px 16px 0 0; background: linear-gradient(180deg,var(--theme-bg-surface),var(--theme-bg-surface)); }
.shot-content.expanded .storyboard-compose { height: auto; min-height: 0; max-height: none; flex: 1 1 auto; grid-template-columns: auto minmax(260px,1fr) 36px; align-items: stretch; gap: 16px; padding: 20px; overflow: hidden; background: var(--theme-bg-elevated); }
.shot-content.expanded .storyboard-compose .storyboard-prompt-editor { width: 100%; height: 100%; min-height: 240px; max-height: none; box-sizing: border-box; padding: 14px; overflow-y: auto; border-color: var(--theme-border-subtle); background: var(--theme-bg-elevated); font-size: 16px; }
.shot-content.expanded .shot-editor-actions { align-self: start; gap: 9px; }
.shot-content.expanded .shot-editor-actions > button { width: 36px; height: 36px; border: 1px solid var(--theme-border-subtle); border-radius: 9px; color: var(--theme-text-primary); background: var(--theme-bg-surface); }
.shot-content.expanded .shot-editor-actions > button:hover { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.shot-content.expanded .shot-editor-actions .shot-send-preview-toggle.active { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.shot-content.expanded .shot-expand { align-self: start; width: 36px; height: 36px; border: 1px solid var(--theme-border-subtle); border-radius: 9px; color: var(--theme-text-primary); background: var(--theme-bg-surface); }
.storyboard-send-preview { display: flex; min-width: 0; min-height: 0; overflow: hidden; flex-direction: column; border: 1px solid var(--theme-border-subtle); border-radius: 11px; background: var(--theme-bg-elevated); box-shadow: inset 0 1px var(--theme-shadow); }
.storyboard-send-preview > header { display: flex; min-height: 42px; flex: 0 0 42px; align-items: center; gap: 8px; padding: 0 13px; border-bottom: 1px solid var(--theme-border-subtle); color: var(--theme-text-secondary); background: var(--theme-bg-elevated); }
.storyboard-send-preview > header svg { width: 15px; height: 15px; fill: none; stroke: var(--theme-accent-text); stroke-width: 1.6; }
.storyboard-send-preview > header strong { color: var(--theme-text-primary); font-size: 12px; }
.storyboard-send-preview > header span { margin-left: auto; color: var(--theme-accent-text); font-size: 11px; }
.storyboard-send-preview > pre { min-height: 0; margin: 0; padding: 14px; overflow: auto; flex: 1; color: var(--theme-text-primary); font: 14px/1.75 "Microsoft YaHei",sans-serif; white-space: pre-wrap; word-break: break-word; scrollbar-width: thin; scrollbar-color: var(--theme-scrollbar-thumb) transparent; }
.storyboard-send-preview.engine-seedance { border-color: var(--theme-accent-border); background: var(--theme-bg-elevated); }
.storyboard-send-preview.engine-seedance > header { border-bottom-color: var(--theme-accent-border); background: var(--theme-bg-surface); }
.storyboard-send-preview.engine-seedance > header svg { stroke: var(--theme-accent-text); }
.storyboard-send-preview.engine-seedance > pre { color: var(--theme-text-primary); font-family: Consolas,"SFMono-Regular",monospace; }
.shot-content.expanded .storyboard-send-preview { width: 100%; height: 100%; min-height: 240px; }
.shot-content.expanded .storyboard-send-preview > pre { font-size: 16px; }
.shot-content.expanded .storyboard-toolbar { min-height: 58px; flex: 0 0 58px; padding: 9px 18px; border-radius: 0 0 16px 16px; background: var(--theme-bg-elevated); }
.shot-content.expanded .mode-popover,.shot-content.expanded .settings-popover { top: auto; bottom: calc(100% + 10px); }

/* Selection states on the video workspace use a neutral gray language. */
.asset-category-tabs button:hover,.asset-category-tabs button.active { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); box-shadow: none; }
.asset-actions-trigger:hover,.asset-actions-trigger.active { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.storyboard-toolbar .mode-popover > button:hover,.storyboard-toolbar .mode-popover > button.active { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.storyboard-toolbar .ratio-options button:hover,.storyboard-toolbar .ratio-options button.active,
.storyboard-toolbar .segmented-options button:hover,.storyboard-toolbar .segmented-options button.active,
.storyboard-toolbar .duration-options button:hover,.storyboard-toolbar .duration-options button.active,
.storyboard-toolbar .count-options button:hover,.storyboard-toolbar .count-options button.active { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); box-shadow: inset 0 1px var(--theme-shadow); }
.storyboard-toolbar .segmented-options button:disabled,.storyboard-toolbar .duration-options button:disabled,.storyboard-toolbar .count-options button:disabled { opacity: .4; cursor: not-allowed; }
.asset-action-model,.asset-generator { --select-accent: var(--theme-accent-border); --select-border-hover: var(--theme-border-subtle); --select-border-focus: var(--theme-accent-border); --select-focus-ring: var(--theme-accent-soft); }

/* Keep storyboard controls inside the left pane and settings inside the viewport. */
.storyboard-toolbar > .toolbar-popover-wrap:first-child { flex: 0 0 auto; }
.storyboard-toolbar > .settings-wrap { min-width: 0; flex: 1 1 150px; }
.storyboard-toolbar .settings-summary-btn { display: flex; width: 100%; min-width: 0; max-width: 100%; box-sizing: border-box; }
.storyboard-toolbar .settings-summary-btn > svg { flex: 0 0 auto; }
.storyboard-toolbar .settings-summary-btn > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.storyboard-toolbar .shot-clear,.storyboard-toolbar .shot-submit { flex-shrink: 0; }
.settings-popover { z-index: 2147482500; min-width: 0; overscroll-behavior: contain; }
.settings-popover > fieldset:nth-child(n) { grid-column: auto; }
.settings-popover > fieldset.settings-field-wide { grid-column: 1 / -1; }
.generation-model-field { padding: 2px !important; }
.generation-model-options { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; }
.storyboard-toolbar .generation-model-card { position: relative; display: grid; min-width: 0; min-height: 62px; grid-template-columns: 38px minmax(0,1fr) auto; grid-template-rows: 1fr; align-items: center; gap: 10px; padding: 9px 10px; overflow: hidden; border: 1px solid var(--theme-border-subtle); border-radius: 11px; color: var(--theme-text-secondary); background: linear-gradient(145deg,var(--theme-bg-elevated),var(--theme-bg-elevated)); cursor: pointer; text-align: left; transition: border-color .16s ease,background .16s ease,box-shadow .16s ease,transform .16s ease; }
.storyboard-toolbar .generation-model-card:hover:not(:disabled) { border-color: var(--theme-border-subtle); color: var(--theme-text-primary); background: linear-gradient(145deg,var(--theme-bg-card-hover),var(--theme-bg-card-hover)); transform: translateY(-1px); }
.storyboard-toolbar .generation-model-card.active { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: linear-gradient(145deg,var(--theme-bg-card-hover),var(--theme-bg-card-hover)); box-shadow: inset 0 0 0 1px var(--theme-shadow),0 5px 16px var(--theme-shadow); }
.storyboard-toolbar .generation-model-card:disabled { cursor: not-allowed; opacity: .42; }
.generation-model-icon { display: grid; width: 38px; height: 38px; box-sizing: border-box; place-items: center; border: 1px solid var(--theme-border-subtle); border-radius: 10px; color: var(--theme-text-primary); background: var(--theme-bg-surface); }
.generation-model-icon svg { width: 21px !important; height: 21px; fill: none; stroke: currentColor; stroke-width: 1.55; stroke-linecap: round; stroke-linejoin: round; }
.generation-model-card.active .generation-model-icon.do { border-color: var(--theme-border-strong); color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.generation-model-card.active .generation-model-icon.seedance { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.generation-model-copy { display: grid; min-width: 0; gap: 4px; }
.generation-model-copy strong { overflow: hidden; color: inherit; font-size: 13px; font-weight: 700; text-overflow: ellipsis; }
.generation-model-copy small { overflow: hidden; color: var(--theme-text-secondary); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.generation-model-card > em { align-self: start; padding: 3px 5px; border: 1px solid var(--theme-border-subtle); border-radius: 999px; color: var(--theme-accent-text); background: var(--theme-bg-elevated); font: 700 8px/1 ui-monospace,SFMono-Regular,Consolas,monospace; font-style: normal; letter-spacing: .06em; }
.generation-model-card > i { position: absolute; right: 8px; bottom: 7px; display: grid; width: 16px; height: 16px; place-items: center; border-radius: 50%; color: var(--theme-text-primary); background: var(--theme-bg-elevated); font-size: 10px; font-style: normal; opacity: 0; transform: scale(.75); transition: opacity .16s ease,transform .16s ease; }
.generation-model-card.active > i { opacity: 1; transform: scale(1); }
.generation-model-field .seedance-model-select { display: block; width: 100%; margin-top: 6px; padding: 0; border: none; background: transparent; }
.generation-model-field .seedance-model-select > span { display: block; margin-bottom: 6px; color: var(--theme-text-secondary); font-size: 10px; }
.generation-model-field .seedance-model-select :deep(.ui-select) { width: 100%; display: block; }
.generation-model-field .seedance-model-select :deep(.ui-select-trigger) { min-height: 38px; border-radius: 8px; width: 100%; box-sizing: border-box; }
.generation-model-field .seedance-model-select :deep(.ui-select-value) { flex: 1 1 auto; min-width: 0; }
.do-account-select, .web-model-select { display: grid; grid-template-columns: 132px minmax(0,1fr); align-items: center; gap: 10px; margin-top: 9px; padding: 8px 9px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; background: var(--theme-bg-input); }
.do-account-select > span, .web-model-select > span { color: var(--theme-text-secondary); font-size: 10px; }
.do-account-select :deep(.ui-select-trigger), .web-model-select :deep(.ui-select-trigger) { min-height: 36px; border-radius: 8px; }
.do-account-hint { display: block; margin: 7px 9px 2px; color: var(--theme-text-secondary); font-size: 10px; }
.ratio-options.dola-ratio-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); }

/* In the two-column card, the generated video fills the complete result pane. */
.storyboard-column-shell { display: flex; overflow: hidden; flex-direction: column; border: 1px solid var(--theme-border-subtle); border-radius: 9px; background: var(--theme-bg-elevated); }
.storyboard-column-shell > .storyboard-column-head { position: relative; z-index: 12; top: auto; width: 100%; flex: 0 0 52px; box-sizing: border-box; margin: 0; border: 0; border-bottom: 1px solid var(--theme-border-subtle); border-radius: 8px 8px 0 0; background: var(--theme-bg-elevated); }
.storyboard-column-shell > .storyboard-column { height: auto !important; min-height: 0; max-height: none !important; flex: 1 1 auto; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.shot-body-grid { width: 100%; min-width: 0; max-width: 100%; box-sizing: border-box; column-gap: 0; }
.shot-body-grid > .shot-content:not(.expanded),.shot-body-grid > .shot-result { width: 100%; min-width: 0; max-width: none; justify-self: stretch; }
.shot-content:not(.expanded) { border-radius: var(--shot-card-radius,14px) 0 0 var(--shot-card-radius,14px); background-clip: padding-box; }
.shot-content > .storyboard-card-head { flex: 0 0 48px; box-sizing: border-box; }
.shot-content.expanded > .storyboard-card-head { display: none; }
.shot-body-grid > .shot-result { width: 100% !important; max-width: none !important; min-width: 0 !important; box-sizing: border-box; margin: 0 !important; padding: 0 !important; align-self: stretch !important; }
.shot-body-grid > .shot-result > .shot-result-player { width: 100% !important; max-width: none !important; box-sizing: border-box; margin: 0 !important; padding: 0 !important; }
.shot-body-grid > .shot-result > .shot-result-player > video { display: block !important; width: 100% !important; max-width: none !important; margin: 0 !important; padding: 0 !important; }
.shot-result.has-player { width: 100%; min-width: 0; align-self: stretch; margin: 0; border: 0; border-radius: 0 0 var(--shot-card-radius,14px) 0; background: var(--theme-bg-elevated); box-shadow: none; }
.shot-result.has-player .shot-result-player { width: 100%; max-width: none; min-height: 0; box-sizing: border-box; margin: 0; aspect-ratio: 16 / 9; flex: 1 1 auto; border-radius: 0 0 var(--shot-card-radius,14px) 0; }
.shot-result.has-player .shot-result-player video { display: block; width: 100%; max-width: none; height: 100%; min-height: 0; margin: 0; object-fit: cover; border-radius: 0; }
@media (min-width: 1451px) {
  .shot-body-grid { grid-template-columns: minmax(0,3fr) minmax(0,2fr) !important; }
  .shot-content > .storyboard-card-head { border-radius: var(--shot-card-radius,14px) 0 0 0; }
  .shot-body-grid > .shot-result,.shot-result.has-player,.shot-result.has-player .shot-result-player { border-radius: 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px) 0; }
  .shot-result-player .shot-result-controls { border-radius: 0 0 var(--shot-card-radius,14px) 0; clip-path: inset(0 round 0 0 var(--shot-card-radius,14px) 0); }
  .shot-body-grid > .shot-result { height: 100% !important; min-height: 0 !important; }
  .shot-body-grid > .shot-result > .shot-result-player { height: 100% !important; min-height: 0 !important; aspect-ratio: auto !important; flex: 1 1 auto !important; }
  .shot-body-grid > .shot-result > .shot-result-player > video { height: 100% !important; min-height: 100% !important; object-fit: cover !important; }
}
@media (max-width: 1450px) {
  .shot-body-grid { grid-template-columns: minmax(0,1fr) !important; }
  .shot-content > .storyboard-card-head { border-radius: var(--shot-card-radius,14px) var(--shot-card-radius,14px) 0 0; }
  .shot-body-grid > .shot-result,.shot-result.has-player,.shot-result.has-player .shot-result-player { border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); }
  .shot-result-player .shot-result-controls { border-radius: 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px); clip-path: inset(0 round 0 0 var(--shot-card-radius,14px) var(--shot-card-radius,14px)); }
}

/* Project association: a visible, editable link shared by task creation and asset sync. */
.video-project-link-pill { display: inline-flex; width: fit-content; max-width: 100%; min-height: 25px; box-sizing: border-box; align-items: center; gap: 6px; margin-top: 10px; padding: 0 9px; overflow: hidden; border: 1px solid var(--theme-accent-border); border-radius: 999px; color: var(--theme-accent-text); background: linear-gradient(100deg,var(--theme-bg-surface),var(--theme-bg-surface)); font-size: 11px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.video-project-link-pill svg { width: 13px; flex: 0 0 auto; fill: none; stroke: var(--theme-accent-text); stroke-width: 1.5; stroke-linecap: round; }
.video-project-link-field :deep(.ui-select-trigger) { min-height: 46px; border-color: var(--theme-accent-border); background: linear-gradient(180deg,var(--theme-bg-input),var(--theme-bg-input)); }
.video-project-link-field :deep(.ui-select-badge) { border-color: var(--theme-accent-border); color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.video-project-link-empty { margin: -6px 0 0; padding: 10px 12px; border: 1px solid var(--theme-danger-border); border-radius: 9px; color: var(--theme-danger-text); background: var(--theme-bg-surface); font-size: 12px; line-height: 1.55; }
.video-project-form-error { margin: -6px 0 0; color: var(--theme-danger-text); font-size: 12px; }
.workbench-project-link { display: inline-flex; min-width: 150px; max-width: 230px; height: 28px; align-items: center; gap: 5px; padding-left: 7px; border: 1px solid var(--theme-border-subtle); border-radius: 7px; color: var(--theme-accent-text); background: var(--theme-bg-surface); }
.workbench-project-link > svg { width: 13px; flex: 0 0 auto; fill: none; stroke: currentColor; stroke-width: 1.55; stroke-linecap: round; }
.workbench-project-link :deep(.ui-select) { min-width: 0; }
.workbench-project-link :deep(.ui-select-trigger) { min-height: 26px; padding: 0 7px 0 2px; border: 0; border-radius: 6px; color: var(--theme-accent-text); background: transparent; box-shadow: none; }
.workbench-project-link :deep(.ui-select-value) { font-size: 11px; }
.workbench-project-link :deep(.ui-select-menu) { min-width: 210px; }
.workbench-task-switcher { display: inline-flex; min-width: 150px; max-width: 250px; height: 28px; align-items: center; gap: 5px; padding-left: 7px; border: 1px solid var(--theme-accent-border); border-radius: 7px; color: var(--theme-accent-text); background: var(--theme-bg-elevated); }
.workbench-task-switcher > svg { width: 13px; flex: 0 0 auto; fill: none; stroke: currentColor; stroke-width: 1.55; stroke-linecap: round; }
.workbench-task-switcher :deep(.ui-select) { min-width: 0; }
.workbench-task-switcher :deep(.ui-select-trigger) { min-height: 26px; padding: 0 7px 0 2px; border: 0; border-radius: 6px; color: var(--theme-accent-text); background: transparent; box-shadow: none; }
.workbench-task-switcher :deep(.ui-select-value) { font-size: 11px; }
.workbench-task-switcher :deep(.ui-select-menu) { min-width: 230px; }

@media (max-width: 940px) {
  .video-workbench { height: auto; max-height: none; min-height: calc(100vh - 98px); min-height: calc(100dvh - 98px); padding: 18px; overflow: visible; }
  .video-workbench-head { align-items: flex-start; flex-direction: row; }
  .video-workbench-head .workbench-add-shot { width: auto; }
  .video-workbench-layout { grid-template-columns: 1fr; overflow: visible; }
  .asset-rail { height: auto; max-height: 520px; }
  .asset-rail-scroll { max-height: 320px; }
  .storyboard-column-shell { height: auto; max-height: none; }
  .storyboard-column { height: auto; max-height: none; overflow: visible; }
  .storyboard-anchor-nav { display: none; }
}
@media (max-width: 680px) {
  .video-workbench { padding: 14px; }
  .video-workbench-head { flex-wrap: wrap; padding: 0; border-radius: 0; }
  .video-workbench-title { flex-basis: calc(100% - 76px); }
  .video-workbench-title .workbench-project-name { width: 100%; font-size: 21px; }
  .workbench-meta .video-project-description { order: 5; width: 100%; }
  .workbench-project-link { order: 4; max-width: 100%; }
  .workbench-head-actions { width: auto; flex: 1 0 calc(100% - 48px); margin-left: 48px; }
  .video-workbench-head .workbench-add-shot { width: 100%; margin-left: 0; }
  .video-workbench-layout { gap: 12px; }
}

.creation-ai-backdrop { position: fixed; z-index: 160; inset: 0; display: grid; place-items: center; padding: 22px; background: var(--theme-overlay); backdrop-filter: blur(8px); }
.creation-ai-dialog { display: grid; width: min(860px, calc(100vw - 44px)); max-height: calc(100vh - 44px); overflow: auto; border: 1px solid var(--theme-border-subtle); border-radius: 17px; color: var(--theme-text-primary); background: var(--theme-bg-elevated); box-shadow: 0 35px 100px var(--theme-shadow); scrollbar-width: none; }
.creation-ai-dialog::-webkit-scrollbar { display: none; }
.creation-ai-dialog > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 22px 24px 17px; border-bottom: 1px solid var(--theme-border-subtle); }
.creation-ai-dialog > header span { color: var(--theme-accent-text); font: 700 10px/1 ui-monospace, monospace; letter-spacing: .16em; }
.creation-ai-dialog > header h2 { margin: 7px 0 5px; font-size: 22px; }
.creation-ai-dialog > header p { max-width: 650px; margin: 0; color: var(--theme-text-secondary); font-size: 12px; line-height: 1.6; }
.creation-ai-dialog > header button { width: 34px; height: 34px; border: 0; border-radius: 9px; color: var(--theme-text-secondary); background: var(--theme-bg-surface); font-size: 21px; line-height: 1; cursor: pointer; }
.creation-ai-dialog > header button:hover { color: var(--theme-text-primary); background: var(--theme-bg-card-hover); }
.creation-ai-form { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 20px 24px 12px; }
.creation-ai-form label, .creation-ai-preview { display: grid; gap: 7px; color: var(--theme-text-secondary); font-size: 12px; }
.creation-ai-form label > span, .creation-ai-preview > span { color: var(--theme-text-secondary); }
.creation-ai-form input, .creation-ai-form select, .creation-ai-form textarea, .creation-ai-preview textarea { box-sizing: border-box; width: 100%; border: 1px solid var(--theme-border-subtle); border-radius: 9px; outline: 0; color: var(--theme-text-primary); background: var(--theme-bg-input); font: inherit; font-size: 12.5px; }
.creation-ai-form input, .creation-ai-form select { height: 40px; padding: 0 11px; }
.creation-ai-form textarea { min-height: 170px; padding: 11px; resize: vertical; line-height: 1.6; }
.creation-ai-form input:focus, .creation-ai-form select:focus, .creation-ai-form textarea:focus, .creation-ai-preview textarea:focus { border-color: var(--theme-accent-border); box-shadow: 0 0 0 3px var(--theme-shadow); }
.creation-ai-title-field, .creation-ai-prompt-field { grid-column: 1 / -1; }
.creation-ai-preview { padding: 8px 24px 0; }
.creation-ai-preview textarea { min-height: 220px; padding: 12px; resize: vertical; color: var(--theme-text-primary); background: var(--theme-bg-input); font-family: ui-monospace, Consolas, monospace; font-size: 11px; line-height: 1.55; }
.creation-ai-error { margin: 0; padding: 0 24px 8px; color: var(--theme-danger-text); font-size: 12px; line-height: 1.5; }
.creation-ai-dialog > footer { display: flex; align-items: center; justify-content: flex-end; gap: 9px; padding: 18px 24px 22px; }
.creation-ai-dialog > footer small { flex: 1; color: var(--theme-text-secondary); font-size: 11px; line-height: 1.4; }
.creation-ai-generate-button { display: inline-flex; min-width: 108px; height: 42px; align-items: center; justify-content: center; gap: 7px; padding: 0 15px; border: 1px solid var(--theme-accent-border); border-radius: 10px; color: var(--theme-text-on-accent); background: var(--theme-accent); cursor: pointer; font-size: 13px; }
.creation-ai-generate-button:hover:not(:disabled) { background: var(--theme-accent-hover); color: var(--theme-text-on-accent); }
.creation-ai-generate-button:disabled { cursor: not-allowed; opacity: .45; }
.asset-action-ai { display: grid; width: 100%; grid-template-columns: 31px minmax(0,1fr) 16px; align-items: center; gap: 9px; padding: 10px 11px; border: 1px solid var(--theme-accent-border); border-radius: 10px; color: var(--theme-text-primary); background: linear-gradient(135deg,var(--theme-bg-surface),var(--theme-bg-surface)); text-align: left; cursor: pointer; }
.asset-action-ai:hover { border-color: var(--theme-accent-border); background: linear-gradient(135deg,var(--theme-bg-card-hover),var(--theme-bg-card-hover)); }
.asset-action-ai > span { display: grid; width: 29px; height: 29px; place-items: center; border-radius: 8px; color: var(--theme-accent-text); background: var(--theme-accent-soft); }
.asset-action-ai > span svg { width: 18px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.asset-action-ai > div { display: grid; min-width: 0; gap: 3px; }
.asset-action-ai strong { color: var(--theme-text-primary); font-size: 12px; }
.storyboard-toolbar .shot-submit.is-running { background: linear-gradient(105deg, var(--theme-danger-soft), var(--theme-danger-soft)) !important; color: var(--theme-text-primary) !important; border: 1px solid var(--theme-danger-border) !important; cursor: pointer !important; box-shadow: 0 4px 14px var(--theme-shadow) !important; }
.storyboard-toolbar .shot-submit.is-running:hover { background: linear-gradient(105deg, var(--theme-danger-soft), var(--theme-danger-soft)) !important; transform: translateY(-1px); }
.storyboard-toolbar .shot-submit.is-running .asset-generate-spinner { border-color: var(--theme-border-subtle); border-top-color: var(--theme-border-subtle); }
.shot-result-cancel-btn { margin-top: 10px; padding: 6px 14px; font-size: 12px; font-weight: 600; color: var(--theme-danger-text); background: var(--theme-danger-soft); border: 1px solid var(--theme-danger-border); border-radius: 6px; cursor: pointer; transition: all 0.15s ease; }
.shot-result-cancel-btn:hover { color: var(--theme-text-primary); background: var(--theme-danger-soft); border-color: var(--theme-danger-border); }
.asset-card-generate.is-generating { border-color: var(--theme-danger-border) !important; background: var(--theme-danger-soft) !important; color: var(--theme-danger-text) !important; cursor: pointer !important; }
.asset-card-generate.is-generating:hover { border-color: var(--theme-danger-border) !important; background: var(--theme-danger-soft) !important; color: var(--theme-text-primary) !important; }
.asset-detail-generate-media.is-generating { border-color: var(--theme-danger-border) !important; background: var(--theme-danger-soft) !important; color: var(--theme-danger-text) !important; cursor: pointer !important; }
.asset-detail-generate-media.is-generating:hover { border-color: var(--theme-danger-border) !important; background: var(--theme-danger-soft) !important; color: var(--theme-text-primary) !important; }
.asset-action-generate-all.is-generating { border-color: var(--theme-danger-border) !important; background: var(--theme-danger-soft) !important; color: var(--theme-danger-text) !important; cursor: pointer !important; }
.asset-action-generate-all.is-generating:hover { background: var(--theme-danger-soft) !important; color: var(--theme-text-primary) !important; }

/* Audio category subtabs */
.asset-audio-subtabs {
  display: flex !important;
  gap: 4px !important;
  margin: 0 10px 10px !important;
  padding: 3px !important;
  background: var(--theme-bg-elevated) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  border-radius: 9px !important;
  box-sizing: border-box !important;
}
.asset-audio-subtabs button.asset-audio-subtab,
.asset-audio-subtabs .asset-audio-subtab,
.asset-audio-subtab {
  flex: 1 1 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 5px !important;
  height: 30px !important;
  padding: 0 6px !important;
  border: 1px solid transparent !important;
  border-radius: 6px !important;
  color: var(--theme-text-secondary) !important;
  background: transparent !important;
  font-size: 11px !important;
  font-weight: 500 !important;
  cursor: pointer !important;
  outline: none !important;
  box-shadow: none !important;
  transition: all 0.15s ease !important;
}
.asset-audio-subtabs button.asset-audio-subtab:hover,
.asset-audio-subtab:hover {
  color: var(--theme-text-primary) !important;
  background: var(--theme-bg-card-hover) !important;
}
.asset-audio-subtabs button.asset-audio-subtab.active,
.asset-audio-subtab.active {
  border-color: var(--theme-border-strong) !important;
  color: var(--theme-text-primary) !important;
  background: var(--theme-bg-card-hover) !important;
  font-weight: 600 !important;
  box-shadow: 0 2px 6px var(--theme-shadow) !important;
}
.asset-audio-subtabs button.asset-audio-subtab b,
.asset-audio-subtab b,
.subtab-count {
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  min-width: 15px !important;
  height: 15px !important;
  padding: 0 4px !important;
  border-radius: 99px !important;
  font-size: 9.5px !important;
  font-weight: normal !important;
  line-height: 1 !important;
  color: var(--theme-text-secondary) !important;
  background: var(--theme-bg-elevated) !important;
}
.asset-audio-subtabs button.asset-audio-subtab.active b,
.asset-audio-subtab.active b {
  color: var(--theme-text-primary) !important;
  background: var(--theme-accent-soft) !important;
  font-weight: 700 !important;
}
.asset-audio-subtabs button.voice-subtab.active,
.asset-audio-subtab.voice-subtab.active {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
}
.asset-audio-subtabs button.voice-subtab.active b,
.asset-audio-subtab.voice-subtab.active b {
  color: var(--theme-text-primary) !important;
  background: var(--theme-accent-soft) !important;
}
.asset-audio-subtabs button.sfx-subtab.active,
.asset-audio-subtab.sfx-subtab.active {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
}
.asset-audio-subtabs button.sfx-subtab.active b,
.asset-audio-subtab.sfx-subtab.active b {
  color: var(--theme-text-primary) !important;
  background: var(--theme-accent-soft) !important;
}

/* Audio card placeholder */
.asset-audio-placeholder {
  display: flex !important;
  width: 100% !important;
  height: 100% !important;
  align-items: center !important;
  justify-content: center !important;
  background: var(--theme-bg-elevated) !important;
  color: var(--theme-accent-text) !important;
}
.asset-audio-placeholder.voice {
  color: var(--theme-accent-text) !important;
  background: radial-gradient(circle at center, var(--theme-accent-soft) 0%, var(--theme-accent-soft) 100%) !important;
}
.asset-audio-placeholder.sfx {
  color: var(--theme-accent-text) !important;
  background: radial-gradient(circle at center, var(--theme-accent-soft) 0%, var(--theme-accent-soft) 100%) !important;
}
.asset-audio-placeholder.missing {
  opacity: 0.8 !important;
}
.asset-audio-placeholder svg {
  width: 24px !important;
  height: 24px !important;
  fill: none !important;
  stroke: currentColor !important;
  stroke-width: 1.6 !important;
}

/* Asset Pick Card audio badge & layout */
.asset-pick-title-row {
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  gap: 6px !important;
  width: 100% !important;
  min-width: 0 !important;
  overflow: hidden !important;
}
.asset-pick-title-row strong {
  flex: 1 1 auto !important;
  min-width: 0 !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  white-space: nowrap !important;
  font-size: 13px !important;
  color: var(--theme-text-primary) !important;
  text-align: left !important;
}
.asset-audio-tag {
  flex: 0 0 auto !important;
  display: inline-flex !important;
  align-items: center !important;
  padding: 1px 5px !important;
  border-radius: 4px !important;
  font-size: 10px !important;
  font-weight: 600 !important;
  line-height: 1.3 !important;
  white-space: nowrap !important;
}
.asset-audio-tag.voice {
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
  border: 1px solid var(--theme-accent-border) !important;
}
.asset-audio-tag.sfx {
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
  border: 1px solid var(--theme-accent-border) !important;
}

/* SFX direct import button in card */
.asset-card-generate.sfx-direct-import {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
}
.asset-card-generate.sfx-direct-import:hover {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-text-primary) !important;
  background: var(--theme-accent-soft) !important;
}

/* Asset Detail Audio UI */
.audio-type-selector { display: flex; flex-direction: column; gap: 7px; margin-bottom: 2px; }
.audio-type-selector > span { color: var(--theme-text-secondary); font-size: 14px; }
.audio-type-tabs { display: flex !important; gap: 8px !important; width: 100% !important; box-sizing: border-box !important; }
.audio-type-tabs button,
.audio-type-tabs .audio-type-tab,
.audio-type-tab {
  flex: 1 1 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 8px !important;
  height: 40px !important;
  padding: 0 14px !important;
  border: 1px solid var(--theme-border-subtle) !important;
  border-radius: 9px !important;
  color: var(--theme-accent-text) !important;
  background: var(--theme-bg-elevated) !important;
  cursor: pointer !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  outline: none !important;
  box-shadow: none !important;
  transition: all 0.16s ease !important;
}
.audio-type-tabs button:hover,
.audio-type-tab:hover {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-text-primary) !important;
  background: var(--theme-bg-card-hover) !important;
}
.audio-type-tabs button.active,
.audio-type-tab.active {
  font-weight: 600 !important;
}
.audio-type-tabs button.voice-tab.active,
.audio-type-tabs button:first-child.active,
.audio-type-tab.voice-tab.active {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
  box-shadow: 0 0 16px var(--theme-shadow) !important;
}
.audio-type-tabs button.sfx-tab.active,
.audio-type-tabs button:last-child.active,
.audio-type-tab.sfx-tab.active {
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
  box-shadow: 0 0 16px var(--theme-shadow) !important;
}
.asset-detail-field select { width: 100%; height: 38px; padding: 0 10px; border: 1px solid var(--theme-border-subtle); border-radius: 9px; outline: 0; color: var(--theme-text-primary); background: var(--theme-bg-input); font: 13.5px/1.6 inherit; }
.asset-detail-field select:focus { border-color: var(--theme-border-strong); box-shadow: 0 0 0 3px var(--theme-shadow); }

/* Voice local MP3 upload banner */
.voice-dual-action-card {
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  gap: 14px !important;
  padding: 14px 16px !important;
  border: 1px solid var(--theme-accent-border) !important;
  border-radius: 12px !important;
  background: linear-gradient(135deg, var(--theme-accent-soft) 0%, var(--theme-accent-soft) 100%) !important;
  box-shadow: 0 4px 14px var(--theme-shadow) !important;
}
.voice-dual-action-info {
  display: flex !important;
  flex-direction: column !important;
  gap: 4px !important;
  min-width: 0 !important;
  flex: 1 !important;
}
.voice-dual-action-info strong {
  color: var(--theme-accent-text) !important;
  font-size: 13.5px !important;
  font-weight: 700 !important;
}
.voice-dual-action-info p {
  margin: 0 !important;
  color: var(--theme-accent-text) !important;
  font-size: 11.5px !important;
  line-height: 1.6 !important;
}
.voice-dual-action-info p b {
  color: var(--theme-accent-text) !important;
}
.voice-dual-action-card button.voice-upload-btn,
.voice-upload-btn {
  flex-shrink: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 7px !important;
  height: 38px !important;
  padding: 0 16px !important;
  border: 1px solid var(--theme-accent-border) !important;
  border-radius: 8px !important;
  color: var(--theme-text-primary) !important;
  background: linear-gradient(135deg, var(--theme-accent-soft) 0%, var(--theme-accent-soft) 100%) !important;
  font-size: 12.5px !important;
  font-weight: 700 !important;
  cursor: pointer !important;
  outline: none !important;
  box-shadow: 0 4px 12px var(--theme-shadow) !important;
  transition: all 0.16s ease !important;
}
.voice-dual-action-card button.voice-upload-btn:hover,
.voice-upload-btn:hover {
  background: linear-gradient(135deg, var(--theme-accent-soft) 0%, var(--theme-accent-soft) 100%) !important;
  border-color: var(--theme-accent-border) !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 16px var(--theme-shadow) !important;
}
.voice-dual-action-card button.voice-upload-btn svg,
.voice-upload-btn svg {
  width: 16px !important;
  height: 16px !important;
  fill: none !important;
  stroke: currentColor !important;
  stroke-width: 2 !important;
}

/* SFX local MP3 upload banner */
.sfx-upload-card {
  display: flex !important;
  align-items: center !important;
  justify-content: space-between !important;
  gap: 14px !important;
  padding: 14px 16px !important;
  border: 1px solid var(--theme-accent-border) !important;
  border-radius: 12px !important;
  background: linear-gradient(135deg, var(--theme-accent-soft) 0%, var(--theme-bg-elevated) 100%) !important;
  box-shadow: 0 4px 14px var(--theme-shadow) !important;
}
.sfx-upload-info {
  display: flex !important;
  flex-direction: column !important;
  gap: 4px !important;
  min-width: 0 !important;
  flex: 1 !important;
}
.sfx-upload-info strong {
  color: var(--theme-accent-text) !important;
  font-size: 13.5px !important;
  font-weight: 700 !important;
}
.sfx-upload-info p {
  margin: 0 !important;
  color: var(--theme-accent-text) !important;
  font-size: 11.5px !important;
  line-height: 1.5 !important;
}
.sfx-upload-card button.sfx-upload-btn,
.sfx-upload-btn {
  flex-shrink: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 7px !important;
  height: 38px !important;
  padding: 0 16px !important;
  border: 1px solid var(--theme-accent-border) !important;
  border-radius: 8px !important;
  color: var(--theme-text-primary) !important;
  background: linear-gradient(135deg, var(--theme-accent-soft) 0%, var(--theme-accent-soft) 100%) !important;
  font-size: 12.5px !important;
  font-weight: 700 !important;
  cursor: pointer !important;
  outline: none !important;
  box-shadow: 0 4px 12px var(--theme-shadow) !important;
  transition: all 0.16s ease !important;
}
.sfx-upload-card button.sfx-upload-btn:hover,
.sfx-upload-btn:hover {
  background: linear-gradient(135deg, var(--theme-accent-soft) 0%, var(--theme-accent-soft) 100%) !important;
  border-color: var(--theme-accent-border) !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 16px var(--theme-shadow) !important;
}
.sfx-upload-card button.sfx-upload-btn svg,
.sfx-upload-btn svg {
  width: 16px !important;
  height: 16px !important;
  fill: none !important;
  stroke: currentColor !important;
  stroke-width: 2 !important;
}

/* Attached audio toggle in asset card */
.asset-card-add.audio-toggle-btn.is-attached {
  border-color: var(--theme-success-border) !important;
  color: var(--theme-success-text) !important;
  background: linear-gradient(135deg, var(--theme-success-soft) 0%, var(--theme-accent-soft) 100%) !important;
}
.asset-card-add.audio-toggle-btn.is-attached:hover {
  border-color: var(--theme-danger-border) !important;
  color: var(--theme-text-primary) !important;
  background: linear-gradient(135deg, var(--theme-danger-soft) 0%, var(--theme-danger-soft) 100%) !important;
}

.audio-detail-toggle-btn.is-attached {
  border-color: var(--theme-danger-border) !important;
  color: var(--theme-danger-text) !important;
  background: var(--theme-danger-soft) !important;
}
.audio-detail-toggle-btn.is-attached:hover {
  border-color: var(--theme-danger-border) !important;
  color: var(--theme-text-primary) !important;
  background: var(--theme-danger-soft) !important;
}

/* Storyboard attached audio track bar */
.storyboard-audio-track {
  display: flex !important;
  flex-direction: column !important;
  gap: 6px !important;
  margin-bottom: 10px !important;
}
.storyboard-audio-pill {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
  padding: 8px 12px !important;
  border-radius: 10px !important;
  border: 1px solid var(--theme-accent-border) !important;
  background: linear-gradient(135deg, var(--theme-accent-soft) 0%, var(--theme-accent-soft) 100%) !important;
  box-shadow: 0 3px 10px var(--theme-shadow) !important;
  transition: all 0.16s ease !important;
}
.storyboard-audio-pill.sfx {
  border-color: var(--theme-accent-border) !important;
  background: linear-gradient(135deg, var(--theme-accent-soft) 0%, var(--theme-bg-elevated) 100%) !important;
}
.audio-pill-icon {
  display: grid !important;
  place-items: center !important;
  width: 24px !important;
  height: 24px !important;
  flex-shrink: 0 !important;
  border-radius: 6px !important;
  background: var(--theme-accent-soft) !important;
  color: var(--theme-accent-text) !important;
}
.storyboard-audio-pill.sfx .audio-pill-icon {
  background: var(--theme-accent-soft) !important;
  color: var(--theme-accent-text) !important;
}
.audio-pill-icon svg {
  width: 15px !important;
  height: 15px !important;
  fill: none !important;
  stroke: currentColor !important;
  stroke-width: 2 !important;
}
.audio-pill-label {
  flex: 1 !important;
  min-width: 0 !important;
  display: flex !important;
  align-items: center !important;
  gap: 6px !important;
  color: var(--theme-text-primary) !important;
  font-size: 12.5px !important;
}
.audio-pill-label strong {
  color: var(--theme-accent-text) !important;
  font-weight: 700 !important;
}
.storyboard-audio-pill.sfx .audio-pill-label strong {
  color: var(--theme-accent-text) !important;
}
.audio-pill-name {
  color: var(--theme-text-primary) !important;
  font-weight: 600 !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  white-space: nowrap !important;
}
.audio-pill-label small {
  color: var(--theme-accent-text) !important;
  font-size: 11px !important;
}
.audio-pill-tip {
  flex-shrink: 0 !important;
  font-size: 10.5px !important;
  font-weight: 600 !important;
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
  border: 1px solid var(--theme-accent-border) !important;
  padding: 2px 7px !important;
  border-radius: 4px !important;
}
.storyboard-audio-pill.sfx .audio-pill-tip {
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
  border-color: var(--theme-accent-border) !important;
}
.audio-pill-btn {
  flex-shrink: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  gap: 5px !important;
  height: 28px !important;
  padding: 0 10px !important;
  border-radius: 6px !important;
  border: 1px solid transparent !important;
  font-size: 11.5px !important;
  font-weight: 600 !important;
  cursor: pointer !important;
  outline: none !important;
  transition: all 0.15s ease !important;
}
.audio-pill-btn svg {
  width: 13px !important;
  height: 13px !important;
  fill: none !important;
  stroke: currentColor !important;
  stroke-width: 2 !important;
}
.audio-pill-play {
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
  border-color: var(--theme-accent-border) !important;
}
.audio-pill-play:hover {
  background: var(--theme-accent-soft) !important;
  border-color: var(--theme-accent-border) !important;
  color: var(--theme-text-primary) !important;
}
.audio-pill-play.is-playing {
  color: var(--theme-text-primary) !important;
  background: var(--theme-accent-soft) !important;
  border-color: var(--theme-accent-border) !important;
  box-shadow: 0 0 10px var(--theme-shadow) !important;
}
.audio-pill-mux {
  color: var(--theme-success-text) !important;
  background: var(--theme-success-soft) !important;
  border-color: var(--theme-success-border) !important;
}
.audio-pill-mux:hover {
  background: var(--theme-success-soft) !important;
  border-color: var(--theme-success-border) !important;
  color: var(--theme-text-primary) !important;
}
.audio-pill-remove {
  color: var(--theme-accent-text) !important;
  background: var(--theme-accent-soft) !important;
  border-color: var(--theme-border-subtle) !important;
}
.audio-pill-remove:hover {
  color: var(--theme-text-primary) !important;
  background: var(--theme-danger-soft) !important;
  border-color: var(--theme-danger-border) !important;
}

@media (max-width: 720px) { .creation-ai-backdrop { padding: 12px; }.creation-ai-dialog { width: calc(100vw - 24px); max-height: calc(100vh - 24px); }.creation-ai-dialog > header,.creation-ai-form,.creation-ai-preview { padding-right: 18px; padding-left: 18px; }.creation-ai-form { grid-template-columns: 1fr; }.creation-ai-title-field,.creation-ai-prompt-field { grid-column: auto; }.creation-ai-dialog > footer { flex-wrap: wrap; padding-right: 18px; padding-left: 18px; }.creation-ai-dialog > footer small { flex-basis: 100%; } }
</style>

<style scoped>
/* 单镜工作台：上方横向切换分镜，正文只保留当前分镜。 */
.storyboard-shot-tabs {
  display: flex;
  min-width: 0;
  flex: 0 0 auto;
  gap: 7px;
  padding: 9px 12px;
  overflow-x: auto;
  overflow-y: hidden;
  border-bottom: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-surface);
  scrollbar-width: thin;
  scrollbar-color: var(--theme-scrollbar-thumb) transparent;
}
.storyboard-shot-tabs::-webkit-scrollbar { height: 5px; }
.storyboard-shot-tabs::-webkit-scrollbar-thumb { border-radius: 99px; background: var(--theme-scrollbar-thumb); }
.storyboard-shot-tabs button {
  position: relative;
  display: grid;
  min-width: 128px;
  max-width: 168px;
  height: 38px;
  box-sizing: border-box;
  grid-template-columns: 27px minmax(0,1fr) 7px;
  align-items: center;
  gap: 7px;
  padding: 0 9px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
  color: var(--theme-text-secondary);
  background: var(--theme-bg-elevated);
  cursor: pointer;
  transition: border-color .16s ease,background .16s ease,color .16s ease,box-shadow .16s ease;
}
.storyboard-shot-tabs button:hover {
  border-color: var(--theme-border-strong);
  color: var(--theme-text-primary);
  background: var(--theme-bg-card-hover);
}
.storyboard-shot-tabs button.active {
  border-color: var(--theme-accent-border);
  color: var(--theme-text-primary);
  background: var(--theme-accent-soft);
  box-shadow: inset 0 0 0 1px var(--theme-shadow);
}
.storyboard-shot-tabs button > span {
  display: grid;
  width: 27px;
  height: 23px;
  place-items: center;
  border-radius: 6px;
  color: var(--theme-accent-text);
  background: var(--theme-bg-surface);
  font: 700 11px/1 ui-monospace,SFMono-Regular,Consolas,monospace;
}
.storyboard-shot-tabs button > strong {
  min-width: 0;
  overflow: hidden;
  font-size: 11px;
  font-weight: 650;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.storyboard-shot-tabs button > i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--theme-border-strong);
}
.storyboard-shot-tabs button.complete > i { background: var(--theme-success-text); }
.storyboard-shot-tabs button.error > i { background: var(--theme-danger-text); }
.storyboard-shot-tabs button.running > i {
  background: var(--theme-accent-text);
  box-shadow: 0 0 0 4px var(--theme-accent-soft);
  animation: storyboardTabPulse 1.15s ease-in-out infinite;
}
@keyframes storyboardTabPulse { 50% { opacity: .42; transform: scale(.76); } }

@media (max-width: 720px) {
  .storyboard-shot-tabs { padding: 8px; }
  .storyboard-shot-tabs button { min-width: 58px; max-width: 58px; grid-template-columns: 27px 7px; }
  .storyboard-shot-tabs button > strong { display: none; }
}
</style>

<style scoped>
.dialogue-confirm-btn,.dialogue-review-btn { padding:5px 9px; color:var(--theme-accent-text); border:1px solid var(--theme-accent-border); border-radius:6px; background:var(--theme-bg-surface); font-size:12px; cursor:pointer; }
.dialogue-review-btn:disabled { opacity:.6; cursor:wait; }
.shot-audio-review { display:flex; flex-direction:column; gap:5px; padding:10px 14px; border-top:1px solid var(--theme-accent-border); background:var(--theme-bg-surface); color:var(--theme-text-primary); font-size:12px; overflow-wrap:anywhere; }
.shot-audio-review.needs_review { background:var(--theme-bg-surface); color:var(--theme-accent-text); }
.shot-audio-review.close_text { background:var(--theme-bg-surface); color:var(--theme-accent-text); }
.shot-audio-review.matched_text { background:var(--theme-bg-surface); color:var(--theme-success-text); }
.shot-audio-review small { opacity:.8; }
</style>

<style scoped>
.dialogue-controls { display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:8px 14px; flex:0 0 auto; border-top:1px solid var(--theme-border-subtle); background:var(--theme-bg-surface); }
.dialogue-controls button { width:auto; height:30px; flex:0 0 auto; white-space:nowrap; }
.shot-content:not(.expanded) { height:auto; }
.shot-content:not(.expanded) .storyboard-compose { box-sizing:border-box; flex:0 0 200px; overflow:hidden; }
.shot-audio-review { box-sizing:border-box; flex:0 0 auto; line-height:1.5; position:relative; overflow:hidden; }
.audio-pill-btn:disabled { opacity:.4 !important; cursor:not-allowed !important; }

/* ===== 视频任务工作区全量黄白暖色适配 ===== */
.video-project-workspace-head {
  border: 1px solid var(--theme-border-subtle) !important;
  border-radius: 22px !important;
  background: var(--theme-bg-card) !important;
  box-shadow: 0 10px 30px var(--theme-shadow) !important;
}
.video-project-workspace-head::before {
  opacity: .12 !important;
  background-image: radial-gradient(circle, var(--theme-bg-elevated) 1px, transparent 1px) !important;
}
.video-project-head-copy h1 { color: var(--theme-text-primary) !important; }
.video-project-head-copy p { color: var(--theme-text-secondary) !important; }
.video-project-head-copy > span { color: var(--theme-accent-text) !important; }
.video-project-head-copy b {
  background: var(--theme-bg-elevated) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  color: var(--theme-text-secondary) !important;
}
.video-project-search {
  border: 1px solid var(--theme-border-subtle) !important;
  background: var(--theme-bg-input) !important;
}
.video-project-search input {
  color: var(--theme-text-primary) !important;
  background: transparent !important;
}
.video-project-search svg { stroke: var(--theme-text-secondary) !important; }
.video-project-new-button {
  background: linear-gradient(135deg, var(--theme-accent-soft), var(--theme-accent-soft)) !important;
  border: 1px solid var(--theme-accent-border) !important;
  color: var(--theme-text-primary) !important;
  box-shadow: 0 4px 14px var(--theme-shadow) !important;
}
.video-project-new-button:hover {
  background: linear-gradient(135deg, var(--theme-accent-soft), var(--theme-accent-soft)) !important;
  transform: translateY(-1px) !important;
}

.video-project-library > header h2 { color: var(--theme-text-primary) !important; }
.video-project-library > header span { color: var(--theme-accent-text) !important; }
.video-project-library > header b {
  background: var(--theme-bg-elevated) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  color: var(--theme-text-secondary) !important;
}

.video-project-card {
  border: 1px solid var(--theme-border-subtle) !important;
  border-radius: 16px !important;
  background: var(--theme-bg-card) !important;
  box-shadow: 0 4px 16px var(--theme-shadow) !important;
  color: var(--theme-text-primary) !important;
}
.video-project-card:hover {
  border-color: var(--theme-border-subtle) !important;
  box-shadow: 0 8px 24px var(--theme-shadow) !important;
  transform: translateY(-2px) !important;
}
.video-project-card-body {
  background: var(--theme-bg-card) !important;
}
.video-project-card-body header > span {
  color: var(--theme-accent-text) !important;
}
.video-project-card-body h2 {
  color: var(--theme-text-primary) !important;
}
.video-project-card-body p {
  color: var(--theme-text-secondary) !important;
}
.video-project-link-pill {
  background: var(--theme-bg-elevated) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  color: var(--theme-text-secondary) !important;
}
.video-project-link-pill svg { stroke: var(--theme-text-secondary) !important; }
.stat-pill {
  background: var(--theme-bg-elevated) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  color: var(--theme-text-primary) !important;
}
.stat-pill b { color: var(--theme-text-primary) !important; }
.stat-pill small { color: var(--theme-text-secondary) !important; }
.stat-pill-asset .stat-dot { background: var(--theme-accent-text) !important; }
.stat-pill-shot .stat-dot { background: var(--theme-accent-text) !important; }

.video-project-finished-stat {
  background: var(--theme-bg-elevated) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  color: var(--theme-accent-text) !important;
}
.video-project-finished-stat:hover {
  background: var(--theme-bg-card-hover) !important;
}
.video-project-finished-icon {
  background: var(--theme-accent-soft) !important;
  color: var(--theme-text-primary) !important;
}
.video-project-card footer time {
  color: var(--theme-text-secondary) !important;
}
.video-project-card footer span {
  color: var(--theme-accent-text) !important;
  font-weight: 600 !important;
}

.video-project-create-card {
  border: 1.5px dashed var(--theme-border-subtle) !important;
  border-radius: 16px !important;
  background: var(--theme-bg-elevated) !important;
}
.video-project-create-card:hover {
  border-color: var(--theme-accent-border) !important;
  background: var(--theme-bg-card-hover) !important;
}
.video-project-create-card > button {
  background: transparent !important;
  color: var(--theme-text-primary) !important;
  border: none !important;
}
.video-project-create-card > button > strong {
  color: var(--theme-text-primary) !important;
}
.video-project-create-card > div {
  background: transparent !important;
  color: var(--theme-text-secondary) !important;
  border-top: 1px solid var(--theme-border-subtle) !important;
}
.video-project-new-script, .video-project-new-frame {
  background: var(--theme-bg-card) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  box-shadow: 0 4px 10px var(--theme-shadow) !important;
}
.video-project-new-plus {
  background: var(--theme-accent-soft) !important;
  color: var(--theme-text-primary) !important;
}

.video-project-create {
  background: var(--theme-bg-card) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  color: var(--theme-text-primary) !important;
  box-shadow: 0 24px 64px var(--theme-shadow) !important;
}
.video-project-create input, .video-project-create textarea {
  background: var(--theme-bg-input) !important;
  border: 1px solid var(--theme-border-subtle) !important;
  color: var(--theme-text-primary) !important;
}
.video-project-create input:focus, .video-project-create textarea:focus {
  border-color: var(--theme-accent-border) !important;
  box-shadow: 0 0 0 3px var(--theme-shadow) !important;
}

/* 视频工作台编辑器适配 */
.video-workbench {
  color: var(--theme-text-primary) !important;
}
.video-workbench-head h1 { color: var(--theme-text-primary) !important; }
.storyboard-column, .asset-rail, .video-workbench-layout > * {
  background: var(--theme-bg-card) !important;
  border-color: var(--theme-border-subtle) !important;
  color: var(--theme-text-primary) !important;
}
.storyboard-card, .shot-card {
  background: var(--theme-bg-elevated) !important;
  border-color: var(--theme-border-subtle) !important;
  color: var(--theme-text-primary) !important;
}

/* Each shot has one editing task at a time; video keeps its original framing. */
.video-workbench-layout { grid-template-columns:244px minmax(0,1fr); gap:16px; }
.video-workbench-head h1 { font-size:24px; line-height:1.35; }
.video-workbench-head .workbench-meta { gap:8px; }
.asset-rail-head > div:first-child > span,.storyboard-column-head > div > span { display:none; }
.shot-workspace-tabs { display:flex; flex:0 0 auto; gap:20px; min-height:44px; align-items:stretch; padding:0 16px; border-bottom:1px solid var(--theme-border-subtle); }
.shot-workspace-tabs button { display:flex; align-items:center; gap:6px; padding:0 2px; border:0; border-bottom:2px solid transparent; color:var(--theme-text-secondary); background:transparent; font-size:13px; cursor:pointer; }
.shot-workspace-tabs button.active { color:var(--theme-accent-text); border-bottom-color:var(--theme-accent); font-weight:650; }.shot-workspace-tabs span { padding:1px 5px; border-radius:4px; background:var(--theme-bg-surface); font-size:11px; }
.storyboard-audio-track { display:block !important; margin:12px 16px 0 !important; }.storyboard-audio-track:not([open]) > .storyboard-audio-pill { display:none !important; }
.storyboard-audio-track summary { cursor:pointer; padding:8px 0; font-size:12px; color:var(--theme-text-primary); }.storyboard-audio-track summary span { margin-left:8px; font-size:11px; color:var(--theme-text-secondary); }
.storyboard-audio-pill { flex-wrap:wrap !important; gap:6px !important; margin:5px 0 !important; padding:8px !important; border-color:var(--theme-border-subtle) !important; background:var(--theme-bg-surface) !important; box-shadow:none !important; }
.audio-pill-label { flex:1 1 160px !important; }.audio-pill-label strong { flex-shrink:0; white-space:nowrap; font-size:11px !important; }.audio-pill-tip { font-weight:400 !important; }.audio-pill-label small { white-space:nowrap; }
.dialogue-controls { padding:10px 16px; border:0; border-bottom:1px solid var(--theme-border-subtle); background:var(--theme-bg-elevated); gap:8px; flex-wrap:wrap; }
.shot-content:not(.expanded) .storyboard-compose { height:180px; min-height:130px; max-height:210px; grid-template-columns:minmax(0,1fr) 28px; grid-template-rows:52px minmax(0,1fr); gap:6px; padding:10px 14px; }
.shot-content:not(.expanded) .reference-stack { grid-column:1/-1; height:48px; min-width:90px; max-width:100%; }.shot-content:not(.expanded) .reference-card { width:46px; height:46px; flex-basis:46px; }.shot-content:not(.expanded) .reference-add { width:48px; flex-basis:48px; font-size:10px; }.shot-content:not(.expanded) .reference-stack-add { left:58px; }
.shot-content:not(.expanded) .storyboard-prompt-editor { min-width:0; font-size:12.5px; line-height:1.6; }
.shot-content:not(.expanded) { height:auto; min-width:0; }
.shot-content:not(.expanded) .storyboard-toolbar { position:sticky; bottom:0; z-index:10; background:var(--theme-bg-elevated); box-shadow:0 -2px 10px rgba(0,0,0,0.06); min-height:38px; padding:5px 10px; }
.shot-body-grid > .shot-result.has-player { display:flex !important; flex-direction:column !important; height:auto !important; max-height:100% !important; align-self:stretch !important; padding:10px !important; box-sizing:border-box !important; border-left:1px solid var(--theme-border-subtle); background:var(--theme-bg-surface); }
.shot-body-grid > .shot-result.has-player > .shot-result-player { display:flex !important; flex:1 1 0% !important; width:100% !important; height:100% !important; min-height:200px !important; position:relative !important; border-radius:9px !important; overflow:hidden !important; background:#090b10 !important; align-items:center !important; justify-content:center !important; }
.shot-body-grid > .shot-result.has-player > .shot-result-player > video { width:100% !important; height:100% !important; min-height:0 !important; max-height:100% !important; object-fit:contain !important; background:transparent !important; cursor:pointer; }
.shot-preview-switch { position:absolute; z-index:8; top:10px; left:10px; display:flex; gap:3px; padding:3px; border:1px solid var(--theme-border-subtle); border-radius:8px; background:var(--theme-bg-elevated); }.shot-preview-switch button { padding:5px 8px; border:0; border-radius:5px; color:var(--theme-text-secondary); background:transparent; font-size:11px; cursor:pointer; }.shot-preview-switch button.active { color:var(--theme-accent-text); background:var(--theme-accent-soft); }
@media(min-width:1300px) { .shot-body-grid { grid-template-columns:minmax(0,1.15fr) minmax(0,1fr) !important; } }
@media(max-width:1299px) { .shot-body-grid { grid-template-columns:minmax(0,1fr) !important; }.shot-body-grid > .shot-result.has-player { border-left:0; border-top:1px solid var(--theme-border-subtle); }.shot-body-grid > .shot-result.has-player > .shot-result-player { min-height:280px !important; aspect-ratio:16/9 !important; height:auto !important; }.video-workbench-layout { grid-template-columns:220px minmax(0,1fr); } }
@media(max-width:900px) { .video-workbench-layout { grid-template-columns:minmax(0,1fr); }.shot-workspace-tabs { gap:14px; } }
</style>

<style scoped>
.dialogue-extra{margin:0;padding:12px 20px;border-top:1px solid var(--theme-border-subtle);font-size:12px;color:var(--theme-text-secondary)}.dialogue-extra>summary{cursor:pointer}.dialogue-extra .dialogue-controls{padding:12px 0 0;border:0}
.narrative-transition{margin:8px 14px;padding:10px 12px;min-width:0;flex:0 0 auto;border:1px solid var(--theme-border-subtle);border-radius:10px;background:var(--theme-bg-elevated);font-size:13px;overflow-wrap:anywhere}
.narrative-transition summary{cursor:pointer;color:var(--theme-text-primary);font-weight:600}
.narrative-transition small{display:block;margin-top:6px;color:var(--theme-text-secondary);font-weight:400;line-height:1.6}
.narrative-transition summary small{display:inline;margin-left:8px}
.transition-fields{display:grid;grid-template-columns:minmax(0,1fr);gap:10px;padding-top:12px}
.transition-fields label{display:grid;gap:6px;min-width:0}
.transition-fields textarea{box-sizing:border-box;width:100%;min-width:0;padding:9px;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-elevated);color:var(--theme-text-primary);font:inherit;line-height:1.6;resize:vertical}

/* ===== 专属上一镜尾帧衔接卡 (Continuity Slot Warm-White Styling) ===== */
.shot-continuity-slot {
  margin: 10px 0 14px;
  padding: 12px 14px;
  border: 1px solid #e2dcd1;
  border-left: 3.5px solid #c87a2b;
  border-radius: 12px;
  background: #fffdf9;
  box-shadow: 0 2px 10px rgba(60, 48, 30, 0.04);
  transition: border-color .18s, background .18s;
}
.shot-continuity-slot.is-disabled {
  border-left-color: #dcd5c8;
  background: #faf7f2;
  opacity: .78;
}
.continuity-bar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.continuity-tag-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.continuity-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 6px;
  background: #fdf4e7;
  border: 1px solid rgba(200, 122, 43, 0.3);
  color: #96520e;
  font-size: 11px;
  font-weight: 700;
}
.continuity-tag-group strong {
  color: #2b2520;
  font-size: 13px;
  font-weight: 700;
}
.continuity-scope-pill {
  font-size: 11px;
  color: #786f63;
  padding: 1px 7px;
  border-radius: 99px;
  background: #f5f0e6;
  border: 1px solid #e5dfd3;
}
.continuity-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}
.continuity-toggle-btn input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}
.continuity-toggle-track {
  position: relative;
  width: 36px;
  height: 20px;
  border-radius: 99px;
  background: #dcd5c8;
  transition: background .18s;
}
.continuity-toggle-track::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,0.15);
  transition: transform .18s;
}
.continuity-toggle-btn input:checked + .continuity-toggle-track {
  background: #c87a2b;
}
.continuity-toggle-btn input:checked + .continuity-toggle-track::after {
  transform: translateX(16px);
}
.continuity-toggle-btn em {
  font-style: normal;
  font-size: 12px;
  font-weight: 600;
  color: #4a4238;
}

.continuity-bar-content {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #efeae0;
}
.continuity-mode-switch {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}
.continuity-mode-switch button {
  display: grid;
  min-width: 0;
  gap: 2px;
  padding: 8px 10px;
  border: 1px solid #ded7cc;
  border-radius: 8px;
  color: #665f55;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
}
.continuity-mode-switch button.active {
  border-color: #bf6a16;
  color: #6f3507;
  background: #fff7e8;
  box-shadow: inset 3px 0 0 #d97706;
}
.continuity-mode-switch strong {
  font-size: 12px;
}
.continuity-mode-switch small {
  overflow: hidden;
  font-size: 10px;
  color: #8a8176;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.continuity-frame-card {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr);
  column-gap: 14px;
  row-gap: 5px;
  align-items: start;
  container-type: inline-size;
}
.continuity-thumb-box {
  position: relative;
  grid-column: 1;
  grid-row: 1 / span 3;
  width: 120px;
  height: 68px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid #dcd5c8;
  background: #f5f0e6;
  cursor: pointer;
}
.continuity-thumb-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.continuity-zoom-overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(43, 37, 32, 0.65);
  color: #fff;
  font-size: 11px;
  opacity: 0;
  transition: opacity .15s;
}
.continuity-thumb-box:hover .continuity-zoom-overlay {
  opacity: 1;
}

.continuity-info-box {
  display: contents;
}
.continuity-info-head {
  display: flex;
  grid-column: 2;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.continuity-origin-label {
  font-size: 12px;
  font-weight: 700;
  color: #2b2520;
}
.continuity-pill-synced {
  font-size: 11px;
  color: #2b7a4b;
  background: #ebf7f0;
  border: 1px solid #c2e8d0;
  padding: 1px 6px;
  border-radius: 4px;
}
.continuity-pill-warning {
  font-size: 11px;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fde68a;
  padding: 1px 6px;
  border-radius: 4px;
}
.continuity-info-desc {
  grid-column: 2;
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #6e6559;
}
.continuity-info-desc strong {
  color: #8a4805;
}
.continuity-review-alert {
  display: flex;
  grid-column: 2;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 8px 0 2px;
  padding: 10px 12px;
  border: 1px solid #dcd5c8;
  border-radius: 10px;
  background: #faf7f2;
  color: #6e6559;
  font-size: 12px;
}
.continuity-review-alert > div {
  display: grid;
  gap: 2px;
  flex: 1 1 280px;
}
.continuity-review-alert strong {
  color: #2b2520;
}
.continuity-review-alert.is-failed {
  border-color: #efb5ba;
  background: #fff4f5;
  color: #8e3942;
}
.continuity-review-alert.is-failed strong {
  color: #9f2633;
}
.continuity-review-alert.is-passed {
  border-color: #b9dfca;
  background: #f2fbf6;
  color: #28784e;
}
.continuity-review-alert button {
  border: 1px solid #dcd5c8;
  border-radius: 8px;
  padding: 7px 10px;
  background: #fff;
  color: #2b2520;
  cursor: pointer;
}
.continuity-review-alert button.is-primary {
  border-color: #ca5a65;
  background: #b93846;
  color: #fff;
}
.continuity-btn-row {
  display: flex;
  grid-column: 2;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 3px;
}
.continuity-btn-refresh {
  padding: 4px 10px;
  border: 1px solid #dcd5c8;
  border-radius: 6px;
  background: #f7f3eb;
  color: #4a4238;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background .12s, color .12s;
}
.continuity-btn-refresh:hover:not(:disabled) {
  background: #eae4d7;
  color: #2b2520;
}
.continuity-btn-clear {
  padding: 4px 8px;
  border: none;
  background: transparent;
  color: #8c8275;
  font-size: 11px;
  cursor: pointer;
}
.continuity-btn-clear:hover {
  color: #b91c1c;
}

.continuity-pending-box {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #faf7f2;
  border: 1px dashed #dcd5c8;
  font-size: 12px;
  color: #786f63;
}
.continuity-pending-box svg {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  fill: none;
  stroke: #8c8275;
  stroke-width: 1.8;
}
.continuity-btn-fetch {
  margin-left: auto;
  padding: 3px 9px;
  border: 1px solid #c87a2b;
  border-radius: 5px;
  background: #fdf4e7;
  color: #96520e;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.continuity-btn-fetch:hover {
  background: #faecd7;
}


/* 全局工作区浮动提示与按钮反馈 */
.workspace-floating-toast {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 99999;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 20px;
  border-radius: 999px;
  background: #ffffff;
  color: #1e293b;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.12), 0 8px 10px -6px rgba(0, 0, 0, 0.08);
  border: 1px solid #e2e8f0;
  pointer-events: none;
  animation: toast-slide-down 0.22s ease-out;
}
.workspace-floating-toast.success {
  background: #f0fdf4;
  border-color: #86efac;
  color: #166534;
}
.workspace-floating-toast.error {
  background: #fef2f2;
  border-color: #fca5a5;
  color: #991b1b;
}
.workspace-floating-toast.warning {
  background: #fefce8;
  border-color: #fde047;
  color: #854d0e;
}
.workspace-floating-toast.info {
  background: #f8fafc;
  border-color: #cbd5e1;
  color: #334155;
}
.workspace-toast-fade-enter-active,
.workspace-toast-fade-leave-active {
  transition: all 0.22s ease;
}
.workspace-toast-fade-enter-from,
.workspace-toast-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -12px);
}
@keyframes toast-slide-down {
  from {
    opacity: 0;
    transform: translate(-50%, -12px);
  }
  to {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}
.btn-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(150, 82, 14, 0.25);
  border-top-color: #96520e;
  border-radius: 50%;
  animation: btn-spin 0.8s linear infinite;
  vertical-align: middle;
  margin-right: 5px;
}
@keyframes btn-spin {
  to { transform: rotate(360deg); }
}
.continuity-btn-fetch:disabled,
.continuity-btn-refresh:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}


/* 3×3 变焦九宫格与动作截断抽屉 */
.continuity-btn-tool {
  padding: 3px 10px;
  border: 1px solid #d4c5b3;
  border-radius: 5px;
  background: #fbf8f3;
  color: #78350f;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.continuity-btn-tool:hover {
  background: #f5eedf;
  border-color: #b45309;
}
.continuity-btn-tool.active {
  background: #fde68a;
  border-color: #d97706;
  color: #78350f;
}
.continuity-matrix-drawer,
.continuity-scrubber-drawer {
  grid-column: 1 / -1;
  min-width: 0;
  margin-top: 10px;
  padding: 12px;
  border-radius: 8px;
  background: #faf6f0;
  border: 1px dashed #d97706;
  animation: toast-slide-down 0.2s ease-out;
}
.matrix-drawer-head,
.scrubber-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.matrix-drawer-title {
  flex: 1 1 260px;
  min-width: 0;
}
.matrix-drawer-title strong,
.scrubber-head strong {
  display: block;
  font-size: 13px;
  color: #78350f;
  font-weight: 700;
}
.matrix-drawer-title span,
.scrubber-head span {
  font-size: 11px;
  color: #8c7258;
}
.matrix-btn-gen {
  padding: 6px 14px;
  border: 1px solid #b45309;
  border-radius: 6px;
  background: #b45309;
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(180, 83, 9, 0.2);
}
.matrix-btn-gen:hover {
  background: #92400e;
}
.matrix-btn-preview,
.matrix-btn-regen {
  padding: 4px 10px;
  border: 1px solid #d4c5b3;
  border-radius: 5px;
  background: #ffffff;
  color: #78350f;
  font-size: 11px;
  cursor: pointer;
}
.matrix-drawer-actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.matrix-btn-split {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid #b45309;
  border-radius: 5px;
  color: #ffffff;
  background: #b45309;
  font-size: 11px;
  font-weight: 650;
  cursor: pointer;
}
.matrix-btn-split:disabled,
.matrix-btn-regen:disabled { opacity: .55; cursor: wait; }
.matrix-drawer-body {
  display: grid;
  grid-template-columns: minmax(140px, 170px) minmax(0, 1fr);
  gap: 14px;
  align-items: flex-start;
}
.matrix-preview-card {
  position: relative;
  width: 100%;
  aspect-ratio: 1 / 1;
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid #d4c5b3;
  flex-shrink: 0;
  cursor: pointer;
}
.matrix-preview-card img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.matrix-preview-tip {
  position: absolute;
  bottom: 0;
  inset-inline: 0;
  padding: 2px 0;
  background: rgba(0, 0, 0, 0.65);
  color: #ffffff;
  font-size: 10px;
  text-align: center;
}
.matrix-grid-picker {
  min-width: 0;
}
.matrix-grid-tip {
  font-size: 11px;
  color: #78350f;
  font-weight: 600;
  margin-bottom: 6px;
}
.matrix-cells-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}
.matrix-cell-btn {
  position: relative;
  display: grid;
  min-width: 0;
  padding: 4px;
  border: 1px solid #e7ded3;
  border-radius: 6px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
  overflow: hidden;
}
.matrix-cell-btn:hover {
  border-color: #b45309;
  background: #fefce8;
  transform: translateY(-1px);
}
.matrix-cell-btn > img,
.matrix-cell-placeholder {
  display: grid;
  width: 100%;
  aspect-ratio: 16 / 9;
  place-items: center;
  overflow: hidden;
  border-radius: 4px;
  background: #171717;
  object-fit: cover;
}
.matrix-cell-placeholder b {
  color: #d6c6ad;
  font: 700 12px/1 ui-monospace,SFMono-Regular,Consolas,monospace;
}
.matrix-cell-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
  padding: 5px 3px 2px;
}
.matrix-cell-btn strong {
  overflow: hidden;
  font-size: 11px;
  color: #1e293b;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.matrix-cell-btn small {
  overflow: hidden;
  font-size: 10px;
  color: #64748b;
  margin-top: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@container (max-width: 650px) {
  .matrix-preview-card {
    display: none;
  }

  .matrix-drawer-body {
    grid-template-columns: minmax(0, 1fr);
  }

  .matrix-grid-tip {
    line-height: 1.45;
  }
}

@container (max-width: 440px) {
  .matrix-cells-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.matrix-cell-btn.is-recommended {
  border: 1.5px solid #d97706;
  background: #fffbeb;
}
.matrix-cell-btn.is-selected {
  border: 1.5px solid #16a34a;
  background: #f0fdf4;
}
.cell-rec-tag {
  position: absolute;
  z-index: 2;
  top: 2px;
  right: 4px;
  padding: 1px 4px;
  border-radius: 3px;
  background: #d97706;
  color: #ffffff;
  font-size: 9px;
  font-weight: 700;
}
/* 时间轴截断控制 */
.scrubber-controls {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.scrubber-slider-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.scrubber-slider-row label {
  font-size: 12px;
  color: #78350f;
  white-space: nowrap;
}
.scrubber-slider-row input[type="range"] {
  flex: 1;
  accent-color: #b45309;
}
.scrubber-presets {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.scrubber-presets button {
  padding: 4px 8px;
  border: 1px solid #d4c5b3;
  border-radius: 4px;
  background: #ffffff;
  color: #475569;
  font-size: 11px;
  cursor: pointer;
}
.scrubber-presets button.active {
  border-color: #b45309;
  background: #fef3c7;
  color: #78350f;
  font-weight: 600;
}
.btn-custom-scrub {
  background: #b45309 !important;
  color: #ffffff !important;
  border-color: #b45309 !important;
  font-weight: 600;
}
.btn-inject-relay {
  background: #fefce8 !important;
  color: #854d0e !important;
  border-color: #fde047 !important;
  font-weight: 600;
}

/* 最终覆盖：播放器空白区保持纯黑，禁用旧版装饰网格。 */
.shot-result-player,
.shot-body-grid > .shot-result.has-player > .shot-result-player,
.shot-result-player video,
.shot-body-grid > .shot-result.has-player > .shot-result-player > video {
  background: #000 !important;
}
.shot-result-player::before,
.shot-result-player::after {
  display: none !important;
  content: none !important;
  background: none !important;
}


.scene-transition-hint {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 8px 0 12px;
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.28);
  font-size: 12px;
  color: var(--theme-text-primary);
}
.scene-transition-title {
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.5;
}
.scene-transition-title strong {
  color: var(--theme-accent);
}
.scene-transition-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}
.scene-transition-actions button {
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}
.btn-both-motion {
  background: rgba(14, 165, 233, 0.15) !important;
  color: #0284c7 !important;
  border-color: rgba(14, 165, 233, 0.4) !important;
}
.btn-both-motion:hover {
  background: #0284c7 !important;
  color: #fff !important;
}
.btn-both-dissolve {
  background: rgba(16, 185, 129, 0.15) !important;
  color: #059669 !important;
  border-color: rgba(16, 185, 129, 0.4) !important;
}
.btn-both-dissolve:hover {
  background: #059669 !important;
  color: #fff !important;
}
.btn-both-cut {
  background: rgba(148, 163, 184, 0.15) !important;
  color: var(--theme-text-primary) !important;
  border-color: rgba(148, 163, 184, 0.35) !important;
}
.btn-both-cut:hover {
  background: rgba(148, 163, 184, 0.3) !important;
}
.continuity-accept-transition-btn {
  padding: 6px 12px;
  background: #059669 !important;
  color: #fff !important;
  border: none !important;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s ease;
}
.continuity-accept-transition-btn:hover {
  opacity: 0.9;
}
.scene-anchor-hint { display: flex; align-items: center; gap: 8px; margin: 8px 0 0; padding: 8px 12px; border-radius: 8px; background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.28); font-size: 12px; color: var(--theme-text-primary); }
.scene-anchor-hint strong { color: #10b981; }
.gaze-handoff-hint { display: flex; align-items: center; gap: 8px; margin: 8px 0 0; padding: 8px 12px; border-radius: 8px; background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.3); font-size: 12px; color: var(--theme-text-primary); }
.gaze-handoff-hint strong { color: #3b82f6; }
.gaze-handoff-hint.is-off { background: rgba(148, 163, 184, 0.1); border-color: rgba(148, 163, 184, 0.28); }
.gaze-handoff-hint.is-off strong { color: #94a3b8; }
.gaze-handoff-hint span { flex: 1; line-height: 1.5; }
.gaze-handoff-hint button { flex-shrink: 0; padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(59, 130, 246, 0.4); background: rgba(59, 130, 246, 0.12); color: var(--theme-text-primary); font-size: 12px; cursor: pointer; }
.gaze-handoff-hint button:hover { background: rgba(59, 130, 246, 0.22); }
.continuity-review-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.continuity-switch-cut-btn { padding: 6px 12px; background: var(--theme-accent-soft); color: var(--theme-accent-text); border: 1px solid var(--theme-accent-border); border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s ease; }
.continuity-switch-cut-btn:hover { background: var(--theme-accent); color: #fff; }

.continuity-occlusion-drawer {
  grid-column: 1 / -1;
  min-width: 0;
  margin-top: 10px;
  padding: 14px;
  border-radius: 8px;
  background: #fbf7f0;
  border: 1px dashed #d97706;
  animation: toast-slide-down 0.2s ease-out;
}
.occlusion-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.occlusion-drawer-title strong {
  display: block;
  font-size: 13px;
  color: #78350f;
  font-weight: 700;
}
.occlusion-drawer-title span {
  font-size: 11px;
  color: #8c7258;
}
.occlusion-btn-apply-both {
  padding: 6px 14px;
  border: 1px solid #b45309;
  border-radius: 6px;
  background: #b45309;
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(180, 83, 9, 0.2);
  transition: background 0.15s ease;
}
.occlusion-btn-apply-both:hover {
  background: #92400e;
}
.occlusion-config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.occlusion-config-col label {
  display: block;
  font-size: 12px;
  color: #78350f;
  margin-bottom: 6px;
}
.occlusion-pills-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.occlusion-pill-btn {
  padding: 4px 9px;
  border: 1px solid #d4c5b3;
  border-radius: 6px;
  background: #ffffff;
  color: #574637;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.occlusion-pill-btn:hover {
  border-color: #b45309;
  color: #b45309;
}
.occlusion-pill-btn.active {
  border-color: #b45309;
  background: #fef3c7;
  color: #92400e;
  font-weight: 600;
  box-shadow: 0 1px 2px rgba(180, 83, 9, 0.15);
}
.occlusion-preview-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 12px;
}
@media (max-width: 800px) {
  .occlusion-preview-cards {
    grid-template-columns: 1fr;
  }
}
.occlusion-step-card {
  padding: 10px;
  border-radius: 6px;
  background: #ffffff;
  border: 1px solid #ebdccb;
}
.occlusion-step-card header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.occlusion-step-card header strong {
  font-size: 11px;
  color: #78350f;
}
.btn-step-inject {
  padding: 3px 8px;
  border: 1px solid #d4c5b3;
  border-radius: 4px;
  background: #fdfaf6;
  color: #78350f;
  font-size: 10px;
  cursor: pointer;
  font-weight: 600;
}
.btn-step-inject:hover {
  border-color: #b45309;
  background: #fef3c7;
}
.btn-step-inject.is-primary {
  background: #d97706;
  color: #ffffff;
  border-color: #b45309;
}
.btn-step-inject.is-primary:hover {
  background: #b45309;
}
.occlusion-step-formula {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: #4b3e34;
  background: #fcf9f5;
  padding: 6px 8px;
  border-radius: 4px;
  border-left: 3px solid #d97706;
}
.occlusion-checklist-box {
  padding: 8px 12px;
  border-radius: 6px;
  background: #f4ede2;
  border: 1px solid #e2d3be;
}
.checklist-title strong {
  font-size: 11px;
  color: #78350f;
}
.checklist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 4px 12px;
  margin-top: 6px;
  font-size: 10px;
  color: #63503f;
}

</style>
