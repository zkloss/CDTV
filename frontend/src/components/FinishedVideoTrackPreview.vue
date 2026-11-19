<template>
  <Teleport to="body">
    <Transition name="track-dialog-fade">
      <div v-if="visible" class="track-dialog-overlay" @mousedown.self="close">
        <section ref="dialogRef" class="track-dialog" role="dialog" aria-modal="true" aria-labelledby="project-track-title" tabindex="-1" @mousedown.stop>
          <header class="track-dialog-head">
            <div class="track-dialog-heading">
              <span>成片预览</span>
              <h2 id="project-track-title">项目成片</h2>
              <p>{{ projectTitle || '未命名项目' }}</p>
            </div>
            <div class="track-dialog-summary"><b>{{ videoTimeline.length }}</b> / {{ videos.length }} 个分镜<button v-if="assemblyEnabled" class="track-assembly-toggle" type="button" @click="assemblyOpen=!assemblyOpen">{{ assemblyOpen ? '返回连续预览' : 'AI 衔接组片' }}</button></div>
            <button class="track-close" type="button" aria-label="关闭成片预览" @click="close">
              <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
          </header>

          <div v-if="loading" class="track-loading-wrap">
            <BaseLoadingState size="lg" text="正在加载项目成片…" description="读取视频片段并整理 V1 轨道" />
          </div>
          <div v-else-if="error" class="track-dialog-state error"><strong>成片加载失败</strong><span>{{ error }}</span></div>
          <div v-else-if="!videos.length" class="track-dialog-state"><strong>当前项目还没有成片</strong><span>完成视频生成后，再从项目列表点击“成片”。</span></div>

          <div v-else class="track-editor">
            <aside class="track-assets">
              <header><strong>成片列表</strong><span>{{ videos.length }}</span></header>
              <div class="track-asset-list">
                <button v-for="(item, index) in videos" :key="`asset-${item.id}`" type="button" class="track-asset-item" :class="{ active: activeVideoId === item.id, hidden: isVideoHidden(item) }" @click="selectVideo(item.id, 0)">
                  <span class="track-asset-thumb">
                    <video :src="item.src" muted preload="auto" @loadeddata="ensureVideoRenderable(item, $event)" @error="safeEmitVideoError(item)"></video>
                    <i>{{ String(index + 1).padStart(2, '0') }}</i>
                  </span>
                  <span class="track-asset-info">
                    <strong>{{ item.title }}</strong>
                    <span class="track-asset-meta">
                      <small>{{ formatTime(mediaDuration(item)) }} · 视频</small>
                      <span class="track-asset-toggle" :class="{ off: isVideoHidden(item) }" role="button" tabindex="0" :aria-disabled="assemblyLocked" :aria-label="isVideoHidden(item) ? '在轨道显示' : '从轨道隐藏'" :data-tooltip="assemblyEnabled ? (isVideoHidden(item) ? '加入预览和AI组片' : '从预览和AI组片中取消选择') : (isVideoHidden(item) ? '在轨道显示' : '从轨道隐藏')" @click.stop="toggleVideoHidden(item)" @keydown.stop.enter.prevent="toggleVideoHidden(item)" @keydown.stop.space.prevent="toggleVideoHidden(item)">
                        <svg v-if="!isVideoHidden(item)" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>
                        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="m3 3 18 18M10.6 10.6a3 3 0 0 0 4 4M9.4 5.2A9.5 9.5 0 0 1 12 5c6.5 0 10 7 10 7a17.8 17.8 0 0 1-3.3 4.1M6.1 6.1A17.8 17.8 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 3.8-1"/></svg>
                      </span>
                    </span>
                  </span>
                </button>
              </div>
            </aside>

            <section v-show="!assemblyOpen" class="track-player">
              <header class="track-player-head">
                <div><i></i><strong>预览监视器</strong></div>
                <span v-if="!packMessage">{{ activeVideo?.title || '没有可播放的成片' }}</span>
                <div v-if="packMessage" class="track-pack-result" :class="{ success: Boolean(packResult), warning: packWarning }" role="status">
                  <div class="track-pack-result-main">
                    <strong>{{ packResult ? '完整成片已生成' : '打包结果' }}</strong>
                    <span v-if="!packResult">{{ packMessage }}</span>
                    <code v-else :title="packResult.path">{{ packResult.path }}</code>
                  </div>
                  <div v-if="packResult" class="track-pack-result-actions">
                    <button type="button" @click="openPackedVideo">打开成片</button>
                    <button type="button" @click="openPackedFolder">打开所在文件夹</button>
                    <button type="button" @click="copyPackedPath">复制路径</button>
                  </div>
                </div>
                <button v-if="assemblyEnabled && projectId" class="track-pack-btn" type="button" @click="motionOpen=true">接点处理</button>
                <label class="track-pack-prefix" data-tooltip="可选。填 1 时导出为 101、102；留空导出为 01、02">
                  <span>序号前缀</span>
                  <input
                    :value="sequencePrefix"
                    type="text"
                    inputmode="numeric"
                    maxlength="8"
                    placeholder="不添加"
                    aria-label="打包视频序号前缀，可不填写"
                    :disabled="packaging"
                    @input="updateSequencePrefix"
                  />
                </label>
                <button
                  type="button"
                  class="track-pack-btn"
                  :disabled="packaging || !videos.length"
                  :data-tooltip="packMessage || '按分镜顺序打包所有成片到视频输出目录'"
                  @click="packageVideos"
                >
                  <svg v-if="!packaging" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 7v10l10 4 10-4V7L12 3Zm0 0v18M2 7l10 4 10-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>
                  <span v-else class="track-pack-spin" aria-hidden="true"></span>
                  <span>{{ packaging ? '打包中…' : '打包成片' }}</span>
                </button>
              </header>
              <div v-if="hasReviewWarnings" :title="activeVideo?.reviewWarning" class="track-review-warning" :class="{ empty: !activeVideo?.reviewWarning }" role="status">{{ activeVideo?.reviewWarning || '\u00a0' }}</div>
              <!-- ✂️ 接缝效果调换工具栏：不满意直接换，立即生效实时看！ -->
              <div v-if="props.seams && props.seams.length > 0" class="track-seam-live-bar">
                <div class="seam-bar-top">
                  <div class="seam-bar-title">
                    <span class="seam-bar-tag">✂️ 调换转场</span>
                    <strong>正在调节：第 {{ currentSeamIndex + 1 }} 镜 ➔ 第 {{ currentSeamIndex + 2 }} 镜 接缝</strong>
                    <div v-if="isRawMode" class="seam-engine-badge raw-badge" title="当前为原视频纯拼接模式，不添加任何遮挡物或运镜惯性，展示原片最原始拼接样貌">
                      <i class="engine-pulse-dot dot-gray"></i>
                      <strong>原视频纯拼接模式</strong>
                      <span>(原片无遮挡 · 无动能 · 纯硬切拼接)</span>
                    </div>
                    <div v-else class="seam-engine-badge" title="全自动技术，已默认自动开启生效：在上一镜播放到最后1.5秒时系统在后台自动完成下一镜首帧解码并预热，接缝点0ms无感秒级推帧，保持运镜动量守恒，全程全自动无需手动调节！">
                      <i class="engine-pulse-dot"></i>
                      <strong>全自动消顿引擎：已生效</strong>
                      <span>(1.5s 预解码 + 0ms 动能融接)</span>
                    </div>
                  </div>
                  <div class="seam-bar-btns">
                    <button
                      type="button"
                      class="btn-seam-compare-toggle"
                      :class="{ 'is-active': compareMode }"
                      @click="toggleCompareMode"
                      title="上下分屏同时播放两版：上屏原视频纯拼接 vs 下屏消顿转场版，同屏直接对比"
                    >
                      {{ compareMode ? '📺 切回单屏' : '🔀 上下两版对比' }}
                    </button>
                    <button
                      v-if="!compareMode"
                      type="button"
                      class="btn-seam-raw-toggle"
                      :class="{ 'is-raw': isRawMode }"
                      @click="toggleRawPreview"
                      :title="isRawMode ? '点击切回带消顿与转场特效的连续播放' : '点击直接观看无任何遮挡和运镜特效的原视频纯拼接效果'"
                    >
                      {{ isRawMode ? '⚡ 恢复消顿转场效果' : '🎞️ 看原视频纯拼接' }}
                    </button>
                    <button type="button" class="btn-seam-replay" @click="replayCurrentSeam">
                      🔁 重新试看当前接缝
                    </button>
                    <button type="button" class="btn-seam-save" :class="{ 'is-saved': seamJustSaved }" @click="saveCurrentSeamFromPreview">
                      {{ seamJustSaved ? '✅ 已保存并写入分镜！' : '💾 满意，保存并写入分镜' }}
                    </button>
                  </div>
                </div>
                <div class="seam-bar-options">
                  <!-- 换遮挡物 -->
                  <div class="option-row">
                    <span class="option-name">遮挡物：</span>
                    <div class="option-chips">
                      <button
                        v-for="item in OCCLUSION_PRESETS"
                        :key="item.id"
                        type="button"
                        class="seam-chip-btn"
                        :class="{ active: currentSeamConfig.occlusion === item.id }"
                        @click="changeSeamOcclusion(item.id)"
                      >
                        {{ item.label }}
                      </button>
                    </div>
                  </div>
                  <!-- 换运镜方向 -->
                  <div class="option-row">
                    <span class="option-name">运镜动能：</span>
                    <div class="option-chips">
                      <button
                        v-for="item in MOMENTUM_DIRECTIONS"
                        :key="item.id"
                        type="button"
                        class="seam-chip-btn"
                        :class="{ active: currentSeamConfig.momentum === item.id }"
                        @click="changeSeamMomentum(item.id)"
                      >
                        {{ item.label }}
                      </button>
                    </div>
                  </div>
                  <!-- 换转场方式 -->
                  <div class="option-row">
                    <span class="option-name">衔接模式：</span>
                    <div class="option-chips">
                      <button
                        type="button"
                        class="seam-chip-btn"
                        :class="{ active: currentSeamConfig.mode === 'raw' }"
                        @click="changeSeamMode('raw')"
                      >
                        🎞️ 原视频纯拼接
                      </button>
                      <button
                        type="button"
                        class="seam-chip-btn"
                        :class="{ active: currentSeamConfig.mode === 'transition' }"
                        @click="changeSeamMode('transition')"
                      >
                        🌊 顺畅遮挡
                      </button>
                      <button
                        type="button"
                        class="seam-chip-btn"
                        :class="{ active: currentSeamConfig.mode === 'exact' }"
                        @click="changeSeamMode('exact')"
                      >
                        🏃 动作接演
                      </button>
                      <button
                        type="button"
                        class="seam-chip-btn"
                        :class="{ active: currentSeamConfig.mode === 'matchCut' }"
                        @click="changeSeamMode('matchCut')"
                      >
                        🎬 直接换镜头
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div class="track-monitor" :class="{ 'is-split-compare': compareMode }">
                <!-- 上下两版对比模式：上屏原视频纯拼接 vs 下屏消顿转场版 -->
                <div v-if="compareMode" class="compare-split-container">
                  <!-- 上屏：原视频纯拼接 -->
                  <div class="compare-split-pane pane-raw">
                    <div class="split-pane-header">
                      <span class="split-badge raw">🎞️ 上屏：原视频纯拼接（未消顿原片 · 纯硬切）</span>
                    </div>
                    <div class="track-player-stage mode-raw occ-none mom-none">
                      <video
                        v-for="clip in videoTimeline"
                        :key="'raw_' + clip.id"
                        :ref="el => setRawPlayerVideo(el, clip)"
                        :class="[
                          'player-video',
                          { active: activeVideoId === clip.id }
                        ]"
                        :src="clip.src"
                        playsinline
                        muted
                        preload="auto"
                        @click="togglePlayback"
                      ></video>
                    </div>
                  </div>

                  <!-- 下屏：消顿转场版 -->
                  <div class="compare-split-pane pane-smooth">
                    <div class="split-pane-header">
                      <span class="split-badge smooth">⚡ 下屏：全自动消顿版（已生效消顿引擎 · 平滑融接）</span>
                    </div>
                    <div
                      class="track-player-stage"
                      :class="[
                        `occ-${smoothOcclusion}`,
                        `mom-${smoothMomentum}`,
                        `mode-${smoothMode}`,
                        { 'is-transitioning': isTransitioning }
                      ]"
                    >
                      <video
                        v-for="clip in videoTimeline"
                        :key="clip.id"
                        :ref="el => setPlayerVideo(el, clip)"
                        :class="[
                          'player-video',
                          {
                            active: activeVideoId === clip.id,
                            'fading-out': fadingOutVideoId === clip.id,
                            'entering': enteringVideoId === clip.id
                          }
                        ]"
                        :src="clip.src"
                        playsinline
                        preload="auto"
                        @click="togglePlayback"
                        @loadedmetadata="onMainVideoMetadata($event, clip)"
                        @loadeddata="ensureVideoRenderable(clip, $event)"
                        @durationchange="onMainVideoMetadata($event, clip)"
                        @timeupdate="onMainVideoTime"
                        @play="onVideoPlay"
                        @pause="onVideoPause"
                        @volumechange="onVolumeChange"
                        @ended="advanceVideo($event)"
                        @error="safeEmitVideoError(clip)"
                      ></video>

                      <!-- 🗡️ 剑光/刀影 电影级瞬间光刃高光闪切 (0.24s 瞬间扫过，无多余 UI) -->
                      <div
                        v-if="isTransitioning && smoothOcclusion === 'sword_light'"
                        class="seam-blade-gleam"
                        aria-hidden="true"
                      ></div>

                      <!-- 🌫️ 烟雾/黑雾 电影级暗场溶解 (0.35s 柔和沉入暗色后亮起) -->
                      <div
                        v-if="isTransitioning && smoothOcclusion === 'smoke_fog'"
                        class="seam-dark-dip"
                        aria-hidden="true"
                      ></div>
                    </div>
                  </div>
                </div>

                <!-- 单屏模式 -->
                <div
                  v-else
                  class="track-player-stage"
                  :class="[
                    `occ-${currentSeamConfig.occlusion}`,
                    `mom-${currentSeamConfig.momentum}`,
                    `mode-${currentSeamConfig.mode}`,
                    { 'is-transitioning': isTransitioning }
                  ]"
                >
                  <video
                    v-for="clip in videoTimeline"
                    :key="clip.id"
                    :ref="el => setPlayerVideo(el, clip)"
                    :class="[
                      'player-video',
                      {
                        active: activeVideoId === clip.id,
                        'fading-out': fadingOutVideoId === clip.id,
                        'entering': enteringVideoId === clip.id
                      }
                    ]"
                    :src="clip.src"
                    playsinline
                    preload="auto"
                    @click="togglePlayback"
                    @loadedmetadata="onMainVideoMetadata($event, clip)"
                    @loadeddata="ensureVideoRenderable(clip, $event)"
                    @durationchange="onMainVideoMetadata($event, clip)"
                    @timeupdate="onMainVideoTime"
                    @play="onVideoPlay"
                    @pause="onVideoPause"
                    @volumechange="onVolumeChange"
                    @ended="advanceVideo($event)"
                    @error="safeEmitVideoError(clip)"
                  ></video>

                  <!-- 🗡️ 剑光/刀影 电影级瞬间光刃高光闪切 (0.24s 瞬间扫过，无多余 UI) -->
                  <div
                    v-if="isTransitioning && currentSeamConfig.occlusion === 'sword_light'"
                    class="seam-blade-gleam"
                    aria-hidden="true"
                  ></div>

                  <!-- 🌫️ 烟雾/黑雾 电影级暗场溶解 (0.35s 柔和沉入暗色后亮起) -->
                  <div
                    v-if="isTransitioning && currentSeamConfig.occlusion === 'smoke_fog'"
                    class="seam-dark-dip"
                    aria-hidden="true"
                  ></div>
                </div>
                <div v-if="playbackError" class="track-playback-error" role="status">{{ playbackError }}</div>
                <footer class="track-player-controls">
                  <button type="button" :aria-label="playing ? '暂停' : '播放'" @click="togglePlayback">
                    <svg v-if="playing" viewBox="0 0 24 24"><path d="M7.5 5.5h3.5v13H7.5zM13 5.5h3.5v13H13z" /></svg>
                    <svg v-else viewBox="0 0 24 24"><path d="m9 6.7 9 5.3-9 5.3z" /></svg>
                  </button>
                  <div class="track-progress-control">
                    <input type="range" min="0" :max="totalDuration" step="0.01" :value="currentTime" :style="{ '--track-progress': `${timelineProgress * 100}%` }" aria-label="项目视频播放进度" @input="seekTimeline(Number($event.target.value))" />
                    <div><span class="track-time current">{{ formatTime(currentTime) }}</span><span class="track-time">{{ formatTime(totalDuration) }}</span></div>
                  </div>
                  <button type="button" :aria-label="muted ? '打开声音' : '静音'" @click="toggleMuted">
                    <svg v-if="muted" viewBox="0 0 24 24"><path d="M4 10v4h4l5 4V6l-5 4H4zM17 9l4 6M21 9l-4 6" /></svg>
                    <svg v-else viewBox="0 0 24 24"><path d="M4 10v4h4l5 4V6l-5 4H4zM16 9c1.5 1.4 1.5 4.6 0 6M19 7c3 2.7 3 7.3 0 10" /></svg>
                  </button>
                </footer>
              </div>
            </section>

            <section v-if="assemblyEnabled && projectId" v-show="assemblyOpen" class="track-assembly">
              <ShotAssemblyPanel :key="projectId" :project-id="projectId" :token="token" :clips="videoTimeline" :models="models" :text-models="textModels" :text-model="textModel" :value="assemblyValue" :save="saveAssembly" :file-url="fileUrl" @busy-change="assemblyLocked=$event" @edit-shot="emit('edit-shot',$event)" />
            </section>
            <MotionAssemblyPreview v-if="motionOpen && assemblyEnabled && projectId" :key="projectId" :project-id="projectId" :token="token" :clips="videoTimeline" :file-url="fileUrl" @close="motionOpen=false" />

            <section class="project-timeline" aria-label="项目视频轨道">
              <header><div><strong>视频轨道</strong><span>项目视频轨道</span></div><p>V1 · {{ videoTimeline.length }} 个片段 · {{ Math.round(timelineZoom * 100) }}%</p></header>
              <div ref="timelineScrollRef" class="timeline-scroll" @wheel="zoomTimeline">
                <div class="timeline-content" :style="{ width: `${timelineZoom * 100}%` }">
                  <div class="timeline-ruler"><span v-for="mark in rulerMarks" :key="mark" :style="{ left: `${mark / timelineDuration * 100}%` }">{{ formatTime(mark) }}</span></div>
                  <div class="timeline-row">
                    <span class="timeline-label">V1</span>
                    <div ref="timelineLaneRef" class="timeline-lane">
                      <button v-for="clip in videoTimeline" :key="clip.id" type="button" class="timeline-clip" :class="{ active: activeVideoId === clip.id }" :style="clipStyle(clip)" @click="selectVideo(clip.id, clip.duration * pointerRatio($event))">
                        <span class="clip-filmstrip"><video v-for="frame in filmstripFrameCount(clip)" :key="`${clip.id}-${frame}`" :src="clip.src" muted playsinline preload="auto" @loadedmetadata="loadFilmstripFrame($event, frame, filmstripFrameCount(clip))" @loadeddata="ensureVideoRenderable(clip, $event)" @error="safeEmitVideoError(clip)"></video></span>
                        <strong>{{ clip.title }}</strong>
                      </button>
                      <button class="timeline-playhead" :class="{ dragging: draggingPlayhead }" type="button" :style="{ left: `${timelinePosition * 100}%` }" aria-label="拖动播放指针" @pointerdown.stop.prevent="startPlayheadDrag"></button>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { waitForDesktopApi } from '../utils/desktopApi.js'
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import BaseLoadingState from './BaseLoadingState.vue'
import ShotAssemblyPanel from './ShotAssemblyPanel.vue'
import MotionAssemblyPreview from './MotionAssemblyPreview.vue'
import { watchForDecodedVideoFrame } from '../utils/videoCompatibility.js'
import { prepareVideoFrame } from '../utils/prepareVideoFrame.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  projectTitle: { type: String, default: '' },
  videos: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  token: { type: String, default: '' },
  projectId: { type: String, default: '' },
  assemblyEnabled: { type: Boolean, default: false },
  assemblyValue: Object,
  models: Array,
  textModels: Array,
  textModel: String,
  saveAssembly: Function,
  fileUrl: Function,
  initialVideoId: { type: String, default: '' },
  initialOffset: { type: Number, default: 0 },
  autoPlay: { type: Boolean, default: false },
  initialCompareMode: { type: Boolean, default: false },
  seams: { type: Array, default: () => [] },
  activeSeamIndex: { type: Number, default: 0 },
})
const emit = defineEmits(['update:visible', 'video-error', 'edit-shot', 'update-seam'])
const dialogRef = ref(null)
const videoRef = ref(null)
const timelineScrollRef = ref(null)
const timelineLaneRef = ref(null)
// 视频元素池：每个片段一个 <video preload="auto">，切换片段只切可见性，避免重建造成的卡顿
const playerVideos = new Map()       // clipId -> HTMLVideoElement
function setPlayerVideo(el, clip) {
  if (el) {
    playerVideos.set(clip.id, el)
    if (clip.id === activeVideoId.value) videoRef.value = el
  } else {
    playerVideos.delete(clip.id)
  }
}

// 🔀 上下两版对比模式：上屏原视频纯拼接 vs 下屏全自动消顿版
const compareMode = ref(false)
const rawPlayerVideos = new Map()     // clipId -> HTMLVideoElement (用于上屏原视频纯拼接)
function setRawPlayerVideo(el, clip) {
  if (el) {
    rawPlayerVideos.set(clip.id, el)
  } else {
    rawPlayerVideos.delete(clip.id)
  }
}

function syncRawVideosState() {
  const curId = activeVideoId.value
  const targetTime = videoRef.value ? videoRef.value.currentTime : 0
  for (const [id, rv] of rawPlayerVideos.entries()) {
    if (id === curId) {
      try {
        rv.currentTime = targetTime
        if (playing.value) {
          rv.play().catch(() => {})
        } else {
          rv.pause()
        }
      } catch (_) {}
    } else {
      try { rv.pause() } catch (_) {}
    }
  }
}

function toggleCompareMode() {
  compareMode.value = !compareMode.value
  if (compareMode.value) {
    nextTick(() => {
      syncRawVideosState()
    })
  } else {
    for (const rv of rawPlayerVideos.values()) {
      try { rv.pause() } catch (_) {}
    }
  }
}

const OCCLUSION_PRESETS = [
  { id: 'none', label: '🚫 无遮挡 (原片)' },
  { id: 'smoke_fog', label: '🌫️ 烟雾/黑雾' },
  { id: 'sword_light', label: '🗡️ 剑光/刀影' },
  { id: 'cloak_pass', label: '🥋 披风/衣角' },
  { id: 'stone_pillar', label: '🪨 石碑/立柱' },
  { id: 'tree_trunk', label: '🌲 树木/树干' },
  { id: 'ground_shadow', label: '🌑 地面暗影' },
]

const MOMENTUM_DIRECTIONS = [
  { id: 'none', label: '⏹️ 原机位无动能' },
  { id: 'push_in', label: '⏩ 往前推' },
  { id: 'pan_right', label: '➡️ 往右移' },
  { id: 'pan_left', label: '⬅️ 往左移' },
  { id: 'pull_out', label: '⏪ 往后拉' },
  { id: 'orbit_low', label: '🔄 仰头转圈' },
  { id: 'crane_down', label: '⬇️ 往下压' },
]

const currentSeamIndex = ref(props.activeSeamIndex || 0)
const currentSeamConfig = reactive({
  occlusion: 'smoke_fog',
  momentum: 'push_in',
  mode: 'transition',
})
const seamJustSaved = ref(false)

const isRawMode = computed(() => {
  return currentSeamConfig.mode === 'raw' || currentSeamConfig.occlusion === 'none'
})

let savedTransitionConfig = {
  occlusion: 'smoke_fog',
  momentum: 'push_in',
  mode: 'transition',
}

const smoothOcclusion = computed(() => {
  if (currentSeamConfig.occlusion && currentSeamConfig.occlusion !== 'none') {
    return currentSeamConfig.occlusion
  }
  return savedTransitionConfig.occlusion && savedTransitionConfig.occlusion !== 'none'
    ? savedTransitionConfig.occlusion
    : 'smoke_fog'
})

const smoothMomentum = computed(() => {
  if (currentSeamConfig.momentum && currentSeamConfig.momentum !== 'none') {
    return currentSeamConfig.momentum
  }
  return savedTransitionConfig.momentum && savedTransitionConfig.momentum !== 'none'
    ? savedTransitionConfig.momentum
    : 'push_in'
})

const smoothMode = computed(() => {
  if (currentSeamConfig.mode && currentSeamConfig.mode !== 'raw') {
    return currentSeamConfig.mode
  }
  return savedTransitionConfig.mode && savedTransitionConfig.mode !== 'raw'
    ? savedTransitionConfig.mode
    : 'transition'
})

function restoreSmoothTransition() {
  const occ = savedTransitionConfig.occlusion && savedTransitionConfig.occlusion !== 'none' ? savedTransitionConfig.occlusion : 'smoke_fog'
  const mom = savedTransitionConfig.momentum && savedTransitionConfig.momentum !== 'none' ? savedTransitionConfig.momentum : 'push_in'
  const mode = savedTransitionConfig.mode && savedTransitionConfig.mode !== 'raw' ? savedTransitionConfig.mode : 'transition'
  currentSeamConfig.occlusion = occ
  currentSeamConfig.momentum = mom
  currentSeamConfig.mode = mode
  emit('update-seam', {
    seamIndex: currentSeamIndex.value,
    occlusion: occ,
    momentum: mom,
    mode: mode,
    save: true
  })
  replayCurrentSeam()
}

function toggleRawPreview() {
  if (isRawMode.value) {
    restoreSmoothTransition()
  } else {
    savedTransitionConfig = {
      occlusion: currentSeamConfig.occlusion && currentSeamConfig.occlusion !== 'none' ? currentSeamConfig.occlusion : 'smoke_fog',
      momentum: currentSeamConfig.momentum && currentSeamConfig.momentum !== 'none' ? currentSeamConfig.momentum : 'push_in',
      mode: currentSeamConfig.mode && currentSeamConfig.mode !== 'raw' ? currentSeamConfig.mode : 'transition',
    }
    currentSeamConfig.occlusion = 'none'
    currentSeamConfig.momentum = 'none'
    currentSeamConfig.mode = 'raw'
    emit('update-seam', {
      seamIndex: currentSeamIndex.value,
      occlusion: 'none',
      momentum: 'none',
      mode: 'raw',
      save: false
    })
    replayCurrentSeam()
  }
}

watch(() => props.activeSeamIndex, idx => {
  if (typeof idx === 'number' && idx >= 0) currentSeamIndex.value = idx
})

watch(() => [props.seams, currentSeamIndex.value], () => {
  const s = props.seams?.[currentSeamIndex.value]
  if (s) {
    currentSeamConfig.occlusion = s.occlusion || 'smoke_fog'
    currentSeamConfig.momentum = s.momentum || 'push_in'
    currentSeamConfig.mode = s.mode || 'transition'
  }
}, { immediate: true, deep: true })

function replayCurrentSeam() {
  const idx = currentSeamIndex.value
  if (idx < 0 || idx >= videoTimeline.value.length - 1) return
  const fromClip = videoTimeline.value[idx]
  if (!fromClip) return
  preTransitionTriggered = false
  preSeekedVideoId = null
  fadingOutVideoId.value = ''
  enteringVideoId.value = ''
  isTransitioning.value = false
  if (transitionTimer) { clearTimeout(transitionTimer); transitionTimer = null }
  const offset = Math.max(0, fromClip.duration - 2.5)
  selectVideo(fromClip.id, offset, true)
}

function changeSeamOcclusion(occ) {
  currentSeamConfig.occlusion = occ
  if (occ === 'none') {
    currentSeamConfig.mode = 'raw'
  } else if (currentSeamConfig.mode === 'raw') {
    currentSeamConfig.mode = 'transition'
  }
  emit('update-seam', {
    seamIndex: currentSeamIndex.value,
    occlusion: occ,
    momentum: currentSeamConfig.momentum,
    mode: currentSeamConfig.mode,
    save: false
  })
  replayCurrentSeam()
}

function changeSeamMomentum(mom) {
  currentSeamConfig.momentum = mom
  emit('update-seam', {
    seamIndex: currentSeamIndex.value,
    occlusion: currentSeamConfig.occlusion,
    momentum: mom,
    mode: currentSeamConfig.mode,
    save: false
  })
  replayCurrentSeam()
}

function changeSeamMode(m) {
  currentSeamConfig.mode = m
  if (m === 'raw') {
    currentSeamConfig.occlusion = 'none'
    currentSeamConfig.momentum = 'none'
  } else if (currentSeamConfig.occlusion === 'none') {
    currentSeamConfig.occlusion = 'smoke_fog'
    currentSeamConfig.momentum = 'push_in'
  }
  emit('update-seam', {
    seamIndex: currentSeamIndex.value,
    occlusion: currentSeamConfig.occlusion,
    momentum: currentSeamConfig.momentum,
    mode: m,
    save: false
  })
  replayCurrentSeam()
}

function saveCurrentSeamFromPreview() {
  emit('update-seam', {
    seamIndex: currentSeamIndex.value,
    occlusion: currentSeamConfig.occlusion,
    momentum: currentSeamConfig.momentum,
    mode: currentSeamConfig.mode,
    save: true
  })
  seamJustSaved.value = true
  setTimeout(() => { seamJustSaved.value = false }, 3000)
}

const activeVideoId = ref('')
const fadingOutVideoId = ref('')
const enteringVideoId = ref('')
const isTransitioning = ref(false)
let transitionTimer = null
let preSeekedVideoId = null
const currentTime = ref(0)
const playing = ref(false)
const playbackError = ref('')
let pendingSelection = null
let retrySelection = null
const draggingPlayhead = ref(false)
const timelineZoom = ref(1)
const muted = ref(false)
const measuredDurations = reactive({})
const hiddenVideoIds = ref(new Set())
const assemblyOpen = ref(false)
const motionOpen = ref(false)
const assemblyLocked = ref(false)
function isVideoHidden(video) { return video ? hiddenVideoIds.value.has(String(video.id)) : false }
function toggleVideoHidden(video) {
  if (!video?.id || assemblyLocked.value) return
  const id = String(video.id)
  const next = new Set(hiddenVideoIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  hiddenVideoIds.value = next
}
let previousFocus = null
let previousBodyOverflow = ''
let playbackFrame = 0
let playbackVideo = null
let playbackTick = null
let preTransitionTriggered = false
let scrubFrame = 0
let pendingScrubX = 0
let scrubWasPlaying = false
let videoSelectionVersion = 0
let stopVideoFrameWatch = null
let isUnmounted = false
// 安全 emit：组件卸载后或实例被回收时，emit 内部访问 instance.emitsOptions 可能拿到 null 抛错
function safeEmitVideoError(clip) {
  if (isUnmounted) return
  try { emit('video-error', clip) } catch (_) {}
}

function ensureVideoRenderable(clip, event) {
  const video = event.currentTarget
  window.setTimeout(() => {
    if (!video.isConnected || isUnmounted) return
    if (video.videoWidth <= 0 || video.videoHeight <= 0) safeEmitVideoError(clip)
  }, 250)
}

function mediaDuration(item) { return Math.max(.1, Number(measuredDurations[item.id] || item.duration) || 5) }
function buildTimeline(items) { let start = 0; return items.map(item => { const duration = mediaDuration(item); const clip = { ...item, start, duration }; start += duration; return clip }) }
const videoTimeline = computed(() => buildTimeline(props.videos.filter(v => !isVideoHidden(v))))
const totalDuration = computed(() => videoTimeline.value.at(-1)?.start + videoTimeline.value.at(-1)?.duration || 0)
const timelineDuration = computed(() => Math.max(5, Math.ceil(totalDuration.value)))
const timelineProgress = computed(() => totalDuration.value ? Math.min(1, currentTime.value / totalDuration.value) : 0)
const timelinePosition = computed(() => Math.min(1, currentTime.value / timelineDuration.value))
const activeVideo = computed(() => props.videos.find(item => item.id === activeVideoId.value) || props.videos[0])
const hasReviewWarnings = computed(() => props.videos.some(item => item.reviewWarning))
const rulerMarks = computed(() => { const step = timelineDuration.value <= 12 ? 2 : timelineDuration.value <= 30 ? 5 : 10; const marks = []; for (let n = 0; n <= timelineDuration.value; n += step) marks.push(n); if (marks.at(-1) !== timelineDuration.value) marks.push(timelineDuration.value); return marks })

watch(() => props.visible, async visible => {
  if (visible) {
    compareMode.value = !!props.initialCompareMode
    assemblyOpen.value = false
    motionOpen.value = false
    sequencePrefix.value = ''
    previousFocus = document.activeElement
    previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKeydown)
    await nextTick()
    dialogRef.value?.focus()

    // 针对性定位与播放：支持传入指定的起始镜头与秒数偏移（如接缝处前 2.5 秒）
    const targetId = props.initialVideoId && props.videos.some(v => String(v.id) === String(props.initialVideoId))
      ? String(props.initialVideoId)
      : (props.videos[0]?.id || '')
    const targetOffset = Math.max(0, Number(props.initialOffset) || 0)
    if (targetId) {
      await selectVideo(targetId, targetOffset, props.autoPlay)
    }
  } else cleanup()
})
watch(() => JSON.stringify(props.videos.map(v => [v.id, v.src])), () => {
  cancelSelection()
  for (const v of playerVideos.values()) v.pause()
  stopPlaybackClock()
  const videos = props.videos
  if (!videos.some(item => item.id === activeVideoId.value)) activeVideoId.value = videos[0]?.id || ''
  currentTime.value = currentVideoClip()?.start || 0
  playing.value = false
  hiddenVideoIds.value = new Set([...hiddenVideoIds.value].filter(id => videos.some(video => String(video.id) === id)))
}, { immediate: true })
watch(videoTimeline, clips => {
  if (pendingSelection && !clips.some(c => c.id === pendingSelection.id)) cancelSelection()
  if (!clips.some(c => c.id === activeVideoId.value)) {
    videoRef.value?.pause()
    if (clips.length) selectVideo(clips[0].id, 0, false)
    else { activeVideoId.value = ''; playing.value = false; stopPlaybackClock() }
  }
})
watch(assemblyOpen, open => { if (open) { cancelSelection(); videoRef.value?.pause(); playing.value = false } })
watch(motionOpen, open => { if (open) { cancelSelection(); videoRef.value?.pause(); playing.value = false } })
watch(activeVideoId, id => { videoRef.value = playerVideos.get(id) || null })
onBeforeUnmount(() => { isUnmounted = true; cleanup() })

function close() { emit('update:visible', false) }

// 视频打包：按分镜顺序下载到 <outputDir>/<项目名>/01.mp4、02.mp4、...
const packaging = ref(false)
const packMessage = ref('')
const packResult = ref(null)
const packWarning = ref(false)
const sequencePrefix = ref('')
function safePackName(name) {
  return String(name || '未命名项目').replace(/[\\/:*?"<>|\r\n\t]+/g, '_').replace(/^\.+|\.+$/g, '').trim() || '未命名项目'
}
function updateSequencePrefix(event) {
  const value = String(event?.target?.value || '').replace(/\D/g, '').slice(0, 8)
  sequencePrefix.value = value
  if (event?.target && event.target.value !== value) event.target.value = value
}
async function copyPackedPath() {
  const path = String(packResult.value?.path || '')
  if (!path) return
  try {
    await navigator.clipboard.writeText(path)
    packMessage.value = `已复制文件路径：${path}`
  } catch (_) {
    const textarea = document.createElement('textarea')
    textarea.value = path
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    textarea.remove()
    packMessage.value = `已复制文件路径：${path}`
  }
}
async function openPackedVideo() {
  const path = String(packResult.value?.path || '')
  if (!path || !window.pywebview?.api?.open_path) return
  try { await window.pywebview.api.open_path(path) } catch (err) { packMessage.value = String(err?.message || err || '无法打开成片') }
}
async function openPackedFolder() {
  const path = String(packResult.value?.path || packResult.value?.projectDir || '')
  if (!path || !window.pywebview?.api?.reveal_path) return
  try { await window.pywebview.api.reveal_path(path) } catch (err) { packMessage.value = String(err?.message || err || '无法打开所在文件夹') }
}
async function packageVideos() {
  if (packaging.value || !props.videos.length) return
  if (props.videos.some(item => item.exportBlocked)) {
    packWarning.value = true
    packMessage.value = '有分镜候选未通过人物或场景参考检查，暂不能作为确认成片打包；请先修正对应分镜。'
    return
  }
  if (!window.pywebview?.api?.package_project_videos) {
    packMessage.value = '当前客户端不支持打包功能'
    return
  }
  packaging.value = true
  packResult.value = null
  packWarning.value = false
  packMessage.value = '正在准备打包目录…'
  try {
    const payload = props.videos.map((item, index) => {
      const seam = props.seams?.[index - 1]
      return {
        fileId: String(item.fileId || ''),
        title: String(item.title || `成片 ${index + 1}`),
        sequencePrefix: sequencePrefix.value,
        occlusion: seam?.occlusion || item.occlusion || 'smoke_fog',
        momentum: seam?.momentum || item.momentum || 'push_in',
        mode: seam?.mode || item.mode || 'transition',
      }
    })
    const result = await window.pywebview.api.package_project_videos(
      props.projectTitle,
      payload,
      props.token,
    )
    const saved = Array.isArray(result?.saved) ? result.saved.length : 0
    const skipped = Array.isArray(result?.skipped) ? result.skipped.length : 0
    if (skipped > 0) {
      packWarning.value = true
      packMessage.value = `已下载 ${saved} 个分镜，但有 ${skipped} 个失败，未生成不完整成片；分镜目录：${result.projectDir}`
    } else if (result?.merged?.path) {
      packResult.value = {
        path: String(result.merged.path),
        name: String(result.merged.name || result.merged.path),
        projectDir: String(result.projectDir || ''),
      }
      packMessage.value = `文件名：${packResult.value.name}`
      // 只打开成片所在目录，不再使用 Explorer /select,，避免跳到“文档”。
      if (window.pywebview?.api?.reveal_path) {
        window.pywebview.api.reveal_path(packResult.value.path).catch(() => {})
      }
    } else if (result?.projectDir) {
      packWarning.value = true
      packMessage.value = `分镜已下载到：${result.projectDir}，但没有生成完整成片`
    }
  } catch (err) {
    packMessage.value = String(err?.message || err || '打包失败')
  } finally {
    packaging.value = false
  }
}
function cleanup() { cancelSelection(); fadingOutVideoId.value = ''; enteringVideoId.value = ''; isTransitioning.value = false; preSeekedVideoId = null; if (transitionTimer) { clearTimeout(transitionTimer); transitionTimer = null }; preTransitionTriggered = false; for (const v of playerVideos.values()) v.pause(); for (const rv of rawPlayerVideos.values()) rv.pause(); stopVideoFrameWatch?.(); stopVideoFrameWatch = null; stopPlaybackClock(); stopPlayheadDrag(false); playing.value = false; window.removeEventListener('keydown', onKeydown); document.body.style.overflow = previousBodyOverflow; previousFocus?.focus?.(); previousFocus = null }
function onKeydown(event) { if (event.key === 'Escape') close(); if (event.key === ' ' && !['INPUT', 'BUTTON', 'TEXTAREA', 'SELECT'].includes(event.target?.tagName) && !event.target?.isContentEditable) { event.preventDefault(); togglePlayback() } }
function onMainVideoMetadata(event, clip) { if (!clip) return; const value = Number(event.currentTarget.duration); if (Number.isFinite(value) && value > 0) measuredDurations[clip.id] = value }
function currentVideoClip() { return videoTimeline.value.find(clip => clip.id === activeVideo.value?.id) }
function updatePlaybackTime(video, mediaTime = video?.currentTime) {
  if (!video || video !== videoRef.value || draggingPlayhead.value || pendingSelection) return
  const clip = currentVideoClip()
  if (!clip) return
  const curMediaTime = Number(mediaTime) || video.currentTime || 0
  const duration = video.duration || 8
  const remaining = duration - curMediaTime
  currentTime.value = Math.min(totalDuration.value, clip.start + curMediaTime)
  keepPlayheadVisible()

  if (compareMode.value) {
    const rawV = rawPlayerVideos.get(activeVideo.value?.id)
    if (rawV && !rawV.paused && Math.abs(rawV.currentTime - curMediaTime) > 0.12) {
      try { rawV.currentTime = curMediaTime } catch (_) {}
    }
  }

  const index = videoTimeline.value.findIndex(item => item.id === activeVideo.value?.id)
  if (index >= 0 && index < videoTimeline.value.length - 1) {
    if (currentSeamIndex.value !== index && !preTransitionTriggered) {
      currentSeamIndex.value = index
    }
  }

  // 1. 提前 1.5 秒预解码下一镜第 0 秒，彻底消灭切换时的异步 seek 延迟与顿挫（消灭“顿一下”）
  if (remaining <= 1.5 && remaining > 0.25 && index >= 0 && index < videoTimeline.value.length - 1) {
    const next = videoTimeline.value[index + 1]
    if (next && preSeekedVideoId !== next.id) {
      preSeekedVideoId = next.id
      const nv = playerVideos.get(next.id)
      if (nv && (nv.currentTime > 0.05 || nv.paused)) {
        try { nv.currentTime = 0 } catch (_) {}
      }
    }
  }

  // 2. 接缝触发点：在距离上一镜自然终点仅剩 2 帧（约 0.06s）时切换，保证完整动作演完
  const isRaw = isRawMode.value
  const triggerThreshold = isRaw ? 0.03 : (currentSeamConfig.mode === 'matchCut' ? 0.05 : (currentSeamConfig.mode === 'exact' ? 0.08 : 0.20))
  if (playing.value && !preTransitionTriggered && curMediaTime > 0.4 && remaining <= triggerThreshold && index >= 0 && index < videoTimeline.value.length - 1) {
    preTransitionTriggered = true
    const next = videoTimeline.value[index + 1]
    if (next) {
      advanceToNextSeamless(next)
    }
  }
}
function onMainVideoTime(event) { updatePlaybackTime(event.currentTarget) }
function startPlaybackClock() {
  stopPlaybackClock()
  const video = videoRef.value
  if (!video) return
  playbackVideo = video
  playbackTick = (_, metadata) => {
    if (!playing.value || video !== videoRef.value) return
    updatePlaybackTime(video, metadata?.mediaTime)
    playbackFrame = typeof video.requestVideoFrameCallback === 'function'
      ? video.requestVideoFrameCallback(playbackTick)
      : requestAnimationFrame(playbackTick)
  }
  playbackFrame = typeof video.requestVideoFrameCallback === 'function'
    ? video.requestVideoFrameCallback(playbackTick)
    : requestAnimationFrame(playbackTick)
}
function stopPlaybackClock() {
  if (playbackFrame && playbackVideo) {
    if (typeof playbackVideo.cancelVideoFrameCallback === 'function') playbackVideo.cancelVideoFrameCallback(playbackFrame)
    else cancelAnimationFrame(playbackFrame)
  }
  playbackFrame = 0
  playbackVideo = null
  playbackTick = null
}
function onVideoPlay(event) {
  if (event.currentTarget !== videoRef.value) return
  playing.value = true
  startPlaybackClock()
  stopVideoFrameWatch?.()
  stopVideoFrameWatch = watchForDecodedVideoFrame(event.currentTarget, () => safeEmitVideoError(activeVideo.value))
  if (compareMode.value) {
    const rawV = rawPlayerVideos.get(activeVideoId.value)
    if (rawV) {
      if (videoRef.value && Math.abs(rawV.currentTime - videoRef.value.currentTime) > 0.12) {
        try { rawV.currentTime = videoRef.value.currentTime } catch (_) {}
      }
      rawV.play().catch(() => {})
    }
  }
}
function onVideoPause(event) {
  if (fadingOutVideoId.value && event.currentTarget === playerVideos.get(fadingOutVideoId.value)) return
  if (preTransitionTriggered) return
  if (event.currentTarget !== videoRef.value) return
  if (!pendingSelection) playing.value = false
  stopVideoFrameWatch?.()
  stopVideoFrameWatch = null
  stopPlaybackClock()
  if (compareMode.value) {
    const rawV = rawPlayerVideos.get(activeVideoId.value)
    if (rawV) {
      try { rawV.pause() } catch (_) {}
    }
  }
}
function onVolumeChange(event) { if (event.currentTarget !== videoRef.value) return; muted.value = event.currentTarget.muted }
function togglePlayback() {
  if (pendingSelection) { pendingSelection.resume = !pendingSelection.resume; playing.value = pendingSelection.resume; return }
  if (retrySelection) { const retry = retrySelection; selectVideo(retry.id, retry.offset, true); return }
  const video = videoRef.value
  if (!video) return
  if (video.ended) { selectVideo(videoTimeline.value[0]?.id, 0, true); return }
  if (video.paused) video.play().catch(() => { playing.value = false })
  else video.pause()
}
function toggleMuted() { const video = videoRef.value; if (!video) return; video.muted = !video.muted; muted.value = video.muted }
function cancelSelection() {
  videoSelectionVersion++
  pendingSelection?.controller.abort()
  pendingSelection = null
  retrySelection = null
  playbackError.value = ''
  playing.value = false
}
async function selectVideo(id, offset = 0, forceResume) {
  const clip = videoTimeline.value.find(item => item.id === id)
  if (!clip) return
  const resume = forceResume ?? pendingSelection?.resume ?? playing.value
  cancelSelection()
  preTransitionTriggered = false
  preSeekedVideoId = null
  fadingOutVideoId.value = ''
  enteringVideoId.value = ''
  isTransitioning.value = false
  if (transitionTimer) { clearTimeout(transitionTimer); transitionTimer = null }
  const version = videoSelectionVersion
  const selection = { id, offset, resume, controller: new AbortController() }
  pendingSelection = selection
  videoRef.value?.pause()
  playing.value = resume
  stopPlaybackClock()
  currentTime.value = clip.start + Math.max(0, Math.min(clip.duration, offset))
  await nextTick()
  const video = playerVideos.get(id)
  if (!video || version !== videoSelectionVersion) return
  try {
    video.muted = muted.value
    await prepareVideoFrame(video, offset, { signal: selection.controller.signal })
    if (version !== videoSelectionVersion || isUnmounted || !props.visible) return
    // Reveal only the decoded incoming picture. No opacity animation or source reload.
    video.muted = muted.value
    activeVideoId.value = id
    videoRef.value = video
    pendingSelection = null
    updatePlaybackTime(video)
    await nextTick()
    if (version !== videoSelectionVersion) return
    if (selection.resume) await video.play()
    else playing.value = false
    if (compareMode.value) {
      for (const [vId, rv] of rawPlayerVideos.entries()) {
        if (vId === id) {
          try {
            rv.currentTime = offset
            if (selection.resume) rv.play().catch(() => {})
            else rv.pause()
          } catch (_) {}
        } else {
          try { rv.pause() } catch (_) {}
        }
      }
    }
  } catch (error) {
    if (version !== videoSelectionVersion || error?.name === 'AbortError') return
    pendingSelection = null
    playing.value = false
    playbackError.value = error?.message || '分镜未能开始播放，点击播放可重试'
    retrySelection = { id, offset }
  }
}
function seekTimeline(time) {
  preTransitionTriggered = false
  preSeekedVideoId = null
  fadingOutVideoId.value = ''
  enteringVideoId.value = ''
  isTransitioning.value = false
  if (transitionTimer) { clearTimeout(transitionTimer); transitionTimer = null }
  const safe = Math.max(0, Math.min(totalDuration.value, Number(time) || 0))
  const clip = videoTimeline.value.find(item => safe >= item.start && safe < item.start + item.duration) || videoTimeline.value.at(-1)
  if (!clip) return
  const offset = Math.max(0, safe - clip.start)
  currentTime.value = safe
  if (pendingSelection || clip.id !== activeVideoId.value) selectVideo(clip.id, offset)
  else if (videoRef.value && Number.isFinite(videoRef.value.duration)) {
    retrySelection = null
    playbackError.value = ''
    videoRef.value.currentTime = Math.min(videoRef.value.duration, offset)
    if (compareMode.value) {
      const rawV = rawPlayerVideos.get(clip.id)
      if (rawV) {
        try { rawV.currentTime = Math.min(videoRef.value.duration, offset) } catch (_) {}
      }
    }
  }
}
function scrubTimelineAt(clientX) {
  const rect = timelineLaneRef.value?.getBoundingClientRect()
  if (!rect?.width) return
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  seekTimeline(ratio * timelineDuration.value)
}
function flushPlayheadDrag() { scrubFrame = 0; scrubTimelineAt(pendingScrubX) }
function movePlayheadDrag(event) {
  if (!draggingPlayhead.value) return
  pendingScrubX = event.clientX
  if (!scrubFrame) scrubFrame = requestAnimationFrame(flushPlayheadDrag)
}
function startPlayheadDrag(event) {
  draggingPlayhead.value = true
  scrubWasPlaying = pendingSelection?.resume ?? playing.value
  if (pendingSelection) pendingSelection.resume = false
  videoRef.value?.pause()
  playing.value = false
  pendingScrubX = event.clientX
  scrubTimelineAt(event.clientX)
  window.addEventListener('pointermove', movePlayheadDrag)
  window.addEventListener('pointerup', stopPlayheadDrag, { once: true })
  window.addEventListener('pointercancel', stopPlayheadDrag, { once: true })
}
function stopPlayheadDrag(resumePlayback = true) {
  if (!draggingPlayhead.value) return
  draggingPlayhead.value = false
  cancelAnimationFrame(scrubFrame)
  scrubFrame = 0
  window.removeEventListener('pointermove', movePlayheadDrag)
  window.removeEventListener('pointerup', stopPlayheadDrag)
  window.removeEventListener('pointercancel', stopPlayheadDrag)
  if (scrubWasPlaying && resumePlayback !== false) {
    if (pendingSelection) { pendingSelection.resume = true; playing.value = true }
    else { const version = videoSelectionVersion; nextTick(() => { if (version === videoSelectionVersion && props.visible) videoRef.value?.play().catch(() => {}) }) }
  }
  scrubWasPlaying = false
}
function advanceToNextSeamless(next) {
  if (!next) return
  const oldVideo = videoRef.value
  const oldId = activeVideoId.value
  const nextVideo = playerVideos.get(next.id)
  if (!nextVideo) {
    selectVideo(next.id, 0, true)
    return
  }

  const isRaw = isRawMode.value
  const shouldTransition = !isRaw || compareMode.value
  const activeMode = compareMode.value ? smoothMode.value : (currentSeamConfig.mode || 'transition')
  const transDuration = !shouldTransition ? 0 : (activeMode === 'matchCut' ? 120 : (activeMode === 'exact' ? 140 : 360))

  if (shouldTransition) {
    // 1. 激活转场特效与动能
    isTransitioning.value = true
    if (oldVideo && oldVideo !== nextVideo) {
      try { oldVideo.muted = true } catch (_) {}
    }
    if (oldId && oldId !== next.id) {
      fadingOutVideoId.value = oldId
    }
    enteringVideoId.value = next.id

    if (transitionTimer) clearTimeout(transitionTimer)
    transitionTimer = setTimeout(() => {
      if (oldVideo && oldVideo !== nextVideo) {
        try { oldVideo.pause() } catch (_) {}
      }
      fadingOutVideoId.value = ''
      enteringVideoId.value = ''
      isTransitioning.value = false
    }, transDuration)
  } else {
    // 纯原视频拼接：无遮挡、无运镜动画，两镜硬切
    isTransitioning.value = false
    fadingOutVideoId.value = ''
    enteringVideoId.value = ''
    if (oldVideo && oldVideo !== nextVideo) {
      try { oldVideo.pause() } catch (_) {}
    }
  }

  // 2. 转移主控到新视频
  nextVideo.muted = muted.value
  if (nextVideo.currentTime > 0.1) {
    try { nextVideo.currentTime = 0 } catch (_) {}
  }
  activeVideoId.value = next.id
  videoRef.value = nextVideo
  playing.value = true
  preTransitionTriggered = true

  // 3. 立即起播新视频并维持时钟运转
  const p = nextVideo.play()
  if (p !== undefined) {
    p.catch(() => {
      if (!muted.value) {
        nextVideo.muted = true
        nextVideo.play().catch(() => {})
      }
    })
  }
  startPlaybackClock()
  if (compareMode.value) {
    const oldRaw = rawPlayerVideos.get(oldId)
    if (oldRaw && oldRaw !== rawPlayerVideos.get(next.id)) {
      try { oldRaw.pause() } catch (_) {}
    }
    const nextRaw = rawPlayerVideos.get(next.id)
    if (nextRaw) {
      try {
        nextRaw.currentTime = 0
        nextRaw.play().catch(() => {})
      } catch (_) {}
    }
  }
  setTimeout(() => { preTransitionTriggered = false }, 800)
}
function advanceVideo(event) {
  if (fadingOutVideoId.value && event.currentTarget === playerVideos.get(fadingOutVideoId.value)) {
    return
  }
  if (event.currentTarget !== videoRef.value || pendingSelection || !props.visible) return
  const index = videoTimeline.value.findIndex(item => item.id === activeVideo.value?.id)
  const next = videoTimeline.value[index + 1]
  if (next) advanceToNextSeamless(next)
  else { playing.value = false; stopPlaybackClock() }
}
function keepPlayheadVisible() {
  if (timelineZoom.value <= 1 || draggingPlayhead.value) return
  const scroller = timelineScrollRef.value
  const lane = timelineLaneRef.value
  if (!scroller || !lane) return
  const scrollerRect = scroller.getBoundingClientRect()
  const laneRect = lane.getBoundingClientRect()
  const x = laneRect.left - scrollerRect.left + laneRect.width * timelinePosition.value
  const margin = 72
  if (x > scroller.clientWidth - margin) scroller.scrollLeft += x - scroller.clientWidth + margin
  else if (x < margin + 56) scroller.scrollLeft -= margin + 56 - x
}
function zoomTimeline(event) {
  const scroller = timelineScrollRef.value
  if (!scroller) return
  event.preventDefault()
  const oldZoom = timelineZoom.value
  const delta = event.deltaY || event.deltaX
  const nextZoom = Math.max(1, Math.min(8, oldZoom * Math.exp(-delta * .0018)))
  if (Math.abs(nextZoom - oldZoom) < .001) return
  const rect = scroller.getBoundingClientRect()
  const cursorX = Math.max(0, Math.min(scroller.clientWidth, event.clientX - rect.left))
  const anchor = (scroller.scrollLeft + cursorX) / Math.max(1, scroller.scrollWidth)
  timelineZoom.value = nextZoom
  nextTick(() => { scroller.scrollLeft = anchor * scroller.scrollWidth - cursorX })
}
function pointerRatio(event) { const rect = event.currentTarget.getBoundingClientRect(); return Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) }
function clipStyle(clip) { return { left: `${clip.start / timelineDuration.value * 100}%`, width: `${Math.max(3, clip.duration / timelineDuration.value * 100)}%` } }
// 胶片帧数：片段越宽/占比越大帧越多，2-6 帧足够看出内容；多了浪费 video 元素
function filmstripFrameCount(clip) {
  const base = clip.duration / Math.max(.1, totalDuration.value) * 12 * Math.sqrt(timelineZoom.value)
  return Math.max(2, Math.min(6, Math.ceil(base)))
}
// 每个 <video> 在 metadata 加载后 seek 到自己负责的时间点，浏览器原生显示该帧
function loadFilmstripFrame(event, index, count) {
  const video = event.currentTarget
  const duration = Number(video.duration)
  if (Number.isFinite(duration) && duration > 0) {
    video.currentTime = Math.max(0, Math.min(duration - 0.04, duration * ((index - 0.5) / count)))
  }
}
function formatTime(value) { const seconds = Math.max(0, Math.floor(Number(value) || 0)); return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}` }
</script>

<style scoped>
.track-dialog-overlay{position:fixed;z-index:16000;inset:0;display:grid;place-items:center;box-sizing:border-box;padding:12px 28px;background:var(--theme-overlay);backdrop-filter:blur(14px)}
.track-dialog{display:grid;width:min(1240px,calc(100vw - 56px));height:min(940px,calc(100vh - 24px));min-height:590px;grid-template-rows:72px minmax(0,1fr);overflow:hidden;border:1px solid var(--theme-border-subtle);border-radius:18px;outline:0;color:var(--theme-text-primary);background:var(--theme-bg-elevated);box-shadow:0 40px 120px var(--theme-shadow)}
.track-dialog-head{display:grid;grid-template-columns:minmax(0,1fr) auto 38px;align-items:center;gap:20px;padding:0 18px 0 24px;border-bottom:1px solid var(--theme-border-subtle);background:linear-gradient(180deg,var(--theme-bg-surface),var(--theme-bg-surface))}
.track-dialog-heading{display:grid;grid-template-columns:auto auto;align-items:baseline;justify-content:start;gap:4px 12px;min-width:0}.track-dialog-heading>span{color:var(--theme-accent-text);font:700 9px/1 Consolas,monospace;letter-spacing:.16em}.track-dialog-heading h2{margin:0;color:var(--theme-text-primary);font-size:17px}.track-dialog-heading p{grid-column:1/-1;overflow:hidden;margin:0;color:var(--theme-text-secondary);font-size:11px;text-overflow:ellipsis;white-space:nowrap}.track-dialog-summary{padding:7px 11px;border:1px solid var(--theme-border-subtle);border-radius:99px;color:var(--theme-text-secondary);background:var(--theme-bg-elevated);font-size:10px}.track-dialog-summary b{color:var(--theme-text-primary);font-size:11px}.track-close{display:grid;width:36px;height:36px;place-items:center;padding:0;border:1px solid var(--theme-border-subtle);border-radius:9px;color:var(--theme-text-secondary);background:var(--theme-bg-surface);cursor:pointer;transition:.16s}.track-close:hover{border-color:var(--theme-border-subtle);color:var(--theme-text-primary);background:var(--theme-bg-card-hover)}.track-close svg{width:17px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round}
.track-loading-wrap{display:grid;place-items:center;padding:40px}.track-dialog-state{display:grid;place-content:center;justify-items:center;gap:9px;color:var(--theme-text-secondary);text-align:center}.track-dialog-state strong{color:var(--theme-text-primary);font-size:14px}.track-dialog-state span{max-width:500px;font-size:12px;line-height:1.6}.track-dialog-state.error strong{color:var(--theme-danger-text)}.track-dialog-state.error span{color:var(--theme-danger-text)}
.track-editor{display:grid;min-height:0;grid-template-columns:264px minmax(0,1fr);grid-template-rows:minmax(0,1fr) 210px}.track-assets{display:grid;min-height:0;grid-template-rows:48px minmax(0,1fr);border-right:1px solid var(--theme-border-subtle);background:var(--theme-bg-elevated)}.track-assets>header{display:flex;height:48px;box-sizing:border-box;align-items:center;justify-content:space-between;padding:0 15px;border-bottom:1px solid var(--theme-border-subtle)}.track-assets header strong{color:var(--theme-text-primary);font-size:13px}.track-assets header span{display:grid;min-width:24px;height:24px;place-items:center;border-radius:6px;color:var(--theme-text-primary);background:var(--theme-bg-surface);font:11px/1 Consolas,monospace}.track-asset-list{padding:10px;overflow-y:auto;overflow-x:hidden;scrollbar-width:thin;scrollbar-color: var(--theme-scrollbar-thumb) transparent}.track-asset-list::-webkit-scrollbar{width:8px;height:8px}.track-asset-list::-webkit-scrollbar-track{margin:4px 0;background:transparent}.track-asset-list::-webkit-scrollbar-thumb{border:2px solid transparent;border-radius:99px;background-color:var(--theme-scrollbar-thumb);background-clip:padding-box;transition:background-color .15s}.track-asset-list::-webkit-scrollbar-thumb:hover{background-color:var(--theme-scrollbar-thumb-hover)}.track-asset-item{display:grid;width:100%;grid-template-columns:88px minmax(0,1fr);align-items:center;gap:11px;margin-bottom:6px;padding:8px;border:1px solid transparent;border-radius:9px;background:transparent;text-align:left;cursor:pointer;transition:.15s}.track-asset-item:hover{border-color:var(--theme-border-subtle);background:var(--theme-bg-card-hover)}.track-asset-item.active{border-color:var(--theme-border-strong);background:var(--theme-bg-card-hover);box-shadow:inset 3px 0 var(--theme-shadow)}.track-asset-item.hidden{opacity:.5}.track-asset-thumb{position:relative;display:grid;width:88px;height:52px;overflow:hidden;place-items:center;border:1px solid var(--theme-border-subtle);border-radius:6px;background:var(--theme-bg-elevated)}.track-asset-thumb video{width:100%;height:100%;object-fit:cover;pointer-events:none}.track-asset-thumb i{position:absolute;right:4px;bottom:4px;padding:3px 5px;border-radius:3px;color:var(--theme-text-primary);background:var(--theme-bg-elevated);font:700 9px/1 Consolas,monospace;font-style:normal}.track-asset-info{display:flex;flex-direction:column;gap:7px;min-width:0}.track-asset-meta{display:flex;align-items:center;gap:6px;min-width:0}.track-asset-list strong,.track-asset-list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.track-asset-list strong{color:var(--theme-text-primary);font-size:12px;line-height:1.25}.track-asset-list small{color:var(--theme-text-secondary);font-size:10px;flex:1 1 auto;min-width:0}.track-asset-toggle{flex:0 0 auto;display:grid;width:20px;height:20px;place-items:center;padding:0;border:1px solid var(--theme-border-subtle);border-radius:5px;color:var(--theme-text-secondary);background:var(--theme-bg-surface);cursor:pointer;transition:.15s}.track-asset-toggle:hover{border-color:var(--theme-border-subtle);color:var(--theme-text-primary);background:var(--theme-bg-card-hover)}.track-asset-toggle.off{color:var(--theme-text-primary);border-color:var(--theme-border-subtle)}.track-asset-toggle svg{width:12px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.track-player{display:flex;min-height:0;flex-direction:column;background:var(--theme-bg-elevated)}.track-player-head{position:relative;display:flex;flex:0 0 48px;box-sizing:border-box;align-items:center;justify-content:space-between;gap:16px;padding:0 16px;border-bottom:1px solid var(--theme-border-subtle);background:var(--theme-bg-elevated)}.track-player-head>div{display:flex;align-items:center;gap:8px}.track-player-head i{width:7px;height:7px;border-radius:50%;background:var(--theme-bg-elevated);box-shadow:0 0 9px var(--theme-shadow)}.track-player-head strong{color:var(--theme-text-primary);font-size:12px}.track-player-head>span{flex:1 1 auto;overflow:hidden;color:var(--theme-text-secondary);font-size:11px;text-overflow:ellipsis;white-space:nowrap}.track-pack-btn{flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 13px;border:1px solid var(--theme-border-subtle);border-radius:8px;color:var(--theme-text-primary);background:var(--theme-bg-surface);cursor:pointer;font-size:12px;transition:border-color .15s ease,color .15s ease,background .15s ease}.track-pack-btn:hover:not(:disabled){border-color:var(--theme-border-subtle);background:var(--theme-bg-card-hover)}.track-pack-btn:disabled{cursor:not-allowed;opacity:.55}.track-pack-btn svg{width:14px;height:14px;flex:0 0 auto}.track-pack-spin{width:13px;height:13px;flex:0 0 auto;border:2px solid var(--theme-border-subtle);border-top-color:var(--theme-border-subtle);border-radius:50%;animation:track-pack-spin .8s linear infinite}@keyframes track-pack-spin{to{transform:rotate(360deg)}}.track-pack-result{position:absolute;z-index:4;top:5px;right:360px;bottom:5px;left:164px;display:flex;min-width:0;box-sizing:border-box;align-items:center;gap:10px;margin:0;padding:4px 8px;border:1px solid var(--theme-border-subtle);border-radius:8px;color:var(--theme-text-primary);background:var(--theme-bg-elevated);font-size:10px;box-shadow:0 4px 14px var(--theme-shadow)}.track-pack-result.success{border-color:var(--theme-success-border);background:var(--theme-bg-surface)}.track-pack-result.warning{border-color:var(--theme-accent-border);background:var(--theme-bg-surface)}.track-pack-result-main{display:flex;min-width:0;flex:1 1 auto;align-items:center;gap:8px;overflow:hidden}.track-pack-result-main strong{flex:0 0 auto;color:var(--theme-text-primary);font-size:11px;white-space:nowrap}.track-pack-result-main span,.track-pack-result-main code{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.track-pack-result-main span{flex:0 1 auto;color:var(--theme-text-secondary)}.track-pack-result-main code{flex:1 1 auto;color:var(--theme-success-text);font:10px/1.2 Consolas,monospace}.track-pack-result-actions{display:flex;flex:0 0 auto;gap:4px}.track-pack-result-actions button{height:26px;padding:0 7px;border:1px solid var(--theme-border-subtle);border-radius:6px;color:var(--theme-text-primary);background:var(--theme-bg-surface);cursor:pointer;font-size:10px;white-space:nowrap}.track-pack-result-actions button:hover{border-color:var(--theme-border-subtle);background:var(--theme-bg-card-hover)}.track-monitor{position:relative;display:grid;flex:1 1 auto;min-height:0;margin:14px 18px 16px;overflow:hidden;border:1px solid var(--theme-border-subtle);border-radius:12px;background:var(--theme-bg-elevated);box-shadow:0 18px 45px var(--theme-shadow)}.track-player-stage{position:relative;display:grid;min-height:0;place-items:center;overflow:hidden;background:radial-gradient(circle at 50% 35%,var(--theme-bg-surface),var(--theme-bg-elevated) 70%)}
.track-player-stage>video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:var(--theme-bg-elevated);cursor:pointer;opacity:0;pointer-events:none;transform:translate3d(0,0,0) scale(1);transition:opacity .32s ease-in-out,transform .34s cubic-bezier(0.2,0.85,0.35,1);will-change:transform,opacity}
.track-player-stage>video.active{opacity:1;pointer-events:auto;z-index:2;transform:translate3d(0,0,0) scale(1)}
.track-player-stage>video.fading-out{opacity:0;pointer-events:none;z-index:1}

/* 运镜动能方向 (Camera Momentum) 视觉联动 */
.track-player-stage.mom-push_in>video.fading-out{transform:translate3d(0,0,0) scale(1.07)}
.track-player-stage.mom-push_in>video.entering{animation:mom-enter-push .34s ease-out forwards}
@keyframes mom-enter-push{0%{transform:scale(1.04);opacity:0}100%{transform:scale(1);opacity:1}}

.track-player-stage.mom-pull_out>video.fading-out{transform:translate3d(0,0,0) scale(0.94)}
.track-player-stage.mom-pull_out>video.entering{animation:mom-enter-pull .34s ease-out forwards}
@keyframes mom-enter-pull{0%{transform:scale(0.96);opacity:0}100%{transform:scale(1);opacity:1}}

.track-player-stage.mom-pan_left>video.fading-out{transform:translate3d(-10%,0,0) scale(1.02)}
.track-player-stage.mom-pan_left>video.entering{animation:mom-enter-pan-left .34s cubic-bezier(0.2,0.85,0.35,1) forwards}
@keyframes mom-enter-pan-left{0%{transform:translate3d(10%,0,0) scale(1.02);opacity:0}100%{transform:translate3d(0,0,0) scale(1);opacity:1}}

.track-player-stage.mom-pan_right>video.fading-out{transform:translate3d(10%,0,0) scale(1.02)}
.track-player-stage.mom-pan_right>video.entering{animation:mom-enter-pan-right .34s cubic-bezier(0.2,0.85,0.35,1) forwards}
@keyframes mom-enter-pan-right{0%{transform:translate3d(-10%,0,0) scale(1.02);opacity:0}100%{transform:translate3d(0,0,0) scale(1);opacity:1}}

.track-player-stage.mom-crane_down>video.fading-out{transform:translate3d(0,9%,0) scale(1.01)}
.track-player-stage.mom-crane_down>video.entering{animation:mom-enter-crane-down .34s ease-out forwards}
@keyframes mom-enter-crane-down{0%{transform:translate3d(0,-9%,0) scale(1.01);opacity:0}100%{transform:translate3d(0,0,0) scale(1);opacity:1}}

.track-player-stage.mom-orbit_low>video.fading-out{transform:rotate(1.8deg) scale(1.03)}
.track-player-stage.mom-orbit_low>video.entering{animation:mom-enter-orbit .34s ease-out forwards}
@keyframes mom-enter-orbit{0%{transform:rotate(-1.8deg) scale(1.03);opacity:0}100%{transform:rotate(0) scale(1);opacity:1}}

/* 遮挡物/转场光效 (Occlusion Effects) */
.seam-blade-gleam{position:absolute;inset:-50%;z-index:10;pointer-events:none;background:linear-gradient(135deg,transparent 36%,rgba(255,255,255,0.85) 46%,#ffffff 50%,rgba(255,255,255,0.85) 54%,transparent 64%);animation:blade-slash .24s cubic-bezier(0.16,1,0.3,1) forwards}
@keyframes blade-slash{0%{transform:translate3d(-60%,-60%,0) rotate(-15deg);opacity:0}40%{opacity:1}100%{transform:translate3d(60%,60%,0) rotate(-15deg);opacity:0}}

.seam-dark-dip{position:absolute;inset:0;z-index:10;pointer-events:none;background:rgba(8,8,12,0.96);animation:dark-dip .34s ease-in-out forwards}
@keyframes dark-dip{0%{opacity:0}42%{opacity:.95}58%{opacity:.95}100%{opacity:0}}

.track-player-stage.occ-stone_pillar>video.entering,
.track-player-stage.occ-cloak_pass>video.entering,
.track-player-stage.occ-tree_trunk>video.entering{clip-path:inset(0 0 0 0);animation:sweep-reveal .32s cubic-bezier(0.2,0.8,0.25,1) forwards}
@keyframes sweep-reveal{0%{clip-path:inset(0 100% 0 0)}100%{clip-path:inset(0 0 0 0)}}

.track-player-stage.occ-ground_shadow>video.entering{animation:ground-sweep .32s ease-out forwards}
@keyframes ground-sweep{0%{clip-path:inset(100% 0 0 0)}100%{clip-path:inset(0 0 0 0)}}
.track-pack-prefix{flex:0 0 auto;display:flex;height:30px;box-sizing:border-box;align-items:center;gap:7px;padding:0 5px 0 9px;border:1px solid var(--theme-border-subtle);border-radius:8px;color:var(--theme-text-secondary);background:var(--theme-bg-elevated);font-size:10px}.track-pack-prefix input{width:66px;height:22px;box-sizing:border-box;padding:0 7px;border:1px solid var(--theme-border-subtle);border-radius:5px;outline:0;color:var(--theme-text-primary);background:var(--theme-bg-input);font:11px/1 Consolas,monospace}.track-pack-prefix input::placeholder{color:var(--theme-text-secondary)}.track-pack-prefix input:focus{border-color:var(--theme-border-strong);box-shadow:0 0 0 2px var(--theme-shadow)}.track-pack-prefix input:disabled{opacity:.55}
.track-player-controls{position:absolute;z-index:3;bottom:12px;left:50%;display:grid;box-sizing:border-box;width:min(640px,calc(100% - 28px));height:56px;grid-template-columns:40px minmax(120px,1fr) 40px;align-items:center;gap:13px;padding:0 13px;border:1px solid var(--theme-border-subtle);border-radius:11px;background:var(--theme-bg-elevated);box-shadow:0 10px 30px var(--theme-shadow);opacity:0;pointer-events:none;transform:translate(-50%,8px);transition:opacity .18s ease,transform .18s ease;backdrop-filter:blur(12px) saturate(120%);-webkit-backdrop-filter:blur(12px) saturate(120%)}.track-monitor:hover .track-player-controls,.track-player-controls:focus-within{opacity:1;pointer-events:auto;transform:translate(-50%,0)}.track-player-controls>button{display:grid;width:38px;height:38px;place-items:center;padding:0;border:1px solid var(--theme-border-subtle);border-radius:9px;color:var(--theme-text-primary);background:var(--theme-accent-soft);cursor:pointer;transition:.15s}.track-player-controls>button:hover,.track-player-controls>button:focus-visible{border-color:var(--theme-border-strong);outline:0;color:var(--theme-text-primary);background:var(--theme-accent-soft)}.track-player-controls button svg{width:18px;fill:currentColor;stroke:currentColor;stroke-width:1.4;stroke-linecap:round;stroke-linejoin:round}.track-progress-control{display:grid;min-width:0;gap:7px}.track-progress-control>div{display:flex;align-items:center;justify-content:space-between}.track-time{color:var(--theme-text-secondary);font:10px/1 Consolas,monospace}.track-time.current{color:var(--theme-text-primary)}.track-progress-control input{width:100%;height:6px;margin:0;appearance:none;border-radius:99px;background:linear-gradient(90deg,var(--theme-bg-input) var(--track-progress),var(--theme-accent-soft) var(--track-progress));cursor:pointer}.track-progress-control input::-webkit-slider-thumb{width:15px;height:15px;appearance:none;border:3px solid var(--theme-border-subtle);border-radius:50%;background:var(--theme-accent);box-shadow:0 0 0 1px var(--theme-shadow);color:var(--theme-text-on-accent)}.track-progress-control input:focus-visible{outline:2px solid var(--theme-border-strong);outline-offset:4px}@media(hover:none){.track-player-controls{opacity:1;pointer-events:auto;transform:translate(-50%,0)}}
.project-timeline{grid-column:1/-1;display:grid;min-height:0;grid-template-rows:42px minmax(0,1fr);border-top:1px solid var(--theme-border-subtle);background:var(--theme-bg-elevated)}.project-timeline>header{display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid var(--theme-border-subtle)}.project-timeline>header>div{display:flex;align-items:center;gap:8px}.project-timeline header strong{font-size:11px}.project-timeline header span{color:var(--theme-text-secondary);font:8px/1 Consolas,monospace;letter-spacing:.12em}.project-timeline header p{margin:0;color:var(--theme-text-secondary);font-size:9px}.timeline-scroll{min-width:0;overflow:auto}.timeline-ruler{position:relative;height:30px;margin-left:56px;border-bottom:1px solid var(--theme-border-subtle);background:repeating-linear-gradient(90deg,transparent 0,transparent calc(10% - 1px),var(--theme-accent-soft) calc(10% - 1px),var(--theme-accent-soft) 10%)}.timeline-ruler span{position:absolute;top:11px;color:var(--theme-text-secondary);font:8px/1 Consolas,monospace;transform:translateX(-50%)}.timeline-row{display:grid;height:108px;grid-template-columns:56px minmax(0,1fr)}.timeline-label{position:relative;display:grid;place-items:center;border-right:1px solid var(--theme-border-subtle);color:var(--theme-text-secondary);font:700 10px/1 Consolas,monospace}.timeline-label::before{position:absolute;top:10px;bottom:10px;left:0;width:2px;background:var(--theme-accent-text);content:""}.timeline-lane{position:relative;margin:8px 12px 8px 0;background:var(--theme-accent-soft)}.timeline-clip{position:absolute;top:5px;bottom:5px;display:flex;min-width:52px;align-items:flex-end;overflow:hidden;padding:0;border:1px solid var(--theme-accent-border);border-radius:5px;color:var(--theme-text-primary);background:var(--theme-accent-soft);cursor:pointer}.timeline-clip:hover{border-color:var(--theme-accent-border)}.timeline-clip.active{border-color:var(--theme-accent-border);box-shadow:0 0 0 1px var(--theme-shadow),0 7px 22px var(--theme-shadow)}.timeline-clip>strong{position:relative;z-index:2;display:block;width:100%;overflow:hidden;padding:5px 7px;background:linear-gradient(180deg,transparent,var(--theme-bg-elevated));font-size:8px;text-align:left;text-overflow:ellipsis;white-space:nowrap}.clip-filmstrip{position:absolute;inset:0;display:flex;opacity:.82;pointer-events:none}.clip-filmstrip video{flex:1 0 0;min-width:0;height:100%;object-fit:cover}.timeline-playhead{position:absolute;z-index:5;top:-30px;bottom:0;width:1px;background:var(--theme-danger-text);pointer-events:none}.timeline-playhead::before{position:absolute;top:0;left:-4px;width:9px;height:7px;background:var(--theme-danger-text);clip-path:polygon(0 0,100% 0,50% 100%);content:""}
.timeline-scroll{overflow-x:auto;overflow-y:hidden}.timeline-content{height:100%;min-width:100%}.timeline-content .timeline-ruler{box-sizing:border-box;width:calc(100% - 56px)}.timeline-content .timeline-row{width:100%}.timeline-content .clip-filmstrip video{flex:1 0 0;min-width:0}
.timeline-playhead{width:17px;padding:0;border:0;outline:0;color:var(--theme-text-primary);background:transparent;cursor:ew-resize;pointer-events:auto;transform:translateX(-50%);touch-action:none}.timeline-playhead::after{position:absolute;top:0;bottom:0;left:8px;width:1px;background:var(--theme-accent);box-shadow:0 0 6px var(--theme-shadow);content:"";color:var(--theme-text-on-accent)}.timeline-playhead::before{z-index:1;left:4px;background:var(--theme-accent);color:var(--theme-text-on-accent)}.timeline-playhead:focus-visible::after{left:7.5px;width:2px}.timeline-playhead.dragging{cursor:grabbing}
.track-dialog-fade-enter-active,.track-dialog-fade-leave-active{transition:opacity .18s}.track-dialog-fade-enter-from,.track-dialog-fade-leave-to{opacity:0}@media(max-width:1100px){.track-pack-result{right:246px;left:150px}.track-pack-result-actions button{padding:0 5px;font-size:9px}}@media(max-width:850px),(max-height:650px){.track-dialog-overlay{padding:10px}.track-dialog{width:calc(100vw - 20px);height:calc(100vh - 20px);min-height:0}.track-editor{grid-template-columns:210px minmax(0,1fr);grid-template-rows:minmax(0,1fr) 170px}.track-monitor{margin:8px 10px 10px}.track-player-controls{bottom:8px;width:calc(100% - 20px)}.project-timeline{grid-template-rows:36px minmax(0,1fr)}.timeline-row{height:94px}.track-pack-result{right:10px;left:10px}.track-pack-result-actions button{padding:0 6px;font-size:9px}}
.track-editor{grid-template-rows:minmax(0,1fr) 180px}.timeline-row{height:90px}
@media(max-width:850px),(max-height:650px){.track-editor{grid-template-rows:minmax(0,1fr) 170px}.timeline-row{height:78px}}
</style>

<style scoped>
.track-review-warning { flex: 0 0 41px; height: 41px; box-sizing: border-box; overflow: hidden; padding: 10px 16px; color: #854d0e; background: #fef9c3; font-size: 13px; line-height: 21px; white-space: nowrap; text-overflow: ellipsis; }
.track-review-warning.empty { background: transparent; }
.track-playback-error { position: absolute; z-index: 4; top: 12px; left: 12px; right: 12px; padding: 10px; border-radius: 8px; background: var(--theme-bg-elevated); color: var(--theme-danger-text); font-size: 13px; }
.track-assembly{min-height:0;overflow:auto;padding:20px;background:var(--theme-bg-elevated)}.track-assembly-toggle{margin-left:12px;padding:8px 12px;border:1px solid var(--theme-accent-border);border-radius:8px;background:var(--theme-accent-soft);color:var(--theme-accent-text);font:inherit;font-size:12px;cursor:pointer}.track-asset-toggle[aria-disabled="true"]{opacity:.45;cursor:default}
</style>

<style scoped>

/* 接缝实时调换工具栏 */
.track-seam-live-bar {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 10px 18px 0;
  padding: 10px 16px;
  background: var(--theme-bg-surface);
  border: 1px solid var(--theme-border-subtle);
  border-radius: 12px;
  box-shadow: 0 4px 14px var(--theme-shadow);
}
.seam-bar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.seam-bar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.seam-bar-tag {
  padding: 2px 8px;
  border-radius: 6px;
  background: #ffedd5;
  color: #c2410c;
  font-weight: 700;
  font-size: 11px;
}
.seam-bar-desc {
  color: var(--theme-text-secondary);
  font-size: 12px;
}
.seam-bar-btns {
  display: flex;
  align-items: center;
  gap: 8px;
}
.btn-seam-replay {
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 7px;
  background: var(--theme-bg-elevated);
  color: var(--theme-text-primary);
  font-size: 12px;
  cursor: pointer;
  transition: all .15s ease;
}
.btn-seam-replay:hover {
  border-color: #ea580c;
  color: #ea580c;
  background: #fff7ed;
}
.btn-seam-save {
  height: 28px;
  padding: 0 14px;
  border: 1px solid #ea580c;
  border-radius: 7px;
  background: #ea580c;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  transition: all .15s ease;
}
.btn-seam-save.is-saved {
  background: #10b981;
  border-color: #10b981;
}
.seam-bar-options {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.option-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.option-name {
  width: 65px;
  flex: 0 0 65px;
  color: var(--theme-text-secondary);
  font-weight: 600;
}
.option-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.seam-chip-btn {
  padding: 3px 10px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 6px;
  background: var(--theme-bg-elevated);
  color: var(--theme-text-secondary);
  font-size: 11.5px;
  cursor: pointer;
  transition: all .14s ease;
}
.seam-chip-btn:hover {
  border-color: #ea580c;
  color: var(--theme-text-primary);
}
.seam-chip-btn.active {
  border-color: #ea580c;
  background: #fff7ed;
  color: #c2410c;
  font-weight: 700;
}

/* 原视频纯拼接模式 & 镜头接演/首尾帧一致模式：无位移缩放，无抖动，自然流淌 */
.track-player-stage.occ-none > video,
.track-player-stage.mode-raw > video {
  clip-path: none !important;
  animation: none !important;
}
.track-player-stage.mom-none > video,
.track-player-stage.mode-raw > video,
.track-player-stage.mode-matchCut > video,
.track-player-stage.mode-exact > video {
  transform: none !important;
  animation: none !important;
}
.track-player-stage.mode-matchCut > video,
.track-player-stage.mode-exact > video {
  transition: opacity .08s linear !important;
}
.track-player-stage.mode-raw > video {
  transition: none !important;
}

.btn-seam-raw-toggle {
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 7px;
  background: var(--theme-bg-elevated);
  color: var(--theme-text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s ease;
}
.btn-seam-raw-toggle:hover {
  border-color: #64748b;
  color: #0f172a;
  background: #f1f5f9;
}
.btn-seam-raw-toggle.is-raw {
  background: #334155;
  border-color: #1e293b;
  color: #ffffff;
}

.seam-engine-badge.raw-badge {
  background: rgba(100, 116, 139, 0.12);
  border-color: rgba(100, 116, 139, 0.35);
  color: #334155;
}
.seam-engine-badge.raw-badge strong {
  color: #1e293b;
}
.seam-engine-badge.raw-badge span {
  color: #64748b;
}
.engine-pulse-dot.dot-gray {
  background: #94a3b8;
  box-shadow: none;
  animation: none;
}

/* 全自动消顿引擎标识 */
.seam-engine-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 9999px;
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.45);
  color: #065f46;
  font-size: 11px;
  cursor: help;
  user-select: none;
}
.seam-engine-badge strong {
  color: #047857;
  font-weight: 700;
}
.seam-engine-badge span {
  color: #059669;
  font-size: 10.5px;
}
.engine-pulse-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
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

/* 上下两版对比模式容器与分屏 */
.track-monitor.is-split-compare {
  display: flex !important;
  flex-direction: column !important;
}
.compare-split-container {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  gap: 8px;
  padding: 8px;
  box-sizing: border-box;
}
.compare-split-pane {
  flex: 1 1 50%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  border: 1px solid var(--theme-border-subtle);
  background: var(--theme-bg-surface);
}
.compare-split-pane .track-player-stage {
  flex: 1 1 auto;
  min-height: 0;
  height: 100%;
  width: 100%;
  position: relative;
}
.split-pane-header {
  position: absolute;
  top: 8px;
  left: 12px;
  z-index: 10;
  pointer-events: none;
}
.split-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.25);
}
.split-badge.raw {
  background: rgba(30, 41, 59, 0.88);
  color: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.4);
}
.split-badge.smooth {
  background: rgba(6, 78, 59, 0.88);
  color: #a7f3d0;
  border: 1px solid rgba(52, 211, 153, 0.5);
}
.btn-seam-compare-toggle {
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 7px;
  background: var(--theme-bg-elevated);
  color: var(--theme-text-primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all .15s ease;
}
.btn-seam-compare-toggle:hover {
  border-color: #3b82f6;
  color: #2563eb;
  background: #eff6ff;
}
.btn-seam-compare-toggle.is-active {
  background: #2563eb;
  border-color: #1d4ed8;
  color: #ffffff;
}
</style>
