<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  token: String, scopeKey: String, value: Object, models: Array, assets: Array,
  clips: Array, script: String, fileUrl: Function, save: Function,
})
const draft = ref({})
const error = ref('')
const submitting = ref(false)
const querying = ref(false)
const importing = ref(false)
let timer = null
let alive = true
const owner = props.scopeKey
const clone = value => JSON.parse(JSON.stringify(value))
const museModels = computed(() => (props.models || []).filter(m => /^muse[-_ ]?video/i.test(m.modelName || '')))
const modelId = computed(() => draft.value.model || String(museModels.value[0]?.id || ''))
const images = computed(() => (props.assets || []).filter(a => a.fileId || a.coverId))
const sources = computed(() => draft.value.sources || [])
const candidate = computed(() => draft.value.history?.[0])
const adopted = computed(() => draft.value.adopted)
const running = computed(() => Boolean(draft.value.attempt?.taskId && !['succeeded', 'failed', 'cancelled'].includes(draft.value.attempt.status)))
const awaitingReceipt = computed(() => !draft.value.attempt?.taskId && ['submitting', 'unknown'].includes(draft.value.attempt?.status))
const locked = computed(() => running.value || submitting.value || awaitingReceipt.value)
const preview = computed(() => candidate.value?.fileId ? candidate.value : adopted.value)
const api = () => {
  if (!window.pywebview?.api) throw new Error('请从桌面客户端打开整场制作')
  return window.pywebview.api
}
async function persist(snapshot = clone(draft.value)) {
  await props.save(snapshot, owner)
}
async function changed() {
  draft.value.prompts = { ...(draft.value.prompts || {}), [draft.value.mode]: draft.value.prompt || '' }
  try { await persist() } catch (err) { error.value = `保存失败：${err.message || err}` }
}
function switchMode(mode) {
  if (locked.value || draft.value.mode === mode) return
  draft.value.prompts = { ...(draft.value.prompts || {}), [draft.value.mode]: draft.value.prompt || '' }
  draft.value.mode = mode
  draft.value.prompt = draft.value.prompts[mode] || ''
  void changed()
}
function selectImage(asset) {
  const id = String(asset.fileId || asset.coverId)
  const selected = draft.value.images || []
  draft.value.images = selected.some(a => a.fileId === id)
    ? selected.filter(a => a.fileId !== id)
    : [...selected, { fileId: id, title: asset.name || '参考图' }]
  void changed()
}
function addSource(clip) {
  if (locked.value || sources.value.some(s => s.fileId === clip.fileId)) return
  draft.value.sources = [...sources.value, { fileId: clip.fileId, title: clip.title || '视频素材' }]
  void changed()
}
function moveSource(index, delta) {
  const next = [...sources.value]
  const target = index + delta
  if (target < 0 || target >= next.length) return
  ;[next[index], next[target]] = [next[target], next[index]]
  draft.value.sources = next
  void changed()
}
async function importSource() {
  importing.value = true
  error.value = ''
  try {
    const selected = await api().select_local_video_file()
    if (!selected) return
    const uploaded = await api().upload_local_file(props.token, selected.path)
    if (!uploaded?.id) throw new Error('视频未成功入库')
    addSource({ fileId: uploaded.id, title: selected.name })
  } catch (err) { error.value = String(err.message || err) }
  finally { importing.value = false }
}
function schedule() {
  clearTimeout(timer)
  if (alive && running.value) timer = setTimeout(() => void poll(), 5000)
}
async function poll() {
  if (querying.value || !draft.value.attempt?.taskId) return
  querying.value = true
  const attempt = clone(draft.value.attempt)
  try {
    const result = await api().backend_request('GET', `/ai/video/${encodeURIComponent(attempt.taskId)}?model=${encodeURIComponent(attempt.model)}`, props.token, null)
    if (!alive || draft.value.attempt?.taskId !== attempt.taskId) return
    const status = String(result.status || result.state || '').toLowerCase()
    draft.value.attempt.status = status || 'running'
    const terminal = ['succeeded', 'completed', 'done', 'success', 'failed', 'cancelled'].includes(status)
    if (terminal) {
      const url = String(result.video_url || result.content?.video_url || '')
      const fileId = decodeURIComponent(url.match(/\/file\/([^/]+)\/download/)?.[1] || '')
      const passed = ['succeeded', 'completed', 'done', 'success'].includes(status) && fileId && result.validation?.passed !== false
      draft.value.attempt.status = passed ? 'succeeded' : status === 'cancelled' ? 'cancelled' : 'failed'
      const message = result.error?.message || result.validation?.reason || (passed ? '' : '未收到可用的完整视频')
      const entry = { ...attempt, status: draft.value.attempt.status, fileId, validation: result.validation || null,
        error: message, finishedAt: Date.now(), reviewStatus: 'needs_review' }
      draft.value.history = [entry, ...(draft.value.history || []).filter(h => h.taskId !== attempt.taskId)]
      error.value = message
      await persist()
    }
  } catch (err) {
    if (alive) error.value = `进度暂未取回：${err.message || err}。可以重新查询，不必重新生成。`
  } finally {
    querying.value = false
    schedule()
  }
}
async function generate() {
  if (locked.value) return
  error.value = ''
  if (!modelId.value) { error.value = '请先在模型配置中启用 Muse 视频模型'; return }
  if (!String(draft.value.prompt || '').trim()) { error.value = '请填写完整剧本或组片要求'; return }
  if (draft.value.mode === 'assemble' && sources.value.length < 2) { error.value = '请至少选择两段视频'; return }
  const attempt = { mode: draft.value.mode, model: modelId.value, prompt: draft.value.prompt,
    ratio: draft.value.ratio, duration: Number(draft.value.duration || 0), images: clone(draft.value.images || []),
    sources: draft.value.mode === 'assemble' ? clone(sources.value) : [], startedAt: Date.now(), status: 'submitting' }
  submitting.value = true
  let dispatched = false
  try {
    draft.value.model = attempt.model
    draft.value.attempt = attempt
    await persist()
    dispatched = true
    const result = await api().backend_request('POST', '/ai/video', props.token, {
      production_mode: attempt.mode, model: attempt.model, project_id: owner,
      prompt: attempt.prompt, duration: attempt.duration, ratio: attempt.ratio,
      reference_images: attempt.images, source_videos: attempt.sources,
    })
    const taskId = String(result.taskId || result.id || '')
    if (!taskId) throw new Error('未收到任务编号，请先检查桥接记录，避免重复提交')
    draft.value.attempt = { ...attempt, taskId, status: String(result.status || 'queued') }
    await persist()
    if (alive) await poll()
  } catch (err) {
    error.value = String(err.message || err)
    if (!draft.value.attempt?.taskId) {
      draft.value.attempt = { ...attempt, status: dispatched && !error.value.includes('未提交') ? 'unknown' : 'failed', error: error.value }
      try { await persist() } catch (_) { /* Preserve the original error. */ }
    }
  } finally { submitting.value = false }
}
async function adopt(entry) {
  draft.value.adopted = { ...clone(entry), adoptedAt: Date.now() }
  await changed()
}
async function exportVideo(entry) {
  try {
    await api().save_server_video_as(props.token, entry.fileId, '整场成片.mp4')
  } catch (err) { error.value = String(err.message || err) }
}
watch(() => props.scopeKey, () => {
  clearTimeout(timer)
  draft.value = { mode: 'scene', model: '', prompt: '', ratio: '16:9', duration: 0, images: [], sources: [], history: [], ...clone(props.value || {}) }
  if (running.value) void poll()
}, { immediate: true })
watch(() => props.value?.attempt?.taskId, taskId => {
  if (taskId && taskId !== draft.value.attempt?.taskId && !submitting.value) {
    draft.value = { ...draft.value, ...clone(props.value) }
    if (running.value) void poll()
  }
})
onBeforeUnmount(() => { alive = false; clearTimeout(timer) })
</script>

<template>
  <section class="native-film-studio" aria-label="AI整场制作">
    <div class="native-film-editor">
      <header><span>AI 整场制作</span><h2>把一场戏完整交给 Muse</h2><p>提交完整剧本，或选择已有视频，让 Muse 完成分段制作与组装。</p></header>
      <div class="native-mode-tabs"><button :class="{active:draft.mode==='scene'}" :disabled="locked" @click="switchMode('scene')">整场生成</button><button :class="{active:draft.mode==='assemble'}" :disabled="locked" @click="switchMode('assemble')">已有视频组片</button></div>
      <div class="native-settings">
        <label>视频模型<select v-model="draft.model" :disabled="locked" @change="changed()"><option value="">{{ museModels.length ? `默认：${museModels[0].name || museModels[0].modelName}` : '尚未配置 Muse 视频模型' }}</option><option v-for="model in museModels" :key="model.id" :value="String(model.id)">{{ model.name || model.modelName }}</option></select></label>
        <label>画幅<select v-model="draft.ratio" :disabled="locked" @change="changed()"><option>16:9</option><option>9:16</option><option>1:1</option><option>21:9</option></select></label>
        <label>目标秒数<input v-model.number="draft.duration" :disabled="locked" type="number" min="0" max="3600" @change="changed()" /><small>0：按剧情安排</small></label>
      </div>
      <label class="native-script"><span>{{ draft.mode==='scene' ? '完整剧本' : '组片要求' }}</span><textarea v-model="draft.prompt" :disabled="locked" rows="12" :placeholder="draft.mode==='scene' ? '写下整场剧情、动作、完整台词和风格要求。Muse 自行分段制作并返回整场视频。' : '说明剧情顺序、需要保留的动作与对白，以及希望如何衔接。'" @change="changed()"></textarea></label>
      <button v-if="draft.mode==='scene' && script" class="native-text-action" :disabled="locked" @click="draft.prompt=script;changed()">载入本集完整剧本</button>
      <section v-if="draft.mode==='assemble'" class="native-sources">
        <header><strong>视频顺序 · {{ sources.length }}</strong><button :disabled="locked || importing" @click="importSource">{{ importing ? '导入中…' : '＋ 导入视频' }}</button></header>
        <ol><li v-for="(source,index) in sources" :key="source.fileId"><span>{{ source.title }}</span><button :disabled="locked || index===0" aria-label="上移" @click="moveSource(index,-1)">↑</button><button :disabled="locked || index===sources.length-1" aria-label="下移" @click="moveSource(index,1)">↓</button><button :disabled="locked" aria-label="移除素材" @click="draft.sources=sources.filter((_,i)=>i!==index);changed()">×</button></li></ol>
        <p v-if="!sources.length">从本集镜头中选择，或导入已有视频。</p>
        <div class="native-chips"><button v-for="clip in clips" :key="clip.fileId" :disabled="locked || sources.some(s=>s.fileId===clip.fileId)" @click="addSource(clip)">＋ {{ clip.title }}</button></div>
      </section>
      <details v-if="images.length" class="native-references"><summary>人物与场景参考 · 已选 {{ draft.images.length }}</summary><div class="native-chips"><button v-for="asset in images" :key="asset.id || asset.fileId" :disabled="locked" :class="{selected:draft.images.some(a=>a.fileId===String(asset.fileId || asset.coverId))}" @click="selectImage(asset)">{{ asset.name || '参考图' }}</button></div></details>
      <p v-if="error" class="native-error" role="alert">{{ error }}</p>
      <p v-if="awaitingReceipt && !submitting" class="native-error">提交回执尚未确认，请先检查 Muse 桥接任务记录，避免重复生成。<button @click="draft.attempt.status='failed';changed()">已确认没有任务，允许重试</button></p>
      <footer><button class="native-generate" :disabled="locked" @click="generate">{{ submitting ? '正在提交…' : running ? 'Muse 正在制作…' : awaitingReceipt ? '等待确认提交结果' : draft.mode==='scene' ? '生成整场视频' : '交给 Muse 组片' }}</button><button v-if="running" :disabled="querying" @click="poll">{{ querying ? '查询中…' : '重新查询' }}</button><small v-if="running">可以离开此页，返回后继续查询。</small></footer>
    </div>
    <aside class="native-film-preview">
      <header><span>整场预览</span><strong>{{ preview?.fileId ? preview.status==='failed' ? '失败候选 · 保留原片' : '检查画面、衔接与完整对白' : '等待第一条整场视频' }}</strong></header>
      <video v-if="preview?.fileId" :key="preview.fileId" :src="fileUrl(preview.fileId)" controls preload="metadata"></video>
      <div v-else class="native-preview-empty">整场结果会显示在这里</div>
      <p v-if="preview?.validation?.actualDuration">实际 {{ preview.validation.actualDuration }} 秒 · {{ preview.status==='failed' ? '尚未通过文件检查' : '已收到视频，内容待检查' }}</p>
      <p v-if="preview?.error" class="native-error">{{ preview.error }}</p>
      <div v-if="candidate?.fileId" class="native-result-actions"><button v-if="candidate.status==='succeeded'" @click="adopt(candidate)">{{ adopted?.taskId===candidate.taskId ? '当前采用版本' : '采用这版整场' }}</button><button @click="exportVideo(candidate)">导出视频</button></div>
      <section v-if="adopted?.fileId && adopted.fileId!==preview?.fileId"><h3>当前采用版本</h3><video :src="fileUrl(adopted.fileId)" controls preload="metadata"></video><button @click="exportVideo(adopted)">导出采用版</button></section>
      <details v-if="draft.history.length"><summary>历史版本 · {{ draft.history.length }}</summary><article v-for="entry in draft.history" :key="entry.taskId"><strong>{{ entry.mode==='scene' ? '整场生成' : '视频组片' }} · {{ entry.status==='succeeded' ? '视频已返回' : '失败候选' }}</strong><p v-if="entry.error">{{ entry.error }}</p><video v-if="entry.fileId" :src="fileUrl(entry.fileId)" controls preload="none"></video><button v-if="entry.status==='succeeded'" @click="adopt(entry)">采用此版</button></article></details>
    </aside>
  </section>
</template>

<style scoped>
.native-film-studio{display:grid;grid-template-columns:minmax(320px,1.1fr) minmax(280px,1fr);gap:28px;padding:28px;max-width:1450px;margin:auto;color:var(--theme-text-primary, #253047)}.native-film-editor,.native-film-preview{min-width:0}.native-film-editor>header span,.native-film-preview>header span{font-size:12px;color:var(--theme-accent, #4f70a8);letter-spacing:.1em}.native-film-editor h2{font-size:25px;margin:10px 0}.native-film-editor p,.native-film-preview p{font-size:13px;color:var(--theme-text-secondary, #68768c);line-height:1.7}.native-mode-tabs{display:flex;gap:8px;margin:22px 0}.native-film-studio button{border:1px solid var(--theme-border-subtle, #dce2eb);border-radius:9px;background:var(--theme-bg-elevated, #fff);color:var(--theme-text-primary, #253047);padding:9px 13px;cursor:pointer}.native-film-studio button:disabled{opacity:.45;cursor:default}.native-mode-tabs button.active,.native-chips .selected{background:var(--theme-accent-soft, #eaf0fa);border-color:var(--theme-accent, #4f70a8)}.native-settings{display:grid;grid-template-columns:2fr 1fr 1fr;gap:12px}.native-settings label,.native-script{display:flex;flex-direction:column;gap:8px;font-size:12px;color:var(--theme-text-secondary, #68768c)}.native-settings select,.native-settings input,.native-script textarea{width:100%;box-sizing:border-box;background:var(--theme-bg-elevated, #fff);border:1px solid var(--theme-border-subtle, #dce2eb);border-radius:8px;color:var(--theme-text-primary, #253047);padding:10px;font:inherit}.native-script{margin-top:18px}.native-script textarea{resize:vertical;font-size:14px;line-height:1.8;min-height:230px}.native-settings small{font-size:10px}.native-text-action{margin-top:9px}.native-sources,.native-references{margin-top:22px}.native-sources header{display:flex;justify-content:space-between;align-items:center}.native-sources ol{padding-left:24px}.native-sources li{padding:6px 0}.native-sources li span{display:inline-block;max-width:65%;font-size:13px;margin-right:8px}.native-sources li button{padding:4px 8px;margin:0 2px}.native-chips{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0}.native-chips button{font-size:12px}.native-film-studio summary{cursor:pointer;color:var(--theme-text-secondary, #68768c);font-size:13px}.native-film-editor footer{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:24px}.native-film-editor footer small{font-size:12px;color:var(--theme-text-secondary, #68768c)}.native-film-studio .native-generate{background:var(--theme-accent, #4f70a8);border:0;color:var(--theme-text-on-accent, #fff);font-weight:700;padding:12px 22px}.native-film-studio .native-error{color:var(--theme-danger-text, #b13e37);background:var(--theme-danger-soft, #fff1ef);padding:12px;border-radius:8px}.native-film-preview{background:var(--theme-bg-elevated, #fff);border:1px solid var(--theme-border-subtle, #dce2eb);border-radius:16px;padding:22px;align-self:start}.native-film-preview>header{display:flex;flex-direction:column;gap:9px;margin-bottom:20px}.native-film-preview>header strong{font-size:15px}.native-film-preview video{width:100%;max-height:430px;background:#08070a;border-radius:9px}.native-preview-empty{aspect-ratio:16/9;display:grid;place-items:center;background:var(--theme-bg-surface, #f8f9fb);color:var(--theme-text-secondary, #68768c);border-radius:9px;font-size:14px}.native-result-actions{display:flex;gap:10px;margin:14px 0}.native-film-preview details{margin-top:22px}.native-film-preview article{border-top:1px solid var(--theme-border-subtle, #dce2eb);margin-top:15px;padding-top:15px;font-size:12px}.native-film-preview article video{max-height:220px;margin:10px 0}@media(max-width:1000px){.native-film-studio{grid-template-columns:1fr;padding:18px}.native-settings{grid-template-columns:1fr 1fr}.native-settings label:first-child{grid-column:1/-1}}
</style>
