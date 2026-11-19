<script setup>
import { computed, ref } from 'vue'
import { desktopBackendRequest } from '../utils/desktopApi.js'
const props = defineProps({ catalog: Object, selected: { type: Array, default: () => [] }, token: String })
const emit = defineEmits(['update:selected', 'template'])
const section = ref('shots'), category = ref('all'), query = ref(''), page = ref(1), playing = ref('')
const document = ref(null), error = ref(''), loading = ref(false)
const samples = computed(() => (props.catalog?.cards || []).flatMap(card => card.styles.map(style => ({ ...style, card }))))
const filtered = computed(() => samples.value.filter(item => (category.value === 'all' || category.value === item.card.category)
  && (!query.value.trim() || `${item.card.name} ${item.key} ${item.card.summary} ${item.card.use}`.toLowerCase().includes(query.value.trim().toLowerCase()))))
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / 12)))
const visible = computed(() => filtered.value.slice((Math.min(page.value, pageCount.value) - 1) * 12, Math.min(page.value, pageCount.value) * 12))
function toggle(key) { emit('update:selected', props.selected.includes(key) ? props.selected.filter(value => value !== key) : [...props.selected, key]) }
async function read(path) {
  loading.value = true; error.value = ''
  try { document.value = await desktopBackendRequest('GET', `/shotcraft/resource?path=${encodeURIComponent(path)}`, props.token) }
  catch (err) { error.value = String(err) }
  finally { loading.value = false }
}
const guides = [
  ['SKILL.md', '完整技能'], ['references/pipeline.md', '完整制作流程'], ['references/guided-free-creation.md', '逐步共创'],
  ['references/aesthetic-rules.md', '审美与节奏'], ['references/sound-design.md', '声音设计'], ['references/sfx-sourcing.md', '音效选材'],
  ['references/music-beat-sync.md', '音乐卡点'], ['references/final-review.md', '终片检查'], ['references/workbench.md', '动效工作台'],
  ['references/jianying-export.md', '剪映工程导出'], ['references/publish-upload-post.md', '按需发布'], ['README_CN.md', '仓库说明'],
]
</script>

<template>
  <section class="shotcraft-library">
    <header class="shotcraft-head"><div><span class="gv-eyebrow">VIDEO SHOTCRAFT</span><h2>模板与镜头库</h2><p>{{ catalog?.cardCount || 0 }} 张镜头卡 · {{ catalog?.styleCount || 0 }} 种效果 · {{ catalog?.previewCount || 0 }} 条本地样片</p></div><span class="gv-pill">完整技能已接入</span></header>
    <div class="gv-tabs"><button v-for="tab in [['shots','动效镜头'],['template','整片模板'],['guides','技能与工具'] ]" :key="tab[0]" :class="{active:section===tab[0]}" @click="section=tab[0]">{{ tab[1] }}</button></div>
    <p v-if="error" role="alert" class="gv-error">{{ error }}</p>
    <template v-if="section==='shots'">
      <div class="sc-search"><input v-model="query" type="search" placeholder="搜索效果、用途或镜头名" @input="page=1"/><span>已选 {{ selected.length }} 个效果</span></div>
      <div class="sc-categories"><button :class="{active:category==='all'}" @click="category='all';page=1">全部</button><button v-for="(label,key) in catalog?.categories || {}" :key="key" :class="{active:category===key}" @click="category=key;page=1">{{ label.zh }}</button></div>
      <div class="sc-grid"><article v-for="sample in visible" :key="sample.key" class="sc-card" :class="{selected:selected.includes(sample.key)}">
        <div class="sc-preview"><video v-if="playing===sample.key" :src="sample.previewUrl" :poster="sample.posterUrl" controls autoplay muted playsinline preload="metadata" :aria-label="sample.key+' 动态预览'"></video><button v-else class="sc-play" :aria-label="'播放 '+sample.key+' 样片'" @click="playing=sample.key"><img :src="sample.posterUrl" :alt="sample.label" loading="lazy"/><span>▶ 动态预览</span></button></div>
        <div><small>{{ catalog?.categories?.[sample.card.category]?.zh }}</small><h3>{{ sample.label }}</h3><p>{{ sample.description || sample.card.summary }}</p><footer><button @click="read(sample.card.source)">镜头配方</button><button :aria-pressed="selected.includes(sample.key)" @click="toggle(sample.key)">{{ selected.includes(sample.key)?'✓ 已选用':'选用效果' }}</button></footer></div>
      </article></div>
      <div class="sc-pagination"><button :disabled="page<=1" @click="page--">上一页</button><span>{{ Math.min(page,pageCount) }} / {{ pageCount }} · 共 {{ filtered.length }} 个效果</span><button :disabled="page>=pageCount" @click="page++">下一页</button></div>
    </template>
    <article v-else-if="section==='template'" class="sc-template"><div class="sc-template-art"><small>COMPLETE FILM TEMPLATE</small><strong>Ink<br>Press.</strong><span>纸墨晨读 · 产品宣传</span></div><div><span class="gv-pill">完整成片工程 · 约36秒</span><h2>从完整节奏开始，换成你的产品</h2><p>品牌开场、功能展示、字卡过渡、声音设计与品牌收尾已安排。选用后，助手按这套模板适配你的素材与文案。</p><p>界面、图片、Logo 与文案使用你的资料；原始模板和全部源码均保留。</p><button class="gv-primary" @click="emit('template')">使用整片模板</button><button class="gv-secondary" @click="read('template/TEMPLATE.md')">查看完整结构</button></div></article>
    <div v-else class="sc-guides"><p>全部技能资料与源码保留在本地。创作时按任务读取，镜头卡会连同对应实现一起交给助手。</p><div><button v-for="guide in guides" :key="guide[0]" @click="read(guide[0])"><strong>{{ guide[1] }}</strong><small>{{ guide[0] }}</small></button></div><details><summary>浏览全部 {{ catalog?.resources?.length || 0 }} 份文档</summary><button v-for="path in catalog?.resources || []" :key="path" class="sc-resource-link" @click="read(path)">{{ path }}</button></details></div>
    <p v-if="loading" role="status">正在读取完整资料…</p>
    <div v-if="document" class="sc-doc-overlay" @click.self="document=null"><section role="dialog" aria-modal="true" aria-label="技能资料"><header><strong>{{ document.path }}</strong><button aria-label="关闭技能资料" @click="document=null">×</button></header><pre>{{ document.content }}</pre></section></div>
  </section>
</template>

<style scoped>
.shotcraft-head{display:flex;align-items:center;justify-content:space-between;gap:20px}.shotcraft-head h2{margin:7px 0}.shotcraft-head p,.sc-guides p{color:var(--theme-text-secondary);line-height:1.7}.sc-search{display:flex;gap:20px;align-items:center;margin:20px 0 12px}.sc-search input{flex:1}.sc-search span{font-size:13px;color:var(--theme-text-secondary)}.sc-categories{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:20px}.sc-categories button{border:1px solid var(--theme-border-subtle);border-radius:20px;padding:7px 12px;color:var(--theme-text-secondary);background:var(--theme-bg-card);cursor:pointer}.sc-categories button.active{color:var(--theme-accent);border-color:var(--theme-accent);background:var(--theme-accent-soft)}.sc-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.sc-card{overflow:hidden;border:1px solid var(--theme-border-subtle);border-radius:14px;background:var(--theme-bg-card)}.sc-card.selected{border-color:var(--theme-accent)}.sc-card video{display:block;width:100%;aspect-ratio:16/9;background:#10131c}.sc-card>div:not(.sc-preview){padding:14px}.sc-preview{aspect-ratio:16/9;background:#10131c}.sc-card .sc-play{position:relative;display:block;width:100%;height:100%;padding:0;border:0;border-radius:0;background:#10131c;overflow:hidden}.sc-play img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover}.sc-play span{position:absolute;bottom:12px;left:12px;padding:6px 10px;border-radius:20px;background:#0009;color:white;font-size:11px}.sc-play:hover span{background:var(--theme-accent)}.sc-card small{color:var(--theme-accent);font-size:11px}.sc-card h3{font-size:13px;overflow-wrap:anywhere;margin:8px 0}.sc-card p{font-size:12px;line-height:1.7;color:var(--theme-text-secondary);min-height:62px}.sc-card footer{display:flex;justify-content:space-between;gap:8px}.sc-card button,.sc-pagination button{padding:7px 11px;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-elevated);color:var(--theme-text-primary);cursor:pointer}.sc-card button[aria-pressed=true]{background:var(--theme-accent);color:white}.sc-pagination{display:flex;align-items:center;justify-content:center;gap:18px;margin:25px 0;font-size:13px}.sc-template{display:grid;grid-template-columns:34% 1fr;gap:36px;margin:25px 0;padding:28px;border:1px solid var(--theme-border-subtle);border-radius:18px;background:var(--theme-bg-card)}.sc-template-art{min-height:290px;padding:25px;background:#f2eee6;color:#24201b;display:flex;flex-direction:column;justify-content:space-between}.sc-template-art small{font-size:9px;letter-spacing:2px}.sc-template-art strong{font:68px/1 Georgia,serif}.sc-template-art span{font-size:12px;letter-spacing:2px}.sc-template p{line-height:1.9;color:var(--theme-text-secondary)}.sc-template button{margin:12px 10px 0 0}.sc-guides>div{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:20px 0}.sc-guides>div button{display:flex;flex-direction:column;gap:8px;text-align:left;padding:18px;border:1px solid var(--theme-border-subtle);border-radius:12px;color:var(--theme-text-primary);background:var(--theme-bg-card);cursor:pointer}.sc-guides small{font-size:11px;color:var(--theme-text-secondary);overflow-wrap:anywhere}.sc-resource-link{display:block;padding:7px 0;border:0;color:var(--theme-accent);background:transparent;cursor:pointer}.sc-doc-overlay{position:fixed;inset:0;z-index:500;background:#11182788;display:grid;place-items:center;padding:35px}.sc-doc-overlay section{width:min(1000px,95vw);max-height:90vh;display:flex;flex-direction:column;border-radius:16px;background:var(--theme-bg-elevated);overflow:hidden;box-shadow:0 24px 80px #0005}.sc-doc-overlay header{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;border-bottom:1px solid var(--theme-border-subtle)}.sc-doc-overlay header button{font-size:26px;border:0;background:transparent;color:var(--theme-text-secondary);cursor:pointer}.sc-doc-overlay pre{white-space:pre-wrap;overflow:auto;margin:0;padding:24px;font:13px/1.9 Consolas,monospace;color:var(--theme-text-primary)}@media(max-width:1150px){.sc-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:800px){.sc-grid,.sc-template,.sc-guides>div{grid-template-columns:1fr}}
</style>
