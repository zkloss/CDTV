<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { assemblySources, assemblyProblem } from '../utils/shotAssembly.js'
const props = defineProps({ token:String, projectId:String, clips:Array, models:Array, textModels:Array, textModel:String, value:Object, save:Function, fileUrl:Function })
const emit=defineEmits(['busy-change','edit-shot'])
const plan=ref(null),error=ref(''),busy=ref(false),model=ref(''),requirements=ref(''),checks=ref({}),actionPlans=ref({})
const operation=ref(null),analysisMessages=ref({})
const stopping=ref({})
const referenceChoices=ref({}),referenceConfirmed=ref({})
const analysisModel=ref(props.textModel||''),reviewModel=ref('')
const analysisModels=computed(()=>(props.textModels||[]).filter(m=>m.supportsVision!==false))
let alive=true,timer=null,analysisTimer=null,operationSerial=0
const sources=computed(()=>assemblySources(props.clips||[]))
const problem=computed(()=>assemblyProblem(props.clips||[]))
const models=computed(()=>(props.models||[]).filter(m=>/^muse[-_ ]?video/i.test(m.modelName||'')))
const running=computed(()=>Boolean(plan.value?.joins?.some(j=>j.attempt && ['submitting','queued','running','processing','pending','generating'].includes(j.attempt.status))))
const analysisRunning=computed(()=>Boolean(plan.value?.joins?.some(j=>j.analysisAttempt?.status==='running')))
const changedSources=computed(()=>plan.value && JSON.stringify(plan.value.sources.map(s=>s.inputFileId||s.fileId))!==JSON.stringify(sources.value.map(s=>s.fileId)))
const api=()=>window.pywebview.api
const candidate=j=>j.candidates?.[0]
const accepted=j=>Boolean(j.directReview||j.selected)
const ready=computed(()=>plan.value?.joins.every(accepted)&&!changedSources.value)
const labels={entry:'接入自然',exit:'接出自然',identity:'全段人物与质感一致',action:'完整动作与剧情合理',sound:'对白完整、没有新增错误人声',space:'空间方向与视线关系合理',prop:'持物与动作阶段连续'}
const strategyNames={direct_cut:'直接切镜',trim_cut:'调整切点',bridge:'补出缺失动作',repair_source:'局部修复原镜头',scene_cut:'按剧情换场'}
const strategy=j=>j.actionAnalysis?.edit_strategy||{}
const references=j=>[...new Map([j.from,j.to].flatMap(i=>plan.value.sources[i].context?.references||[]).map(r=>[r.fileId,r])).values()]
const formatFailure=j=>!j.analysisAttempt?.reviewPending&&j.analysisAttempt?.failureCategory==='schema'&&j.analysisAttempt?.planningResult
const usableMessage=j=>strategy(j).type&&strategy(j).type!=='bridge'?'请按上方剪辑建议处理，无需强行生成补段。':'可使用下方按钮生成视频。'
const motionLabels={head_yaw:'转头',head_pitch:'抬头／低头',torso:'肩膀与身体',gaze:'视线',hands_prop:'双手与持物',camera_position:'机位',framing:'景别与构图'}
const motionChange={required:'需要衔接',none:'保持',uncertain:'尚不确定'}
const currentAnalysis=j=>j?.actionAnalysis?.promptVersion==='visual-action-planner-v3-edit-strategy'
const sourceRepair=j=>currentAnalysis(j)&&strategy(j).type==='repair_source'&&!retainedAfterRequest(j)
const repairable=j=>currentAnalysis(j)&&j.actionAnalysis.executionReady!==true&&strategy(j).type!=='repair_source'
const repairing=j=>(operation.value?.joinId===j.id&&Boolean(operation.value.repairOf))||(j.analysisAttempt?.status==='running'&&Boolean(j.analysisAttempt.repairOf))
const primaryMotion=j=>(j.actionAnalysis?.primary_components||[]).map(k=>motionLabels[k]||k).join('、')
const allChecked=j=>Object.keys(labels).every(k=>checks.value[j.id]?.[k]===true)
const normalize=value=>String(value||'').trim().replace(/\s+/g,' ')
const terminal=status=>['succeeded','failed','cancelled','canceled'].includes(status)
const analyzing=j=>(operation.value?.action==='plan_action'&&operation.value.joinId===j.id)||j.analysisAttempt?.status==='running'
const analysisTime=j=>j.actionAnalysis?.analyzedAt?new Date(j.actionAnalysis.analyzedAt).toLocaleString():''
const formatTime=value=>value?new Date(value).toLocaleString():'尚无记录'
const retainedAfterRequest=j=>Boolean(j.actionAnalysis&&['running','failed','unknown','cancelled'].includes(j.analysisAttempt?.status))
const timedOut=j=>j.analysisAttempt?.errorKind==='timeout'||/超时/.test(j.analysisAttempt?.error||j.analysisAttempt?.reviewError||'')
const stoppable=j=>['running','unknown'].includes(j.analysisAttempt?.status)
const stoppedMessage='已终止本地分析等待，旧方案和视频保留。上游是否停止尚未确认，可能仍消耗额度；不会自动重试或生成视频。'
function receiptStatus(j){
  const a=j.analysisAttempt
  if(a?.reviewPending)return '已恢复返回的规划，等待独立复核'
  if(a?.status==='cancelled')return '已终止本地分析等待'
  if(a?.status==='running')return a.stage==='reviewing'?'已收到规划，正在等待独立复核':'已开始请求，正在等待分析返回'
  if(timedOut(j))return a?.failedStage==='reviewing'?'复核请求超时，未取得可用复核结果':'分析请求超时，未取得新方案'
  return a?.status==='failed'?'本次请求未取得可用方案':a?.status==='succeeded'?'本次分析已返回':a?.status==='unknown'?'本次请求回执待确认':'仅有历史结果'
}
function analysisMessage(j){
  if(analyzing(j))return j.analysisAttempt?.stage==='reviewing'?'正在复核真实两端；下面暂时保留上次结果，完成后自动替换。':repairing(j)?'正在根据上次失败原因纠正动作；本次会形成新方案，不读取失败缓存，也不生成视频。':'正在识别衔接动作；下面暂时保留上次结果，完成后自动替换，不需要再次点击。'
  if(analysisMessages.value[j.id])return analysisMessages.value[j.id]
  if(j.analysisAttempt?.status==='cancelled')return stoppedMessage
  if(j.analysisAttempt?.reviewPending)return '已从保存的实际回复恢复完整规划，没有重新调用模型；可仅执行独立复核，无需从头识别。'
  if(j.analysisAttempt?.status==='failed')return `上次识别未完成：${j.analysisAttempt.error||'未收到完整回执'}。下面保留上次结果，没有提交视频生成。`
  if(sourceRepair(j))return '分析已返回：建议先修复原镜头。这是处理建议，不是平台审核拒绝，也不代表视频已通过检查。请使用“去修复原镜头”，不用继续重复纠正补段。'
  if(currentAnalysis(j))return formatFailure(j)?'规划已保存，复核返回格式不完整；可仅重试独立复核，无需从头规划。':j.actionAnalysis.executionReady?`已收到当前分析。${usableMessage(j)}`:'当前分析仍有待解决项，请查看剪辑建议或根据失败原因纠正。'
  return ''
}
function generationBlockReason(j){
  if(busy.value||analyzing(j))return '当前操作尚未完成，请等待下方进度更新。'
  if(changedSources.value)return '源视频已变化，请按当前素材另建接点。'
  if(running.value)return '已有补段任务正在执行，请先查询已有视频任务。'
  if(j.attempt&&!terminal(j.attempt.status))return '已有补段任务尚未结束，请查询已有任务，不能再次提交。'
  if(!models.value.length)return '请先启用并选择补段视频模型。'
  if(!j.actionAnalysis)return '先点击“识别衔接动作”，再使用当前分析生成视频。'
  if(j.analysisAttempt?.status==='failed')return `本次识别失败，尚未取得新方案：${j.analysisAttempt.error||'没有收到完整结果'}。旧方案仅在历史记录中保留；请按本次具体错误处理，不必原样反复重跑分析。`
  if(!currentAnalysis(j))return '当前仍是旧版分析，请先点击“识别衔接动作”更新。'
  if(sourceRepair(j))return '这处建议修复原镜头，补段生成暂不可用。请点击“去修复原镜头”查看具体建议；原视频保留。'
  if(strategy(j).type&&strategy(j).type!=='bridge')return `当前建议“${strategyNames[strategy(j).type]}”，请使用上方对应入口；无需强行生成补段。`
  if(!j.actionAnalysis.executionReady)return `当前分析未通过终态复核：${j.actionAnalysis.planReview?.unresolved?.join('；')||'仍有未解决的动作矛盾'}。请点击“根据失败原因纠正”修正这份方案；尚未提交视频生成。`
  if(j.actionAnalysis.decision!=='bridge')return j.actionAnalysis.decision==='direct_cut'?'当前建议直接切镜，无需生成补段。':'当前方案仍需复核，暂不能生成补段。'
  if(!['high','medium'].includes(j.actionAnalysis.confidence))return '当前方案把握不足，暂不能生成补段。'
  if(normalize(j.actionAnalysis.bridge_prompt)===normalize(j.attempt?.actionPlan))return '这份动作方案已提交过，请查看已有视频；不会原样重复生成。'
  return ''
}
function canGenerate(j){
  const action=normalize(actionPlans.value[j.id])
  if(j.attempt&&!terminal(j.attempt.status))return false
  return action ? action!==normalize(j.attempt?.actionPlan) : Boolean(analysisModels.value.length)
}
function statusLabel(j){
  if(j.attempt&&!terminal(j.attempt.status))return j.attempt.status==='unknown'?'提交回执待确认，请查询原任务':'正在制作补段，旧候选继续保留'
  if(candidate(j))return candidate(j).technicalPassed?(candidate(j).needsSemanticReview?'视频已保存 · 动作切镜待完整检查':'视频已保存 · 衔接待完整检查'):'视频已保存 · 衔接未通过'
  if(j.attempt?.status==='failed')return '生成未完成，原候选继续保留'
  return '尚未制作独立补段'
}
function tick(){clearTimeout(timer);if(alive&&running.value)timer=setTimeout(()=>void pollNext(),5000)}
async function call(action,extra={}){
  return api().backend_request('POST','/ai/video',props.token,{production_mode:`assembly_${action}`,project_id:props.projectId,plan_id:plan.value?.id,...extra})
}
async function apply(result){
  if(!alive)return
  if(!Array.isArray(result?.joins))throw Error('接点记录尚未完整取回，请查询原记录，不要重复提交生成')
  if(plan.value?.id===result.id&&Number.isFinite(Number(plan.value.revision))&&Number.isFinite(Number(result.revision))&&Number(result.revision)<Number(plan.value.revision))return
  if(plan.value?.id===result.id)for(const j of result.joins){const previous=plan.value.joins.find(item=>item.id===j.id);if(currentAnalysis(j)&&j.actionAnalysis.id!==previous?.actionAnalysis?.id&&j.analysisAttempt?.status!=='running')analysisMessages.value[j.id]=`已取回本次新分析（${analysisTime(j)}）。${j.actionAnalysis.executionReady?usableMessage(j):'仍有待处理项，见上方建议和错误分类。'}`}
  plan.value=result;tick();analysisTick()
}
function analysisTick(){clearTimeout(analysisTimer);if(alive&&(analysisRunning.value||operation.value?.action==='plan_action'))analysisTimer=setTimeout(()=>void refreshAnalysis(),1000)}
async function refreshAnalysis(){
  const id=plan.value?.id;if(!id||!alive)return
  try{const result=await call('status',{plan_id:id});if(alive&&plan.value?.id===id)await apply(result)}catch(_){/* Query only; never resubmit an analysis. */}
  finally{analysisTick()}
}
async function run(action,extra={}){
  if(busy.value)return
  busy.value=true;error.value='';const serial=++operationSerial;operation.value={serial,action,joinId:extra.join_id,repairOf:extra.repair_analysis_id};analysisTick()
  try{const result=await call(action,extra);if(serial!==operationSerial)return {superseded:true};await apply(result);return {ok:true,result}}
  catch(e){if(serial!==operationSerial)return {superseded:true};error.value=String(e.message||e);if(plan.value){try{const result=await call('status');if(serial===operationSerial)await apply(result)}catch(_){}}return {ok:false,error:error.value}}
  finally{if(operation.value?.serial===serial){operation.value=null;busy.value=false}analysisTick()}
}
async function stopAnalysis(j){
  if(!stoppable(j)||stopping.value[j.id])return
  stopping.value[j.id]=true;error.value=''
  try{
    const result=await call('cancel_analysis',{join_id:j.id,analysis_attempt_id:j.analysisAttempt.id})
    if(operation.value?.action==='plan_action'&&operation.value.joinId===j.id){++operationSerial;operation.value=null;busy.value=false}
    await apply(result)
    analysisMessages.value[j.id]=result.joins.find(item=>item.id===j.id)?.analysisAttempt?.status==='cancelled'?stoppedMessage:'分析状态已更新，请查看请求记录。'
  }catch(e){error.value=`终止未确认：${String(e.message||e)}。请查询请求状态，不要重复提交分析。`}
  finally{stopping.value[j.id]=false;analysisTick()}
}
async function prepare(){
  if(problem.value||busy.value||running.value)return
  busy.value=true;error.value=''
  try{
    const result=await call('prepare',{source_videos:sources.value})
    // Persist the owner-bound pointer before exposing any paid generation.
    await props.save({planId:result.id,history:[result.id,...(props.value?.history||[]).filter(id=>id!==result.id)]})
    checks.value={};actionPlans.value={};await apply(result)
  }catch(e){error.value=String(e.message||e)}finally{busy.value=false}
}
async function restore(id){
  actionPlans.value={};const response=await run('status',{plan_id:id})
  if(response?.ok){
    const preferences=response.result.analysisModels
    if(preferences){
      if(analysisModels.value.some(m=>String(m.id)===preferences.analysisModel))analysisModel.value=preferences.analysisModel
      if(analysisModels.value.some(m=>String(m.id)===preferences.reviewModel))reviewModel.value=preferences.reviewModel
    }
  }
}
const selectedAnalysisModel=()=>analysisModel.value||String(analysisModels.value[0]?.id||'')
const selectedReviewModel=()=>reviewModel.value||selectedAnalysisModel()
async function analyze(j,reviewOnly=false){
  if(busy.value||analyzing(j))return
  const previousId=j.actionAnalysis?.id,isRepair=repairable(j);analysisMessages.value[j.id]=''
  const response=await run('plan_action',{join_id:j.id,analysis_model:selectedAnalysisModel(),review_model:selectedReviewModel(),
    ...(isRepair?{repair_analysis_id:previousId,request_id:crypto.randomUUID()}: {}),...(reviewOnly?{review_only:true,request_id:crypto.randomUUID()}: {})})
  if(response?.superseded||plan.value?.joins.find(item=>item.id===j.id)?.analysisAttempt?.status==='cancelled')return
  const current=plan.value?.joins.find(item=>item.id===j.id)
  if(currentAnalysis(current)&&current.actionAnalysis.id!==previousId)analysisMessages.value[j.id]=`${isRepair?'已完成本次纠正':'已更新本次分析'}（${analysisTime(current)}）。${current.actionAnalysis.executionReady?usableMessage(current):'仍有未解决项，本次新结果与旧版均已保留；请按错误分类或剪辑建议处理。'}`
  else if(isRepair)analysisMessages.value[j.id]=`本次纠正未完成：${response?.error||current?.analysisAttempt?.error||'未收到新的完整方案'}。旧方案保留，没有生成视频。`
  else if(response?.ok&&currentAnalysis(current))analysisMessages.value[j.id]='已读取当前分析缓存，与上次相同；没有重复调用分析模型。生成入口在下方。'
  else analysisMessages.value[j.id]=`本次识别未完成：${response?.error||'未收到新版分析'}。下面仍保留上次结果，没有提交视频生成。`
}
async function generateCurrent(j){
  if(generationBlockReason(j))return
  await run('generate',{join_id:j.id,model:model.value||String(models.value[0]?.id||''),auto_plan:true,
    use_analysis_id:j.actionAnalysis.id,accept_analysis_id:j.actionAnalysis.confidence==='medium'?j.actionAnalysis.id:undefined,
    requirements:requirements.value,request_id:crypto.randomUUID()});checks.value[j.id]={}
}
async function generateManual(j){if(!canGenerate(j)||!normalize(actionPlans.value[j.id]))return;await run('generate',{join_id:j.id,model:model.value||String(models.value[0]?.id||''),requirements:requirements.value,action_plan:actionPlans.value[j.id],request_id:crypto.randomUUID()});checks.value[j.id]={}}
async function pollNext(){
  const j=plan.value?.joins.find(j=>j.attempt?.taskId&&!['succeeded','failed','cancelled','canceled'].includes(j.attempt.status))
  if(j)await run('query',{join_id:j.id})
  tick()
}
async function upload(j){
  if(busy.value)return
  busy.value=true;error.value=''
  try{
    const chosen=await api().select_local_video_file();if(!chosen?.path)return
    const stored=await api().upload_local_file(props.token,chosen.path)
    const id=stored?.id||stored?.fileId||stored?.data?.id
    if(!id)throw Error('视频尚未入库')
    await apply(await call('import',{join_id:j.id,file_id:id}));checks.value[j.id]={}
  }catch(e){error.value=String(e.message||e)}finally{busy.value=false}
}
async function approve(j,direct=false){await run('review',{join_id:j.id,candidate_id:candidate(j)?.id,direct,checks:checks.value[j.id]})}
async function applyCut(j){
  if(!checks.value[j.id]?.sound||!checks.value[j.id]?.action){error.value='请先连看原片，确认切掉的区间没有对白或必要动作，再勾选动作和声音检查。';return}
  const result=await run('apply_cut',{join_id:j.id,use_analysis_id:j.actionAnalysis.id,checks:checks.value[j.id]})
  if(result?.ok){await props.save({planId:result.result.id,history:[result.result.id,...new Set([plan.value.parentPlanId,...(props.value?.history||[])])]});checks.value={}}
}
async function saveReferences(j){await run('approve_refs',{join_id:j.id,confirmed:referenceConfirmed.value[j.id]===true,reference_ids:references(j).filter(r=>referenceChoices.value[j.id]?.[r.fileId]??r.approvedForCurrentFootage).map(r=>r.fileId)})}
function editSource(j){const source=plan.value.sources[strategy(j).repair_target==='previous'?j.from:j.to];emit('edit-shot',{shotId:source.shotId,action:strategy(j).repair_action})}
async function exportVideo(fileId){try{await api().save_server_video_as(props.token,fileId,'分镜组片_待整片检查.mp4')}catch(e){error.value=String(e.message||e)}}
watch([busy,running,analysisRunning],()=>emit('busy-change',busy.value||running.value||analysisRunning.value),{immediate:true})
if(props.value?.planId)void restore(props.value.planId)
onBeforeUnmount(()=>{alive=false;clearTimeout(timer);clearTimeout(analysisTimer)})
</script>

<template>
  <section class="verified-assembly" aria-label="独立补段与双端检查">
    <h3>逐接点补过渡</h3>
    <p>AI先查看前镜末段和后镜开头，识别人物、持物、视线与机位的变化，自行规划缺失动作，再制作独立补段。你可以留空动作，让AI分析；额外意图只在需要时补充。</p>
    <p class="notice">先识别衔接动作，再点击“按当前分析生成补段视频”。识别会进行看图分析和独立复核，不生成视频；生成按钮使用当前方案，不再次分析，会调用Muse并可能消耗额度。分析建议不代表视频验收通过。</p>
    <div class="toolbar"><button :disabled="busy||running||Boolean(problem)" @click="prepare">{{ plan ? '按当前素材另建一版接点' : '准备接点（不生成）' }}</button><select v-if="value?.history?.length>1" :value="plan?.id" :disabled="busy||running" aria-label="接点方案历史" @change="restore($event.target.value)"><option v-for="(id,i) in value.history" :key="id" :value="id">接点方案 {{ value.history.length-i }}</option></select></div>
    <p v-if="problem" class="notice">{{ problem }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="changedSources" class="error">所选源视频已变化，请另建接点；旧方案和候选继续保留。</p>
    <template v-if="plan">
      <div class="settings"><label>动作分析模型（需支持看图）<select v-model="analysisModel" :disabled="busy||running"><option value="">{{analysisModels[0]?.name||'请启用支持看图的模型'}}</option><option v-for="m in analysisModels" :key="m.id" :value="String(m.id)">{{m.name||m.modelName}}</option></select></label><label>独立复核模型（需支持看图）<select v-model="reviewModel" :disabled="busy||running"><option value="">{{analysisModels.find(m=>String(m.id)===selectedReviewModel())?.name||'跟随分析模型'}}</option><option v-for="m in analysisModels" :key="m.id" :value="String(m.id)">{{m.name||m.modelName}}</option></select></label><label>补段模型<select v-model="model" :disabled="busy||running"><option value="">{{ models[0]?.name||'请启用 Muse 视频模型' }}</option><option v-for="m in models" :key="m.id" :value="String(m.id)">{{m.name||m.modelName}}</option></select></label><label>补充衔接要求（选填）<input v-model="requirements" :disabled="busy||running" placeholder="例如保留原有表演与声音" /></label></div>
      <article v-for="j in plan.joins" :key="j.id" :aria-label="`接点${j.from+1}到${j.to+1}`">
        <h4>接点 {{j.from+1}} → {{j.to+1}} <span>{{ accepted(j)?'已检查':'待检查' }}</span></h4>
        <div class="boundaries"><figure><img :src="fileUrl(j.startImage)" alt="上一镜真实末帧"/><figcaption>上一镜真实末帧</figcaption></figure><figure><img :src="fileUrl(j.endImage)" alt="下一镜真实首帧"/><figcaption>下一镜真实首帧</figcaption></figure></div>
        <details><summary>查看前后原视频与原声</summary><div class="boundaries"><video :src="fileUrl(plan.sources[j.from].fileId)" controls preload="none"/><video :src="fileUrl(plan.sources[j.to].fileId)" controls preload="none"/></div></details>
        <details class="source-context"><summary>原分镜资料与参考职责</summary>
          <div v-for="i in [j.from,j.to]" :key="i"><strong>{{plan.sources[i].title}}</strong><p v-for="warning in plan.sources[i].context?.warnings||[]" :key="warning" class="notice">{{warning}}</p><p>{{plan.sources[i].context?.intendedAction||'没有关联的原分镜文字，以当前视频为准。'}}</p><button v-if="plan.sources[i].context?.sourceNeedsRepair&&plan.sources[i].shotId" :disabled="busy" @click="emit('edit-shot',{shotId:plan.sources[i].shotId,action:plan.sources[i].context.warnings[0]})">核对这个待更新的原分镜</button></div>
          <div v-for="r in references(j)" :key="r.fileId"><label><input type="checkbox" :checked="referenceChoices[j.id]?.[r.fileId]??r.approvedForCurrentFootage" @change="referenceChoices[j.id]={...referenceChoices[j.id],[r.fileId]:$event.target.checked}"/>{{r.name}} · {{r.role}} · {{r.approvedForCurrentFootage?'已核对':'待核对版本/风格'}}</label><img :src="fileUrl(r.fileId)" :alt="r.name"/></div>
          <template v-if="references(j).length"><label><input v-model="referenceConfirmed[j.id]" type="checkbox"/>已核对所选图片与当前成片的身份、风格和版本一致</label><button :disabled="busy||!referenceConfirmed[j.id]" @click="saveReferences(j)">保存参考核对（不调用模型）</button></template>
        </details>
        <section v-if="currentAnalysis(j)&&strategy(j).type&&!retainedAfterRequest(j)" class="edit-strategy notice"><strong>建议处理：{{strategyNames[strategy(j).type]}}</strong><p>{{strategy(j).reason}}</p><p v-if="strategy(j).type==='bridge'">{{strategy(j).join_mode==='action_cut'?'补出必要动作后切入下一机位；不要求末帧复制下一镜构图。':'连续衔接，两端均需核对实际边界。'}}</p>
          <template v-if="strategy(j).type==='trim_cut'"><p>上一镜保留至 {{strategy(j).previous_out}} 秒；下一镜从 {{strategy(j).next_in}} 秒开始。先连看原片并核对声音、必要动作；采用后另存剪辑副本与新接点方案，旧版完整保留。</p><button :disabled="busy||!checks[j.id]?.sound||!checks[j.id]?.action" @click="applyCut(j)">按建议制作切点副本</button></template>
          <template v-if="strategy(j).type==='repair_source'"><p>{{strategy(j).repair_action}}</p><button :disabled="busy||!plan.sources[strategy(j).repair_target==='previous'?j.from:j.to].shotId" @click="editSource(j)">定位需要修复的原分镜</button><p>回到原分镜核对后再生成，原视频保留；这里不会自动重拍。</p></template>
          <p v-if="['direct_cut','scene_cut'].includes(strategy(j).type)">连看两段并完成下方检查后，可直接采用原切镜，无需生成补段。</p>
        </section>
        <p v-if="formatFailure(j)" class="format-failure notice">这是复核返回格式错误，尚不能判断画面是否通过。已保存规划，可只重试独立复核。缺项：{{j.analysisAttempt.missingFields?.join('、')||j.analysisAttempt.reviewError}}</p>
        <section v-if="j.analysisAttempt?.startedAt" class="analysis-receipt notice" aria-label="本次分析请求记录" aria-live="polite">
          <strong>最近一次{{j.analysisAttempt.repairOf?'纠正':'识别'}}请求：{{receiptStatus(j)}}</strong>
          <p>开始时间：{{formatTime(j.analysisAttempt.startedAt)}}<template v-if="j.analysisAttempt.finishedAt"> · 结束时间：{{formatTime(j.analysisAttempt.finishedAt)}}</template></p>
          <p v-if="j.analysisAttempt.modelName">分析模型：{{j.analysisAttempt.modelName}}<template v-if="j.analysisAttempt.requestTimeoutSeconds"> · 单阶段最长等待 {{j.analysisAttempt.requestTimeoutSeconds/60}} 分钟</template></p>
          <p v-if="j.analysisAttempt.responseReceivedAt">规划返回时间：{{formatTime(j.analysisAttempt.responseReceivedAt)}}<template v-if="j.analysisAttempt.reviewStartedAt"> · 独立复核开始：{{formatTime(j.analysisAttempt.reviewStartedAt)}}</template></p>
          <p v-if="j.analysisAttempt.reviewResponseReceivedAt">独立复核返回时间：{{formatTime(j.analysisAttempt.reviewResponseReceivedAt)}}</p>
          <p v-if="timedOut(j)">本次已发起本地请求，但未收到可用的完整结果；服务商是否完成暂时未知。{{retainedAfterRequest(j)?'下方保留的是旧方案，旧方案时间不会因本次超时改变。':''}}没有自动重试或生成视频。</p>
          <p v-if="j.analysisAttempt.providerReceipt">接口回执：HTTP {{j.analysisAttempt.providerReceipt.httpStatus}} · {{j.analysisAttempt.providerReceipt.contentType||'未声明格式'}}<template v-if="j.analysisAttempt.providerReceipt.keepaliveOnly"> · 只有保活，没有答案</template></p><details><summary>请求编号与历史记录</summary><p>本次：{{j.analysisAttempt.requestId||j.analysisAttempt.id}}</p><p v-for="a in [...(j.analysisAttemptHistory||[])].reverse()" :key="a.id">{{formatTime(a.startedAt)}} → {{formatTime(a.finishedAt)}} · {{a.error||a.reviewError||a.status}}</p></details>
          <details v-if="j.analysisAttempt.reviewRaw"><summary>查看实际复核返回</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{{j.analysisAttempt.reviewRaw}}</pre></details>
        </section>
        <p v-if="analysisMessage(j)" class="analysis-progress notice" aria-live="polite" aria-atomic="true">{{analysisMessage(j)}}</p>
        <p v-if="repairable(j)&&!analyzing(j)" class="repair-notice notice">纠正会带上本次失败原因，重新调用分析和复核模型，可能消耗分析额度；不会生成视频。每次点击只提交一轮，旧方案保留。</p>
        <button v-if="j.analysisAttempt?.reviewPending" class="review-recovered" :disabled="busy||running||analyzing(j)" @click="analyze(j,true)">仅执行独立复核（保留已返回规划）</button><button v-if="formatFailure(j)" class="retry-review" :disabled="busy||running||analyzing(j)" @click="analyze(j,true)">仅重试独立复核（保留规划）</button>
        <section v-if="j.actionAnalysis" class="action-analysis"><details :open="!retainedAfterRequest(j)"><summary>{{retainedAfterRequest(j)?'历史分析（非本次结果，点击查看）':'查看当前分析'}}</summary>
          <strong>{{j.analysisAttempt?.reviewPending?'规划已恢复 · 等待独立复核':sourceRepair(j)?'分析已完成 · 建议修复原镜头':analyzing(j)?'正在更新动作分析 · 下方暂为上次结果':retainedAfterRequest(j)?'保留的旧分析 · 本次请求未取得新方案':currentAnalysis(j)&&!j.actionAnalysis.executionReady?'AI初步分析 · 终态复核未通过':`AI已分析 · ${j.actionAnalysis.decision==='bridge'?'建议补过渡':j.actionAnalysis.decision==='direct_cut'?'建议直接切镜':'需要进一步复核'}`}}</strong>
          <p v-if="!currentAnalysis(j)&&!analyzing(j)&&!retainedAfterRequest(j)" class="notice">这是旧版分析，尚未分别判断转头、低头和机位。请重新点击“识别衔接动作”，旧结果继续保留。</p>
          <p v-if="analysisTime(j)" class="analysis-time">{{retainedAfterRequest(j)?'保留的旧方案返回时间':'此份分析返回时间'}}：{{analysisTime(j)}}</p>
          <div v-if="j.actionAnalysis.repair_changes?.length" class="repair-changes"><strong>本次纠正了什么</strong><ul><li v-for="(change,n) in j.actionAnalysis.repair_changes" :key="n">{{change}}</li></ul></div>
          <p v-if="primaryMotion(j)" class="primary-motion"><strong>主要缺失：{{primaryMotion(j)}}</strong></p>
          <p>前镜末态：{{j.actionAnalysis.start_state}}</p><p>后镜初态：{{j.actionAnalysis.end_state}}</p>
          <div v-if="j.actionAnalysis.motion_components?.length" class="motion-table-wrap"><table class="motion-table"><thead><tr><th>变化部位</th><th>判断</th><th>衔接动作</th></tr></thead><tbody><tr v-for="m in j.actionAnalysis.motion_components" :key="m.component"><th>{{motionLabels[m.component]}}</th><td>{{motionChange[m.change]}}</td><td>{{m.action}}</td></tr></tbody></table></div>
          <ol><li v-for="(step,n) in j.actionAnalysis.action_steps" :key="n">{{step}}</li></ol>
          <p>机位：{{j.actionAnalysis.camera_action}}</p>
          <div v-if="j.actionAnalysis.failure_diagnosis" class="failure-diagnosis"><strong>上次补段漏了什么</strong><p>实际做了：{{j.actionAnalysis.failure_diagnosis.observed_actions.join('；')}}</p><p v-if="j.actionAnalysis.failure_diagnosis.missing_components.length">尚缺：{{j.actionAnalysis.failure_diagnosis.missing_components.map(k=>motionLabels[k]||k).join('、')}}</p><p>这次修正：{{j.actionAnalysis.failure_diagnosis.corrections.join('；')}}</p></div>
          <p v-if="j.actionAnalysis.planReview" class="plan-review">{{j.analysisAttempt?.reviewPending?'独立复核尚未执行':sourceRepair(j)?'补段方案暂不采用；按原镜头修复建议处理':j.actionAnalysis.executionReady?'已核对动作方案，视频效果仍待验证':'终态复核仍有矛盾，暂不生成'}}<span v-if="j.actionAnalysis.planReview.issues.length">。修正：{{j.actionAnalysis.planReview.issues.join('；')}}</span></p>
          <p v-if="j.actionAnalysis.uncertainties.length">待确认：{{j.actionAnalysis.uncertainties.join('；')}}</p>
          <details><summary>查看真实帧与分析依据</summary><p v-if="j.actionAnalysis.attribution_reason">人物与机位的区分依据：{{j.actionAnalysis.attribution_reason}}</p><p v-for="m in j.actionAnalysis.motion_components||[]" :key="m.component">{{motionLabels[m.component]}}：前镜 {{m.start}}；后镜 {{m.end}}。依据：{{m.reason}}</p><figure v-for="e in j.actionAnalysis.evidence" :key="e.image"><img :src="fileUrl(e.fileId)" :alt="`分析图${e.image}`"/><figcaption>图{{e.image}} · {{e.role}} · {{e.timeSeconds}}秒</figcaption></figure><p v-for="o in j.actionAnalysis.observations" :key="o.frame">图{{o.frame}}：{{o.visible}}</p></details>
        </details></section>
        <details><summary>补充动作意图（选填）</summary><label class="join-action">补充动作意图<textarea v-model="actionPlans[j.id]" :disabled="busy||running||changedSources" rows="3" placeholder="留空由AI根据前后片段识别；只有需要指定额外意图时再填写。"></textarea></label></details>
        <div v-if="sourceRepair(j)" class="repair-next-step notice"><strong>下一步：修复{{strategy(j).repair_target==='previous'?'前':'后'}}一镜开头</strong><p>{{strategy(j).repair_action}}</p><button class="repair-source-primary" :disabled="busy||running||changedSources||!plan.sources[strategy(j).repair_target==='previous'?j.from:j.to].shotId" @click="editSource(j)">去修复原镜头</button><p>打开对应分镜并保留建议，不会自动调用模型或替换视频。</p></div><div class="toolbar"><button v-if="!sourceRepair(j)" class="analyze-action" :disabled="busy||running||analyzing(j)||changedSources||!analysisModels.length" @click="analyze(j)">{{analyzing(j)?(j.analysisAttempt?.stage==='reviewing'?'正在复核两端…':repairing(j)?'正在纠正动作…':'正在识别动作…'):repairable(j)?'根据失败原因纠正（不生成视频）':'识别衔接动作（不生成视频）'}}</button><button v-if="stoppable(j)" class="stop-analysis" :disabled="stopping[j.id]" @click="stopAnalysis(j)">{{stopping[j.id]?'正在终止…':'终止本次分析'}}</button><button class="generate-current" :disabled="Boolean(generationBlockReason(j))" @click="generateCurrent(j)">按当前分析生成补段视频</button><button v-if="normalize(actionPlans[j.id])" :disabled="busy||running||changedSources||!canGenerate(j)||!models.length" @click="generateManual(j)">按补充动作生成补段视频</button><button :disabled="busy||running||changedSources" @click="upload(j)">导入独立补段并检查</button><button v-if="j.attempt?.taskId&&!terminal(j.attempt.status)" :disabled="busy" @click="run('query',{join_id:j.id})">查询已有补段</button></div>
        <p v-if="generationBlockReason(j)" class="generation-reason notice">{{generationBlockReason(j)}}</p><p v-else class="generation-reason notice">将使用上方当前分析直接生成补段，不重复分析。{{j.actionAnalysis?.confidence==='medium'?'此方案有不确定项，点击生成即确认按此方案制作。':''}}原片保留，可能消耗视频额度。</p>
        <p role="status">{{statusLabel(j)}} {{j.attempt?.error||''}}</p>
        <p v-if="j.attempt&&terminal(j.attempt.status)" class="notice">需要重做时，AI会结合失败补段重新分析动作；也可补充意图。旧任务和候选继续保留，不必重建所有接点。</p>
        <template v-if="candidate(j)">
          <video :src="fileUrl(candidate(j).fileId)" controls preload="metadata"/>
          <p :class="candidate(j).technicalPassed?'notice':'error'">{{candidate(j).technicalPassed?(candidate(j).needsSemanticReview?'接入与解码检查完成；接出采用动作切镜，不以整图像素相似度判通过。仍须连看人物、空间、持物、动作阶段及声音后才能采用。':'视频已保存，两端画面与时长检查通过，仍需连看完整动作和声音'):`视频已保存，衔接未通过：${candidate(j).reasons.join('；')}。可让AI结合失败片重新分析，或导入其他补段；当前候选暂不能合回原片。`}}</p>
          <div class="boundaries"><figure><img :src="fileUrl(candidate(j).head)" alt="补段实际首帧"/><figcaption>补段实际首帧</figcaption></figure><figure><img :src="fileUrl(candidate(j).tail)" alt="补段实际尾帧"/><figcaption>补段实际尾帧</figcaption></figure></div>
          <details v-if="j.candidates.length>1"><summary>保留候选 · {{j.candidates.length}}</summary><video v-for="c in j.candidates.slice(1)" :key="c.id" :src="fileUrl(c.fileId)" controls preload="none"/></details>
        </template>
        <fieldset :disabled="busy||running||changedSources"><legend>连看前段、完整补段和后段后记录检查；采用原切镜时检查原视频</legend><label v-for="(label,key) in labels" :key="key"><input type="checkbox" :checked="checks[j.id]?.[key]||false" @change="checks[j.id]={...checks[j.id],[key]:$event.target.checked}"/>{{label}}</label></fieldset>
        <div class="toolbar"><button v-if="candidate(j)" :disabled="busy||running||changedSources||!allChecked(j)||!candidate(j).technicalPassed" @click="approve(j)">采用已检查的补段</button><button :disabled="busy||running||changedSources||!allChecked(j)" @click="approve(j,true)">确认此处原切镜可用，不加补段</button></div>
      </article>
      <button :disabled="busy||running||!ready" @click="run('finalize')">{{busy?'处理中…':'合成已检查的接点（本地）'}}</button>
      <section v-for="r in plan.results" :key="r.fileId"><h4>合片候选 · 请连看整片节奏与声音</h4><video :src="fileUrl(r.fileId)" controls preload="metadata"/><button @click="exportVideo(r.fileId)">导出合片候选</button></section>
    </template>
  </section>
</template>

<style scoped>
.primary-motion{font-size:14px;color:var(--theme-text-primary)}.motion-table-wrap{overflow-x:auto}.motion-table{width:100%;border-collapse:collapse;line-height:1.6}.motion-table th,.motion-table td{padding:7px;text-align:left;vertical-align:top;border-bottom:1px solid var(--theme-border-subtle)}.motion-table th:first-child{min-width:75px}.motion-table td:nth-child(2){min-width:65px}.failure-diagnosis{margin:10px 0;padding:10px;border-left:3px solid var(--theme-border-subtle)}
.action-analysis{padding:12px;margin:14px 0;border:1px solid var(--theme-border-subtle);border-radius:8px;background:var(--theme-bg-surface);font-size:12px}.action-analysis ol{padding-left:22px;line-height:1.8}.action-analysis details figure{display:inline-block;width:24%;vertical-align:top;margin:8px 1% 0 0}
.join-action{display:grid;gap:6px;font-size:12px;margin-top:14px}.join-action textarea{box-sizing:border-box;width:100%;resize:vertical;font:inherit;line-height:1.6;padding:9px;border-radius:7px;border:1px solid var(--theme-border-subtle);color:var(--theme-text-primary);background:var(--theme-bg-input)}
.verified-assembly{max-width:900px;color:var(--theme-text-primary)}h3{margin:0 0 10px}p,legend,summary{font-size:12px;line-height:1.7}p{color:var(--theme-text-secondary)}button,select,input{font:inherit;font-size:12px;color:var(--theme-text-primary);background:var(--theme-bg-input);border:1px solid var(--theme-border-subtle);border-radius:7px;padding:8px}button{cursor:pointer}button:disabled{opacity:.45;cursor:default}.toolbar{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.settings{display:grid;gap:12px;margin:15px 0}.settings label{display:grid;gap:6px;font-size:12px}article{padding:16px;margin:18px 0;border:1px solid var(--theme-border-subtle);border-radius:10px}h4{margin:0 0 12px}h4 span{font-size:12px;font-weight:normal;color:var(--theme-text-secondary)}.boundaries{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:0;min-width:0}img{width:100%;max-height:200px;object-fit:contain;background:#111}figcaption{font-size:11px;color:var(--theme-text-secondary);margin:5px 0}video{width:100%;max-height:270px;background:#111;border-radius:8px;margin:10px 0}fieldset{border:1px solid var(--theme-border-subtle);border-radius:8px;display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}fieldset label{font-size:12px;display:flex;align-items:center;gap:5px}.error,.notice{padding:10px;border-radius:7px;background:var(--theme-bg-surface)}.error{color:var(--theme-danger-text);background:var(--theme-danger-soft)}
</style>
