<script setup>
import { computed } from 'vue'
import UiSelect from './UiSelect.vue'
import { extractRoleVoiceInstruction, STANDARD_VOICE_PRESETS } from '../utils/audioContract.js'
const props = defineProps({
  general: Boolean,
  prompt: { type: String, default: '' },
  contract: { type: Object, required: true }, bindings: { type: Object, default: () => ({}) },
  root: { type: String, default: '' }, connection: { type: Object, default: () => ({}) },
  quick: Boolean, audioApplied: Boolean, hasAppliedAudio: Boolean, legacyMix: Boolean, busy: Boolean, connecting: Boolean, progress: { type: Object, default: null },
  audio: { type: Object, default: null }, stale: Boolean, hasVideo: Boolean, mixing: Boolean, mixed: Boolean,
  alignment: { type: Object, default: null }, aligning: Boolean, alignmentMessage: String,
})
const emit = defineEmits(['quick', 'play-current', 'binding', 'root', 'connect', 'start', 'generate', 'convert', 'accept-review', 'cancel', 'play', 'mix', 'restore', 'align', 'timing', 'preview'])
const converted = computed(() => props.audio?.mode === 'voice-conversion')
const roles = computed(() => [...new Set((props.contract?.lines || []).map((_, i) => props.contract?.roles?.[i] || '未标注角色'))])
const totalDialogueChars = computed(() => (props.contract?.lines || []).join('').length)

function roleDeliveryHint(role) {
  if (!props.contract?.roles || !props.contract?.deliveries) return ''
  for (let i = 0; i < props.contract.roles.length; i++) {
    if ((props.contract.roles[i] || '未标注角色') === role && props.contract.deliveries[i]) {
      return props.contract.deliveries[i]
    }
  }
  return ''
}

function roleTimbreHint(role) {
  return extractRoleVoiceInstruction(props.prompt || '', role, roleDeliveryHint(role))
}

const voiceOptions = computed(() => [{ value: '', label: '按描述建立角色声音（自动复用）' },
  ...(props.connection.voices || []).map(v => ({ value: v.id, label: v.description ? `${v.id} · ${v.description}` : v.id }))])
function update(role, field, value) { emit('binding', { role, field, value }) }
const canMix = computed(() => {
  if (converted.value && props.audio.conversionReview?.status !== 'matched_text' && !props.audio.conversionReviewAccepted) return false
  if (!props.audio || !props.hasVideo) return false
  if (!props.alignment?.rows?.length) return true
  let previous = 0
  return props.alignment.rows.every(r => {
    const valid = Number.isFinite(r.start) && Number.isFinite(r.end) && r.start >= previous - 0.05 && r.end - r.start >= 0.12 && r.end <= (props.alignment.videoDuration || 9999) + .02
    if (valid) previous = r.end
    return valid
  })
})
const working = computed(() => props.busy || props.aligning || props.mixing || props.quick)
const hasMissingTiming = computed(() => {
  if (!props.alignment?.rows?.length) return false
  return props.alignment.rows.some(r => !Number.isFinite(r.start) || !Number.isFinite(r.end) || r.end - r.start < 0.12)
})
const needsTiming = computed(() => hasMissingTiming.value)
const applyBlockReason = computed(() => {
  if (!props.audio || props.audioApplied) return ''
  if (!props.hasVideo) return ''
  if (props.stale) return '台词或角色声音已变化，请重新生成配音。'
  if (hasMissingTiming.value) return props.hasAppliedAudio ? '新配音的说话位置尚未填写；当前视频已应用的配音仍保留。' : '尚未获取到说话时间，请定位或在高级设置填写说话时间。'
  if (!canMix.value) return '时间超出视频范围或台词顺序重叠，请调整后应用。'
  return ''
})
const timingAdvice = computed(() => {
  if (!props.hasVideo || !props.alignment?.rows?.length) return ''
  const rows = props.alignment.rows
  const totalWindow = rows.reduce((acc, r) => acc + (Number.isFinite(r.start) && Number.isFinite(r.end) ? Math.max(0, r.end - r.start) : 0), 0)
  if (totalWindow <= 0.1) return ''
  const currentChars = (props.contract?.lines || []).join('').length
  const minChars = Math.max(2, Math.floor(totalWindow * 2.8))
  const maxChars = Math.max(3, Math.ceil(totalWindow * 3.6))
  if (currentChars > maxChars + 3) {
    return `💡 本镜画面发声窗口约 ${totalWindow.toFixed(1)} 秒（最佳容量 ${minChars}~${maxChars} 字，当前 ${currentChars} 字）。字数偏多时建议精简台词，或使用【原声换音色】保持原片口型与节奏。`
  }
  return `💡 本镜画面发声窗口约 ${totalWindow.toFixed(1)} 秒，台词容量匹配（建议 ${minChars}~${maxChars} 字）。`
})
function timing(index, field, value) { emit('timing', { index, field, value: field === 'confirmed' ? value : value === '' ? null : Number(value) }) }
</script>

<template>
  <section class="breeze-panel" aria-label="Breeze 本地分镜配音">
    <header>
      <div>
        <strong>{{ general ? '旁白与人声' : '本镜配音' }}</strong>
        <p>{{ general ? '按镜头文案制作旁白，保留原视频与原声。' : '自动定位说话位置，保留停顿，不拉慢声音。' }}</p>
      </div>
      <em :class="{ ready: connection.ready }">{{ connection.ready ? '本机已连接' : '未连接' }}</em>
    </header>

    <!-- 📢 已识别本镜台词与旁白展示卡片 -->
    <div v-if="contract.lines && contract.lines.length" class="dubbing-dialogue-card">
      <div class="dubbing-dialogue-head">
        <div class="dubbing-dialogue-title">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 14h-2v-2h2v2zm0-4h-2V7h2v5z"/></svg>
          <strong>已识别本镜{{ contract.lines.some((_, i) => contract.roles[i] === '旁白') ? '台词 / 旁白' : '台词' }}</strong>
          <span class="dubbing-count-pill">共 {{ contract.lines.length }} 句 · {{ totalDialogueChars }} 字</span>
        </div>
      </div>
      <div class="dubbing-lines-stack">
        <div v-for="(line, i) in contract.lines" :key="i" class="dubbing-line-bubble">
          <div class="dubbing-line-meta">
            <span class="role-pill" :class="{ 'narrator-pill': contract.roles[i] === '旁白' }">
              {{ contract.roles[i] === '旁白' ? '🎙️ 旁白' : `🗣️ ${contract.roles[i] || '未标注角色'}` }}
            </span>
            <span v-if="contract.deliveries && contract.deliveries[i]" class="delivery-pill">
              语气: {{ contract.deliveries[i] }}
            </span>
          </div>
          <div class="dubbing-line-content">
            “{{ line }}”
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="!contract.explicit" class="dubbing-empty-state error">
      <strong>⚠️ 台词格式提示</strong>
      <p>{{ contract.errors.join('；') }}</p>
      <small>支持格式：<code>对白：旁白（低沉沧桑）：“台词内容”</code> 或 <code>角色名（咬牙）：“台词内容”</code></small>
    </div>
    <div v-else class="dubbing-empty-state">
      <span>💡 本镜暂无对白或旁白。可在【画面与提示词】中添加：<code>对白：旁白（语气）：“台词内容”</code> 或 <code>角色名：“台词内容”</code></span>
    </div>

    <div class="dubbing-state" :class="{ pending: legacyMix || (audio && !audioApplied) }" role="status">
      <template v-if="stale">角色声音或台词已修改 · 视频仍是旧配音，请生成并替换。</template>
      <template v-else-if="legacyMix">当前视频还是旧版配音，请重新生成并替换。</template>
      <template v-else-if="audioApplied">配音已替换到视频 · 点击播放查看效果</template>
      <template v-else-if="audio && hasAppliedAudio">当前视频保留已应用的配音；新生成的配音尚未应用。{{ needsTiming ? '本次定位未完成，原成片不受影响。' : '可沿用已确认的时间，应用新配音。' }}</template>
      <template v-else-if="audio">配音已保存，可复用；尚未替换当前视频。{{ !hasVideo ? '视频生成完成后可一键对齐替换。' : needsTiming ? '需要核对新视频的说话位置。' : '可按当前时间表应用配音。' }}</template>
      <template v-else>选择角色声音后，点下方按钮即可制作。</template>
    </div>

    <details v-if="roles.length" class="breeze-settings" open>
      <summary>角色声音设定 <small>{{ roles.join('、') }}</small></summary>
      <div class="breeze-settings-content">
        <div v-for="role in roles" :key="role" class="breeze-role">
          <div class="breeze-role-head">
            <strong>{{ role === '旁白' ? '🎙️ 旁白' : role }}</strong>
            <span class="role-locked-tag">🔒 全剧统一音色 · 全片保持一致声线</span>
            <span v-if="roleTimbreHint(role)" class="role-cue-tag" :title="`已从分镜提示词提取音色`">
              🎧 音色提示: {{ roleTimbreHint(role).replace(/，普通话，清晰自然，语速适中$/, '') }}
            </span>
          </div>
          <UiSelect :model-value="bindings[role]?.voiceId || ''" :options="voiceOptions" :disabled="working" @update:model-value="update(role, 'voiceId', $event)" />
          <textarea
            :value="bindings[role]?.instruction || roleTimbreHint(role)"
            :disabled="working"
            :aria-label="`${role}的声音描述`"
            rows="2"
            :placeholder="roleTimbreHint(role) || '描述角色音色和语气，如：低沉浑厚男声、沧桑稳重、清晰普通话'"
            @change="update(role, 'instruction', $event.target.value)"
          ></textarea>
          <div class="preset-pills-row">
            <span class="preset-label">快捷行业音色模板:</span>
            <button
              v-for="preset in STANDARD_VOICE_PRESETS"
              :key="preset.id"
              type="button"
              class="preset-pill-btn"
              :title="preset.text"
              @click.stop="update(role, 'instruction', preset.text)"
            >
              {{ preset.label }}
            </button>
          </div>
        </div>
        <small>同一项目复用角色声音，修改后需重新生成。</small>
      </div>
    </details>

    <div v-if="!connection.ready" class="connect-actions"><span>{{ connection.message || '先连接本机 Breeze，再制作配音。' }}</span><button :disabled="connecting || working" @click="emit('connect')">重新连接</button><button :disabled="connecting || working" @click="emit('start')">启动 Breeze</button></div>
    <p v-if="!contract.explicit" class="breeze-warning">{{ contract.errors.join('；') }}</p>
    <p v-else-if="!contract.lines.length">{{ general ? '本镜没有旁白或对白，可保留原声；需要人声时，在画面文案中添加旁白。' : '本镜无对白，无需配音。' }}</p>
    <template v-else>
      <div class="main-actions">
        <button v-if="audio && hasVideo && !audioApplied" type="button" class="primary" :disabled="working || stale" @click="emit('mix')">{{ !alignment || hasMissingTiming ? '重新对齐并应用已有配音' : '应用已有配音到视频' }}</button>
        <button type="button" class="primary" :disabled="working || !connection.ready || !contract.explicit" @click="emit(hasVideo ? 'quick' : 'generate')">{{ quick ? (mixing ? '正在替换视频…' : aligning ? '正在对齐说话位置…' : '正在生成配音…') : hasVideo ? (audio && !stale ? '重新生成并替换配音' : '生成并替换配音') : '生成本镜配音' }}</button>
        <button v-if="hasVideo" type="button" :disabled="working" @click="emit('play-current')">播放当前视频</button>
        <button v-if="mixed" type="button" :disabled="working" @click="emit('restore')">恢复原声</button>
        <button v-if="progress?.status === 'running'" type="button" @click="emit('cancel')">停止配音</button>
      </div>
      <p class="flow-note">{{ hasVideo ? '生成 → 对齐 → 替换，完成后自动播放对白。原视频可随时恢复。' : '先生成配音；有视频后可自动对齐说话位置。' }}</p>
      <p v-if="timingAdvice" class="timing-advice" role="note">{{ timingAdvice }}</p>
      <div v-if="progress && ['running','failed'].includes(progress.status)" class="breeze-progress" role="status"><progress v-if="progress.status === 'running'" :max="progress.total || 1" :value="progress.completed || 0"></progress><span>{{ progress.message }}</span></div>
      <p v-if="alignmentMessage && !quick" class="job-message" role="status">{{ alignmentMessage }}</p>
      <p v-if="stale" class="breeze-warning">台词、表演或角色声音已修改，请重新生成并替换配音。</p>
      <p v-if="applyBlockReason" class="breeze-warning" role="status">{{ applyBlockReason }}</p>
      <p v-if="converted && !audioApplied" class="breeze-warning">换音色实验结果尚未应用。请在高级设置中试听核对，或用上方按钮重新制作普通配音。</p>
      <details class="advanced-settings" :open="needsTiming"><summary>高级设置 <small>单独生成、时间微调、原声换音色</small></summary>
        <details class="dialogue-lines"><summary>本镜台词 · {{ contract.lines.length }} 句</summary><ol><li v-for="(line, i) in contract.lines" :key="i"><b>{{ contract.roles[i] || '未标注角色' }}：</b>{{ line }}</li></ol></details>
        <div class="breeze-actions">
          <button type="button" :disabled="working || !connection.ready" @click="emit('generate')">仅生成配音</button>
          <button v-if="audio" type="button" :disabled="working" @click="emit('play')">试听独立配音</button>
          <button v-if="audio && hasVideo && !converted" type="button" :disabled="working || stale" @click="emit('align')">{{ aligning ? '定位中…' : '重新定位原声' }}</button>
          <button v-if="audio && hasVideo" type="button" :disabled="working || stale || !connection.ready" @click="emit('convert')">原声换音色（实验）</button>
        </div>
        <p>单独生成不会替换视频；实验换音色沿用原片节奏，可能出现错字，需试听核对。</p>
        <div v-if="converted && audio.conversionReview?.status !== 'matched_text'" class="conversion-review" role="status"><strong>{{ audio.conversionReview.summary || '识别台词有差异，尚未应用' }}</strong><p>识别：{{ audio.conversionReview.transcript || '未能可靠识别' }}</p><label><input type="checkbox" :checked="Boolean(audio.conversionReviewAccepted)" @change="emit('accept-review', $event.target.checked)" />已试听并核对台词</label></div>
        <div v-if="audio && hasVideo" class="alignment-area">
          <p v-if="!alignment">点“重新定位原声”可查看与微调说话时间。</p>
          <template v-else>
            <div class="alignment-head"><strong>对白时间表</strong><small>单位：秒</small></div>
            <p v-if="alignment.recognitionNote">{{ alignment.recognitionNote }}</p>
            <p v-if="alignment.warning" class="breeze-warning">{{ alignment.warning }}</p>
            <div v-for="(row, index) in alignment.rows" :key="index" class="alignment-row">
              <div class="alignment-line"><b>{{ row.role || '未标注角色' }}</b><span>{{ row.text }}</span><button type="button" :disabled="row.start == null || working" @click="emit('preview', row)">看原片</button></div>
              <div class="alignment-times"><label>开始<input type="number" min="0" :max="alignment.videoDuration" step="0.05" :value="row.start" :aria-label="`第${index + 1}句开始时间`" :disabled="working || converted" @change="timing(index, 'start', $event.target.value)" /></label><span>→</span><label>结束<input type="number" min="0" :max="alignment.videoDuration" step="0.05" :value="row.end" :aria-label="`第${index + 1}句结束时间`" :disabled="working || converted" @change="timing(index, 'end', $event.target.value)" /></label><label class="timing-confirm"><input type="checkbox" :checked="row.confirmed || (Number.isFinite(row.start) && Number.isFinite(row.end) && row.end - row.start >= 0.12)" :disabled="working || converted" @change="timing(index, 'confirmed', $event.target.checked)" />{{ row.method === 'matched' ? '台词已匹配' : row.method === 'order' ? '按顺序自动定位' : '已核对人物与时间' }}</label></div>
              <small v-if="row.pieces?.length > 1">已保留句内 {{ row.pieces.length }} 段发声之间的停顿</small>
            </div>
            <details class="recognized-text"><summary>原声识别结果</summary><p>{{ alignment.transcript || '请预览并填写时间。' }}</p></details>
            <div class="alignment-submit"><span>保持自然语速，不拉长填满时段。</span><button type="button" class="primary" :disabled="!canMix || stale || working" @click="emit('mix')">{{ mixing ? '正在替换…' : '应用当前配音' }}</button></div>
          </template>
        </div>
        <details class="connection-settings"><summary>本机连接设置</summary><div class="breeze-connection"><input :value="root" aria-label="Breeze 应用目录" :disabled="working || connecting" @change="emit('root', $event.target.value)" /><button type="button" :disabled="connecting || working" @click="emit('connect')">刷新连接</button></div><p>{{ connection.message }}</p></details>
        <small>自动定位供时间参考；多人或识别不准时，请核对人物与时间。画面中的口型动作不会被重新生成。</small>
      </details>
    </template>
  </section>
</template>

<style scoped>
.breeze-panel{margin:0;padding:20px;border:0;background:var(--theme-bg-card);color:var(--theme-text-primary);min-width:0}
header{display:flex;justify-content:space-between;gap:12px;align-items:start;margin-bottom:14px}header strong{font-size:15px}header p{margin:4px 0 0}header em{flex-shrink:0;padding:3px 7px;border-radius:6px;background:var(--theme-bg-surface);font-size:11px;font-style:normal;color:var(--theme-text-secondary)}header em.ready{color:var(--theme-accent-text);background:var(--theme-accent-soft)}

/* 📢 本镜台词/旁白高亮卡片 */
.dubbing-dialogue-card{margin-bottom:14px;padding:12px 14px;border:1px solid var(--theme-accent-border, rgba(59,130,246,0.3));border-radius:10px;background:var(--theme-bg-surface);box-shadow:0 1px 3px rgba(0,0,0,0.04)}
.dubbing-dialogue-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.dubbing-dialogue-title{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--theme-text-primary)}
.dubbing-dialogue-title svg{color:var(--theme-accent)}
.dubbing-count-pill{padding:2px 8px;border-radius:12px;background:var(--theme-accent-soft, rgba(59,130,246,0.12));color:var(--theme-accent);font-size:11px;font-weight:600}
.dubbing-lines-stack{display:flex;flex-direction:column;gap:8px}
.dubbing-line-bubble{padding:8px 12px;border-radius:8px;background:var(--theme-bg-card);border:1px solid var(--theme-border-subtle)}
.dubbing-line-meta{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.role-pill{display:inline-flex;align-items:center;padding:2px 8px;border-radius:4px;background:var(--theme-accent-soft, rgba(59,130,246,0.15));color:var(--theme-accent-text, #2563eb);font-size:11px;font-weight:600}
.role-pill.narrator-pill{background:rgba(217,119,6,0.15);color:#d97706}
.delivery-pill{font-size:11px;color:var(--theme-text-secondary);font-style:italic}
.dubbing-line-content{font-size:13px;line-height:1.6;color:var(--theme-text-primary);font-weight:500;word-break:break-word}
.dubbing-empty-state{padding:10px 12px;margin-bottom:14px;border-radius:8px;background:var(--theme-bg-surface);font-size:12px;line-height:1.6;color:var(--theme-text-secondary);border:1px dashed var(--theme-border-subtle)}
.dubbing-empty-state.error{border-color:rgba(239,68,68,0.4);background:rgba(239,68,68,0.06);color:#dc2626}
.dubbing-empty-state code{padding:2px 5px;background:rgba(0,0,0,0.06);border-radius:4px;font-size:11px}
.breeze-role-head{display:flex;align-items:center;gap:8px;grid-column:1/-1}
.role-cue-tag{font-size:11px;color:var(--theme-accent-text, #2563eb);background:var(--theme-accent-soft, rgba(59,130,246,0.1));padding:2px 8px;border-radius:4px;border:1px solid var(--theme-accent-border, rgba(59,130,246,0.2))}
.preset-pills-row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:6px}
.preset-label{font-size:11px;color:var(--theme-text-secondary);font-weight:600}
.preset-pill-btn{padding:3px 8px;border-radius:12px;background:var(--theme-bg-surface);border:1px solid var(--theme-border-subtle);font-size:11px;color:var(--theme-text-primary);cursor:pointer;line-height:1.4;transition:all 0.15s ease}
.preset-pill-btn:hover{border-color:var(--theme-accent);color:var(--theme-accent);background:var(--theme-accent-soft, rgba(59,130,246,0.08))}

p,small{color:var(--theme-text-secondary);font-size:12px;line-height:1.7}small{display:block;margin-top:8px}.dubbing-state{padding:10px 12px;margin-bottom:14px;border-radius:8px;background:var(--theme-bg-surface);font-size:12px;line-height:1.7}.dubbing-state.pending{color:var(--theme-accent-text)}
details{margin:12px 0;font-size:12px;line-height:1.8}summary{cursor:pointer;color:var(--theme-accent-text)}summary small{display:inline;margin-left:8px}.breeze-settings{border:1px solid var(--theme-border-subtle);border-radius:8px}.breeze-settings>summary{padding:9px 12px}.breeze-settings-content{padding:0 12px 12px}
button{padding:9px 12px;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-card);color:var(--theme-text-primary);cursor:pointer;font-size:12px;line-height:1.5}button.primary{background:var(--theme-accent);color:var(--theme-text-on-accent);border-color:var(--theme-accent)}button:disabled{opacity:.5;cursor:not-allowed}.main-actions,.breeze-actions,.connect-actions,.breeze-connection{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.main-actions{margin-top:16px}.main-actions .primary{padding:11px 16px;font-weight:600}.flow-note{margin:8px 0 0}.timing-advice{margin:8px 0 0;padding:6px 10px;border-radius:6px;background:rgba(79,112,168,0.08);color:var(--theme-text-primary);font-size:12px;line-height:1.6}.connect-actions{font-size:12px;color:var(--theme-text-secondary);margin:12px 0}
.breeze-role{display:grid;grid-template-columns:minmax(0,1fr);gap:8px;align-items:center;margin-top:10px;padding-bottom:10px;border-bottom:1px solid var(--theme-border-subtle)}.breeze-role:last-child{border-bottom:0}.breeze-role :deep(.ui-select){min-width:0}.breeze-role textarea{resize:vertical}input,textarea{min-width:0;padding:8px 10px;border:1px solid var(--theme-border-subtle);border-radius:7px;background:var(--theme-bg-input);color:var(--theme-text-primary);font:inherit;font-size:12px;line-height:1.7}
.advanced-settings{border-top:1px solid var(--theme-border-subtle);padding-top:14px;margin:18px 0 0}.advanced-settings>summary{color:var(--theme-text-secondary)}.advanced-settings>.breeze-actions{margin-top:14px}.breeze-warning,.conversion-review strong{color:#ad4b30}.breeze-progress{display:flex;gap:10px;align-items:center;margin:12px 0;font-size:12px;line-height:1.7}.breeze-progress progress{width:100px;height:6px;accent-color:var(--theme-accent);flex-shrink:0}.job-message{margin:10px 0 0}
.alignment-area{margin-top:14px;padding-top:12px;border-top:1px solid var(--theme-border-subtle)}.alignment-head{display:flex;align-items:center;gap:8px;font-size:13px}.alignment-head small{margin:0}.alignment-row,.conversion-review{margin-top:10px;padding:12px;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-surface)}.alignment-line{display:flex;gap:8px;align-items:start}.alignment-line span{flex:1;min-width:0;overflow-wrap:anywhere}.alignment-line b{flex-shrink:0}.alignment-line button{padding:3px 7px;white-space:nowrap}.alignment-times{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-top:10px;color:var(--theme-text-secondary)}.alignment-times label,.conversion-review label{display:flex;align-items:center;gap:6px}.alignment-times input[type=number]{width:68px;padding:5px}.timing-confirm{margin-left:auto}.alignment-submit{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;margin-top:12px;color:var(--theme-text-secondary)}.breeze-connection{margin-top:10px}.breeze-connection input{flex:1 1 180px}.dialogue-lines ol{padding-left:20px;overflow-wrap:anywhere}
@media(max-width:1100px){.breeze-panel{padding:14px}summary small{display:block;margin-left:0}.alignment-times{gap:6px}.timing-confirm{margin-left:0}}

.role-locked-tag { display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border-radius: 4px; background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; font-size: 11px; font-weight: 600; }
</style>
