import json, unittest
from unittest.mock import patch
from local_storage import _Handler,StorageError
from scripts import test_verified_assembly as fixtures
from continuity_planner import parse_result, compile_motion, COMPONENTS, PROMPT_VERSION

def answer(decision='bridge',confidence='high',frame_count=8):
 result={'decision':decision,'confidence':confidence,'start_frame':4,'end_frame':5,
  'start_state':'侧面持物','end_state':'近景持物并注视','observations':[{'frame':i,'visible':f'图{i}可见的人物和道具状态'} for i in range(1,9)],
  'differences':['头部朝向、持物位置及景别变化'],'duration_seconds':2.5,'uncertainties':[],
  'motion_components':[{'component':key,'change':'required' if key in ('head_yaw','gaze','framing') else 'none',
   'start':'前镜'+label,'end':'后镜'+label,'action':{'head_yaw':'朝下一镜可见朝向平缓转头，肩膀保持稳定','gaze':'目光落到持物上','framing':'切入下一镜近景'}.get(key,'保持原有'+label),
   'reason':'对照实际首尾的'+label,'evidence_frames':[4,5]} for key,label in COMPONENTS.items()],
  'primary_components':['head_yaw'],'attribution_reason':'头相对肩线变化是转头，身体无需整体转身，景别差异另行切近景。',
  'failure_diagnosis':None,
  'edit_strategy':{'type':'direct_cut' if decision=='direct_cut' else 'bridge','reason':'依据真实动作阶段','join_mode':'continuous'},
  'continuity_contract':{'invariants':['同一人物和持物'],'action_phase':'拿稳后转头','attention_target':'持物','spatial_basis':'人物原地，画面方位随机位改变','reveal_boundary':'不提前出现蓝色界面'}}
 if frame_count>8:
  result['observations'] += [{'frame':i,'visible':'失败片低头而没有转到目标朝向'} for i in range(9,frame_count+1)]
  result['failure_diagnosis']={'observed_actions':['只低头看持物'],'missing_components':['head_yaw'],
   'corrections':['先补实际转头，不能再仅低头看持物'],'evidence_frames':list(range(9,frame_count+1))}
 result['action_steps'],result['camera_action'],result['bridge_prompt']=compile_motion(result)
 return result

def review_answer(body):
 import re
 text=body['messages'][-1]['content'][0]['text']
 frame_count=int(re.search(r'原始帧数：(\d+)',text).group(1))
 result=answer(frame_count=frame_count)
 return {**result,'verdict':'pass','checks':[{'component':key,'supported':True,'reason':'实际端点支持此项判断'} for key in COMPONENTS],
         'issues':[],'unresolved':[]}

class PlannerTests(unittest.TestCase):
 call=fixtures.VerifiedAssemblyTests.call
 candidate=fixtures.VerifiedAssemblyTests.candidate
 def setUp(self):
  fixtures.VerifiedAssemblyTests.setUp(self)
  self.text=self.storage.create_document('ai_models',{'name':'Vision fixture','modelName':'vision-fixture','modelType':'text',
   'apiUrl':'http://127.0.0.1:1/v1','enabled':True})
  self.calls=[];self.answer=answer()
 def request(self,model,url,operation,body=None,*args,**kw):
  self.calls.append(body)
  if body is None:return {'production_modes':['shot','scene','assemble']}
  if 'messages' in body:
   if operation=='衔接动作终态复核':
    result=review_answer(body)
    if hasattr(self,'review_transform'):result=self.review_transform(result)
    return {'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}]}
   import re
   result=json.loads(json.dumps(self.answer));frame_count=int(re.search(r'原始帧数：(\d+)',body['messages'][-1]['content'][0]['text']).group(1))
   if frame_count>8:
    failed=answer(frame_count=frame_count);result['observations']=failed['observations'];result['failure_diagnosis']=failed['failure_diagnosis']
   return {'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}]}
  return {'id':'auto-planned-task','status':'queued'}
 def analyze(self):
  self.plan=self.call('plan_action',analysis_model=self.text['id']);return self.plan['joins'][0]['actionAnalysis']
 def blocked(self):
  def contradictory(result):result['primary_components']=['torso'];return result
  self.review_transform=contradictory
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):result=self.analyze()
  del self.review_transform
  self.calls=[]
  return result
 def repair(self,previous,request_id='repair-fixture'):
  self.answer['repair_changes']=['移除不需要身体转动的主要动作，按真实两端保留转头。']
  self.plan=self.call('plan_action',analysis_model=self.text['id'],repair_analysis_id=previous['id'],request_id=request_id)
  return self.plan['joins'][0]['actionAnalysis']
 def test_assembly_model_preferences_persist_without_changing_general_models(self):
  before=self.storage.get_document('ai_models',self.text['id'])
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):self.analyze()
  restored=self.call('status')
  self.assertEqual(restored['analysisModels'],{'analysisModel':self.text['id'],'reviewModel':self.text['id']})
  self.assertEqual(self.storage.get_document('ai_models',self.text['id']),before)
 def test_failed_candidate_can_violate_a_component_that_sources_keep_unchanged(self):
  result=answer(frame_count=11)
  result['failure_diagnosis']['missing_components']=['head_pitch']
  result['failure_diagnosis']['corrections']=['失败片低头，原两端均保持水平，需要去掉错误低头。']
  parsed=parse_result(json.dumps(result),11)
  self.assertEqual(next(m for m in parsed['motion_components'] if m['component']=='head_pitch')['change'],'none')
  self.assertEqual(parsed['failure_diagnosis']['missing_components'],['head_pitch'])
 def test_failed_candidate_diagnosis_still_rejects_unknown_components(self):
  result=answer(frame_count=11);result['failure_diagnosis']['missing_components']=['made_up']
  with self.assertRaises(StorageError):parse_result(json.dumps(result),11)
 def test_explicit_flat_repair_fields_are_normalized_without_guessing(self):
  data=answer();data['edit_strategy']={'type':'repair_source','reason':'旧源开头需修复','join_mode':'action_cut'}
  data.update(repair_target='next',repair_action='保持原持物姿态更新下一镜开头')
  parsed=parse_result(json.dumps(data),8)
  self.assertEqual(parsed['edit_strategy']['repair_target'],'next')
  self.assertEqual(parsed['edit_strategy']['repair_action'],data['repair_action'])
 def test_conflicting_nested_and_flat_repair_targets_are_rejected(self):
  data=answer();data['edit_strategy'].update(type='repair_source',repair_target='previous',repair_action='保留原片修复')
  data.update(repair_target='next',repair_action='保留原片修复')
  with self.assertRaisesRegex(StorageError,'冲突'):parse_result(json.dumps(data),8)
 def test_missing_repair_action_is_still_rejected(self):
  data=answer();data['edit_strategy'].update(type='repair_source');data['repair_target']='next'
  with self.assertRaisesRegex(StorageError,'缺少目标或具体动作'):parse_result(json.dumps(data),8)
 def test_flat_repair_fields_in_independent_review_are_not_discarded(self):
  def flat(result):
   result['edit_strategy']={'type':'repair_source','reason':'依据原片修复','join_mode':'action_cut'}
   result.update(repair_target='next',repair_action='保持原持物阶段修复下一镜')
   return result
  self.review_transform=flat
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):result=self.analyze()
  self.assertEqual(result['edit_strategy']['repair_target'],'next')
  self.assertTrue(result['executionReady'])
 def test_failed_cached_analysis_has_explicit_correction_and_preserves_history(self):
  failed=self.blocked()
  self.assertFalse(failed['executionReady'])
  self.assertIn('rejectedProposal',failed['planReview'])
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   self.assertEqual(self.analyze()['id'],failed['id'])
   self.assertEqual(self.calls,[])
   corrected=self.repair(failed)
   self.assertEqual(self.analyze()['id'],corrected['id'])
  self.assertNotEqual(corrected['id'],failed['id']);self.assertTrue(corrected['executionReady'])
  self.assertEqual(corrected['repairOf'],failed['id']);self.assertTrue(corrected['repair_changes'])
  self.assertEqual(len(self.calls),2)
  context=self.calls[0]['messages'][-1]['content'][-1]['text']
  self.assertIn('主要动作与分量判断矛盾',context);self.assertIn(failed['id'],context)
  self.assertIn('rejectedReviewProposal',context)
  # Independent review must still judge the pictures without the failed answer.
  self.assertNotIn(failed['id'],json.dumps(self.calls[1]))
  self.assertEqual(self.plan['joins'][0]['actionAnalysisHistory'][-1]['id'],failed['id'])
  self.assertFalse(any(c and 'production_mode' in c for c in self.calls))
 def test_completed_correction_request_is_idempotent_even_with_old_target(self):
  failed=self.blocked()
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   corrected=self.repair(failed);again=self.repair(failed)
  self.assertEqual(corrected['id'],again['id']);self.assertEqual(len(self.calls),2)
 def test_pending_and_failed_correction_receipts_cannot_spend_twice(self):
  import verified_assembly
  failed=self.blocked()
  for status in ('running','failed','unknown'):
   self.plan['joins'][0]['analysisAttempt']={'status':status,'requestId':'same-repair','repairOf':failed['id']}
   self.plan=verified_assembly.save(self.storage,self.plan)
   with patch.object(_Handler,'_request_ai_json') as request:self.repair(failed,'same-repair')
   request.assert_not_called()
 def test_stale_or_missing_correction_identity_never_calls_models(self):
  failed=self.blocked()
  for target,request_id in [('stale','new-repair'),(failed['id'],''),(failed['id'],'x'*129)]:
   with patch.object(_Handler,'_request_ai_json') as request:
    with self.assertRaises(StorageError):self.call('plan_action',analysis_model=self.text['id'],repair_analysis_id=target,request_id=request_id)
   request.assert_not_called()
 def test_correction_of_usable_analysis_is_rejected_before_paid_request(self):
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):usable=self.analyze()
  with patch.object(_Handler,'_request_ai_json') as request:
   with self.assertRaisesRegex(StorageError,'已经通过复核'):self.repair(usable)
  request.assert_not_called()
 def test_explicit_next_correction_replaces_a_still_blocked_result(self):
  failed=self.blocked()
  def blocked(result):result.update(verdict='needs_review',unresolved=['目光落点仍不确定']);return result
  self.review_transform=blocked
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):still_blocked=self.repair(failed,'round-one')
  self.assertNotEqual(still_blocked['id'],failed['id']);self.assertFalse(still_blocked['executionReady'])
  del self.review_transform
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):corrected=self.repair(still_blocked,'round-two')
  self.assertTrue(corrected['executionReady']);self.assertEqual(len(self.calls),4)
  self.assertIn('目光落点仍不确定',self.calls[2]['messages'][-1]['content'][-1]['text'])
  self.assertEqual([a['id'] for a in self.plan['joins'][0]['actionAnalysisHistory']], [failed['id'],still_blocked['id']])
  self.assertFalse(any(c and 'production_mode' in c for c in self.calls))
 def test_correction_must_explain_changes_and_failed_receipt_has_a_fresh_retry(self):
  failed=self.blocked()
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   with self.assertRaisesRegex(StorageError,'没有说明如何处理'):self.call('plan_action',analysis_model=self.text['id'],repair_analysis_id=failed['id'],request_id='missing-changes')
   self.plan=self.call('status')
   self.assertEqual(self.plan['joins'][0]['analysisAttempt']['status'],'failed')
   self.assertEqual(self.plan['joins'][0]['actionAnalysis']['id'],failed['id'])
   corrected=self.repair(failed,'fresh-request')
  self.assertTrue(corrected['executionReady']);self.assertEqual(len(self.calls),3)
 def test_visual_analysis_is_scoped_temporal_and_not_a_video_approval(self):
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):analysis=self.analyze()
  self.assertEqual(len(self.calls),2);content=self.calls[0]['messages'][-1]['content']
  self.assertEqual(sum(c['type']=='image_url' for c in content),1)
  self.assertEqual(len(analysis['evidence']),8)
  self.assertEqual(analysis['evidence'][3]['frameIndex'],47)
  self.assertEqual(analysis['evidence'][4]['frameIndex'],0)
  self.assertEqual(analysis['evidence'][3]['sourceSha256'],self.plan['sources'][0]['sha256'])
  self.assertFalse(analysis['isVideoApproval']);self.assertNotIn('attempt',self.plan['joins'][0])
  self.assertEqual(self.plan['results'],[])
 def test_cached_analysis_does_not_repeat_model_call(self):
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   first=self.analyze();second=self.analyze()
  self.assertEqual(first['id'],second['id']);self.assertEqual(len(self.calls),2)
 def test_empty_manual_input_automatically_plans_before_one_video_request(self):
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   self.plan=self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True,request_id='smart-click')
  self.assertEqual(sum(bool(c and 'messages' in c) for c in self.calls),2)
  videos=[c for c in self.calls if c and 'production_mode' in c];self.assertEqual(len(videos),1)
  self.assertIn(self.answer['bridge_prompt'],videos[0]['prompt'])
  self.assertEqual(self.plan['joins'][0]['attempt']['actionAnalysisId'],self.plan['joins'][0]['actionAnalysis']['id'])
 def test_uncertain_or_direct_cut_analysis_cannot_dispatch_video(self):
  for decision,confidence in [('needs_review','low'),('direct_cut','high'),('bridge','medium')]:
   self.answer=answer(decision,confidence)
   # Separate cache keys by model identity, without modifying source videos.
   model=self.storage.create_document('ai_models',{'name':decision,'modelName':'vision-'+decision,'modelType':'text','apiUrl':'http://127.0.0.1:1/v1','enabled':True})
   with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
    with self.assertRaisesRegex(StorageError,'未调用视频'):self.call('generate',model=self.model['id'],analysis_model=model['id'],auto_plan=True)
  self.assertFalse(any(c and 'production_mode' in c for c in self.calls))
 def test_medium_confidence_requires_explicit_acceptance_of_this_ai_plan(self):
  self.answer=answer('bridge','medium')
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   analysis=self.analyze()
   with self.assertRaisesRegex(StorageError,'未调用视频'):self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True,accept_analysis_id='wrong-plan')
   self.plan=self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True,accept_analysis_id=analysis['id'])
  self.assertEqual(sum(bool(c and 'messages' in c) for c in self.calls),2)
  self.assertEqual(sum(bool(c and 'production_mode' in c) for c in self.calls),1)
 def test_previous_human_answer_is_not_leaked_into_visual_request(self):
  import verified_assembly
  self.plan['joins'][0]['attempt']={'status':'succeeded','actionPlan':'UNIQUE_HUMAN_ANSWER_DO_NOT_SEND'}
  self.plan=verified_assembly.save(self.storage,self.plan)
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):self.analyze()
  self.assertNotIn('UNIQUE_HUMAN_ANSWER_DO_NOT_SEND',json.dumps(self.calls))
 def test_new_failed_candidate_invalidates_cache_and_includes_actual_tail(self):
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):first=self.analyze()
  with patch('verified_assembly.MAE_LIMIT',0):self.candidate()
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):second=self.analyze()
  self.assertNotEqual(first['cacheKey'],second['cacheKey'])
  self.assertEqual(len(second['evidence']),11)
  self.assertEqual(second['evidence'][-1]['frameIndex'],47)
 def test_bad_model_json_blocks_before_video_and_records_failure(self):
  self.answer['end_frame']=8
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   with self.assertRaisesRegex(StorageError,'真实前镜末帧'):self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True)
  self.assertFalse(any(c and 'production_mode' in c for c in self.calls))
  self.assertEqual(self.call('status')['joins'][0]['analysisAttempt']['status'],'failed')
 def test_missing_observations_are_not_accepted_as_seeing_video(self):
  data=answer();data['observations']=data['observations'][:4]
  with self.assertRaisesRegex(StorageError,'未覆盖'):parse_result(json.dumps(data),8)
 def test_unknown_video_receipt_does_not_trigger_even_a_planning_call(self):
  import verified_assembly
  self.plan['joins'][0]['attempt']={'status':'unknown'};self.plan=verified_assembly.save(self.storage,self.plan)
  with patch.object(_Handler,'_request_ai_json') as request:
   with self.assertRaisesRegex(StorageError,'回执尚未确认'):self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True)
  request.assert_not_called()
 def test_video_prompt_cannot_drop_head_turn_even_if_model_free_text_only_says_look_down(self):
  self.answer['bridge_prompt']='仅低头看物体并推近'
  self.answer['action_steps']=['只低头']
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True)
  video=next(c for c in self.calls if c and 'production_mode' in c)
  self.assertIn('朝下一镜可见朝向平缓转头',video['prompt'])
  self.assertIn('仅低头、移动视线、抬起道具或相机绕拍都不能代替',video['prompt'])
  self.assertNotIn('仅低头看物体并推近',video['prompt'])
 def test_camera_only_change_does_not_invent_a_head_or_body_turn(self):
  result=answer('direct_cut')
  result['primary_components']=[]
  for m in result['motion_components']:
   m['change']='none';m['action']='保持原态'
  parsed=parse_result(json.dumps(result),8)
  self.assertEqual(parsed['decision'],'direct_cut');self.assertEqual(parsed['action_steps'],[])
  self.assertNotIn('必须实际完成头部左右',parsed['bridge_prompt'])
 def test_missing_or_duplicate_motion_components_cannot_dispatch(self):
  for mode in ('missing','duplicate'):
   result=answer()
   if mode=='missing':result['motion_components'].pop()
   else:result['motion_components'][-1]=result['motion_components'][0]
   with self.assertRaises(StorageError):parse_result(json.dumps(result),8)
 def test_motion_component_must_compare_real_endpoints(self):
  result=answer();result['motion_components'][0]['evidence_frames']=[1,8]
  with self.assertRaisesRegex(StorageError,'真实两端'):parse_result(json.dumps(result),8)
 def test_primary_motion_must_match_required_component(self):
  result=answer();result['primary_components']=['torso']
  with self.assertRaisesRegex(StorageError,'主要动作与分量'):parse_result(json.dumps(result),8)
 def test_uncertain_motion_cannot_be_marked_high_and_silently_dispatched(self):
  self.answer['motion_components'][2]['change']='uncertain'
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   with self.assertRaisesRegex(StorageError,'未调用视频'):self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True)
  self.assertFalse(any(c and 'production_mode' in c for c in self.calls))
 def test_failure_analysis_requires_all_failed_frames_and_concrete_correction(self):
  for mode in ('no_observation','no_diagnosis','no_correction','no_tail'):
   result=answer(frame_count=11)
   if mode=='no_observation':result['observations'].pop()
   if mode=='no_diagnosis':result['failure_diagnosis']=None
   if mode=='no_correction':result['failure_diagnosis']['corrections']=[]
   if mode=='no_tail':result['failure_diagnosis']['evidence_frames']=[9,10]
   with self.assertRaises(StorageError):parse_result(json.dumps(result),11)
 def test_v1_cache_is_reanalyzed_once_and_old_plan_is_preserved(self):
  import verified_assembly
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):old=self.analyze()
  old['promptVersion']='visual-action-planner-v1';old['cacheKey']='v1-signature'
  self.plan['joins'][0]['actionAnalysis']=old
  self.plan=verified_assembly.save(self.storage,self.plan)
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):new=self.analyze();cached=self.analyze()
  self.assertEqual(new['promptVersion'],PROMPT_VERSION)
  self.assertEqual(new['id'],cached['id']);self.assertNotEqual(old['id'],new['id'])
  self.assertEqual(len(self.calls),4)
  self.assertEqual(self.plan['joins'][0]['actionAnalysisHistory'][-1]['id'],old['id'])
 def test_review_corrects_wrong_gaze_and_video_uses_corrected_target(self):
  def correct(result):
   result['verdict']='corrected';result['issues']=['正脸不等于看镜头']
   for m in result['motion_components']:
    if m['component']=='gaze':m.update(action='目光落在画面右下方的原包装上',end='眼睛看画面右下方')
   return result
  self.review_transform=correct
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   self.plan=self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True)
  video=next(c for c in self.calls if c and 'production_mode' in c)
  self.assertIn('目光落在画面右下方的原包装上',video['prompt'])
  self.assertEqual(self.plan['joins'][0]['actionAnalysis']['planReview']['verdict'],'corrected')
 def test_unresolved_review_cannot_be_bypassed_by_medium_acceptance(self):
  def unresolved(result):result.update(verdict='needs_review',unresolved=['目光落点互相矛盾']);return result
  self.review_transform=unresolved
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   analysis=self.analyze()
   with self.assertRaisesRegex(StorageError,'未调用视频'):self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True,accept_analysis_id=analysis['id'])
  self.assertFalse(any(c and 'production_mode' in c for c in self.calls))
 def test_unmeasured_numeric_rotation_is_blocked_even_if_model_review_says_pass(self):
  def numeric(result):result['motion_components'][0]['action']='向左转90度';return result
  self.review_transform=numeric
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):analysis=self.analyze()
  self.assertFalse(analysis['executionReady']);self.assertEqual(analysis['decision'],'needs_review')
  self.assertIn('数字旋转角度',';'.join(analysis['planReview']['unresolved']))
 def test_review_cannot_report_error_without_correcting_the_component(self):
  def unchanged(result):result['checks'][0]['supported']=False;return result
  self.review_transform=unchanged
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   with self.assertRaisesRegex(StorageError,'未调用视频'):self.call('generate',model=self.model['id'],analysis_model=self.text['id'],auto_plan=True)
  self.assertFalse(any(c and 'production_mode' in c for c in self.calls))
 def test_blind_review_keeps_exact_image_order_without_initial_answer_text(self):
  import continuity_planner
  self.answer['start_state']='UNIQUE_INITIAL_OBSERVATION_NOT_FOR_REVIEW'
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request),patch('continuity_planner.review_sheet',wraps=continuity_planner.review_sheet) as sheet:self.analyze()
  first=self.calls[0]['messages'][-1]['content'];second=self.calls[1]['messages'][-1]['content']
  self.assertEqual(sheet.call_args_list[0].args[0],sheet.call_args_list[1].args[0])
  self.assertEqual(sheet.call_args.args[1],8)
  self.assertEqual(sum(c['type']=='image_url' for c in second),1)
  self.assertNotIn('UNIQUE_INITIAL_OBSERVATION_NOT_FOR_REVIEW',json.dumps(second))
  self.assertIn('START图4',second[0]['text']);self.assertIn('END图5',second[0]['text'])
 def test_changed_review_model_invalidates_cache_once(self):
  reviewer=self.storage.create_document('ai_models',{'name':'Second vision','modelName':'second-vision','modelType':'text','apiUrl':'http://127.0.0.1:1/v1','enabled':True})
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   first=self.analyze()
   self.plan=self.call('plan_action',analysis_model=self.text['id'],review_model=reviewer['id'])
   second=self.plan['joins'][0]['actionAnalysis']
   self.call('plan_action',analysis_model=self.text['id'],review_model=reviewer['id'])
  self.assertNotEqual(first['id'],second['id']);self.assertEqual(len(self.calls),4)
  self.assertEqual(self.calls[3]['model'],'second-vision')
  self.assertEqual(second['sourceSignature']['reviewModel'],reviewer['id'])
 def test_nonvisual_review_model_is_rejected_before_planning(self):
  reviewer=self.storage.create_document('ai_models',{'name':'No images','modelName':'text-only','modelType':'text','supportsVision':False,'apiUrl':'http://127.0.0.1:1/v1','enabled':True})
  with patch.object(_Handler,'_request_ai_json') as request:
   with self.assertRaisesRegex(StorageError,'复核模型不支持看图'):self.call('plan_action',analysis_model=self.text['id'],review_model=reviewer['id'])
  request.assert_not_called()
 def test_current_analysis_generation_does_not_resolve_or_call_analysis_models(self):
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):analysis=self.analyze()
  self.calls=[]
  with patch('continuity_planner.analyze',side_effect=AssertionError('Do not reanalyze')),patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   self.plan=self.call('generate',model=self.model['id'],use_analysis_id=analysis['id'],auto_plan=True,analysis_model='not-selected-now')
  self.assertFalse(any(c and 'messages' in c for c in self.calls))
  self.assertEqual(sum(bool(c and 'production_mode' in c) for c in self.calls),1)
  self.assertEqual(self.plan['joins'][0]['attempt']['actionAnalysisId'],analysis['id'])
 def test_wrong_current_analysis_id_is_rejected_without_any_model_call(self):
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):self.analyze()
  with patch.object(_Handler,'_request_ai_json') as request:
   with self.assertRaisesRegex(StorageError,'分析已经更新'):self.call('generate',model=self.model['id'],use_analysis_id='stale-id',auto_plan=True)
  request.assert_not_called()
 def test_blocked_current_analysis_still_cannot_dispatch_video(self):
  def blocked(result):result.update(verdict='needs_review',unresolved=['主要动作与分量判断矛盾']);return result
  self.review_transform=blocked
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):analysis=self.analyze()
  with patch.object(_Handler,'_request_ai_json') as request:
   with self.assertRaisesRegex(StorageError,'未调用视频'):self.call('generate',model=self.model['id'],use_analysis_id=analysis['id'],accept_analysis_id=analysis['id'],auto_plan=True)
  request.assert_not_called()
 def test_new_failed_video_invalidates_explicit_current_analysis_generation(self):
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):analysis=self.analyze()
  with patch('verified_assembly.MAE_LIMIT',0):self.candidate()
  with patch.object(_Handler,'_request_ai_json') as request:
   with self.assertRaisesRegex(StorageError,'失败补段已经变化'):self.call('generate',model=self.model['id'],use_analysis_id=analysis['id'],auto_plan=True)
  request.assert_not_called()
 def test_failed_first_analysis_keeps_old_result_and_next_success_retains_failure_receipt(self):
  import verified_assembly
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):old=self.analyze()
  self.plan['joins'][0]['actionAnalysis']['promptVersion']='visual-action-planner-v1'
  self.plan=verified_assembly.save(self.storage,self.plan)
  self.answer['end_frame']=8
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   with self.assertRaises(StorageError):self.analyze()
  failed=self.call('status')['joins'][0]
  self.assertEqual(failed['actionAnalysis']['id'],old['id'])
  self.assertEqual(failed['analysisAttempt']['stage'],'failed')
  self.assertIn('finishedAt',failed['analysisAttempt'])
  self.answer['end_frame']=5
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):new=self.analyze()
  self.assertNotEqual(new['id'],old['id'])
  joined=self.plan['joins'][0]
  self.assertEqual(joined['analysisAttempt']['stage'],'completed')
  self.assertTrue(any(a.get('status')=='failed' and a.get('error') for a in joined['analysisAttemptHistory']))
 def test_persisted_stage_changes_allow_read_only_progress_query(self):
  stages=[]
  def observe(*args,**kwargs):
   stages.append(self.storage.get_document('assembly_plans',self.plan['id'])['joins'][0]['analysisAttempt']['stage'])
   return self.request(*args,**kwargs)
  with patch.object(_Handler,'_request_ai_json',side_effect=observe):self.analyze()
  self.assertEqual(stages,['analyzing','reviewing'])
  attempt=self.plan['joins'][0]['analysisAttempt']
  self.assertEqual(attempt['stage'],'completed');self.assertIn('startedAt',attempt);self.assertIn('finishedAt',attempt)
 def test_legacy_version_with_matching_cache_key_is_not_returned_as_current(self):
  import verified_assembly
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):old=self.analyze()
  self.plan['joins'][0]['actionAnalysis']['promptVersion']='visual-action-planner-v1'
  self.plan=verified_assembly.save(self.storage,self.plan)
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):new=self.analyze()
  self.assertNotEqual(old['id'],new['id']);self.assertEqual(new['promptVersion'],PROMPT_VERSION)
 def test_current_plan_cannot_generate_while_new_analysis_is_pending(self):
  import verified_assembly
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):analysis=self.analyze()
  for status in ('running','unknown'):
   self.plan['joins'][0]['analysisAttempt']['status']=status
   self.plan=verified_assembly.save(self.storage,self.plan)
   with patch.object(_Handler,'_request_ai_json') as request:
    with self.assertRaisesRegex(StorageError,'分析仍在执行或回执'):self.call('generate',model=self.model['id'],use_analysis_id=analysis['id'],auto_plan=True)
   request.assert_not_called()
 def test_correction_timeout_has_its_own_durable_time_and_keeps_old_analysis_date(self):
  failed=self.blocked();seen=[]
  def timeout(model,url,operation,body,*args,**kwargs):
   seen.append(kwargs['timeout'])
   raise StorageError(504,'衔接动作纠正超时')
  with patch.object(_Handler,'_request_ai_json',side_effect=timeout):
   with self.assertRaisesRegex(StorageError,'超时'):self.repair(failed,'timeout-attempt')
  state=self.call('status')['joins'][0];attempt=state['analysisAttempt']
  self.assertEqual(seen,[600]);self.assertEqual(attempt['errorKind'],'timeout')
  self.assertEqual(attempt['failedStage'],'analyzing');self.assertEqual(attempt['providerOutcome'],'unknown')
  self.assertTrue(attempt['startedAt']);self.assertTrue(attempt['finishedAt'])
  self.assertNotIn('responseReceivedAt',attempt)
  self.assertEqual(state['actionAnalysis']['analyzedAt'],failed['analyzedAt'])
  self.assertEqual(state['actionAnalysis']['id'],failed['id'])
  self.assertEqual(attempt['requestId'],'timeout-attempt')
 def test_both_analysis_stages_record_response_times_and_wait_longer_than_180_seconds(self):
  waits=[]
  def observe(*args,**kwargs):waits.append(kwargs['timeout']);return self.request(*args,**kwargs)
  with patch.object(_Handler,'_request_ai_json',side_effect=observe):self.analyze()
  attempt=self.plan['joins'][0]['analysisAttempt']
  self.assertEqual(waits,[600,600]);self.assertTrue(attempt['responseReceivedAt'])
  self.assertTrue(attempt['reviewStartedAt']);self.assertTrue(attempt['reviewResponseReceivedAt'])
  self.assertLessEqual(attempt['responseReceivedAt'],attempt['reviewStartedAt'])
  self.assertLessEqual(attempt['reviewStartedAt'],attempt['reviewResponseReceivedAt'])
  self.assertEqual(attempt['status'],'succeeded')
 def test_review_timeout_is_distinct_from_no_planning_response_and_never_sends_video(self):
  def timeout_review(*args,**kwargs):
   if args[2]=='衔接动作终态复核':raise StorageError(504,'终态复核超时')
   return self.request(*args,**kwargs)
  with patch.object(_Handler,'_request_ai_json',side_effect=timeout_review):analysis=self.analyze()
  attempt=self.plan['joins'][0]['analysisAttempt']
  self.assertTrue(attempt['responseReceivedAt']);self.assertTrue(attempt['reviewStartedAt'])
  self.assertNotIn('reviewResponseReceivedAt',attempt)
  self.assertEqual(attempt['errorKind'],'timeout');self.assertEqual(attempt['failedStage'],'reviewing')
  self.assertFalse(analysis['executionReady']);self.assertTrue(analysis['analyzedAt'])
  self.assertFalse(any(c and 'production_mode' in c for c in self.calls))

if __name__=='__main__':unittest.main()
