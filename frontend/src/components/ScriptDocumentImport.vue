<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { waitForDesktopApi } from '../utils/desktopApi.js'
import { autoAdaptScriptText, decodeScriptFile, MAX_IMPORT_BYTES, parseScriptDocument } from '../utils/scriptDocumentImport.js'

const props = defineProps({ projectId: String, token: String, reuseChapterId: String, documentId: String })
const emit = defineEmits(['close', 'imported'])
const owner = props.projectId
const dialog = ref(null)
const fileInput = ref(null)
const folderInput = ref(null)
const document = ref(null)
const paste = ref('')
const selected = ref([])
const shown = ref('')
const tab = ref('script')
const plan = ref(null)
const error = ref('')
const reading = ref(false)
const planning = ref(false)
const busy = ref(false)
const copiedNotice = ref('')
const showGuide = ref(false)


const lastRawSourceText = ref('')
const lastDocName = ref('')
const aiAdapting = ref(false)

const isLikelyUnstructuredNovel = computed(() => {
  if (!document.value || !document.value.episodes?.length) return false
  const totalShots = document.value.shotCount || 0
  const totalChars = (lastRawSourceText.value || document.value.rawText || '').length
  // 规则：如果总字数较多(>100字)但分镜只有1~2个，或者没有任何台词字段被分离出来，判定为小说或粗文本
  if (totalChars > 120 && totalShots <= 2) return true
  const firstEp = document.value.episodes[0]
  if (firstEp && firstEp.shots) {
    const hasDialogue = firstEp.shots.some(s => s.dialogue?.trim())
    const hasMultipleFields = firstEp.shots.some(s => s.fields && s.fields.length >= 2)
    if (!hasDialogue && !hasMultipleFields && totalShots <= 3) return true
  }
  return false
})

async function runAiAdapt() {
  const raw = lastRawSourceText.value || paste.value || document.value?.rawText || ''
  if (!raw.trim()) {
    error.value = '没有可供 AI 重构的原始文本'
    return
  }
  aiAdapting.value = true
  error.value = ''
  try {
    const res = await call('ai-adapt', {
      sourceText: raw,
      title: lastDocName.value ? lastDocName.value.replace(/\.[^.]+$/, '') : '第1集'
    })
    if (!res?.adaptedText) throw Error('AI 文本模型未返回重构剧本，请检查模型管理中的文本模型配置')
    await parse(res.adaptedText, (lastDocName.value || '剧本') + ' (AI大模型重构)')
  } catch (err) {
    error.value = 'AI 文本模型精编失败：' + (err.message || err)
  } finally {
    aiAdapting.value = false
  }
}

const previousFocus = window.document.activeElement
let alive = true, sequence = 0

const current = computed(() => document.value?.episodes.find(e => e.key === shown.value) || document.value?.episodes[0])
const selectedStats = computed(() => document.value?.episodes.filter(e => selected.value.includes(e.key)).reduce((s, e) => ({ shots: s.shots + e.shots.length, duration: s.duration + e.duration }), { shots: 0, duration: 0 }) || { shots: 0, duration: 0 })
const archiveText = computed(() => {
  if (!document.value) return ''
  return [
    '【全局规范与母模原文】',
    document.value.archive.preamble,
    ...(current.value?.archive || []).flatMap(s => s.fields.length ? [`\n第${s.shot}段 ${s.title}`, ...s.fields.map(f => `【${f.label}】\n${f.text}`)] : []),
    '\n【剪辑与交互执行清单】',
    document.value.archive.tail
  ].join('\n')
})

function arrayBufferToBase64(buffer) {
  let binary = ''
  const bytes = new Uint8Array(buffer)
  const len = bytes.byteLength
  for (let i = 0; i < len; i++) binary += String.fromCharCode(bytes[i])
  return window.btoa(binary)
}

async function call(action, body) {
  const api = await waitForDesktopApi()
  if (!api?.backend_request) throw Error('请在桌面客户端中使用文档导入')
  const path = action === 'convert-file' ? '/api/script-document/convert-file' : `/project/${encodeURIComponent(owner)}/script-document/${action === 'get' ? props.documentId : action}`
  return api.backend_request(action === 'get' ? 'GET' : 'POST', path, props.token, body)
}

function close() { if (!busy.value) emit('close') }

async function refreshPlan() {
  const id = ++sequence
  plan.value = null
  planning.value = false
  if (!document.value || document.value.errors.length || !selected.value.length) return
  planning.value = true
  error.value = ''
  try {
    const result = await call('preview', { document: document.value, selectedEpisodes: selected.value, reuseChapterId: props.reuseChapterId || '' })
    if (alive && id === sequence) plan.value = result
  } catch (e) {
    if (alive && id === sequence) error.value = String(e.message || e)
  } finally {
    if (alive && id === sequence) planning.value = false
  }
}

async function parse(value, name) {
  document.value = parseScriptDocument(value, name)
  selected.value = document.value.episodes.map(e => e.key)
  shown.value = selected.value[0] || ''
  tab.value = 'script'
  await refreshPlan()
}

async function extractFileText(file) {
  const isBinary = /\.(docx|doc|pdf|xlsx|xls)$/i.test(file.name)
  const bytes = await file.arrayBuffer()
  if (isBinary) {
    const b64 = arrayBufferToBase64(bytes)
    try {
      const res = await call('convert-file', { fileName: file.name, contentBase64: b64 })
      return res?.adaptedText || res?.extractedText || ''
    } catch (err) {
      console.warn('Backend convert failed, falling back to local decode:', err)
      return decodeScriptFile(bytes)
    }
  }
  return decodeScriptFile(bytes)
}

async function choose(event) {
  const files = Array.from(event.target.files || [])
  event.target.value = ''
  if (!files.length) return
  document.value = null
  plan.value = null
  selected.value = []
  reading.value = true
  error.value = ''
  const id = ++sequence

  try {
    if (files.length === 1) {
      const file = files[0]
      if (file.size > MAX_IMPORT_BYTES * 5) throw Error('文档超过 10MB，请拆分后导入')
      const text = await extractFileText(file)
      lastRawSourceText.value = text
      lastDocName.value = file.name
      if (alive && id === sequence) await parse(text, file.name)
    } else {
      const texts = []
      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        const raw = await extractFileText(file)
        const epTitle = file.name.replace(/\.[^.]+$/, '')
        texts.push(`# 第${i + 1}集：${epTitle}\n\n${raw}`)
      }
      const mergedText = texts.join('\n\n---\n\n')
      lastRawSourceText.value = mergedText
      lastDocName.value = `批量导入 (${files.length}个文件)`
      if (alive && id === sequence) await parse(mergedText, lastDocName.value)
    }
  } catch (e) {
    if (alive) error.value = String(e.message || e)
  } finally {
    if (alive) reading.value = false
  }
}

async function chooseFolder(event) {
  const files = Array.from(event.target.files || []).filter(f => !f.name.startsWith('.') && /\.(md|markdown|txt|docx|doc|pdf|json|csv|xlsx|xls|html)$/i.test(f.name))
  event.target.value = ''
  if (!files.length) {
    error.value = '文件夹中未找到支持的文档格式（.md, .txt, .docx, .pdf, .xlsx, .csv, .json）'
    return
  }
  // 自然数字排序文件名
  files.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }))

  document.value = null
  plan.value = null
  selected.value = []
  reading.value = true
  error.value = ''
  const id = ++sequence

  try {
    const texts = []
    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      const raw = await extractFileText(file)
      const epTitle = file.name.replace(/\.[^.]+$/, '')
      texts.push(`# 第${i + 1}集：${epTitle}\n\n${raw}`)
    }
    const folderName = files[0].webkitRelativePath?.split('/')[0] || `整季文件夹导入 (${files.length}集)`
    const mergedFolder = texts.join('\n\n---\n\n')
      lastRawSourceText.value = mergedFolder
      lastDocName.value = folderName
      if (alive && id === sequence) await parse(mergedFolder, folderName)
  } catch (e) {
    if (alive) error.value = String(e.message || e)
  } finally {
    if (alive) reading.value = false
  }
}

async function parsePaste() {
  reading.value = true
  error.value = ''
  try {
    lastRawSourceText.value = paste.value
    lastDocName.value = '粘贴文本'
    await parse(paste.value, '粘贴的分镜文档')
  } catch (e) {
    error.value = String(e.message || e)
  } finally {
    reading.value = false
  }
}

async function confirm() {
  if (busy.value || planning.value || reading.value || !plan.value?.newCount || document.value?.errors.length) return
  busy.value = true
  error.value = ''
  try {
    const result = await call('import', { document: document.value, selectedEpisodes: selected.value, reuseChapterId: props.reuseChapterId || '', previewToken: plan.value.previewToken })
    if (alive) emit('imported', result)
  } catch (e) {
    if (alive) {
      error.value = String(e.message || e)
      plan.value = null
    }
  } finally {
    if (alive) busy.value = false
  }
}

const SAMPLE_TEMPLATE = `# 第1集：无言的见证者

### 镜头 01：大远景·九疑山全貌
【时长】: 8秒
【场景】: 九疑山玉琯岩·云海林田
【角色】: 石碑
【画面描述】: 云海缭绕九疑山峰峦，山峦层峦叠嶂，梯田如镜，树石参差。镜头由高空云海缓缓前推下压。
【景别与运镜】: 大远景·24mm·高空俯瞰缓慢下压推近
【旁白】: "岩岩九疑，峻极于天。触石肤合，兴播建云。"——东汉·蔡邕《九疑山铭》
【环境音】: 高空苍茫山风呼啸，空灵低沉金石钟磬鸣响。
【转场】: 顺畅推近接玉琯岩林木
【拍摄约束】: 手绘二维国风，水墨写意打底 + 民俗年画感赛璐璐分层 + 水墨肌理。

### 镜头 02：全景·方信孺伫立玉琯岩前
【时长】: 8秒
【场景】: 玉琯岩前石壁
【角色】: 方信孺、随从
【画面描述】: 玉琯岩前石壁空旷无字，方信孺青衫长袍负手手捧史书凝望石壁，随从侍立一侧作揖。
【景别与运镜】: 全景·35mm·平视微仰
【对白】: 方信孺："蔡邕先生这铭写得神妙，只是这般美景，竟无人题刻，当真遗憾啊！"
【环境音】: 融雪春雨淅沥，空谷鸟鸣。
【转场】: 运镜微移接随从对答
【拍摄约束】: 宋代文士衣冠考究，举止洒脱兼具书卷气。`

async function copySampleTemplate() {
  try {
    await navigator.clipboard.writeText(SAMPLE_TEMPLATE)
    copiedNotice.value = '已成功复制标准分镜示例模板！可直接粘贴测试'
    window.setTimeout(() => { copiedNotice.value = '' }, 3000)
  } catch (_) {
    copiedNotice.value = '复制失败，请手动选择复制'
  }
}

function keydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
  if (event.key !== 'Tab') return
  const items = [...dialog.value.querySelectorAll('button,input,textarea,select,[tabindex="0"]')].filter(e => !e.disabled && e.getClientRects().length)
  const first = items[0], last = items.at(-1)
  if (event.shiftKey && window.document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && window.document.activeElement === last) { event.preventDefault(); first?.focus() }
}

onMounted(async () => {
  await nextTick()
  dialog.value?.focus()
  if (props.documentId) {
    reading.value = true
    try {
      const record = await call('get')
      if (alive) {
        document.value = record.document
        selected.value = document.value.episodes.map(e => e.key)
        shown.value = selected.value[0]
        await refreshPlan()
      }
    } catch (e) {
      if (alive) error.value = String(e.message || e)
    } finally {
      if (alive) reading.value = false
    }
  }
})

onBeforeUnmount(() => { alive = false; sequence++; if (previousFocus?.isConnected) previousFocus.focus() })
</script>

<template>
  <Teleport to="body">
    <div class="document-import-overlay" @mousedown.self="close" @keydown.stop="keydown">
      <section ref="dialog" class="document-import-dialog" role="dialog" aria-modal="true" aria-labelledby="document-import-title" tabindex="-1">
        <header>
          <div>
            <h2 id="document-import-title">导入已有剧本／分镜文档</h2>
            <p>默认本机极速全能识别；遇到纯小说或非标草稿时，自动智能无缝交由 AI 文本大模型进行工业级镜头重构。支持 .docx、.pdf、.md、.xlsx、.txt 及 📁 文件夹整季批量导入。</p>
          </div>
          <button aria-label="关闭文档导入" :disabled="busy" @click="close">×</button>
        </header>

        <!-- 格式规范与帮助折叠栏 -->
        <div class="guide-banner">
          <div class="format-tags">
            <span class="tag-pill">Markdown (.md)</span>
            <span class="tag-pill">Word (.docx)</span>
            <span class="tag-pill">PDF (.pdf)</span>
            <span class="tag-pill">表格 (.xlsx/.csv)</span>
            <span class="tag-pill">文本文档 (.txt)</span>
            <span class="tag-pill highlight">📁 文件夹整季导入</span>
            <span class="tag-pill smart">✨ 智能格式自动适配</span>
          </div>
          <button type="button" class="guide-toggle-btn" @click="showGuide = !showGuide">
            {{ showGuide ? '收起格式规范与模版' : '📖 查看支持格式与标准模版' }}
          </button>
        </div>

        <div v-if="showGuide" class="guide-details-card">
          <div class="guide-header">
            <strong>标准分镜格式规范与支持说明</strong>
            <button type="button" class="copy-template-btn" @click="copySampleTemplate">一键复制标准模版</button>
          </div>
          <span v-if="copiedNotice" class="copied-pill">{{ copiedNotice }}</span>
          <div class="guide-grid">
            <div class="guide-col">
              <h4>1. 支持的文档格式</h4>
              <ul>
                <li><b>Word 文档 (.docx, .doc)</b>：自动提取段落正文及分镜表格，小说剧本直接转分镜。</li>
                <li><b>PDF 文档 (.pdf)</b>：自动解析跨页文本与分镜结构。</li>
                <li><b>Excel 表格 (.xlsx, .csv)</b>：自动识别分镜表（镜号、景别、运镜、画面、台词等）。</li>
                <li><b>Markdown / TXT (.md, .txt)</b>：标准分镜语法，包含动作、台词、时长等。</li>
                <li><b>📁 文件夹批量导入</b>：选择含有多集剧本或分镜文件的文件夹，一键合并为整季项目。</li>
              </ul>
            </div>
            <div class="guide-col">
              <h4>2. 标准分镜字段识别规则</h4>
              <ul>
                <li><code>### 镜头 01：[景别·运镜·镜头名]</code> （也支持 <code>【镜1-1】</code>、<code>Shot 1</code>）</li>
                <li><code>【时长】: 8秒</code>（支持 <code>8s</code> 或 <code>00:00-00:08</code>）</li>
                <li><code>【场景】: ...</code> / <code>【角色】: ...</code></li>
                <li><code>【画面描述】: ...</code>（核心动作与视觉演进）</li>
                <li><code>【景别与运镜】: ...</code>（远景、全景、特写、推拉摇移）</li>
                <li><code>【对白】: 角色名："..."</code> / <code>【旁白】: "..."</code></li>
                <li><code>【环境音】: ...</code> / <code>【转场】: ...</code> / <code>【拍摄约束】: ...</code></li>
              </ul>
            </div>
          </div>
        </div>

        <!-- 导入选择区 -->
        <div class="document-import-pick">
          <input
            ref="fileInput"
            hidden
            type="file"
            accept=".md,.markdown,.txt,.docx,.doc,.pdf,.json,.csv,.xlsx,.xls,.html,text/plain,text/markdown"
            multiple
            aria-label="选择分镜文档"
            :disabled="reading || busy"
            @change="choose"
          />
          <input
            ref="folderInput"
            hidden
            type="file"
            webkitdirectory
            directory
            multiple
            aria-label="选择分镜文件夹"
            :disabled="reading || busy"
            @change="chooseFolder"
          />

          <button class="primary-pick-btn" :disabled="reading || busy" @click="fileInput.click()">
            {{ reading ? '正在智能读取…' : '📄 选择文档（支持 docx/pdf/md/xlsx 等）' }}
          </button>
          <button class="folder-pick-btn" :disabled="reading || busy" @click="folderInput.click()">
            📁 批量导入文件夹（整季）
          </button>
          <span class="doc-chosen-label">{{ document?.name || '先选择一份或多份已有剧本文档' }}</span>
        </div>

        <!-- 文本直接粘贴 -->
        <details v-if="!busy" class="paste-details">
          <summary>也可以直接粘贴文本（小说/剧本/分镜均支持智能识别）</summary>
          <textarea
            v-model="paste"
            aria-label="粘贴分镜文档"
            placeholder="在此粘贴剧本、小说草稿或分镜表格，系统将自动进行语义分析并适配为标准分镜…"
          ></textarea>
          <button :disabled="reading || !paste.trim()" @click="parsePaste">智能识别并预览</button>
        </details>

        <p v-if="error" role="alert" class="document-import-error">{{ error }}</p>

        <!-- 识别成果与预览 -->
        <template v-if="document">
          <!-- 梯级协同：本机识别与 AI 文本大模型深度重构横幅 -->
          <div class="ai-cascade-banner" :class="{ 'is-novel': isLikelyUnstructuredNovel }">
            <div class="cascade-meta">
              <div class="cascade-badge">
                <span v-if="isLikelyUnstructuredNovel" class="badge-tag novel">💡 检测到当前为小说/散文叙述文本（本机仅做基础段落提取）</span>
                <span v-else class="badge-tag ok">⚡ 本机极速结构化识别完成（共 {{ document.shotCount }} 镜）</span>
              </div>
              <p class="cascade-text">
                {{ isLikelyUnstructuredNovel 
                  ? '非标准小说缺乏镜头景别、视觉画面与纯净对白。建议一键交由 AI 文本大模型进行工业级视听语言重构！' 
                  : '已按结构完成精准解析。如需更生动的镜头构图、机位运动与光影氛围，可随时交给 AI 文本模型深度精编。' 
                }}
              </p>
            </div>
            <button
              type="button"
              class="cascade-ai-btn"
              :class="{ 'pulse': isLikelyUnstructuredNovel }"
              :disabled="aiAdapting || reading || busy"
              @click="runAiAdapt"
            >
              <i v-if="aiAdapting" class="btn-spinner"></i>
              <svg v-else viewBox="0 0 24 24"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3z"/></svg>
              {{ aiAdapting ? 'AI 大模型正在重构分镜…' : '✨ 调用 AI 文本大模型深度重塑分镜' }}
            </button>
          </div>

          <p class="document-import-stats">识别到 {{ document.episodes.length }} 集 · {{ document.shotCount}} 段 · {{ document.duration }} 秒</p>
          <p class="guide-note">动作、首尾帧、对白、旁白、环境音和交接要求进入正文。沙盘、黑金字幕、档案卡、教材出处与剪辑清单另存为资料库；未识别栏位自动归档。</p>
          <p v-for="item in document.errors" :key="item" role="alert" class="document-import-error">{{ item }}</p>
          <details v-if="document.warnings.length" class="warnings-details">
            <summary>解析提示与规范建议 ({{ document.warnings.length }} 项)</summary>
            <p v-for="item in document.warnings" :key="item">{{ item }}</p>
          </details>

          <div class="document-import-columns">
            <aside>
              <label v-for="ep in document.episodes" :key="ep.key">
                <input v-model="selected" :value="ep.key" type="checkbox" :disabled="busy || reading" @change="refreshPlan" />
                <button :class="{ active: current?.key === ep.key }" @click="shown = ep.key">
                  原第{{ ep.number }}集 {{ ep.title }}
                  <small>{{ ep.shots.length }} 段 · {{ ep.duration }} 秒</small>
                </button>
              </label>
            </aside>
            <main>
              <nav>
                <button :class="{ active: tab === 'script' }" @click="tab = 'script'">可拍摄剧本 ({{ current?.shots?.length || 0 }} 镜)</button>
                <button :class="{ active: tab === 'archive' }" @click="tab = 'archive'">已分离资料</button>
                <button :class="{ active: tab === 'raw' }" @click="tab = 'raw'">原文/提取文本</button>
              </nav>
              <pre class="document-import-preview" tabindex="0">{{ tab === 'script' ? current?.script : tab === 'archive' ? archiveText : document.rawText }}</pre>
            </main>
          </div>

          <div class="document-import-target">
            <strong>导入到当前项目</strong>
            <p v-if="planning">正在检查集数与重复文档…</p>
            <template v-if="plan">
              <p v-for="item in plan.plan" :key="item.episodeKey">
                {{ item.sourceTitle }} → {{ item.targetTitle }} · {{ item.action === 'duplicate' ? '已导入，本次跳过' : item.action === 'fill_empty' ? '填入当前空白集' : '新建分集' }} ({{ item.shotCount }} 镜)
              </p>
              <p>已有内容的分集不会覆盖；同一份文档重复导入会跳过已导入部分。原文与包装资料随项目保存。</p>
            </template>
            <button v-if="!plan && !planning && !document.errors.length" @click="refreshPlan">刷新导入预览</button>
          </div>
        </template>

        <footer>
          <span v-if="document">已选 {{ selected.length }} 集 · {{ selectedStats.shots }} 段 · {{ selectedStats.duration }} 秒</span>
          <button :disabled="busy" @click="close">关闭</button>
          <button
            class="document-import-confirm"
            :disabled="busy || reading || planning || !plan?.newCount || Boolean(document?.errors.length)"
            @click="confirm"
          >
            {{ busy ? '正在导入…' : plan?.newCount === 0 ? '所选分集已导入' : '确认导入所选分集' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.document-import-overlay {
  position: fixed;
  inset: 0;
  z-index: 19000;
  background: var(--theme-overlay);
  backdrop-filter: blur(6px);
  display: grid;
  place-items: center;
  padding: 24px;
}
.document-import-dialog {
  width: min(1180px, 100%);
  max-height: calc(100vh - 48px);
  overflow: auto;
  border-radius: 16px;
  padding: 24px;
  background: var(--theme-bg-elevated);
  color: var(--theme-text-primary);
  border: 1px solid var(--theme-border-subtle);
  box-shadow: 0 18px 70px var(--theme-shadow);
  box-sizing: border-box;
}
header {
  display: flex;
  align-items: start;
  justify-content: space-between;
  gap: 20px;
}
h2 {
  font-size: 21px;
  margin: 0;
}
p {
  font-size: 13px;
  line-height: 1.7;
  color: var(--theme-text-secondary);
  margin: 8px 0;
}
button {
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
  padding: 8px 12px;
  color: var(--theme-text-primary);
  background: var(--theme-bg-surface);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  transition: all 0.2s ease;
}
button:hover:not(:disabled) {
  border-color: var(--theme-accent);
}
button:disabled {
  opacity: 0.5;
  cursor: default;
}
.guide-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  background: var(--theme-bg-surface);
  border: 1px solid var(--theme-border-subtle);
  border-radius: 10px;
  padding: 8px 12px;
  margin: 12px 0;
}
.format-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.tag-pill {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 6px;
  background: var(--theme-bg-subtle, rgba(120, 120, 120, 0.12));
  color: var(--theme-text-secondary);
}
.tag-pill.highlight {
  background: rgba(33, 150, 243, 0.15);
  color: #1976d2;
  font-weight: 600;
}
.tag-pill.smart {
  background: rgba(76, 175, 80, 0.15);
  color: #2e7d32;
  font-weight: 600;
}
.guide-toggle-btn {
  font-size: 12px;
  padding: 4px 10px;
  border-color: var(--theme-accent-border, #ccc);
  color: var(--theme-accent, #1976d2);
}
.guide-details-card {
  background: var(--theme-bg-surface);
  border: 1px dashed var(--theme-accent, #1976d2);
  border-radius: 10px;
  padding: 14px;
  margin: 10px 0 16px;
  font-size: 12px;
}
.guide-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.copy-template-btn {
  font-size: 11px;
  padding: 4px 8px;
  background: var(--theme-accent);
  color: #fff;
  border: none;
}
.copied-pill {
  display: inline-block;
  font-size: 12px;
  color: #2e7d32;
  background: #e8f5e9;
  padding: 3px 8px;
  border-radius: 4px;
  margin-bottom: 8px;
}
.guide-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.guide-col h4 {
  margin: 4px 0 6px;
  font-size: 12px;
  color: var(--theme-text-primary);
}
.guide-col ul {
  margin: 0;
  padding-left: 18px;
  color: var(--theme-text-secondary);
  line-height: 1.6;
}
.document-import-pick {
  display: flex;
  gap: 12px;
  align-items: center;
  margin: 14px 0;
  font-size: 13px;
  flex-wrap: wrap;
}
.primary-pick-btn {
  background: var(--theme-accent);
  color: #fff;
  border-color: var(--theme-accent);
  font-weight: 600;
}
.folder-pick-btn {
  background: var(--theme-bg-surface);
  font-weight: 500;
}
.doc-chosen-label {
  color: var(--theme-text-secondary);
  font-size: 13px;
}
.paste-details summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--theme-text-secondary);
}
textarea {
  box-sizing: border-box;
  width: 100%;
  height: 120px;
  margin: 10px 0;
  background: var(--theme-bg-surface);
  color: var(--theme-text-primary);
  border: 1px solid var(--theme-border-subtle);
  border-radius: 8px;
  padding: 12px;
  font-family: inherit;
}
.document-import-stats {
  font-weight: 700;
  color: var(--theme-accent);
  font-size: 15px;
  margin-top: 14px;
}
.guide-note {
  font-size: 12px;
  color: var(--theme-text-secondary);
}
.document-import-error {
  color: var(--theme-danger-text);
  background: var(--theme-danger-soft);
  padding: 10px;
  border-radius: 8px;
}
.warnings-details {
  margin: 8px 0;
  padding: 8px 12px;
  background: rgba(255, 152, 0, 0.08);
  border-radius: 8px;
  border-left: 3px solid #ff9800;
  font-size: 12px;
}
.warnings-details summary {
  cursor: pointer;
  font-weight: 600;
  color: #e65100;
}
.warnings-details p {
  margin: 4px 0;
  color: #bf360c;
}
.document-import-columns {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 16px;
  margin: 14px 0;
}
.document-import-columns aside {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.document-import-columns label {
  display: flex;
  align-items: center;
  gap: 8px;
}
.document-import-columns label button {
  flex: 1;
  text-align: left;
}
.document-import-columns small {
  display: block;
  margin-top: 5px;
  color: var(--theme-text-secondary);
}
nav {
  display: flex;
  gap: 8px;
}
.active {
  border-color: var(--theme-accent);
  color: var(--theme-accent);
  font-weight: 600;
}
.document-import-preview {
  font: 13px/1.8 inherit;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  background: var(--theme-bg-surface);
  border: 1px solid var(--theme-border-subtle);
  border-radius: 10px;
  padding: 14px;
  height: 310px;
  overflow: auto;
  margin: 10px 0 0;
}
.document-import-target {
  padding: 12px 14px;
  border: 1px solid var(--theme-border-subtle);
  border-radius: 10px;
  font-size: 13px;
  margin-top: 14px;
}
footer {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-end;
  padding-top: 18px;
}
footer span {
  margin-right: auto;
  font-size: 13px;
  color: var(--theme-text-secondary);
}
.document-import-confirm {
  background: var(--theme-accent);
  color: #fff;
  font-weight: 600;
}
@media (max-width: 780px) {
  .document-import-columns {
    grid-template-columns: 1fr;
  }
  .document-import-columns aside {
    max-height: 160px;
    overflow: auto;
  }
  .guide-grid {
    grid-template-columns: 1fr;
  }
}

.ai-cascade-banner{display:flex;align-items:center;justify-content:space-between;gap:14px;padding:12px 16px;background:var(--theme-bg-surface);border:1px solid var(--theme-border-subtle);border-radius:10px;margin:8px 0 14px}
.ai-cascade-banner.is-novel{border-color:var(--theme-accent, #1976d2);background:var(--theme-accent-soft, rgba(25,118,210,.08))}
.cascade-meta{display:flex;flex-direction:column;gap:4px;min-width:0;flex:1}
.badge-tag{font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:5px;display:inline-block}
.badge-tag.novel{background:#fff3cd;color:#856404}
.badge-tag.ok{background:#d4edda;color:#155724}
.cascade-text{font-size:12px;color:var(--theme-text-secondary);margin:0;line-height:1.4}
.cascade-ai-btn{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;background:var(--theme-accent, #1976d2);color:#fff;border:none;border-radius:8px;font-size:12.5px;font-weight:600;cursor:pointer;white-space:nowrap;transition:all .2s ease;box-shadow:0 2px 6px rgba(0,0,0,.1)}
.cascade-ai-btn:hover:not(:disabled){filter:brightness(1.1);transform:translateY(-1px)}
.cascade-ai-btn:disabled{opacity:.6;cursor:not-allowed}
.cascade-ai-btn svg{width:14px;height:14px;fill:currentColor}
.cascade-ai-btn.pulse{box-shadow:0 0 0 0 rgba(25,118,210,.5);animation:pulse-btn 2s infinite}
@keyframes pulse-btn{0%{box-shadow:0 0 0 0 rgba(25,118,210,.5)}70%{box-shadow:0 0 0 8px rgba(25,118,210,0)}100%{box-shadow:0 0 0 0 rgba(25,118,210,0)}}
.btn-spinner{width:12px;height:12px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;border-radius:50%;display:inline-block;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

</style>
