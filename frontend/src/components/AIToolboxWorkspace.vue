<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  token: { type: String, default: '' },
  storageBase: { type: String, default: '' },
  apiBase: { type: String, default: '' },
})

const emit = defineEmits(['back', 'use-prompt', 'use-media'])

// 当前选中的工具 Tab: 'rea_video' | 'zimu' | 'breeze' | 'shuiyin' | 'waifu2x'
const activeTab = ref('rea_video')

// 5 大工具状态
const toolsStatus = ref({
  rea_video: { available: true, name: '爆款视频逆向拆解' },
  zimu: { available: true, name: 'AI 智能字幕工坊' },
  breeze: { available: true, name: 'Breeze 本地语音' },
  shuiyin: { available: true, name: '智能视频去水印' },
  waifu2x: { available: true, name: '画质超分与 60fps 补帧' },
})

const loadingStatus = ref(false)
const globalMessage = ref('')
const globalError = ref('')

// === Tab 1: rea-video 逆向拆解 ===
const reaVideoPath = ref('')
const reaVideoName = ref('')
const reaRunning = ref(false)
const reaProgress = ref(0)
const reaStatusText = ref('')
const reaReport = ref(null)
const reaOutputDir = ref('')
const reaJobId = ref('')
let reaPollTimer = null

// === Tab 2: AutoSubs 字幕生成 ===
const zimuVideoPath = ref('')
const zimuVideoName = ref('')
const zimuText = ref('')
const zimuRunning = ref(false)
const zimuSrtLines = ref([])
const zimuApiPrompt = ref('围绕视频主题与发音规律执行智能纠错，纠正同音字与生僻字')

// === Tab 3: Breeze 本地语音 ===
const breezeRunning = ref(false)
const breezeStarting = ref(false)
const breezeText = ref('大家好，这是通过 Breeze 本地语音大模型生成的专业旁白配音。')
const breezeVoiceDesc = ref('温柔自然的年轻女声，普通话标准清晰，语速适中，充满治愈感')
const breezeAudioUrl = ref('')
const breezeAudioPath = ref('')

// === Tab 4: 视频去水印 ===
const shuiyinVideoPath = ref('')
const shuiyinVideoName = ref('')
const shuiyinBoxes = ref([
  { id: 1, name: '左上角台标', x: 20, y: 20, w: 180, h: 70 },
  { id: 2, name: '右下角作者名', x: 500, y: 1180, w: 200, h: 80 },
])
const shuiyinRunning = ref(false)
const shuiyinProgress = ref(0)
const shuiyinStatusText = ref('')
const shuiyinResultUrl = ref('')
const shuiyinResultPath = ref('')
const shuiyinOutputDir = ref('')
let shuiyinPollTimer = null

// === Tab 5: Waifu2x / RIFE 补帧 ===
const fpsVideoPath = ref('')
const fpsVideoName = ref('')
const fpsTarget = ref(60)
const fpsRunning = ref(false)
const fpsProgress = ref(0)
const fpsStatusText = ref('')
const fpsResultUrl = ref('')
const fpsResultPath = ref('')
const fpsOutputDir = ref('')
let fpsPollTimer = null

onMounted(async () => {
  await fetchToolsStatus()
})

onBeforeUnmount(() => {
  if (reaPollTimer) clearInterval(reaPollTimer)
  if (shuiyinPollTimer) clearInterval(shuiyinPollTimer)
  if (fpsPollTimer) clearInterval(fpsPollTimer)
})

async function fetchToolsStatus() {
  loadingStatus.value = true
  try {
    if (window.pywebview?.api?.get_external_tools_status) {
      const res = await window.pywebview.api.get_external_tools_status()
      if (res && typeof res === 'object') {
        toolsStatus.value = res
      }
    }
  } catch (err) {
    console.warn('获取外部工具状态失败:', err)
  } finally {
    loadingStatus.value = false
  }
}

function showMsg(msg, isErr = false) {
  if (isErr) {
    globalError.value = msg
    setTimeout(() => { globalError.value = '' }, 5000)
  } else {
    globalMessage.value = msg
    setTimeout(() => { globalMessage.value = '' }, 4000)
  }
}

// 调起外部独立客户端
async function launchNativeApp(toolId) {
  try {
    if (!window.pywebview?.api?.launch_external_tool) {
      showMsg('请在桌面客户端中启动外部应用', true)
      return
    }
    const res = await window.pywebview.api.launch_external_tool(toolId)
    if (res?.success) {
      showMsg(res.message || '已成功调起独立程序窗口')
    } else {
      showMsg(res?.message || '启动失败', true)
    }
  } catch (err) {
    showMsg(`调起异常: ${err.message || err}`, true)
  }
}

// 文件选择辅助
// 文件选择辅助（彻底免疫 Vue3 模板 Ref 自动解包 Bug，支持类型标识符、Ref对象与回退机制）
async function pickVideo(target, nameTarget) {
  try {
    if (!window.pywebview?.api?.select_local_video_file) {
      showMsg('请在桌面客户端中使用文件选择', true)
      return
    }
    const file = await window.pywebview.api.select_local_video_file()
    if (!file?.path) return

    const filePath = String(file.path || '').trim().replace(/^["']|["']$/g, '')
    const fileName = file.name || filePath.split(/[/\\]/).pop()

    const type = typeof target === 'string' ? target : ''
    if (type === 'rea' || type === 'rea_video' || type === reaVideoPath.value) {
      reaVideoPath.value = filePath
      reaVideoName.value = fileName
    } else if (type === 'zimu' || type === zimuVideoPath.value) {
      zimuVideoPath.value = filePath
      zimuVideoName.value = fileName
    } else if (type === 'shuiyin' || type === shuiyinVideoPath.value) {
      shuiyinVideoPath.value = filePath
      shuiyinVideoName.value = fileName
    } else if (type === 'fps' || type === 'waifu2x' || type === fpsVideoPath.value) {
      fpsVideoPath.value = filePath
      fpsVideoName.value = fileName
    } else if (target && typeof target === 'object' && 'value' in target) {
      target.value = filePath
      if (nameTarget && typeof nameTarget === 'object' && 'value' in nameTarget) {
        nameTarget.value = fileName
      }
    } else {
      if (activeTab.value === 'rea_video') {
        reaVideoPath.value = filePath
        reaVideoName.value = fileName
      } else if (activeTab.value === 'zimu') {
        zimuVideoPath.value = filePath
        zimuVideoName.value = fileName
      } else if (activeTab.value === 'shuiyin') {
        shuiyinVideoPath.value = filePath
        shuiyinVideoName.value = fileName
      } else if (activeTab.value === 'waifu2x') {
        fpsVideoPath.value = filePath
        fpsVideoName.value = fileName
      }
    }

    showMsg(`已载入视频: ${fileName}`)
  } catch (err) {
    showMsg(`选择文件失败: ${err.message || err}`, true)
  }
}

// 拖拽文件辅助支持
function handleFileDrop(e, target) {
  e.preventDefault()
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    const file = files[0]
    const filePath = String(file.path || file.name || '').trim().replace(/^["']|["']$/g, '')
    const fileName = file.name || filePath.split(/[/\\]/).pop()
    if (target === 'rea' || target === 'rea_video') {
      reaVideoPath.value = filePath
      reaVideoName.value = fileName
    } else if (target === 'zimu') {
      zimuVideoPath.value = filePath
      zimuVideoName.value = fileName
    } else if (target === 'shuiyin') {
      shuiyinVideoPath.value = filePath
      shuiyinVideoName.value = fileName
    } else if (target === 'fps' || target === 'waifu2x') {
      fpsVideoPath.value = filePath
      fpsVideoName.value = fileName
    }
    showMsg(`已拖拽载入视频: ${fileName}`)
  }
}

// 在操作系统文件管理器中打开生成文件
async function revealFile(filePath) {
  if (!filePath) return
  try {
    if (window.pywebview?.api?.reveal_path) {
      await window.pywebview.api.reveal_path(filePath)
    } else {
      showMsg('当前客户端环境未开放 reveal_path 接口', true)
    }
  } catch (err) {
    showMsg(`定位文件失败: ${err.message || err}`, true)
  }
}

// ==================== Tab 1: rea-video 逆向拆解 ====================

async function pickOutputDir(type = 'rea') {
  try {
    const api = window.pywebview?.api
    const selectDirFn = api?.select_tree_directory 
      || api?.select_storage_directory 
      || api?.select_local_directory

    let dir = null
    if (selectDirFn) {
      dir = await selectDirFn()
    } else {
      // 备用：若为纯浏览器模式或无客户端 API，支持输入或提示
      const userPrompt = window.prompt('请输入或粘贴自定义产物输出文件夹绝对路径：', reaOutputDir.value || '')
      if (userPrompt) dir = userPrompt.trim()
    }

    if (dir) {
      const cleanDir = String(dir).trim().replace(/^["']|["']$/g, '')
      if (type === 'rea') reaOutputDir.value = cleanDir
      else if (type === 'shuiyin') shuiyinOutputDir.value = cleanDir
      else if (type === 'fps') fpsOutputDir.value = cleanDir
      showMsg('已成功设置产物输出目录')
    }
  } catch (err) {
    showMsg('选择输出目录失败: ' + (err.message || err), true)
  }
}

async function openFolder(pathStr) {
  try {
    const target = pathStr || reaReport.value?.raw_report_path || reaOutputDir.value || reaVideoPath.value
    if (!target) {
      showMsg('暂无可打开的目录路径', true)
      return
    }
    const cleanTarget = String(target).trim().replace(/^["']|["']$/g, '')
    const api = window.pywebview?.api
    if (api?.reveal_path) {
      await api.reveal_path(cleanTarget)
    } else if (api?.open_path) {
      await api.open_path(cleanTarget)
    } else if (api?.reveal_in_explorer) {
      await api.reveal_in_explorer(cleanTarget)
    } else {
      showMsg('已记录目录路径: ' + cleanTarget)
    }
  } catch (err) {
    showMsg('打开目录失败: ' + (err.message || err), true)
  }
}

async function cancelReaDecompose() {
  if (reaPollTimer) clearInterval(reaPollTimer)
  reaRunning.value = false
  reaStatusText.value = '已终止拆解'
  try {
    if (window.pywebview?.api?.cancel_toolbox_job) {
      await window.pywebview.api.cancel_toolbox_job(reaJobId.value || '')
    }
  } catch (err) {
    console.warn(err)
  }
  showMsg('已成功终止拆解任务')
}

async function startReaDecompose() {
  const cleanPath = String(reaVideoPath.value || '').trim().replace(/^["']|["']$/g, '')
  if (!cleanPath) {
    showMsg('请先选择要拆解的爆款视频文件', true)
    return
  }
  reaRunning.value = true
  reaProgress.value = 5
  reaStatusText.value = '正在解析视频轨道与镜头切分…'
  reaReport.value = null

  try {
    reaJobId.value = ''
    const res = await window.pywebview.api.run_rea_video_decompose(cleanPath, reaOutputDir.value || '')
    if (!res?.success || !res?.job_id) {
      throw new Error(res?.message || '提交拆解任务失败')
    }
    const jobId = res.job_id
    reaJobId.value = jobId

    reaPollTimer = setInterval(async () => {
      try {
        const job = await window.pywebview.api.get_toolbox_job_status(jobId)
        if (job) {
          reaProgress.value = job.progress || 0
          reaStatusText.value = job.message || '正在分析中…'
          if (job.status === 'succeeded') {
            clearInterval(reaPollTimer)
            reaRunning.value = false
            reaReport.value = job.result
            showMsg('🎉 视频逆向拆解完成！已提取分镜结构与提示词')
          } else if (job.status === 'failed') {
            clearInterval(reaPollTimer)
            reaRunning.value = false
            showMsg(job.message || '拆解处理失败', true)
          }
        }
      } catch (err) {
        console.warn('轮询 rea-video 异常:', err)
      }
    }, 1000)
  } catch (err) {
    reaRunning.value = false
    showMsg(`执行拆解失败: ${err.message || err}`, true)
  }
}

function copyAllPrompts() {
  if (!reaReport.value?.shots?.length) return
  const full = reaReport.value.shots.map(s => `【镜头 ${s.index}】 (${s.duration}s)\n运镜：${s.camera} | 景别：${s.framing}\n提示词：${s.prompt}\n`).join('\n')
  navigator.clipboard.writeText(full).then(() => {
    showMsg('✨ 已将全部复刻提示词复制到剪贴板！')
  })
}

// ==================== Tab 3: Breeze 语音工坊 ====================
async function toggleBreezeService() {
  breezeStarting.value = true
  try {
    const res = await window.pywebview.api.start_breeze_service()
    if (res?.success) {
      showMsg(res.message || '正在启动本地语音模型服务…')
      // 轮询检查健康
      let retries = 15
      const checkTimer = setInterval(async () => {
        await fetchToolsStatus()
        if (toolsStatus.value.breeze?.service_running || retries <= 0) {
          clearInterval(checkTimer)
          breezeStarting.value = false
          if (toolsStatus.value.breeze?.service_running) {
            showMsg('🎉 Breeze 语音模型服务已就绪！可以生成配音了')
          }
        }
        retries--
      }, 1000)
    } else {
      breezeStarting.value = false
      showMsg(res?.message || '启动服务失败', true)
    }
  } catch (err) {
    breezeStarting.value = false
    showMsg(`启动异常: ${err.message || err}`, true)
  }
}

function applyVoicePreset(desc) {
  breezeVoiceDesc.value = desc
}

// ==================== Tab 4: 视频去水印 ====================
function addShuiyinBox(name, x, y, w, h) {
  shuiyinBoxes.value.push({
    id: Date.now(),
    name,
    x, y, w, h
  })
  showMsg(`已添加水印区域: ${name}`)
}

function removeShuiyinBox(id) {
  shuiyinBoxes.value = shuiyinBoxes.value.filter(b => b.id !== id)
}

async function startShuiyinProcess() {
  const cleanPath = String(shuiyinVideoPath.value || '').trim().replace(/^["']|["']$/g, '')
  if (!cleanPath) {
    showMsg('请先选择需要去水印的视频文件', true)
    return
  }
  if (!shuiyinBoxes.value.length) {
    showMsg('请至少添加一个水印区域选框', true)
    return
  }

  shuiyinRunning.value = true
  shuiyinProgress.value = 5
  shuiyinStatusText.value = '正在初始化 OpenCV Inpainting 逐帧修复引擎…'
  shuiyinResultUrl.value = ''

  try {
    const rawBoxes = shuiyinBoxes.value.map(b => [b.x, b.y, b.w, b.h])
    const res = await window.pywebview.api.run_watermark_removal(cleanPath, rawBoxes)
    if (!res?.success || !res?.job_id) {
      throw new Error(res?.message || '提交去水印任务失败')
    }
    const jobId = res.job_id
    const outPath = res.output_path

    shuiyinPollTimer = setInterval(async () => {
      try {
        const job = await window.pywebview.api.get_toolbox_job_status(jobId)
        if (job) {
          shuiyinProgress.value = job.progress || 0
          shuiyinStatusText.value = job.message || '正在修复中…'
          if (job.status === 'succeeded') {
            clearInterval(shuiyinPollTimer)
            shuiyinRunning.value = false
            shuiyinResultUrl.value = job.preview_url || outPath
            shuiyinResultPath.value = job.output_path || outPath
            showMsg('🎉 视频无痕去水印已完成！')
          } else if (job.status === 'failed') {
            clearInterval(shuiyinPollTimer)
            shuiyinRunning.value = false
            showMsg(job.message || '去水印处理失败', true)
          }
        }
      } catch (err) {
        console.warn('轮询去水印异常:', err)
      }
    }, 1000)
  } catch (err) {
    shuiyinRunning.value = false
    showMsg(`执行去水印失败: ${err.message || err}`, true)
  }
}

// ==================== Tab 5: 60fps 补帧 ====================
async function startFpsBoost() {
  const cleanPath = String(fpsVideoPath.value || '').trim().replace(/^["']|["']$/g, '')
  if (!cleanPath) {
    showMsg('请先选择需要补帧的视频文件', true)
    return
  }
  fpsRunning.value = true
  fpsProgress.value = 5
  fpsStatusText.value = `正在初始化 RIFE 光流插帧算法 (${fpsTarget.value}fps)…`
  fpsResultUrl.value = ''

  try {
    const res = await window.pywebview.api.run_fps_boost(cleanPath, fpsTarget.value)
    if (!res?.success || !res?.job_id) {
      throw new Error(res?.message || '提交补帧任务失败')
    }
    const jobId = res.job_id
    const outPath = res.output_path

    fpsPollTimer = setInterval(async () => {
      try {
        const job = await window.pywebview.api.get_toolbox_job_status(jobId)
        if (job) {
          fpsProgress.value = job.progress || 0
          fpsStatusText.value = job.message || '正在插帧渲染中…'
          if (job.status === 'succeeded') {
            clearInterval(fpsPollTimer)
            fpsRunning.value = false
            fpsResultUrl.value = job.preview_url || outPath
            fpsResultPath.value = job.output_path || outPath
            showMsg(`🎉 补帧完成！已升级为 ${fpsTarget.value}fps 超丝滑成片`)
          } else if (job.status === 'failed') {
            clearInterval(fpsPollTimer)
            fpsRunning.value = false
            showMsg(job.message || '补帧处理失败', true)
          }
        }
      } catch (err) {
        console.warn('轮询补帧异常:', err)
      }
    }, 1000)
  } catch (err) {
    fpsRunning.value = false
    showMsg(`补帧执行失败: ${err.message || err}`, true)
  }
}
</script>

<template>
  <div class="ai-toolbox-workspace">
    <!-- 顶部状态横幅 -->
    <header class="toolbox-header">
      <div class="header-left">
        <div class="title-row">
          <span class="toolbox-icon">🛠️</span>
          <h1>AI 影视超级工具箱</h1>
          <span class="toolbox-badge">5大专业外部引擎无缝集成</span>
        </div>
        <p class="subtitle">
          安全连接本地 5 大独立影视生产工具，支持在 CDTV 内一键处理并导入素材，亦可随时调起专业独立控制台。
        </p>
      </div>

      <!-- 5 大工具状态指示器 -->
      <div class="header-status-strip">
        <div class="status-chip" :class="{ ok: toolsStatus.rea_video?.available }" title="逆向拆解工具目录">
          <span class="dot"></span>
          <span>逆向拆解</span>
        </div>
        <div class="status-chip" :class="{ ok: toolsStatus.zimu?.available }" title="智能字幕工具目录">
          <span class="dot"></span>
          <span>智能字幕</span>
        </div>
        <div class="status-chip" :class="{ ok: toolsStatus.breeze?.available }" title="Breeze 本地语音目录">
          <span class="dot" :class="{ active: toolsStatus.breeze?.service_running }"></span>
          <span>Breeze语音</span>
        </div>
        <div class="status-chip" :class="{ ok: toolsStatus.shuiyin?.available }" title="去水印工具目录">
          <span class="dot"></span>
          <span>视频去水印</span>
        </div>
        <div class="status-chip" :class="{ ok: toolsStatus.waifu2x?.available }" title="补帧工具目录">
          <span class="dot"></span>
          <span>60fps补帧/超分</span>
        </div>
      </div>
    </header>

    <!-- 消息提示条 -->
    <div v-if="globalMessage" class="banner-alert success-alert">{{ globalMessage }}</div>
    <div v-if="globalError" class="banner-alert error-alert">{{ globalError }}</div>

    <!-- 5 大核心工具 Tab 栏 -->
    <nav class="toolbox-tabs" aria-label="工具箱子模块切换">
      <button
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === 'rea_video' }"
        @click="activeTab = 'rea_video'"
      >
        <span>🎬 视频逆向拆解</span>
        <small>rea-video</small>
      </button>

      <button
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === 'zimu' }"
        @click="activeTab = 'zimu'"
      >
        <span>📝 AI 智能字幕</span>
        <small>AutoSubs</small>
      </button>

      <button
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === 'breeze' }"
        @click="activeTab = 'breeze'"
      >
        <span>🎙️ Breeze 语音工坊</span>
        <small>Breeze-TTS</small>
      </button>

      <button
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === 'shuiyin' }"
        @click="activeTab = 'shuiyin'"
      >
        <span>💧 智能视频去水印</span>
        <small>Inpainting</small>
      </button>

      <button
        type="button"
        class="tab-btn"
        :class="{ active: activeTab === 'waifu2x' }"
        @click="activeTab = 'waifu2x'"
      >
        <span>⚡ 画质超分与 60fps 补帧</span>
        <small>RIFE / Waifu2x</small>
      </button>
    </nav>

    <!-- 主工作区内容 -->
    <main class="toolbox-body">
      <!-- ==================== Tab 1: rea-video 逆向拆解 ==================== -->
      <section v-if="activeTab === 'rea_video'" class="tool-section rea-section">
        <div class="tool-intro-card">
          <div class="intro-left">
            <h3>🎬 爆款视频分镜逆向拆解 (rea-video)</h3>
            <p>输入任意参考爆款视频，AI 自动切分镜头、识别构图景别与运镜方式，提取台词字幕与音效设计，并一键输出复刻提示词。</p>
          </div>
          <button type="button" class="native-launch-btn" @click="launchNativeApp('rea_video')">
            📂 打开外部源码目录
          </button>
        </div>

        <div class="tool-grid">
          <!-- 左侧配置与操作 -->
          <div class="tool-control-card">
            <h4>1. 选择待拆解视频</h4>
            <div class="file-picker-row" @dragover.prevent @drop="handleFileDrop($event, activeTab)">
              <input
                v-model="reaVideoPath"
                type="text"
                class="file-input"
                placeholder="请选择或拖入视频文件 (MP4 / MKV / MOV)..."
              />
              <button type="button" class="pick-file-btn" @click="pickVideo('rea')">
                选择文件…
              </button>
            </div>

            <h4 style="margin-top: 14px;">2. 拆解产物输出目录（可自选）</h4>
            <div class="file-picker-row">
              <input
                v-model="reaOutputDir"
                type="text"
                class="file-input"
                placeholder="默认自动保存在视频同级的 rea_reports 文件夹..."
              />
              <button type="button" class="pick-file-btn" @click="pickOutputDir('rea')">
                选择输出目录…
              </button>
              <button
                type="button"
                class="pick-file-btn"
                style="margin-left: 6px; background: #e2e8f0; color: #334155;"
                @click="openFolder(reaOutputDir || (reaVideoPath ? reaVideoPath.replace(/[^\\/]+$/, 'rea_reports') : ''))"
              >
                打开产物目录
              </button>
            </div>

            <div class="action-submit-row" style="display: flex; gap: 10px; margin-top: 14px;">
              <button
                type="button"
                class="primary-run-btn"
                style="flex: 1;"
                :disabled="reaRunning || !reaVideoPath"
                @click="startReaDecompose"
              >
                <span v-if="reaRunning" class="spinner-dot"></span>
                <span>{{ reaRunning ? '正在全自动静默逆向拆解中…' : '🚀 一键开始逆向拆解' }}</span>
              </button>
              <button
                v-if="reaRunning"
                type="button"
                class="cancel-run-btn"
                style="padding: 0 16px; background: #fee2e2; color: #ef4444; border: 1px solid #fca5a5; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 600;"
                @click="cancelReaDecompose"
              >
                🛑 终止拆解
              </button>
            </div>

            <!-- 进度显示 -->
            <div v-if="reaRunning" class="progress-box">
              <div class="progress-bar-shell">
                <div class="progress-bar-fill" :style="{ width: `${reaProgress}%` }"></div>
              </div>
              <p class="progress-status">{{ reaStatusText }} ({{ reaProgress }}%)</p>
            </div>
          </div>

          <!-- 右侧拆解结果展示 -->
          <div class="tool-result-card">
            <div class="result-header" style="display: flex; justify-content: space-between; align-items: center;">
              <h4>3. 拆解分析结果</h4>
              <button
                v-if="reaReport?.raw_report_path || reaOutputDir"
                type="button"
                class="open-folder-pill-btn"
                style="padding: 4px 10px; font-size: 12px; background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 6px; cursor: pointer; color: #334155;"
                @click="openFolder(reaReport?.raw_report_path || reaOutputDir)"
              >
                📁 打开产物完整文件夹
              </button>
              <button v-if="reaReport?.shots?.length" type="button" class="copy-btn" @click="copyAllPrompts">
                📋 一键复制全部复刻提示词
              </button>
            </div>

            <div v-if="reaReport?.shots?.length" class="shots-list-scroll">
              <div v-for="s in reaReport.shots" :key="s.index" class="shot-card">
                <div class="shot-card-head">
                  <span class="shot-tag">镜头 {{ s.index }}</span>
                  <span class="shot-duration">{{ s.start }}s ~ {{ s.end }}s (时长 {{ s.duration }}s)</span>
                  <span class="shot-meta">{{ s.framing }} · {{ s.camera }}</span>
                </div>
                <div v-if="s.text" class="shot-dialogue">
                  <strong>对白字幕：</strong> {{ s.text }}
                </div>
                <div class="shot-prompt-box">
                  <strong>复刻提示词：</strong>
                  <p>{{ s.prompt }}</p>
                </div>
              </div>
            </div>

            <div v-else class="empty-result-placeholder">
              <span class="placeholder-icon">🎬</span>
              <p>在左侧选择视频后点击【一键开始逆向拆解】，分镜、运镜与复刻提示词将呈现于此。</p>
            </div>
          </div>
        </div>
      </section>

      <!-- ==================== Tab 2: AutoSubs 字幕生成 ==================== -->
      <section v-if="activeTab === 'zimu'" class="tool-section zimu-section">
        <div class="tool-intro-card">
          <div class="intro-left">
            <h3>📝 AI 智能字幕工坊 (AutoSubs)</h3>
            <p>基于 Whisper 离线高精度语音识别与大模型上下文语义纠错，自动去除同音错别字，支持一键压制烧录硬字幕。</p>
          </div>
          <button type="button" class="native-launch-btn" @click="launchNativeApp('zimu')">
            🚀 启动 AutoSubs 独立客户端
          </button>
        </div>

        <div class="tool-grid">
          <div class="tool-control-card">
            <h4>1. 选择音视频文件</h4>
            <div class="file-picker-row" @dragover.prevent @drop="handleFileDrop($event, activeTab)">
              <input
                v-model="zimuVideoPath"
                type="text"
                class="file-input"
                placeholder="选择视频或音频文件..."
              />
              <button type="button" class="pick-file-btn" @click="pickVideo('zimu')">
                选择文件…
              </button>
            </div>

            <h4>2. AI 错别字智能校对引擎</h4>
            <div class="config-box">
              <p class="config-line"><strong>校准模型：</strong> {{ toolsStatus.zimu?.model || 'deepseek-v4.1-flash' }}</p>
              <p class="config-line"><strong>智能纠错：</strong> {{ toolsStatus.zimu?.ai_correction ? '已开启' : '关闭' }}</p>
            </div>

            <div class="action-submit-row">
              <button type="button" class="primary-run-btn" @click="launchNativeApp('zimu')">
                ✨ 调起 AutoSubs / SubtitleBurner 进行全量转录与烧录
              </button>
            </div>
          </div>

          <div class="tool-result-card">
            <div class="result-header">
              <h4>字幕工作台功能说明</h4>
            </div>
            <div class="feature-info-box">
              <div class="feature-item">
                <span class="f-icon">🎙️</span>
                <div>
                  <strong>Whisper 离线转写</strong>
                  <p>支持中文、英文等多种语言高精度离线识别，自动切分分句与毫秒级时间轴对齐。</p>
                </div>
              </div>
              <div class="feature-item">
                <span class="f-icon">🤖</span>
                <div>
                  <strong>AI 上下文语义纠错</strong>
                  <p>结合剧本/科普语境，自动纠正同音字、生僻词汇及断句标点，无需繁琐人工校对。</p>
                </div>
              </div>
              <div class="feature-item">
                <span class="f-icon">🔥</span>
                <div>
                  <strong>SubtitleBurner 硬字幕压制</strong>
                  <p>支持将生成的 .srt 自动压制烧录至视频底部，提供专业字号、阴影描边样式。</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ==================== Tab 3: Breeze 语音工坊 ==================== -->
      <section v-if="activeTab === 'breeze'" class="tool-section breeze-section">
        <div class="tool-intro-card">
          <div class="intro-left">
            <h3>🎙️ Breeze 本地语音工坊 (Breeze-TTS)</h3>
            <p>本地离线运行的高音质自然拟真语音大模型，支持自定义声音描述、语速、音色克隆与语气控制，无需联网。</p>
          </div>
          <button type="button" class="native-launch-btn" @click="launchNativeApp('breeze')">
            🚀 打开 Breeze语音.exe 独立窗口
          </button>
        </div>

        <div class="tool-grid">
          <div class="tool-control-card">
            <div class="service-status-bar" :class="{ ok: toolsStatus.breeze?.service_running }">
              <span class="status-indicator"></span>
              <span>
                {{ toolsStatus.breeze?.service_running ? '本地语音模型服务已就绪 (127.0.0.1:18080)' : '本地语音模型未启动' }}
              </span>
              <button
                v-if="!toolsStatus.breeze?.service_running"
                type="button"
                class="start-service-btn"
                :disabled="breezeStarting"
                @click="toggleBreezeService"
              >
                {{ breezeStarting ? '正在加载模型…' : '⚡ 一键启动本地服务' }}
              </button>
            </div>

            <h4>要朗读的文字</h4>
            <textarea
              v-model="breezeText"
              rows="4"
              class="breeze-textarea"
              placeholder="输入需要转成语音的旁白或对白台词..."
            ></textarea>

            <h4>声音描述与音色</h4>
            <textarea
              v-model="breezeVoiceDesc"
              rows="2"
              class="breeze-textarea"
              placeholder="描述想要的声音质感，如：温柔年轻女声，普通话清晰自然..."
            ></textarea>

            <div class="preset-chips">
              <span class="chip-label">快捷风格：</span>
              <button type="button" class="chip" @click="applyVoicePreset('温柔自然的年轻女声，普通话标准清晰，语速适中，充满治愈感')">🌸 温柔治愈女声</button>
              <button type="button" class="chip" @click="applyVoicePreset('成熟沉稳的青年男声，富有磁性，解说纪录片质感，语速沉着')">🎙️ 磁性沉稳男声</button>
              <button type="button" class="chip" @click="applyVoicePreset('热情洋溢的短视频带货女声，节奏明快，极具感染力')">⚡ 热情高能解说</button>
              <button type="button" class="chip" @click="applyVoicePreset('幽默诙谐的搞笑旁白男声，声调略带调侃魔性，戏剧张力十足')">🤣 搞笑魔性解说</button>
            </div>

            <div class="action-submit-row">
              <button type="button" class="primary-run-btn" @click="launchNativeApp('breeze')">
                🚀 在 Breeze 语音工作台中生成与保存音频
              </button>
            </div>
          </div>

          <div class="tool-result-card">
            <h4>Breeze 核心优势</h4>
            <div class="feature-info-box">
              <div class="feature-item">
                <span class="f-icon">🔒</span>
                <div>
                  <strong>100% 本地纯离线</strong>
                  <p>直接利用本地显卡计算，声音数据完全不上传云端，零网络延迟与零泄露风险。</p>
                </div>
              </div>
              <div class="feature-item">
                <span class="f-icon">🎭</span>
                <div>
                  <strong>自然语气与情感演播</strong>
                  <p>突破传统机械朗读音，呼吸音与顿挫自然连贯，完美适配分镜对白与影视旁白。</p>
                </div>
              </div>
              <div class="feature-item">
                <span class="f-icon">🎬</span>
                <div>
                  <strong>无缝与 CDTV 串联</strong>
                  <p>生成的音频可直接拖入 CDTV 项目作为分镜配音使用，亦支持与 Muse 自动音轨融合。</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ==================== Tab 4: 视频去水印 ==================== -->
      <section v-if="activeTab === 'shuiyin'" class="tool-section shuiyin-section">
        <div class="tool-intro-card">
          <div class="intro-left">
            <h3>💧 智能视频去水印 (Watermark Inpainting)</h3>
            <p>基于 OpenCV 时间域平滑与 Telea/Navier-Stokes 图像补全算法，智能抹除视频中的台标、滚动字幕与浮动水印。</p>
          </div>
          <button type="button" class="native-launch-btn" @click="launchNativeApp('shuiyin')">
            🚀 打开独立去水印客户端
          </button>
        </div>

        <div class="tool-grid">
          <div class="tool-control-card">
            <h4>1. 选择待去水印视频</h4>
            <div class="file-picker-row" @dragover.prevent @drop="handleFileDrop($event, activeTab)">
              <input
                v-model="shuiyinVideoPath"
                type="text"
                class="file-input"
                placeholder="选择视频文件..."
              />
              <button type="button" class="pick-file-btn" @click="pickVideo('shuiyin')">
                选择文件…
              </button>
            </div>

            <h4>2. 水印选区配置 (支持多选区)</h4>
            <div class="preset-chips">
              <span class="chip-label">快捷添加选区：</span>
              <button type="button" class="chip" @click="addShuiyinBox('左上角台标', 20, 20, 180, 70)">+ 左上角台标</button>
              <button type="button" class="chip" @click="addShuiyinBox('右上角水印', 520, 20, 180, 70)">+ 右上角水印</button>
              <button type="button" class="chip" @click="addShuiyinBox('底部字幕条', 40, 1160, 640, 90)">+ 底部字幕条</button>
            </div>

            <div class="boxes-list">
              <div v-for="b in shuiyinBoxes" :key="b.id" class="box-row">
                <span class="box-name">{{ b.name }}</span>
                <span class="box-coords">坐标: [x:{{ b.x }}, y:{{ b.y }}, w:{{ b.w }}, h:{{ b.h }}]</span>
                <button type="button" class="del-box-btn" @click="removeShuiyinBox(b.id)">✕</button>
              </div>
            </div>

            <div class="action-submit-row">
              <button
                type="button"
                class="primary-run-btn"
                :disabled="shuiyinRunning || !shuiyinVideoPath || !shuiyinBoxes.length"
                @click="startShuiyinProcess"
              >
                <span v-if="shuiyinRunning" class="spinner-dot"></span>
                <span>{{ shuiyinRunning ? '正在逐帧去水印中…' : '💧 开始智能无痕去水印' }}</span>
              </button>
            </div>

            <div v-if="shuiyinRunning" class="progress-box">
              <div class="progress-bar-shell">
                <div class="progress-bar-fill" :style="{ width: `${shuiyinProgress}%` }"></div>
              </div>
              <p class="progress-status">{{ shuiyinStatusText }} ({{ shuiyinProgress }}%)</p>
            </div>
          </div>

          <div class="tool-result-card">
            <h4>去水印结果预览</h4>
            <div v-if="shuiyinResultUrl || shuiyinResultPath" class="video-preview-shell">
              <video :src="shuiyinResultUrl" controls autoplay class="clean-video-player"></video>
              <div class="result-path-row">
                <p class="clean-path">已保存：{{ shuiyinResultPath || shuiyinResultUrl }}</p>
                <button type="button" class="reveal-btn" @click="revealFile(shuiyinResultPath || shuiyinResultUrl)">打开文件位置</button>
              </div>
            </div>
            <div v-else class="empty-result-placeholder">
              <span class="placeholder-icon">💧</span>
              <p>设定水印矩形选区并执行后，修复完成的纯净视频将呈现于此。</p>
            </div>
          </div>
        </div>
      </section>

      <!-- ==================== Tab 5: Waifu2x / RIFE 补帧 ==================== -->
      <section v-if="activeTab === 'waifu2x'" class="tool-section waifu2x-section">
        <div class="tool-intro-card">
          <div class="intro-left">
            <h3>⚡ 画质超分与 60fps 补帧 (Waifu2x / RIFE)</h3>
            <p>基于深度学习 RIFE 光流补帧技术，将 24fps/30fps 视频插帧至 60fps/120fps，彻底消除抽帧顿挫感，动作行云流水。</p>
          </div>
          <button type="button" class="native-launch-btn" @click="launchNativeApp('waifu2x')">
            🚀 启动 Waifu2x 完整专业版
          </button>
        </div>

        <div class="tool-grid">
          <div class="tool-control-card">
            <h4>1. 选择视频文件</h4>
            <div class="file-picker-row" @dragover.prevent @drop="handleFileDrop($event, activeTab)">
              <input
                v-model="fpsVideoPath"
                type="text"
                class="file-input"
                placeholder="选择视频文件..."
              />
              <button type="button" class="pick-file-btn" @click="pickVideo('fps')">
                选择文件…
              </button>
            </div>

            <h4>2. 目标帧率规格</h4>
            <div class="preset-chips">
              <button
                type="button"
                class="chip"
                :class="{ active: fpsTarget === 60 }"
                @click="fpsTarget = 60"
              >
                🚀 60 FPS (推荐 · 动作极致丝滑)
              </button>
              <button
                type="button"
                class="chip"
                :class="{ active: fpsTarget === 120 }"
                @click="fpsTarget = 120"
              >
                ⚡ 120 FPS (电竞级超高帧率)
              </button>
            </div>

            <div class="action-submit-row">
              <button
                type="button"
                class="primary-run-btn"
                :disabled="fpsRunning || !fpsVideoPath"
                @click="startFpsBoost"
              >
                <span v-if="fpsRunning" class="spinner-dot"></span>
                <span>{{ fpsRunning ? '正在光流计算插帧中…' : '⚡ 一键提升至 60fps 丝滑高帧率' }}</span>
              </button>
            </div>

            <div v-if="fpsRunning" class="progress-box">
              <div class="progress-bar-shell">
                <div class="progress-bar-fill" :style="{ width: `${fpsProgress}%` }"></div>
              </div>
              <p class="progress-status">{{ fpsStatusText }} ({{ fpsProgress }}%)</p>
            </div>
          </div>

          <div class="tool-result-card">
            <h4>补帧成片预览</h4>
            <div v-if="fpsResultUrl || fpsResultPath" class="video-preview-shell">
              <video :src="fpsResultUrl" controls autoplay class="clean-video-player"></video>
              <div class="result-path-row">
                <p class="clean-path">已保存：{{ fpsResultPath || fpsResultUrl }}</p>
                <button type="button" class="reveal-btn" @click="revealFile(fpsResultPath || fpsResultUrl)">打开文件位置</button>
              </div>
            </div>
            <div v-else class="empty-result-placeholder">
              <span class="placeholder-icon">⚡</span>
              <p>选择视频后点击【一键提升至 60fps】，插帧后的高动态视频将在此播放。</p>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.ai-toolbox-workspace {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  background: var(--theme-bg-main, #f8fafc);
  overflow-y: auto;
  box-sizing: border-box;
}

/* 顶部横幅 */
.toolbox-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: var(--theme-bg-surface, #ffffff);
  border-bottom: 1px solid var(--theme-border-subtle, #e2e8f0);
  gap: 16px;
  flex-wrap: wrap;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbox-icon {
  font-size: 24px;
}

.title-row h1 {
  font-size: 20px;
  font-weight: 700;
  color: var(--theme-text-primary, #0f172a);
  margin: 0;
}

.toolbox-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--theme-accent, #2563eb);
  background: var(--theme-accent-soft, #eff6ff);
  padding: 2px 8px;
  border-radius: 4px;
}

.subtitle {
  font-size: 12.5px;
  color: var(--theme-text-secondary, #64748b);
  margin: 4px 0 0 0;
}

.header-status-strip {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.status-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 14px;
  background: var(--theme-bg-elevated, #f1f5f9);
  font-size: 11.5px;
  font-weight: 500;
  color: var(--theme-text-secondary, #64748b);
}

.status-chip .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #94a3b8;
}

.status-chip.ok .dot {
  background: #10b981;
}

.status-chip.ok .dot.active {
  box-shadow: 0 0 6px #10b981;
}

/* 消息提示 */
.banner-alert {
  padding: 8px 24px;
  font-size: 13px;
  font-weight: 500;
}
.success-alert {
  background: #ecfdf5;
  color: #065f46;
  border-bottom: 1px solid #a7f3d0;
}
.error-alert {
  background: #fef2f2;
  color: #991b1b;
  border-bottom: 1px solid #fecaca;
}

/* Tabs 栏 */
.toolbox-tabs {
  display: flex;
  background: var(--theme-bg-surface, #ffffff);
  border-bottom: 1px solid var(--theme-border-subtle, #e2e8f0);
  padding: 0 24px;
  gap: 8px;
  overflow-x: auto;
}

.tab-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px 18px;
  border: none;
  background: transparent;
  color: var(--theme-text-secondary, #64748b);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s ease;
  font-family: inherit;
}

.tab-btn span {
  font-size: 13.5px;
  font-weight: 600;
}

.tab-btn small {
  font-size: 10.5px;
  opacity: 0.75;
  margin-top: 1px;
}

.tab-btn:hover {
  color: var(--theme-text-primary, #0f172a);
}

.tab-btn.active {
  color: var(--theme-accent, #2563eb);
  border-bottom-color: var(--theme-accent, #2563eb);
}

/* 主内容区 */
.toolbox-body {
  flex: 1;
  padding: 20px 24px;
}

.tool-intro-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  background: var(--theme-bg-surface, #ffffff);
  border: 1px solid var(--theme-border-subtle, #e2e8f0);
  border-radius: 10px;
  margin-bottom: 16px;
  gap: 16px;
  flex-wrap: wrap;
}

.intro-left h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--theme-text-primary, #0f172a);
}

.intro-left p {
  margin: 4px 0 0 0;
  font-size: 12.5px;
  color: var(--theme-text-secondary, #64748b);
}

.native-launch-btn {
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--theme-accent, #2563eb);
  background: var(--theme-accent-soft, #eff6ff);
  border: 1px solid rgba(37, 99, 235, 0.25);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.native-launch-btn:hover {
  background: var(--theme-accent, #2563eb);
  color: #ffffff;
}

/* 网格布局 */
.tool-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

@media (max-width: 900px) {
  .tool-grid {
    grid-template-columns: 1fr;
  }
}

.tool-control-card, .tool-result-card {
  background: var(--theme-bg-surface, #ffffff);
  border: 1px solid var(--theme-border-subtle, #e2e8f0);
  border-radius: 10px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tool-control-card h4, .tool-result-card h4 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--theme-text-primary, #0f172a);
}

.file-picker-row {
  display: flex;
  gap: 8px;
}

.file-input {
  flex: 1;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid var(--theme-border-subtle, #cbd5e1);
  font-size: 12.5px;
  background: var(--theme-bg-input, #f8fafc);
  color: var(--theme-text-primary, #0f172a);
  outline: none;
}

.pick-file-btn {
  padding: 8px 14px;
  font-size: 12.5px;
  font-weight: 600;
  background: var(--theme-bg-elevated, #f1f5f9);
  color: var(--theme-text-primary, #0f172a);
  border: 1px solid var(--theme-border-subtle, #cbd5e1);
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
}

.action-submit-row {
  margin-top: 4px;
}

.primary-run-btn {
  width: 100%;
  padding: 10px 16px;
  border-radius: 8px;
  border: none;
  background: var(--theme-accent, #2563eb);
  color: #ffffff;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: opacity 0.15s;
}

.primary-run-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

/* 进度条 */
.progress-box {
  background: var(--theme-bg-input, #f8fafc);
  border: 1px solid var(--theme-border-subtle, #e2e8f0);
  border-radius: 8px;
  padding: 10px 12px;
}
.progress-bar-shell {
  width: 100%;
  height: 6px;
  background: #e2e8f0;
  border-radius: 3px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: var(--theme-accent, #2563eb);
  transition: width 0.3s ease;
}
.progress-status {
  margin: 6px 0 0 0;
  font-size: 11.5px;
  color: var(--theme-text-secondary, #64748b);
}

/* 结果区 */
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.copy-btn {
  padding: 4px 10px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--theme-accent-soft, #eff6ff);
  color: var(--theme-accent, #2563eb);
  border: 1px solid rgba(37, 99, 235, 0.2);
  border-radius: 4px;
  cursor: pointer;
}

.empty-result-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
  color: var(--theme-text-secondary, #94a3b8);
}
.placeholder-icon {
  font-size: 36px;
  margin-bottom: 8px;
  opacity: 0.6;
}
.empty-result-placeholder p {
  font-size: 12.5px;
  max-width: 300px;
  line-height: 1.5;
  margin: 0;
}

/* 分镜卡片列表 */
.shots-list-scroll {
  max-height: 480px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.shot-card {
  border: 1px solid var(--theme-border-subtle, #e2e8f0);
  background: var(--theme-bg-input, #f8fafc);
  border-radius: 8px;
  padding: 10px 12px;
}
.shot-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.shot-tag {
  font-size: 11px;
  font-weight: 700;
  color: #ffffff;
  background: var(--theme-accent, #2563eb);
  padding: 1px 6px;
  border-radius: 4px;
}
.shot-duration {
  font-size: 11px;
  color: var(--theme-text-secondary, #64748b);
}
.shot-meta {
  font-size: 11px;
  font-weight: 600;
  color: var(--theme-text-primary, #0f172a);
  margin-left: auto;
}
.shot-dialogue {
  font-size: 12px;
  color: #047857;
  background: #ecfdf5;
  padding: 4px 8px;
  border-radius: 4px;
  margin-bottom: 6px;
}
.shot-prompt-box {
  font-size: 12px;
  color: var(--theme-text-primary, #0f172a);
}
.shot-prompt-box p {
  margin: 2px 0 0 0;
  line-height: 1.45;
  color: var(--theme-text-secondary, #334155);
}

/* 按钮与芯片 */
.preset-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.chip-label {
  font-size: 11.5px;
  color: var(--theme-text-secondary, #64748b);
}
.chip {
  padding: 3px 8px;
  font-size: 11.5px;
  background: var(--theme-bg-elevated, #f1f5f9);
  color: var(--theme-text-primary, #0f172a);
  border: 1px solid var(--theme-border-subtle, #cbd5e1);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.chip:hover, .chip.active {
  background: var(--theme-accent-soft, #eff6ff);
  color: var(--theme-accent, #2563eb);
  border-color: var(--theme-accent, #2563eb);
}

/* 水印选区列表 */
.boxes-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 150px;
  overflow-y: auto;
}
.box-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: var(--theme-bg-input, #f8fafc);
  border: 1px solid var(--theme-border-subtle, #e2e8f0);
  border-radius: 6px;
  font-size: 12px;
}
.box-name {
  font-weight: 600;
  color: var(--theme-text-primary, #0f172a);
}
.box-coords {
  color: var(--theme-text-secondary, #64748b);
  font-family: monospace;
}
.del-box-btn {
  background: transparent;
  border: none;
  color: #ef4444;
  cursor: pointer;
  font-weight: 700;
}

/* 视频播放器 */
.clean-video-player {
  width: 100%;
  max-height: 320px;
  border-radius: 8px;
  background: #000000;
}
.clean-path {
  font-size: 11.5px;
  color: var(--theme-text-secondary, #64748b);
  word-break: break-all;
  margin: 6px 0 0 0;
}

/* 特性介绍卡片 */
.feature-info-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.f-icon {
  font-size: 20px;
}
.feature-item strong {
  font-size: 13px;
  color: var(--theme-text-primary, #0f172a);
}
.feature-item p {
  margin: 2px 0 0 0;
  font-size: 12px;
  color: var(--theme-text-secondary, #64748b);
  line-height: 1.4;
}

.breeze-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--theme-border-subtle, #cbd5e1);
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.5;
  background: var(--theme-bg-input, #f8fafc);
  color: var(--theme-text-primary, #0f172a);
  resize: vertical;
  outline: none;
}

.service-status-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  font-size: 12px;
  font-weight: 500;
}
.service-status-bar .status-indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ef4444;
}
.service-status-bar.ok .status-indicator {
  background: #10b981;
}
.start-service-btn {
  margin-left: auto;
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 600;
  background: var(--theme-accent, #2563eb);
  color: #ffffff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.result-path-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 8px;
}
.reveal-btn {
  padding: 4px 10px;
  font-size: 11.5px;
  font-weight: 500;
  border-radius: 4px;
  border: 1px solid #cbd5e1;
  background: var(--theme-bg-elevated, #f1f5f9);
  color: var(--theme-text-primary, #0f172a);
  cursor: pointer;
  white-space: nowrap;
}
.reveal-btn:hover {
  background: var(--theme-accent-soft, #eff6ff);
  color: var(--theme-accent, #2563eb);
  border-color: var(--theme-accent, #2563eb);
}
</style>
