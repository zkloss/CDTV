"""Behavior checks for project evidence, edit decisions and isolated recovery."""
import json,unittest
from unittest.mock import patch
from local_storage import _Handler,StorageError
from scripts import test_continuity_planner as planner_tests
from scripts.test_continuity_planner import answer,review_answer
from scripts import test_verified_assembly as assembly_tests
import verified_assembly as assembly

class EditAssemblyTests(unittest.TestCase):
 setUp=planner_tests.PlannerTests.setUp
 call=assembly_tests.VerifiedAssemblyTests.call
 candidate=assembly_tests.VerifiedAssemblyTests.candidate
 request=planner_tests.PlannerTests.request
 analyze=planner_tests.PlannerTests.analyze
 def link(self):
  ref=self.storage.save_file('refs',b'valid-fixture-image','identity.jpg','image/jpeg')
  self.task=self.storage.create_document('video_projects',{'id':'isolated-test','storyboards':[
   {'id':'shot-a','resultFileId':self.videos[0],'visual':'手持同一泡面桶，注意力由日期转向房间','actionChain':{'start':'拿稳','end':'看屋内'},
    'references':[{'fileId':ref['id'],'name':'原人物','category':'role'}]},
   {'id':'shot-b','resultFileId':self.videos[1],'visual':'系统随后出现','performanceReview':{'status':'pending_generation','message':'当前旧片，需按新版前镜重做'}}]})
  return ref
 def test_prepare_and_resume_hydrate_owner_storyboard_without_promoting_old_reference(self):
  ref=self.link();self.plan=self.call('prepare',source_videos=[{'fileId':v,'shotId':s} for v,s in zip(self.videos,['shot-a','shot-b'])])
  src=self.plan['sources'][0];ctx=src['context']
  self.assertEqual(src['shotId'],'shot-a');self.assertIn('注意力',ctx['intendedAction']);self.assertTrue(ctx['actionChain'])
  self.assertFalse(ctx['references'][0]['approvedForCurrentFootage'])
  self.assertTrue(self.plan['sources'][1]['context']['sourceNeedsRepair'])
  from assembly_context import generation_refs
  self.assertEqual(len(generation_refs(self.storage,self.plan,self.plan['joins'][0])),2)
  self.plan=self.call('approve_refs',confirmed=True,reference_ids=[ref['id']])
  self.assertEqual(len(generation_refs(self.storage,self.plan,self.plan['joins'][0])),3)
  with self.assertRaises(StorageError):self.call('approve_refs',confirmed=True,reference_ids=['foreign-file'])
 def test_analysis_and_blind_review_receive_original_intent_not_a_human_bridge_answer(self):
  self.link()
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):self.analyze()
  self.assertIn('手持同一泡面桶',json.dumps(self.calls[0],ensure_ascii=False))
  self.assertIn('系统随后出现',json.dumps(self.calls[1],ensure_ascii=False))
  self.assertNotIn(self.answer['bridge_prompt'],json.dumps(self.calls[1],ensure_ascii=False))
 def test_reference_or_storyboard_edits_invalidate_generation_before_paid_request(self):
  self.link()
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):a=self.analyze()
  self.task['storyboards'][0]['visual']='新动作意图'
  self.storage.update_document('video_projects','isolated-test',self.task)
  with patch.object(_Handler,'_request_ai_json') as req:
   with self.assertRaisesRegex(StorageError,'原分镜资料已经更新'):self.call('generate',model=self.model['id'],use_analysis_id=a['id'])
  req.assert_not_called()
 def test_malformed_review_retains_exact_missing_fields_raw_reply_and_planning(self):
  def missing(r):r.pop('attribution_reason');return r
  self.review_transform=missing
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):a=self.analyze()
  attempt=self.plan['joins'][0]['analysisAttempt']
  self.assertEqual(a['failureCategory'],'schema');self.assertEqual(attempt['missingFields'],['attribution_reason'])
  self.assertTrue(attempt['reviewRaw']);self.assertTrue(attempt['planningResult'])
  self.assertFalse(a['executionReady'])
  del self.review_transform;self.calls=[]
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   self.plan=self.call('plan_action',analysis_model=self.text['id'],review_only=True,repair_analysis_id=a['id'],request_id='review-only')
  self.assertEqual(len(self.calls),1);self.assertTrue(self.plan['joins'][0]['analysisAttempt']['reusedPlanningResult'])
  self.assertTrue(self.plan['joins'][0]['actionAnalysis']['executionReady'])
 def test_review_only_rejects_changed_source_context_without_model_call(self):
  self.link();self.review_transform=lambda r:{k:v for k,v in r.items() if k!='attribution_reason'}
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):a=self.analyze()
  self.task['storyboards'][0]['visual']='变更';self.storage.update_document('video_projects','isolated-test',self.task)
  with patch.object(_Handler,'_request_ai_json') as req:
   with self.assertRaises(StorageError):self.call('plan_action',analysis_model=self.text['id'],review_only=True,request_id='changed')
  req.assert_not_called()
 def test_direct_cut_strategy_cannot_dispatch_bridge_and_has_review_path(self):
  self.answer=answer('direct_cut');self.answer['edit_strategy']={'type':'direct_cut','reason':'动作阶段已兼容','join_mode':'action_cut'}
  self.review_transform=lambda r:{**r,'edit_strategy':self.answer['edit_strategy']}
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):a=self.analyze()
  with patch.object(_Handler,'_request_ai_json') as req:
   with self.assertRaises(StorageError):self.call('generate',model=self.model['id'],use_analysis_id=a['id'])
  req.assert_not_called()
  self.plan=self.call('review',direct=True,checks={k:True for k in assembly.REVIEW_KEYS})
  self.assertEqual(assembly.approved_parts(self.storage,self.plan),self.videos[:2])
 def test_action_cut_does_not_use_exit_pixel_difference_as_semantic_approval(self):
  self.plan['joins'][0]['actionAnalysis']={'id':'action-cut-plan'}
  self.plan['joins'][0]['attempt']={'joinMode':'action_cut','actionAnalysisId':'action-cut-plan'}
  self.plan=assembly.save(self.storage,self.plan)
  with patch.object(assembly,'MAE_LIMIT',.001):c=self.candidate()
  self.assertTrue(any('接入' in r for r in c['reasons']))
  self.assertFalse(any('接出' in r for r in c['reasons']))
  self.assertTrue(c['needsSemanticReview'])
  with patch.object(assembly,'MAE_LIMIT',1):c=self.candidate()
  with self.assertRaisesRegex(StorageError,'空间方向'):self.call('review',candidate_id=c['id'],checks={k:True for k in assembly.REVIEW_KEYS})
  self.plan=self.call('review',candidate_id=c['id'],checks={k:True for k in (*assembly.REVIEW_KEYS,'space','prop')})
  self.assertEqual(len(assembly.approved_parts(self.storage,self.plan)),3)
 def test_action_cut_request_never_reintroduces_exact_end_frame_instruction(self):
  self.answer['edit_strategy']={'type':'bridge','reason':'补转头后切近景','join_mode':'action_cut'}
  self.review_transform=lambda r:{**r,'edit_strategy':self.answer['edit_strategy']}
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):
   a=self.analyze();self.plan=self.call('generate',model=self.model['id'],use_analysis_id=a['id'])
  payload=next(c for c in self.calls if c and 'production_mode' in c)
  self.assertIn('末帧不要求复制图2构图',payload['prompt']);self.assertNotIn('图2为真实终点；从图1的动作状态自然到达图2',payload['prompt'])
 def test_cut_copy_keeps_original_plan_and_blocks_removing_known_dialogue(self):
  j=self.plan['joins'][0];j['actionAnalysis']={'id':'cut-proposal','edit_strategy':{'type':'trim_cut','previous_out':1.5,'next_in':.25}}
  self.plan=assembly.save(self.storage,self.plan)
  with patch.object(_Handler,'_ffmpeg_binary',return_value=str(__import__('pathlib').Path(__file__).resolve().parents[1]/'runtime/ffmpeg.exe')):
   changed=self.call('apply_cut',use_analysis_id='cut-proposal',checks={'sound':True,'action':True})
  self.assertNotEqual(changed['id'],self.plan['id']);self.assertEqual(changed['parentPlanId'],self.plan['id'])
  self.assertEqual(changed['sources'][0]['originalFileId'],self.videos[0]);self.assertAlmostEqual(changed['sources'][0]['duration'],1.5,places=1)
  self.assertFalse(changed['joins'][0]['selected']);self.assertTrue(self.call('status')['joins'][0]['actionAnalysis'])
  self.plan['sources'][0]['context']={'protectedAudio':[{'start':1,'end':1.8}]};self.plan=assembly.save(self.storage,self.plan)
  with self.assertRaisesRegex(StorageError,'对白区间'):self.call('apply_cut',use_analysis_id='cut-proposal',checks={'sound':True,'action':True})
 def test_source_repair_strategy_is_explicit_and_never_replaces_source_video(self):
  self.answer['edit_strategy']={'type':'repair_source','reason':'后镜仍是旧版本','repair_target':'next','repair_action':'依当前前镜持物状态重拍开头'}
  self.review_transform=lambda r:{**r,'edit_strategy':self.answer['edit_strategy']}
  with patch.object(_Handler,'_request_ai_json',side_effect=self.request):a=self.analyze()
  with patch.object(_Handler,'_request_ai_json') as req:
   with self.assertRaises(StorageError):self.call('generate',model=self.model['id'],use_analysis_id=a['id'])
  req.assert_not_called();self.assertEqual([s['fileId'] for s in self.plan['sources']],self.videos[:2])

if __name__=='__main__':unittest.main()
