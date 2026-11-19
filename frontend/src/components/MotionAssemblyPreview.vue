<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
const props=defineProps({projectId:String,token:String,clips:Array,fileUrl:Function})
const emit=defineEmits(['close'])
const owner=props.projectId
const jobs=ref([]),selectedId=ref(''),error=ref(''),busy=ref(false),querying=ref(false)
const dialog=ref(null),previousFocus=document.activeElement
let alive=true,timer=null
const selected=computed(()=>jobs.value.find(j=>j.id===selectedId.value)||jobs.value[0])
const running=computed(()=>jobs.value.some(j=>['queued','running'].includes(j.status)))
const sources=computed(()=>(props.clips||[]).map(c=>({fileId:c.fileId,shotId:c.shotId||c.id,title:c.title})))
const changed=j=>JSON.stringify(j.sources?.map(s=>s.fileId))!==JSON.stringify(sources.value.map(s=>s.fileId))
const blocked=computed(()=>props.clips?.some(c=>c.exportBlocked)?'有分镜未通过人物或场景参考检查，请先处理该分镜。':sources.value.length<2?'请选择至少两段视频。':'')
const label=j=>j.status==='succeeded'?(j.result?.geometryAlignment?(j.acceptedScope?.joins?.length?`已认可第${j.acceptedScope.joins.map(n=>`${n}→${n+1}`).join('、')}镜接续`:'真实画面接续版 · 候选'):j.result?.artifactProtection?'防重影处理版 · 候选':j.result?.cadenceVersion===2?'旧运动节奏版 · 可能出现补帧重影':j.userAccepted?'已认可的旧版 · 仅对齐首帧':'旧版 · 仅对齐首帧'):['queued','running'].includes(j.status)?j.stage||'正在处理接点':j.status==='interrupted'?'上次处理已中断':'上次处理未完成'
const api=()=>window.pywebview.api
const call=(action,body={})=>api().backend_request('POST','/ai/video',props.token,{production_mode:`assembly_motion_${action}`,project_id:owner,...body})
function schedule(){clearTimeout(timer);if(alive&&running.value)timer=setTimeout(()=>void refresh(),1500)}
async function refresh(){
  if(querying.value)return
  querying.value=true
  try{const result=await call('history');if(!alive)return;if(!Array.isArray(result))throw Error('处理记录未完整返回');jobs.value=result;if(!result.some(j=>j.id===selectedId.value))selectedId.value=result[0]?.id||''}
  catch(e){if(alive)error.value=`状态暂未取回：${e.message||e}。已开始的本地处理不会因此重复提交。`}
  finally{querying.value=false;schedule()}
}
async function start(){
  if(busy.value||running.value||blocked.value)return
  busy.value=true;error.value=''
  try{const job=await call('start',{request_id:crypto.randomUUID(),source_videos:sources.value});if(!alive)return;jobs.value=[job,...jobs.value.filter(j=>j.id!==job.id)];selectedId.value=job.id;schedule()}
  catch(e){if(alive)error.value=String(e.message||e)}
  finally{busy.value=false}
}
async function exportVideo(){
  if(!selected.value?.result?.fileId)return
  try{await api().save_server_video_as(props.token,selected.value.result.fileId,'分镜接点处理_候选.mp4')}
  catch(e){if(alive)error.value=String(e.message||e)}
}
void refresh()
function onEscape(event){if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();emit('close')}}
onMounted(()=>{dialog.value?.focus();window.addEventListener('keydown',onEscape,true)})
onBeforeUnmount(()=>{alive=false;clearTimeout(timer);window.removeEventListener('keydown',onEscape,true);previousFocus?.focus?.()})
</script>
<template>
  <Teleport to="body">
    <div class="motion-overlay" @keydown.esc.stop.prevent="emit('close')" @mousedown.self="emit('close')">
      <section ref="dialog" tabindex="-1" class="motion-dialog" role="dialog" aria-modal="true" aria-labelledby="motion-title">
        <header><h2 id="motion-title">分镜接点处理</h2><button aria-label="关闭接点处理" @click="emit('close')">×</button></header>
        <p>先保护遮挡和人物新出现的位置，再对局部突然错位的接点做真实画面对齐，每帧只用对应时刻的一张画面。保留原分镜、对白和时长；本地执行，不调用模型或消耗视频额度。</p>
        <p>大幅动作、人物或场景不一致，仍需用 AI 补段或修复原镜头。处理版单独保留，供你连看效果。</p>
        <div class="motion-actions"><button class="motion-start" :disabled="busy||running||Boolean(blocked)" @click="start">{{busy?'正在提交…':running?'正在处理接点…':'生成接点处理版'}}</button><button :disabled="querying" @click="refresh">刷新记录</button><button v-if="selected?.result?.fileId" @click="exportVideo">导出处理版</button></div>
        <p v-if="blocked" class="motion-notice">{{blocked}}</p><p v-if="error" class="motion-error" role="alert">{{error}}</p>
        <label v-if="jobs.length>1">保留的处理记录 <select v-model="selectedId" aria-label="接点处理历史"><option v-for="j in jobs" :key="j.id" :value="j.id">{{new Date(j.createdAt||j.createTime).toLocaleString()}} · {{label(j)}}</option></select></label>
        <template v-if="selected">
          <p class="motion-status" role="status">{{label(selected)}} <span v-if="selected.status==='succeeded'">· {{Number(selected.result?.duration||0).toFixed(1)}} 秒</span></p>
          <p v-if="selected.result?.cadenceVersion===2" class="motion-notice">这个旧版可能出现半透明人物、重影或局部拉扯，请使用最新防重影版比较效果。</p>
          <p v-if="selected.result?.joins?.some(j=>j.requiresMotionRepair)" class="motion-notice">部分接点的前后画面不能可靠对应，已保护这些区域，避免强行补帧造成重影；这些位置仍可能跳切，需要 AI 修复原镜头或补动作，不能视为无缝衔接已通过。</p>
          <p v-if="selected.error" class="motion-error">{{selected.error}}</p>
          <p v-if="changed(selected)" class="motion-notice">此记录使用的素材与当前选择不同，仍可查看旧版；新处理会使用当前选择。</p>
          <video v-if="selected.result?.fileId" :key="selected.result.fileId" :src="fileUrl(selected.result.fileId)" controls playsinline preload="metadata" />
          <p v-if="selected.result?.joins?.some(j=>!j.processed)" class="motion-notice">部分接点差异较大，保留了原切镜；可回到 AI 衔接组片处理缺失动作。</p>
          <p v-if="running">离开这个窗口不会取消已开始的本地处理，重新打开可继续查看结果。</p>
        </template>
        <p v-else-if="!querying">尚无处理记录。原分镜不会被覆盖。</p>
      </section>
    </div>
  </Teleport>
</template>
<style scoped>
.motion-overlay{position:fixed;inset:0;z-index:18000;display:grid;place-items:center;padding:24px;background:var(--theme-overlay);backdrop-filter:blur(8px)}.motion-dialog{box-sizing:border-box;width:min(1000px,100%);max-height:calc(100vh - 48px);overflow:auto;padding:20px 24px;border:1px solid var(--theme-border-subtle);border-radius:16px;background:var(--theme-bg-elevated);color:var(--theme-text-primary);box-shadow:0 20px 80px var(--theme-shadow)}header{display:flex;align-items:center;justify-content:space-between;gap:16px}h2{margin:0;font-size:20px}p{font-size:13px;line-height:1.7;color:var(--theme-text-secondary)}button,select{padding:8px 12px;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-surface);color:var(--theme-text-primary);font:inherit;font-size:13px}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}.motion-actions{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.motion-start{background:var(--theme-accent);color:var(--theme-text-on-accent)}.motion-status{font-weight:700;color:var(--theme-text-primary)}.motion-error{padding:10px;border-radius:8px;color:var(--theme-danger-text);background:var(--theme-danger-soft)}.motion-notice{padding:10px;border-radius:8px;background:var(--theme-bg-surface)}label{font-size:12px;display:flex;gap:10px;align-items:center}video{display:block;width:100%;max-height:55vh;background:#111;border-radius:10px;object-fit:contain}
</style>
