<script setup>
import {computed,onMounted,onBeforeUnmount,ref,watch,nextTick} from 'vue'
import UiSelect from './UiSelect.vue'
import { FILM_LAYOUTS, filmLayoutValue } from '../utils/filmLayouts.js'
import {desktopBackendRequest} from '../utils/desktopApi.js'
const props=defineProps({token:String,project:Object,chapterId:String,script:String,brief:Object,model:String,modelOptions:Array,storageBase:String,settingsBusy:Boolean})
const emit=defineEmits(['advanced','save-script','update:model','model-settings','select-layout','template-library'])
const plan=ref(null),jobs=ref([]),selectedId=ref(''),busy=ref(''),error=ref(''),warnings=ref([]),sound=ref(true),audioId=ref(''),audioName=ref(''),duration=ref(30),showSections=ref(false),showVersions=ref(false)
const request=(method,path,body=null)=>desktopBackendRequest(method,path,props.token,body,0)
const context=()=>({projectId:String(props.project.id),chapterId:String(props.chapterId||''),model:props.model,script:props.script,brief:{...props.brief,duration:duration.value}})
const current=computed(()=>jobs.value.find(j=>j.id===selectedId.value)||jobs.value[0])
const running=computed(()=>jobs.value.find(j=>['queued','rendering'].includes(j.status)))
const currentUrl=computed(()=>current.value?.fileId?`${props.storageBase||'http://127.0.0.1:18081'}/file/${current.value.fileId}/download`:'')
const ready=computed(()=>jobs.value.filter(j=>j.status==='succeeded'))
const dirty=computed(()=>plan.value&&current.value?.plan&&JSON.stringify(plan.value)!==JSON.stringify(current.value.plan))
const options=[{value:'title',label:'标题字卡'},{value:'statement',label:'重点说明'},{value:'steps',label:'步骤列表'},{value:'comparison',label:'双栏对比'},{value:'diagram',label:'流程图解'},{value:'image',label:'图片展示'},{value:'outro',label:'结尾字卡'}]
const audioModels=ref([]),audioModel=ref(''),voice=ref(''),narrationMode=ref('auto'),autoExtend=ref(true),musicId=ref(''),musicName=ref(''),theme=ref('auto')
const audioOptions=computed(()=>audioModels.value.map(m=>({value:String(m.id),label:m.name||m.modelName})))
const narrationModes=[{value:'auto',label:'自动生成旁白'},{value:'file',label:'导入已有旁白'},{value:'none',label:'不要旁白'}]
const narrationProvider=ref('breeze'),breezeVoice=ref(''),breezeInstruction=ref('普通话清晰自然，温暖沉稳的女声，语速适中，适合知识讲解。'),breezeStatus=ref(null),breezeStarting=ref(false)
const voiceSources=[{value:'breeze',label:'本地 Breeze TTS'},{value:'cloud',label:'已配置云端语音服务'}]
const breezeVoices=computed(()=>[{value:'',label:'按声音描述固定音色'},...(breezeStatus.value?.voices||[]).map(v=>({value:v.id,label:v.description||v.id}))])
const voiceSourceName=computed(()=>narrationProvider.value==='breeze'?'本地 Breeze TTS':audioOptions.value.find(m=>m.value===audioModel.value)?.label||'请选择云端配音模型')
let breezeTimer=null,breezeDeadline=0
async function loadBreeze(){try{const status=await window.pywebview.api.breeze_status();if(!active)return;breezeStatus.value=status;if(status.ready){breezeStarting.value=false;clearInterval(breezeTimer)}else if(breezeStarting.value&&Date.now()>breezeDeadline){breezeStarting.value=false;clearInterval(breezeTimer);error.value='Breeze 加载尚未完成，请查看本地 Breeze 窗口后刷新连接'}}catch(e){if(active){breezeStarting.value=false;clearInterval(breezeTimer);breezeStatus.value={ready:false,message:'本地配音连接不可用，请重启更新后的 CDTV'}}}}
async function startBreeze(){error.value='';breezeStarting.value=true;try{await window.pywebview.api.breeze_start('');if(!active)return;breezeDeadline=Date.now()+180000;await loadBreeze();if(!breezeStatus.value?.ready){clearInterval(breezeTimer);breezeTimer=setInterval(loadBreeze,3000)}}catch(e){breezeStarting.value=false;error.value=String(e?.message||e)}}

const modelName=computed(()=>props.modelOptions?.find(m=>String(m.value)===String(props.model))?.label||'尚未选择')
const actualSource=computed(()=>current.value?.plannerModelName||current.value?.plan?.plannerModelName||'旧版未记录')
const displayWarnings=computed(()=>[...new Set([...warnings.value,...(current.value?.plan?.imageWarnings||[])])])
const narrationCount=computed(()=>plan.value?.scenes?.filter(s=>s.narration?.trim()).length||0)
const selectedLayout=computed(()=>filmLayoutValue(props.brief))
const selectedLayoutName=computed(()=>FILM_LAYOUTS.find(item=>item.value===selectedLayout.value)?.label||'')
const selectedTemplate=computed(()=>props.brief?.templateId||(props.brief?.mode==='template'?'ink-press':''))
const optionsEl=ref(null),optionsHeight=ref('calc(100vh - 460px)')
function fitOptions(){nextTick(()=>{if(!active||!optionsEl.value||window.innerWidth<=1050)return;optionsHeight.value=Math.max(260,window.innerHeight-optionsEl.value.getBoundingClientRect().top-20)+'px'})}
async function loadAudioModels(){try{audioModels.value=await request('GET','/api/admin/models/public/list?modelType=audio')||[];if(!audioModel.value)audioModel.value=String(audioModels.value[0]?.id||'')}catch(e){error.value=String(e?.message||e)}}
let timer=null,active=true,loading=false,lastSubmitted=null
async function refresh(){
 if(loading||!props.chapterId)return
 loading=true
 try{const list=await request('POST','/shotcraft/film/list',context());if(!active)return;jobs.value=list||[];if(!selectedId.value&&jobs.value.length){chooseVersion(jobs.value.find(j=>['queued','rendering'].includes(j.status))||jobs.value.find(j=>j.status==='succeeded')||jobs.value[0],false)}else if(current.value?.status==='succeeded'&&lastSubmitted?.id===current.value.id&&JSON.stringify(plan.value)===lastSubmitted.signature){chooseVersion(current.value);lastSubmitted=null}}catch(e){if(active)error.value=String(e?.message||e)}finally{loading=false}
}
async function prepare(){
 if(!props.chapterId){emit('save-script');return false}
 const result=await request('POST','/shotcraft/film/prepare',context());if(!active)return false;plan.value=result.plan;warnings.value=result.warnings||[];return true
}
async function generate(){
 if(busy.value||running.value||props.settingsBusy)return
 busy.value='generate';error.value=''
 try{
  if(!props.chapterId){emit('save-script');throw new Error('请先保存脚本，再生成整片')}
  if(narrationMode.value==='auto'&&narrationProvider.value==='breeze'&&!breezeStatus.value?.ready)throw new Error('请先启动本地 Breeze 并等待连接就绪；不会自动切换云端收费配音')
  if(narrationMode.value==='auto'&&narrationProvider.value==='cloud'&&!audioModel.value)throw new Error('请先在模型配置添加或启用配音模型，也可使用本地 Breeze、导入旁白或选择不要旁白')
  if(narrationMode.value==='file'&&!audioId.value)throw new Error('请先导入旁白文件')
  if(!plan.value||!plan.value.rendererVersion||plan.value.rendererVersion<2){busy.value='prepare';if(!await prepare())return;busy.value='generate'}
  if(!active)return
  const job=await request('POST','/shotcraft/film/start',{...context(),plan:{...plan.value,duration:duration.value,...(theme.value!=='auto'?{theme:theme.value}:{})},sound:sound.value,audioFileId:narrationMode.value==='file'?audioId.value:'',musicFileId:musicId.value,narration:{enabled:narrationMode.value==='auto',provider:narrationProvider.value,model:audioModel.value,voice:narrationProvider.value==='breeze'?breezeVoice.value:voice.value,instruction:breezeInstruction.value,autoExtend:autoExtend.value}});if(!active)return;plan.value=JSON.parse(JSON.stringify(job.plan));lastSubmitted={id:job.id,signature:JSON.stringify(plan.value)};selectedId.value=job.id;jobs.value=[job,...jobs.value];await refresh()
 }catch(e){error.value=String(e?.message||e)}finally{busy.value=''}
}
async function replan(){busy.value='prepare';error.value='';try{await prepare();showSections.value=true}catch(e){error.value=String(e?.message||e)}finally{busy.value=''}}
async function cancel(){if(!running.value)return;try{await request('POST','/shotcraft/film/cancel/'+running.value.id,{});await refresh()}catch(e){error.value=String(e?.message||e)}}
async function exportFilm(){if(!current.value?.fileId)return;try{await window.pywebview.api.save_server_video_as(props.token,current.value.fileId,`${props.project.name}.mp4`)}catch(e){error.value=String(e?.message||e)}}
async function chooseAudio(music=false){
 try{const api=window.pywebview.api;const chosen=await api.select_local_reference_file();if(!chosen)return;if(chosen.mediaType!=='audio')throw new Error('请选择音频文件');const result=await api.upload_local_file(props.token,chosen.path);const id=String(result.id||result.fileId||'');if(music){musicId.value=id;musicName.value=chosen.name||'已导入配乐'}else{audioId.value=id;audioName.value=chosen.name||'已导入旁白';narrationMode.value='file'}}catch(e){error.value=String(e?.message||e)}
}
function chooseVersion(job,restoreSource=true){selectedId.value=job.id;plan.value=JSON.parse(JSON.stringify(job.plan));duration.value=job.plan.duration;audioId.value=job.audioFileId||'';sound.value=job.sound!==false;if(job.narration?.enabled&&restoreSource){narrationProvider.value=job.narration.provider||'cloud';if(narrationProvider.value==='breeze'){breezeVoice.value=job.narration.voice||'';breezeInstruction.value=job.narration.instruction||breezeInstruction.value}else{audioModel.value=job.narration.model||audioModel.value;voice.value=job.narration.voice||''}}narrationMode.value=job.audioFileId?'file':job.narration?.enabled===false?'none':'auto';musicId.value=job.musicFileId||'';theme.value=props.brief?.filmTheme||'auto'}
onMounted(()=>{duration.value=Number(props.brief?.duration||30);refresh();loadAudioModels();loadBreeze();timer=setInterval(refresh,1500);fitOptions();window.addEventListener('resize',fitOptions)})
onBeforeUnmount(()=>{active=false;clearInterval(timer);clearInterval(breezeTimer);window.removeEventListener('resize',fitOptions)})
watch(()=>props.brief?.filmTheme,value=>{theme.value=value||'auto'})
watch(()=>props.script,()=>{if(!running.value)plan.value=null})
</script>

<template>
 <section class="whole-film-studio" aria-label="整片制作">
  <header class="whole-film-head"><div><span>模板动效整片</span><h2>制作一支完整作品</h2><p>文本模型规划内容，本地渲染画面；自动旁白使用下方配音模型。</p></div><button class="gv-secondary" @click="emit('advanced')">高级编辑：素材与逐镜制作</button></header>
  <div class="whole-film-method" role="note"><strong>生成设置：{{ selectedTemplate?"Ink Press 原版镜头":"通用图解排版" }}</strong><span>文字规划：{{ modelName }}</span><span>画面：{{selectedTemplate?"原版10镜头与动效，本地渲染":"通用图解，本地渲染"}}，未调用视频模型</span><span>新版本声音：{{ narrationMode==='auto'?voiceSourceName:narrationMode==='file'?'导入旁白':'不含旁白' }}</span><button @click="emit('model-settings')">模型配置</button></div>
  <p v-if="error" class="gv-error" role="alert">{{ error }}</p>
  <div class="whole-film-grid">
   <section class="whole-film-player"><video v-if="currentUrl" :key="current.fileId" :src="currentUrl" controls preload="metadata"></video><div v-else class="whole-film-empty"><span>▶</span><h3>{{ running?'正在制作整片':'整片将在这里显示' }}</h3><p>{{ busy==='prepare'?'正在按脚本安排完整画面与文字…':'点击生成整片，直接输出完整视频。' }}</p></div>
    <div v-if="running" class="whole-film-progress" role="status"><progress :value="running.progress||0" max="100"></progress><span>{{ running.message }} · {{ running.progress||0 }}%</span><button class="gv-secondary" @click="cancel">取消制作</button></div>
    <div v-else-if="current" class="whole-film-result"><span>{{ current.message }}<small v-if="current.status==='succeeded'"> · {{ current.duration }} 秒 · {{ current.narration?.enabled?'已合入自动旁白 · '+(current.narration.modelName||'旧版未记录'):current.audioFileId?'已合入导入音频':'此版本没有旁白' }}</small><small v-if="current.status==='succeeded'">规划模型：{{ actualSource }} · {{current.templateId?current.templateName:"旧版通用排版，未执行整片模板"}}<span v-if="current.extendedForTemplate"> · 已按原模板最低时长延长</span><span v-if="current.extendedForNarration"> · 已按实际旁白延长，未加速或截尾</span></small></span><button v-if="current.fileId" class="gv-primary" @click="exportFilm">导出完整视频</button></div>
    <button v-if="jobs.length" class="whole-film-history-toggle" @click="showVersions=!showVersions">{{ showVersions?'收起':'查看' }}历史版本（{{ jobs.length }}）</button>
    <div v-if="showVersions" class="whole-film-history"><button v-for="job in jobs" :key="job.id" :class="{active:job.id===selectedId}" @click="chooseVersion(job)">{{ new Date(job.createTime).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) }} · {{ job.status==='succeeded'?'已完成':job.status==='failed'?'失败':job.status==='cancelled'?'已取消':job.status==='interrupted'?'已中断':'制作中' }}</button></div>
   </section>
   <aside ref="optionsEl" class="whole-film-options" :style="{maxHeight:optionsHeight}">
    <h3>整片设置</h3>
    <section class="whole-film-layout-picker" aria-label="模板与画面方案"><header><strong>模板与画面方案</strong><button type="button" :disabled="!!busy||!!running||settingsBusy" @click="emit('template-library')">浏览模板库 →</button></header><UiSelect :model-value="selectedLayout" :options="FILM_LAYOUTS" aria-label="整片模板与画面方案" :searchable="false" :disabled="!!busy||!!running||settingsBusy" @update:model-value="emit('select-layout',$event)"/><small>{{ settingsBusy?'正在保存选择…':'选择后自动保存，用于下一次生成；当前播放与历史版本保留。' }}</small></section>
    <label>文字规划模型<UiSelect :model-value="model" :options="modelOptions||[]" aria-label="整片文本模型" :disabled="!!busy||!!running" @update:model-value="emit('update:model',$event)"/></label><small>只在整理或更新方案时调用文本模型。真实动态场景、人物表演请进入高级编辑使用视频模型。</small>
    <details v-if="selectedTemplate" class="whole-film-template-note"><summary>Ink Press 模板说明 · 约36.2秒</summary><p>完整动效包括开场聚光、卡片发牌、行嵌入、列表堆叠、文档揭示与合影收尾。计划不足时按模板延长，旁白另按实际时长安排。</p><p>原演示品牌和截图替换为作品内容图解或已有图片。</p></details><small v-else>当前使用{{ selectedLayoutName }}，按内容呈现标题、图片与图解。完整运镜模板可在上方选择 Ink Press。</small>
    <label>计划时长（秒）<input v-model.number="duration" type="number" min="5" max="180" :disabled="!!running" /></label>
    <label>旁白方式<UiSelect v-model="narrationMode" :options="narrationModes" aria-label="整片旁白方式" :disabled="!!busy||!!running"/></label>
    <template v-if="narrationMode==='auto'">
     <label>配音来源<UiSelect v-model="narrationProvider" :options="voiceSources" aria-label="整片配音来源" :disabled="!!busy||!!running"/></label>
     <template v-if="narrationProvider==='breeze'">
      <div class="whole-film-breeze" role="status"><strong>{{ breezeStatus?.ready?'本地 Breeze 已连接':breezeStarting?'正在加载本地 Breeze…':'本地 Breeze 未连接' }}</strong><small>在本机合成旁白，无云端语音调用费。</small><div><button v-if="!breezeStatus?.ready" class="gv-secondary" :disabled="breezeStarting||!!running" @click="startBreeze">{{ breezeStarting?'正在启动…':'启动本地 Breeze' }}</button><button class="gv-secondary" :disabled="!!running" @click="loadBreeze">刷新连接</button></div></div>
      <label>本地音色<UiSelect v-model="breezeVoice" :options="breezeVoices" aria-label="整片 Breeze 音色" :disabled="!!running"/></label>
      <label>声音描述<textarea v-model="breezeInstruction" rows="3" aria-label="整片 Breeze 声音描述" :disabled="!!running" placeholder="例如：温暖自然的女声，普通话清晰，语速适中"/></label><small>同一作品固定音色，按段落实际语音时长安排画面。Breeze 未就绪时会提示，不会自动改用云端。</small>
     </template>
     <template v-else><label>配音模型<UiSelect v-model="audioModel" :options="audioOptions" aria-label="整片配音模型" placeholder="请先配置配音模型" :disabled="!!running"/></label><details class="whole-film-voice-details"><summary>音色设置（选填）</summary><input v-model="voice" aria-label="整片音色" placeholder="指定音色ID，留空使用固定默认音色" :disabled="!!running"/></details><small>使用已配置语音服务，按其原资费计费。</small></template>
     <label class="whole-film-check"><input v-model="autoExtend" type="checkbox" :disabled="!!running"/> 按实际旁白自动延长，保留完整尾句</label><small>点击生成整片时自动配音并合入。同文同音色配音可复用。</small>
    </template>
    <template v-else-if="narrationMode==='file'"><button class="gv-secondary" :disabled="!!running" @click="chooseAudio(false)">导入旁白</button><div v-if="audioId" class="whole-film-audio">{{ audioName||'已选择旁白文件' }} <button @click="audioId='';audioName=''">移除</button></div></template>
    <small v-else>本次不生成或合入旁白，只保留下面所选音效及配乐。</small>
    <label class="whole-film-check"><input v-model="sound" type="checkbox" :disabled="!!running"/> 模板转场音效</label><button class="gv-secondary" :disabled="!!running" @click="chooseAudio(true)">导入背景音乐（选填）</button><div v-if="musicId" class="whole-film-audio">{{ musicName||'已选择背景音乐' }} <button @click="musicId='';musicName=''">移除</button></div><small>背景音乐会低音量循环铺底，不覆盖旁白。</small>
    <button class="gv-primary whole-film-generate" :disabled="!!busy||!!running||settingsBusy||!script.trim()" @click="generate">{{ busy==='prepare'?'正在整理整片…':busy||running?'正在制作整片…':ready.length?'重新生成整片（保留旧版）':'生成整片' }}</button>
    <button class="gv-secondary" :disabled="!!busy||!!running||settingsBusy||!script.trim()" @click="replan">整理或更新整片方案</button>
    <button v-if="plan" class="whole-film-outline-toggle" @click="showSections=!showSections">{{ showSections?'收起':'调整' }}内容段落（{{ plan.scenes.length }}）</button>
    <p v-if="dirty" class="whole-film-notice">方案已有调整，重新生成后应用，旧成片保留。</p>
    <p v-for="warning in displayWarnings" :key="warning" class="whole-film-notice">{{ warning }}</p>
   </aside>
  </div>
  <section v-if="showSections&&plan" class="whole-film-outline"><header><h3>整片内容 · {{ narrationCount }}段旁白</h3><span>配音只朗读下方旁白，不朗读排版和运镜指令。</span></header><article v-for="(scene,index) in plan.scenes" :key="index"><b>{{ String(index+1).padStart(2,'0') }}</b><div><input v-model="scene.title" aria-label="整片段落标题"/><textarea v-model="scene.subtitle" aria-label="整片段落说明" rows="2"></textarea><textarea v-if="scene.items.length" :value="scene.items.join('\n')" @change="scene.items=$event.target.value.split('\n').filter(Boolean)" aria-label="整片条目" rows="3"></textarea><input v-model="scene.caption" placeholder="字幕（选填）"/><label>本段旁白<textarea v-model="scene.narration" aria-label="整片段落旁白" rows="3" placeholder="这里写观众实际听到的话，留空则此段不配音"></textarea></label></div><div><UiSelect v-model="scene.kind" :options="options" aria-label="整片段落版式"/><label>时长权重<input v-model.number="scene.seconds" type="number" min="1" max="40"/></label></div></article></section>
 </section>
</template>

<style scoped>
.whole-film-studio{display:flex;flex-direction:column;gap:16px;min-height:500px;overflow:auto;padding-bottom:20px}.whole-film-head{display:flex;justify-content:space-between;align-items:center;gap:15px}.whole-film-head span{font-size:12px;color:var(--theme-accent)}.whole-film-head h2{font-size:22px;margin:9px 0}.whole-film-head p{font-size:13px;color:var(--theme-text-secondary);margin:0}.whole-film-grid{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:18px;align-items:start}.whole-film-player,.whole-film-options,.whole-film-outline{border:1px solid var(--theme-border-subtle);background:var(--theme-bg-card);border-radius:12px;padding:18px;min-width:0}.whole-film-player video,.whole-film-empty{width:100%;aspect-ratio:16/9;object-fit:contain;background:#16222b;border-radius:8px;color:#eef3fa}.whole-film-empty{display:flex;flex-direction:column;align-items:center;justify-content:center}.whole-film-empty>span{font-size:32px}.whole-film-empty h3{font-size:19px;font-weight:500}.whole-film-empty p{font-size:12px;color:#b5c3d2}.whole-film-options{display:flex;flex-direction:column;gap:12px}.whole-film-options h3{margin:0;font-size:15px}.whole-film-options label{margin:0;font-size:12px}.whole-film-options p,.whole-film-options small{margin:0;font-size:11px;line-height:1.8;color:var(--theme-text-secondary)}.whole-film-options .whole-film-check{display:flex;align-items:center;gap:8px}.whole-film-check input{width:auto;margin:0}.whole-film-generate{margin-top:6px;min-height:44px}.whole-film-progress,.whole-film-result{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:14px;font-size:12px}.whole-film-progress progress{width:100%}.whole-film-result>span{flex:1;line-height:1.7}.whole-film-result small{color:var(--theme-text-secondary)}.whole-film-outline-toggle,.whole-film-history-toggle{border:0;background:transparent;color:var(--theme-accent);text-align:left;cursor:pointer;padding:8px 0;font-size:12px}.whole-film-history{display:flex;flex-direction:column;gap:6px;max-height:190px;overflow:auto}.whole-film-history button{border:1px solid var(--theme-border-subtle);padding:9px;border-radius:7px;color:var(--theme-text-secondary);background:var(--theme-bg-elevated);cursor:pointer}.whole-film-history .active{border-color:var(--theme-accent)}.whole-film-audio{font-size:12px}.whole-film-audio button{border:0;background:transparent;color:var(--theme-accent);cursor:pointer}.whole-film-outline>header{display:flex;align-items:center;justify-content:space-between;font-size:12px;color:var(--theme-text-secondary)}.whole-film-outline article{display:grid;grid-template-columns:30px minmax(0,1fr) 190px;gap:15px;padding:18px 0;border-top:1px solid var(--theme-border-subtle)}.whole-film-outline article>div{display:flex;flex-direction:column;gap:8px}.whole-film-outline article input,.whole-film-outline article textarea{margin:0;min-height:0}.whole-film-outline article label{margin:0;font-size:11px}.whole-film-notice{color:var(--theme-accent)!important}@media(max-width:1050px){.whole-film-grid{grid-template-columns:1fr}.whole-film-options{display:grid;grid-template-columns:1fr 1fr}.whole-film-head{align-items:flex-start;flex-direction:column}.whole-film-outline article{grid-template-columns:25px minmax(0,1fr)}.whole-film-outline article>div:last-child{grid-column:2}}
</style>
<style scoped>
.whole-film-method{display:flex;align-items:center;gap:10px 18px;flex-wrap:wrap;border:1px solid var(--theme-border-subtle);border-radius:10px;padding:12px 15px;background:var(--theme-accent-soft);font-size:12px;color:var(--theme-text-secondary)}.whole-film-method strong{color:var(--theme-text-primary)}.whole-film-method button{margin-left:auto;border:0;background:transparent;color:var(--theme-accent);cursor:pointer}.whole-film-grid{grid-template-columns:minmax(0,1fr) 330px}.whole-film-options{position:sticky;top:0;max-height:calc(100vh - 260px);overflow:auto;overscroll-behavior:contain;scrollbar-width:thin}.whole-film-result small{display:block;margin-top:6px}.whole-film-options input{font-size:12px}.whole-film-check{line-height:1.7}@media(max-width:1050px){.whole-film-grid{grid-template-columns:1fr}.whole-film-options{position:static;max-height:none;display:flex}}
</style>

<style scoped>
.whole-film-breeze{display:flex;flex-direction:column;gap:8px;padding:12px;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-accent-soft);font-size:12px}.whole-film-breeze>div{display:flex;gap:8px;flex-wrap:wrap}.whole-film-options textarea{font-size:12px;margin:0;min-height:76px;resize:vertical}
</style>

<style scoped>
.whole-film-layout-picker{display:flex;flex-direction:column;gap:9px;padding-bottom:14px;border-bottom:1px solid var(--theme-border-subtle);min-width:0}.whole-film-layout-picker>header{display:flex;align-items:center;justify-content:space-between;gap:8px}.whole-film-layout-picker strong{font-size:12px}.whole-film-layout-picker header button{border:0;padding:4px 0;background:transparent;color:var(--theme-accent);font-size:11px;white-space:nowrap;cursor:pointer}.whole-film-layout-picker header button:disabled{opacity:.5;cursor:default}.whole-film-template-note summary{font-size:12px;color:var(--theme-text-secondary);cursor:pointer}.whole-film-template-note p{margin-top:8px}
</style>

<style scoped>
@media(max-height:850px){.whole-film-layout-picker :deep(.ui-select-menu){max-height:180px}}
</style>
