<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import UiSelect from './UiSelect.vue'
import VerifiedAssemblyPanel from './VerifiedAssemblyPanel.vue'
import { assemblySources, assemblyProblem, assemblyPrompt } from '../utils/shotAssembly.js'

const props = defineProps({ token: String, projectId: String, clips: Array, models: Array, textModels:Array, textModel:String, value: Object, save: Function, fileUrl: Function })
const emit = defineEmits(['busy-change','edit-shot'])
const owner = props.projectId
const clone = value => JSON.parse(JSON.stringify(value))
const draft = ref({ model: '', requirements: '', history: [], ...clone(props.value || {}) })
const error = ref('')
const submitting = ref(false)
const querying = ref(false)
const savedMessage = ref('')
const workflow = ref('verified')
const verifiedBusy = ref(false)
let alive = true, timer = null, saveQueue = Promise.resolve()
const museModels = computed(() => (props.models || []).filter(model => /^muse[-_ ]?video/i.test(model.modelName || '')))
const modelOptions = computed(() => museModels.value.map(model => ({ value: String(model.id), label: model.name || model.modelName })))
const selectedModel = computed(() => draft.value.model || String(museModels.value[0]?.id || ''))
const terminal = status => ['succeeded', 'failed', 'cancelled'].includes(status)
const running = computed(() => Boolean(draft.value.attempt?.taskId && draft.value.attempt.status !== 'unknown' && !terminal(draft.value.attempt.status)))
const uncertain = computed(() => draft.value.attempt?.status === 'unknown' || (!draft.value.attempt?.taskId && draft.value.attempt?.status === 'submitting'))
const locked = computed(() => submitting.value || running.value || uncertain.value)
const problem = computed(() => assemblyProblem(props.clips || []))
const currentSources = computed(() => assemblySources(props.clips || []))
const displayedSources = computed(() => locked.value ? draft.value.attempt?.sources || currentSources.value : currentSources.value)
const latest = computed(() => draft.value.history?.[0])
const preview = computed(() => latest.value?.fileId ? latest.value : draft.value.adopted)
const api = () => {
  if (!window.pywebview?.api) throw new Error('请从CDTV客户端打开组片')
  return window.pywebview.api
}
function persist(snapshot = clone(draft.value)) {
  const pending = saveQueue.catch(() => {}).then(() => props.save(snapshot, owner))
  saveQueue = pending
  return pending
}
async function changed() {
  try { await persist(); savedMessage.value = '' }
  catch (err) { error.value = `组片记录保存失败：${err.message || err}` }
}
async function saveVerified(value) {
  draft.value.verified = value
  await persist()
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
    if (['succeeded', 'completed', 'done', 'success', 'failed', 'cancelled', 'canceled'].includes(status)) {
      const url = String(result.video_url || result.content?.video_url || '')
      const fileId = decodeURIComponent(url.match(/\/file\/([^/]+)\/download/)?.[1] || '')
      const passed = ['succeeded', 'completed', 'done', 'success'].includes(status) && fileId && result.validation?.passed !== false
      const message = result.error?.message || result.validation?.reason || (passed ? '' : '尚未收到可用组片，原分镜和采用版保留')
      const unconfirmed = ['send_unconfirmed', 'assembly_result_unconfirmed'].includes(result.error?.code) || String(message).includes('send_unconfirmed:')
      const entry = { ...attempt, status: unconfirmed ? 'unknown' : passed ? 'succeeded' : /cancel/.test(status) ? 'cancelled' : 'failed',
        fileId, validation: result.validation || null, error: message, finishedAt: Date.now(), reviewStatus: 'needs_review' }
      draft.value.attempt = entry
      draft.value.history = [entry, ...(draft.value.history || []).filter(item => item.taskId !== entry.taskId)]
      error.value = message
      await persist()
    } else {
      draft.value.attempt.status = status || 'running'
      await persist()
    }
  } catch (err) {
    if (alive) error.value = `进度或记录暂未取回：${err.message || err}。重新查询即可，请勿重复组片。`
  } finally { querying.value = false; schedule() }
}
async function assemble() {
  if (locked.value) return
  error.value = ''
  savedMessage.value = ''
  if (problem.value) { error.value = problem.value; return }
  if (!selectedModel.value || !museModels.value.some(model => String(model.id) === selectedModel.value)) {
    error.value = '请先在模型配置中启用并选择 Muse 视频模型'; return
  }
  const sources = clone(currentSources.value)
  const attempt = { mode: 'assemble', assemblyPolicy: 'dual-ended-bridges-v2', model: selectedModel.value, sources,
    prompt: assemblyPrompt(sources, draft.value.requirements), requirements: draft.value.requirements,
    ratio: props.clips?.[0]?.ratio && props.clips[0].ratio !== '智能' ? props.clips[0].ratio : '16:9',
    startedAt: Date.now(), status: 'submitting' }
  submitting.value = true
  let dispatched = false
  try {
    draft.value.model = attempt.model
    draft.value.attempt = attempt
    await persist()
    dispatched = true
    const result = await api().backend_request('POST', '/ai/video', props.token, {
      production_mode: 'assemble', assembly_policy: attempt.assemblyPolicy, model: attempt.model, project_id: owner,
      prompt: attempt.prompt, duration: 0, ratio: attempt.ratio,
      reference_images: [], source_videos: sources,
    })
    const taskId = String(result.taskId || result.id || '')
    if (!taskId) throw new Error('未收到任务编号，请先核对桥接任务，避免重复提交')
    draft.value.attempt = { ...attempt, taskId, status: String(result.status || 'queued') }
    await persist()
    if (alive) await poll()
  } catch (err) {
    error.value = String(err.message || err)
    if (!draft.value.attempt?.taskId) {
      draft.value.attempt = { ...attempt, status: dispatched && !error.value.includes('未提交') ? 'unknown' : 'failed', error: error.value }
      try { await persist() } catch (_) { /* Keep the original save/dispatch error. */ }
    }
  } finally { submitting.value = false }
}
async function adopt(entry) {
  if (entry.status !== 'succeeded' || !entry.fileId) return
  const previous = draft.value.adopted
  draft.value.adopted = { ...clone(entry), adoptedAt: Date.now() }
  try { await persist(); error.value = ''; savedMessage.value = '已保存为采用版，原分镜和视频保持。' }
  catch (err) { draft.value.adopted = previous; error.value = `采用版保存失败：${err.message || err}` }
}
async function exportVideo(entry) {
  try { await api().save_server_video_as(props.token, entry.fileId, 'AI组片成片.mp4') }
  catch (err) { error.value = String(err.message || err) }
}
async function unlockUnsubmitted() {
  draft.value.attempt = { ...draft.value.attempt, status: 'failed', error: '已人工确认 Muse 未开始组片' }
  await changed()
}
watch([locked, verifiedBusy], () => emit('busy-change', locked.value || verifiedBusy.value), { immediate: true })
if (running.value) void poll()
onBeforeUnmount(() => { alive = false; clearTimeout(timer) })
</script>

<template>
  <nav class="assembly-workflows"><button :disabled="locked||verifiedBusy" @click="workflow='verified'">逐接点补段与检查</button><button :disabled="verifiedBusy" @click="workflow='legacy'">整片组片与原有历史</button></nav>
  <VerifiedAssemblyPanel v-if="workflow==='verified'" :token="token" :project-id="projectId" :clips="clips" :models="models" :text-models="textModels" :text-model="textModel" :value="draft.verified" :save="saveVerified" :file-url="fileUrl" @busy-change="verifiedBusy=$event" @edit-shot="emit('edit-shot',$event)" />
  <section v-show="workflow==='legacy'" class="shot-assembly-panel" aria-label="已有分镜AI组片">
    <div class="assembly-setup">
      <header><span>分镜完成后 · AI 衔接组片</span><h3>把已选分镜组装成片</h3><p>以已有分镜为主素材，可调整切点与节奏。补过渡时同时参考上一镜尾部和下一镜开头，两头都要接顺，人物与画面质感向原片靠齐。原分镜、首尾帧和视频分别保留。</p></header>
      <label>组片模型<UiSelect v-model="draft.model" :options="modelOptions" :placeholder="museModels.length ? `默认：${museModels[0].name || museModels[0].modelName}` : '请配置 Muse 视频模型'" :disabled="locked" aria-label="AI组片模型" @change="changed" /></label>
      <section class="assembly-inputs"><strong>{{ locked ? '本次提交' : '当前选中' }} · {{ displayedSources.length }} 段视频</strong><ol><li v-for="(source,index) in displayedSources" :key="`${index}-${source.shotId}-${source.fileId}`">{{ source.title }}</li></ol><small>在左侧隐藏片段即可取消选择。视频过大时仅压缩上传副本，完整时长与原音轨保留，原文件不改。</small></section>
      <label>补充衔接要求（选填）<textarea v-model="draft.requirements" :disabled="locked" rows="3" placeholder="例如：动作接不上时补一小段过渡，保持同一人物、道具与场景，保留完整对白。" @change="changed"></textarea></label>
      <p v-if="problem && !locked" class="assembly-notice">{{ problem }}</p>
      <p v-if="error" class="assembly-error" role="alert">{{ error }}</p>
      <p v-if="savedMessage" class="assembly-notice" role="status">{{ savedMessage }}</p>
      <footer><button class="assembly-submit" :disabled="locked || Boolean(problem)" @click="assemble">{{ submitting ? '正在提交组片…' : running ? 'AI 正在组片…' : uncertain ? '等待确认提交结果' : 'AI 衔接并组片' }}</button><button v-if="draft.attempt?.taskId && (running || error)" :disabled="querying" @click="poll">{{ querying ? '查询中…' : '重新查询' }}</button></footer>
      <p v-if="running" class="assembly-notice">可以关闭预览，回来后继续查询；无需重新生成分镜。</p>
      <p v-if="uncertain && !submitting" class="assembly-error">尚未确认提交回执，请核对 Muse 原对话和桥接记录，避免重复组片。<button @click="unlockUnsubmitted">已确认 Muse 未开始组片，解除等待</button></p>
    </div>
    <aside class="assembly-results">
      <h3>组片结果</h3><p>{{ preview?.fileId ? preview.status==='succeeded' ? '视频已返回，请分别检查上一镜→补段、补段→下一镜，并核对人物、画面质感和完整对白，两头都自然后再采用。' : '失败候选保留，原分镜和上一采用版保持。' : '组片后在这里检查成片，原视频继续保留在分镜中。' }}</p>
      <video v-if="preview?.fileId" :key="preview.fileId" :src="fileUrl(preview.fileId)" controls preload="metadata"></video><div v-else class="assembly-empty">等待分镜组片结果</div>
      <p v-if="preview?.validation?.actualDuration">实际 {{ preview.validation.actualDuration }} 秒 · {{ preview.sources?.length || 0 }} 段源视频</p>
      <p v-if="preview?.error" class="assembly-error">{{ preview.error }}</p>
      <div v-if="preview?.fileId" class="assembly-actions"><button v-if="preview.status==='succeeded'" :disabled="draft.adopted?.taskId===preview.taskId" @click="adopt(preview)">{{ draft.adopted?.taskId===preview.taskId ? '当前采用版' : '检查后采用这版' }}</button><button @click="exportVideo(preview)">导出组片</button></div>
      <section v-if="draft.adopted?.fileId && draft.adopted.taskId!==preview?.taskId" class="assembly-adopted"><h4>当前采用版</h4><video :src="fileUrl(draft.adopted.fileId)" controls preload="metadata"></video><button @click="exportVideo(draft.adopted)">导出采用版</button></section>
      <details v-if="draft.history.length"><summary>组片历史 · {{ draft.history.length }}</summary><article v-for="entry in draft.history" :key="entry.taskId"><strong>{{ entry.status==='succeeded' ? '视频已返回 · 待内容检查' : '失败候选' }} · {{ entry.sources?.length || 0 }} 段</strong><p v-if="entry.error">{{ entry.error }}</p><video v-if="entry.fileId" :src="fileUrl(entry.fileId)" controls preload="none"></video><button v-if="entry.status==='succeeded'" @click="adopt(entry)">检查后采用此版</button><button v-if="entry.fileId" @click="exportVideo(entry)">导出此版</button></article></details>
    </aside>
  </section>
</template>

<style scoped>
.assembly-workflows{display:flex;gap:8px;margin-bottom:18px}.assembly-workflows button{padding:8px 12px;border-radius:7px;border:1px solid var(--theme-border-subtle);background:var(--theme-bg-elevated);color:var(--theme-text-primary);cursor:pointer}.assembly-workflows button:disabled{opacity:.5}
.shot-assembly-panel{display:grid;grid-template-columns:minmax(230px,1fr) minmax(230px,1fr);gap:22px;color:var(--theme-text-primary)}.assembly-setup,.assembly-results{min-width:0}.assembly-setup header>span{font-size:11px;color:var(--theme-accent-text)}.shot-assembly-panel h3{font-size:18px;margin:8px 0 12px}.shot-assembly-panel p{font-size:12px;line-height:1.7;color:var(--theme-text-secondary)}.assembly-setup>label{display:grid;gap:8px;margin:14px 0;font-size:12px}.assembly-setup textarea{width:100%;box-sizing:border-box;border:1px solid var(--theme-border-subtle);border-radius:8px;padding:10px;background:var(--theme-bg-input);color:var(--theme-text-primary);font:inherit;line-height:1.6;resize:vertical;min-height:90px}.assembly-inputs{padding:12px;margin:16px 0;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-surface);font-size:12px}.assembly-inputs ol{max-height:130px;overflow:auto;padding-left:24px;line-height:1.9}.assembly-inputs small{font-size:11px;color:var(--theme-text-secondary)}.shot-assembly-panel button{padding:8px 12px;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-elevated);color:var(--theme-text-primary);font:inherit;font-size:12px;cursor:pointer}.shot-assembly-panel button:disabled{opacity:.5;cursor:default}.assembly-setup footer,.assembly-actions{display:flex;flex-wrap:wrap;gap:8px}.shot-assembly-panel .assembly-submit{background:var(--theme-accent);border-color:var(--theme-accent);color:var(--theme-text-on-accent)}.shot-assembly-panel .assembly-error{padding:10px;border-radius:8px;color:var(--theme-danger-text);background:var(--theme-danger-soft)}.assembly-error button{margin-top:8px}.assembly-results video{display:block;width:100%;max-height:280px;background:#101216;border-radius:9px;margin:12px 0}.assembly-empty{display:grid;place-items:center;aspect-ratio:16/9;border:1px solid var(--theme-border-subtle);border-radius:9px;background:var(--theme-bg-surface);font-size:12px;color:var(--theme-text-secondary)}.assembly-results details{margin-top:20px;font-size:12px}.assembly-results summary{cursor:pointer}.assembly-results article,.assembly-adopted{margin-top:12px;padding-top:12px;border-top:1px solid var(--theme-border-subtle)}.assembly-results article button{margin:4px}.assembly-results article video{max-height:180px}@media(max-width:1100px){.shot-assembly-panel{grid-template-columns:1fr}}
</style>
