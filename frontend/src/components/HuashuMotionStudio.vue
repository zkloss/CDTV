<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import HUASHU_DEFAULT_TEMPLATES from '../utils/huashuTemplates.json'
import { desktopBackendRequest } from '../utils/desktopApi.js'

const props = defineProps({
  project: { type: Object, required: true },
  brief: { type: Object, default: () => ({}) },
  script: { type: String, default: '' },
  token: { type: String, default: '' },
  storageBase: { type: String, default: '' },
})

const emit = defineEmits(['advanced', 'save-script', 'switch-ai'])

const templates = ref(HUASHU_DEFAULT_TEMPLATES || [])
const selectedTemplateId = ref('keynote-ui')
const projectInfo = ref(null)
const status = ref({ ready: true, version: '0.3.1' })
const loading = ref(false)
const busy = ref('')
const error = ref('')
const message = ref('')
const blurMotion = ref(false)

const currentVideoUrl = computed(() => {
  if (projectInfo.value?.previewUrl) {
    return projectInfo.value.previewUrl
  }
  if (projectInfo.value?.videoUrl && (projectInfo.value.videoUrl.startsWith('http://') || projectInfo.value.videoUrl.startsWith('https://'))) {
    return projectInfo.value.videoUrl
  }
  const base = (props.storageBase || 'http://127.0.0.1:18081').replace(/\/+$/, '')
  if (projectInfo.value?.videoUrl) {
    return `${base}${projectInfo.value.videoUrl}`
  }
  if (projectInfo.value?.latestVideo) {
    return `${base}/local-file?path=${encodeURIComponent(projectInfo.value.latestVideo)}`
  }
  return ''
})

async function onVideoError(e) {
  console.warn('宣传片预览加载异常，尝试刷新预览地址:', currentVideoUrl.value, e)
  await refreshProjectInfo()
}

async function handleOpenNative() {
  if (!projectInfo.value?.latestVideo) return
  try {
    const api = window.pywebview?.api
    if (api?.open_path) {
      await api.open_path(projectInfo.value.latestVideo)
    }
  } catch (err) {
    error.value = '调用外部播放器失败: ' + (err?.message || err)
  }
}

async function handleOpenFolder() {
  if (!projectInfo.value?.latestVideo) return
  try {
    const api = window.pywebview?.api
    if (api?.reveal_path) {
      await api.reveal_path(projectInfo.value.latestVideo)
    }
  } catch (err) {
    error.value = '打开文件位置失败: ' + (err?.message || err)
  }
}

const currentTemplate = computed(() => {
  return templates.value.find(t => t.id === selectedTemplateId.value) || templates.value[0] || {}
})

async function callBridge(method, pyApiName, endpoint, payload = {}) {
  const api = window.pywebview?.api
  if (api && typeof api[pyApiName] === 'function') {
    try {
      return await api[pyApiName](...Object.values(payload))
    } catch (e) {
      console.warn(`pywebview.${pyApiName} failed, falling back to HTTP:`, e)
    }
  }
  return await desktopBackendRequest(method, endpoint, props.token, payload)
}

async function fetchStatusAndTemplates() {
  try {
    const api = window.pywebview?.api
    if (api?.huashu_templates) {
      const list = await api.huashu_templates()
      if (Array.isArray(list) && list.length) {
        templates.value = list
      }
    }
    if (api?.huashu_status) {
      status.value = await api.huashu_status()
    }
    await refreshProjectInfo()
  } catch (err) {
    error.value = '加载宣传片配置失败: ' + (err?.message || err)
  }
}

async function refreshProjectInfo() {
  if (!props.project?.id) return
  try {
    const info = await callBridge('GET', 'huashu_project_info', `/api/huashu/project_info?projectId=${encodeURIComponent(props.project.id)}`, { project_id: String(props.project.id) })
    if (info) projectInfo.value = info
  } catch (_) {}
}

async function handleInitProject(force = false) {
  busy.value = 'init'
  error.value = ''
  message.value = '正在为项目定制专属品牌文案、产品画面与离线配乐…'
  try {
    await callBridge('POST', 'huashu_init_project', '/api/huashu/init', {
      project_id: String(props.project.id),
      template_id: selectedTemplateId.value,
      title: props.project?.name || '商业宣传片',
      script_text: props.script || props.project?.description || '',
      force: force === true
    })
    await refreshProjectInfo()
    message.value = `已成功装载【${currentTemplate.value.name || selectedTemplateId.value}】宣传片工程并注入项目专属品牌元素！`
  } catch (err) {
    error.value = '初始化失败: ' + (err?.message || err)
  } finally {
    busy.value = ''
  }
}

async function handleOpenStudio() {
  busy.value = 'studio'
  error.value = ''
  message.value = '正在启动本地 Studio 并打开浏览器…'
  try {
    if (!projectInfo.value?.isInitialized) {
      await handleInitProject()
    }
    const res = await callBridge('POST', 'huashu_open_studio', '/api/huashu/open_studio', {
      project_id: String(props.project.id)
    })
    message.value = `已在浏览器打开指屏修改工作室（${res?.url || 'http://127.0.0.1:4173/studio'}），在画面上按 C 即可点选修改！`
  } catch (err) {
    error.value = '启动 Studio 失败: ' + (err?.message || err)
  } finally {
    busy.value = ''
  }
}

async function handleRender() {
  if (busy.value) return
  busy.value = 'render'
  error.value = ''
  try {
    if (!projectInfo.value?.isInitialized) {
      message.value = '正在为您自动装载模版与生成离线音频卡点…'
      await callBridge('POST', 'huashu_init_project', '/api/huashu/init', {
        project_id: String(props.project.id),
        template_id: selectedTemplateId.value,
        title: props.project?.name || '商业宣传片',
        script_text: props.script || props.project?.description || ''
      })
      await refreshProjectInfo()
    }

    message.value = '正在使用无头浏览器逐帧无损渲染宣传片并压制高清视频，通常耗时 20~40 秒…'
    const res = await callBridge('POST', 'huashu_render_project', '/api/huashu/render', {
      project_id: String(props.project.id),
      blur: blurMotion.value,
      template_id: selectedTemplateId.value
    })
    await refreshProjectInfo()
    message.value = `宣传片渲染完成！文件：${res?.fileName || '成片.mp4'} (${((res?.size || 0) / 1024 / 1024).toFixed(1)} MB)`
  } catch (err) {
    error.value = '渲染失败: ' + (err?.message || err)
  } finally {
    busy.value = ''
  }
}

async function handleExport() {
  if (!projectInfo.value?.latestVideo) return
  try {
    const api = window.pywebview?.api
    if (api?.save_video_as) {
      await api.save_video_as(projectInfo.value.latestVideo, `${props.project.name || '宣传片'}.mp4`)
    }
  } catch (err) {
    error.value = '导出失败: ' + (err?.message || err)
  }
}

onMounted(() => {
  fetchStatusAndTemplates()
})

watch(() => props.project?.id, () => {
  refreshProjectInfo()
})
</script>

<template>
  <section class="huashu-studio" aria-label="花叔商业宣传片工作台">
    <header class="huashu-head">
      <div>
        <span class="huashu-badge">HUASHU-MOTION · 商业发布片动效引擎</span>
        <h2>大厂发布会级宣传片制作</h2>
        <p>基于纯前端代码驱动（HTML5 + GSAP + Three.js + 离线真乐器编曲），UI 与 Logo 像素级精准、文字绝不乱码扭曲，支持指着画面实时修改。</p>
      </div>
      <div class="huashu-head-actions">
        <span v-if="status?.ready" class="huashu-status-chip online">● 动效与渲染环境就绪 (v{{ status.version }})</span>
        <span v-else class="huashu-status-chip offline">○ 环境初始化中</span>
        <button class="gv-secondary" type="button" @click="emit('advanced')">切换到逐镜编辑</button>
      </div>
    </header>

    <p v-if="error" class="gv-error" role="alert">{{ error }}</p>
    <p v-if="message" class="gv-message" role="status">{{ message }}</p>

    <!-- Mode & Model Calling Explanation Notice -->
    <div class="huashu-mode-notice">
      <div class="notice-tag">💡 本地代码动效模式</div>
      <div class="notice-desc">
        <span>当前使用的是<strong>纯本地代码逐帧渲染 (HTML5/Canvas/Three.js + 离线编曲)</strong>，<strong>无需调用云端 AI 视频模型，0 算力消耗、后台无模型调用记录</strong>。</span>
        <button class="switch-link-btn" type="button" @click="emit('switch-ai')">👉 切换到【📹 AI 视频模型直出】(调用云端视频模型)</button>
      </div>
    </div>

    <!-- Main Workspace Layout -->
    <div class="huashu-layout">
      <!-- Left: Player & Actions -->
      <section class="huashu-left-pane">
        <div class="huashu-player-wrap">
          <video
            v-if="projectInfo?.latestVideo"
            :key="currentVideoUrl || projectInfo.latestVideo"
            :src="currentVideoUrl"
            controls
            preload="auto"
            class="huashu-video-player"
            @error="onVideoError"
          ></video>
          <div v-else class="huashu-player-placeholder">
            <span class="huashu-play-icon">🎬</span>
            <h3>尚未渲染宣传片成片</h3>
            <p>请在右侧选择宣传片风格模版，点击【一键高清渲染】即可极速输出完整 60fps 商业宣传片。</p>
          </div>
        </div>

        <!-- Player bottom bar -->
        <div class="huashu-player-bar">
          <div class="huashu-bar-info">
            <strong>{{ currentTemplate.name || '未选择模版' }}</strong>
            <small v-if="projectInfo?.hasRender">
              已生成成片 · 大小：{{ (projectInfo.latestVideoSize / 1024 / 1024).toFixed(1) }} MB
            </small>
            <small v-else>
              预设时长：约 {{ currentTemplate.duration || 25 }} 秒 · 纯本地音频采样与音效卡点
            </small>
          </div>
          <div class="huashu-bar-actions">
            <button
              v-if="projectInfo?.hasRender"
              class="gv-primary"
              type="button"
              @click="handleExport"
            >
              📥 导出完整视频
            </button>
            <button
              v-if="projectInfo?.hasRender"
              class="gv-secondary"
              type="button"
              title="在系统默认播放器中打开视频查看 60fps 流畅效果"
              @click="handleOpenNative"
            >
              ▶ 外部播放
            </button>
            <button
              v-if="projectInfo?.hasRender"
              class="gv-secondary"
              type="button"
              title="在系统资源管理器中定位生成的 MP4 文件"
              @click="handleOpenFolder"
            >
              📂 打开位置
            </button>
            <button
              class="gv-primary huashu-render-btn"
              type="button"
              :disabled="!!busy"
              @click="handleRender"
            >
              {{ busy === 'render' ? '⚡ 正在渲染中…' : projectInfo?.hasRender ? '⚡ 重新渲染宣传片' : '⚡ 一键高清渲染 (60fps)' }}
            </button>
            <button
              class="gv-secondary"
              type="button"
              :disabled="!!busy"
              title="在系统浏览器打开 Studio，鼠标指着任意画面元素按 C 进行修改"
              @click="handleOpenStudio"
            >
              🖱️ 指屏修改工作室 (Studio)
            </button>
          </div>
        </div>

        <!-- Fast Feature Highlights -->
        <div class="huashu-feature-strip">
          <div class="huashu-feat-item">
            <strong>🎯 绝不乱码形变</strong>
            <span>代码矢量渲染，保持品牌 Logo 与产品界面 100% 锐利还原</span>
          </div>
          <div class="huashu-feat-item">
            <strong>🎵 离线真乐器编曲</strong>
            <span>先定节拍谱曲、再拍片，重音与打击点 100% 卡点音效</span>
          </div>
          <div class="huashu-feat-item">
            <strong>🖱️ 指着画面即改</strong>
            <span>按 C 点选任意卡片、标题或数字，微调秒级刷新无需抽卡</span>
          </div>
        </div>
      </section>

      <!-- Right: Template Picker & Project Controls -->
      <aside class="huashu-right-pane">
        <div class="huashu-aside-head">
          <h3>选择商业发布片模版 ({{ templates.length }} 种大厂流派)</h3>
          <button
            class="huashu-init-link"
            type="button"
            :disabled="!!busy"
            @click="handleInitProject(!!projectInfo?.isInitialized)"
          >
            {{ projectInfo?.isInitialized ? '重置工程并套入文案' : '初始化工程' }}
          </button>
        </div>

        <div class="huashu-template-grid">
          <article
            v-for="tpl in templates"
            :key="tpl.id"
            class="huashu-tpl-card"
            :class="{ active: selectedTemplateId === tpl.id }"
            @click="selectedTemplateId = tpl.id"
          >
            <div class="huashu-tpl-icon">{{ tpl.icon }}</div>
            <div class="huashu-tpl-content">
              <div class="huashu-tpl-title-row">
                <h4>{{ tpl.name }}</h4>
                <span class="huashu-tag-energy">{{ tpl.energy }}</span>
              </div>
              <p class="huashu-tpl-desc">{{ tpl.description }}</p>
              <div class="huashu-tpl-footer">
                <span class="huashu-tpl-tag">{{ tpl.tag }}</span>
                <span class="huashu-tpl-dur">~{{ tpl.duration }}s</span>
              </div>
            </div>
          </article>
        </div>

        <!-- Render options -->
        <div class="huashu-options-box">
          <h4>渲染与质感参数</h4>
          <label class="huashu-check-label">
            <input v-model="blurMotion" type="checkbox" :disabled="!!busy" />
            <span>开启电影级运动模糊（Motion Blur，快节奏运镜更丝滑）</span>
          </label>
          <small class="huashu-tip">
            开启运动模糊会在每帧合成 8 个微子帧，质感极高，渲染时间略有增加。
          </small>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.huashu-studio {
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 520px;
  padding-bottom: 24px;
  color: var(--theme-text-primary);
}

.huashu-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
  padding: 18px 24px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 16px;
  background: linear-gradient(135deg, var(--theme-bg-card), color-mix(in srgb, var(--theme-accent) 10%, var(--theme-bg-card)));
}

.huashu-mode-notice {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
  font-size: 13px;
  color: #166534;
}

.notice-tag {
  background: #16a34a;
  color: #fff;
  font-weight: bold;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
}

.notice-desc {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  flex: 1;
}

.switch-link-btn {
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  font-weight: 500;
  transition: background 0.15s ease;
}

.switch-link-btn:hover {
  background: #1d4ed8;
}

.huashu-badge {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: var(--theme-accent);
}

.huashu-head h2 {
  font-size: 22px;
  margin: 6px 0 8px;
}

.huashu-head p {
  font-size: 13px;
  color: var(--theme-text-secondary);
  margin: 0;
  max-width: 680px;
  line-height: 1.6;
}

.huashu-head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.huashu-status-chip {
  padding: 6px 12px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
}

.huashu-status-chip.online {
  background: rgba(34, 197, 94, 0.12);
  color: #16a34a;
  border: 1px solid rgba(34, 197, 94, 0.25);
}

.huashu-status-chip.offline {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.25);
}

/* Layout */
.huashu-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(360px, 1fr);
  gap: 20px;
  align-items: start;
}

.huashu-left-pane {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.huashu-player-wrap {
  width: 100%;
  aspect-ratio: 16/9;
  background: #0f172a;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--theme-border-subtle);
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.25);
}

.huashu-video-player {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.huashu-player-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 30px;
  box-sizing: border-box;
  text-align: center;
  color: #94a3b8;
}

.huashu-play-icon {
  font-size: 42px;
  margin-bottom: 12px;
}

.huashu-player-placeholder h3 {
  font-size: 18px;
  margin: 0 0 8px;
  color: #f1f5f9;
}

.huashu-player-placeholder p {
  font-size: 13px;
  max-width: 440px;
  line-height: 1.7;
  margin: 0;
}

.huashu-player-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-card);
  border-radius: 12px;
}

.huashu-bar-info strong {
  display: block;
  font-size: 15px;
}

.huashu-bar-info small {
  font-size: 12px;
  color: var(--theme-text-secondary);
}

.huashu-bar-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.huashu-render-btn {
  background: linear-gradient(135deg, var(--theme-accent), #6366f1);
  border-color: transparent;
  font-weight: 700;
}

.huashu-feature-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.huashu-feat-item {
  padding: 14px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-card);
  border-radius: 10px;
}

.huashu-feat-item strong {
  display: block;
  font-size: 13px;
  color: var(--theme-accent);
  margin-bottom: 4px;
}

.huashu-feat-item span {
  font-size: 11px;
  color: var(--theme-text-secondary);
  line-height: 1.6;
}

/* Right pane */
.huashu-right-pane {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-card);
  border-radius: 14px;
}

.huashu-aside-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.huashu-aside-head h3 {
  margin: 0;
  font-size: 15px;
}

.huashu-init-link {
  border: 0;
  background: transparent;
  color: var(--theme-accent);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.huashu-template-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 480px;
  overflow-y: auto;
  padding-right: 4px;
}

.huashu-tpl-card {
  display: flex;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-elevated);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.18s ease;
}

.huashu-tpl-card:hover {
  border-color: var(--theme-accent);
  transform: translateY(-1px);
}

.huashu-tpl-card.active {
  border-color: var(--theme-accent);
  background: var(--theme-accent-soft);
  box-shadow: 0 0 0 1px var(--theme-accent);
}

.huashu-tpl-icon {
  font-size: 26px;
  flex-shrink: 0;
  padding-top: 2px;
}

.huashu-tpl-content {
  flex: 1;
  min-width: 0;
}

.huashu-tpl-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.huashu-tpl-title-row h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.huashu-tag-energy {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--theme-accent);
  color: #fff;
}

.huashu-tpl-desc {
  font-size: 12px;
  color: var(--theme-text-secondary);
  line-height: 1.5;
  margin: 0 0 8px;
}

.huashu-tpl-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}

.huashu-tpl-tag {
  color: var(--theme-text-secondary);
  opacity: 0.85;
}

.huashu-tpl-dur {
  color: var(--theme-accent);
  font-weight: 600;
}

.huashu-options-box {
  padding-top: 12px;
  border-top: 1px solid var(--theme-border-subtle);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.huashu-options-box h4 {
  margin: 0;
  font-size: 13px;
}

.huashu-check-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  cursor: pointer;
}

.huashu-tip {
  font-size: 11px;
  color: var(--theme-text-secondary);
  line-height: 1.6;
}

@media (max-width: 1100px) {
  .huashu-layout {
    grid-template-columns: 1fr;
  }
}
</style>
