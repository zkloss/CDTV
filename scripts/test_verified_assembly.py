"""Regression tests for billable dispatch ownership and fail-closed composition."""
import tempfile, unittest, json, subprocess
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from local_storage import LocalStorage,StorageError,_Handler
import verified_assembly as assembly


class VerifiedAssemblyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.work=Path(self.tmp.name);self.storage=LocalStorage(self.work/'storage');self.handler=object.__new__(_Handler)
  self.videos=[]
  for index in range(3):
   path=self.work/f'{index}.mp4';writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),24,(160,90))
   for frame in range(48):
    img=np.full((90,160,3),90+index,np.uint8)
    cv2.circle(img,(20+(frame*2)%100,45),10,(100,120+index*5,180),-1)
    writer.write(img)
   writer.release()
   self.videos.append(self.storage.save_file('video',path.read_bytes(),path.name,'video/mp4')['id'])
  self.model=self.storage.create_document('ai_models',{'name':'Mock Muse','modelName':'muse-video','modelType':'video','apiUrl':'http://127.0.0.1:1/v1','apiKey':'fixture','enabled':True})
  self.plan=self.call('prepare',source_videos=[{'fileId':x} for x in self.videos[:2]])
 def call(self,action,**kwargs):
  return self.handler._submit_video(self.storage,{'production_mode':'assembly_'+action,'project_id':'isolated-test',
   'plan_id':getattr(self,'plan',{}).get('id'),'join_id':'join-1-2',**kwargs})
 def candidate(self):
  self.plan=self.call('import',file_id=self.videos[2]);return self.plan['joins'][0]['candidates'][0]
 def test_two_edges_do_not_certify_whole_candidate(self):
  candidate=self.candidate();self.assertTrue(candidate['technicalPassed'],candidate)
  self.assertIsNone(candidate['review'])
  with patch.object(assembly,'render') as render:
   with self.assertRaisesRegex(StorageError,'尚未通过'):self.call('finalize')
  render.assert_not_called()
 def test_cannot_override_failed_exit(self):
  with patch.object(assembly,'MAE_LIMIT',0):candidate=self.candidate()
  self.assertFalse(candidate['technicalPassed'])
  with self.assertRaisesRegex(StorageError,'不能采用'):self.call('review',candidate_id=candidate['id'],checks={k:True for k in assembly.REVIEW_KEYS})
  with patch.object(assembly,'render') as render:
   with self.assertRaises(StorageError):self.call('finalize')
  render.assert_not_called()
 def test_original_source_cannot_masquerade_as_bridge(self):
  self.plan=self.call('import',file_id=self.videos[0])
  self.assertIn('补段与原分镜文件相同',str(self.plan['joins'][0]['candidates'][0]['reasons']))
 def test_only_complete_review_allows_composition(self):
  candidate=self.candidate()
  with self.assertRaises(StorageError):self.call('review',candidate_id=candidate['id'],checks={'entry':True,'exit':True})
  self.plan=self.call('review',candidate_id=candidate['id'],checks={k:True for k in assembly.REVIEW_KEYS})
  with patch.object(assembly,'render',return_value={'fileId':'local-test'}) as render:
   result=self.call('finalize');again=self.call('finalize')
  self.assertEqual(render.call_count,1);self.assertEqual(result['results'],again['results'])
  self.assertEqual(render.call_args.args[-1],[self.videos[0],self.videos[2],self.videos[1]])
 def test_duplicate_or_unknown_dispatch_never_retries(self):
  import native_film
  with patch.object(native_film,'submit',side_effect=StorageError(502,'回执未确认')) as request:
   # Call dispatch directly; mocking the native seam must not replace routing.
   body={'project_id':'isolated-test','plan_id':self.plan['id'],'join_id':'join-1-2','production_mode':'assembly_generate','model':self.model['id']}
   with self.assertRaises(StorageError):assembly.dispatch(self.handler,self.storage,body)
   with self.assertRaisesRegex(StorageError,'已经提交'):assembly.dispatch(self.handler,self.storage,body)
  self.assertEqual(request.call_count,1)
  self.assertEqual(self.call('status')['joins'][0]['attempt']['status'],'unknown')
 def test_stale_source_blocks_before_render(self):
  self.plan=self.call('review',direct=True,checks={k:True for k in assembly.REVIEW_KEYS})
  meta=self.storage.find_file(self.videos[0])
  (self.storage.file_directory(meta['bucket'],meta['id'])/'content.bin').write_bytes(b'changed')
  with patch.object(assembly,'render') as render:
   with self.assertRaisesRegex(StorageError,'源视频已经变化'):self.call('finalize')
  render.assert_not_called()
 def test_ownership_checked_on_resume(self):
  with self.assertRaisesRegex(StorageError,'其他作品'):self.call('status',project_id='different-project')
 def test_plan_revision_prevents_concurrent_updates(self):
  stale=dict(self.plan);assembly.save(self.storage,self.plan)
  with self.assertRaisesRegex(StorageError,'冲突'):assembly.save(self.storage,stale)
 def test_bridge_request_has_two_actual_references_and_one_dispatch(self):
  calls=[]
  def request(model,url,operation,body=None,**kw):
   if body is None:return {'production_modes':['shot','scene','assemble']}
   calls.append(body);return {'id':'bridge-test','status':'queued'}
  with patch.object(_Handler,'_request_ai_json',side_effect=request):
   self.plan=self.call('generate',model=self.model['id'])
   with self.assertRaisesRegex(StorageError,'已经提交'):self.call('generate',model=self.model['id'])
  self.assertEqual(len(calls),1);payload=calls[0]
  self.assertEqual(len(payload['images']),2);self.assertEqual(payload['videos'],[])
  self.assertEqual(payload['production_mode'],'shot')
  self.assertIn('只制作这一处过渡，不组装整片',payload['prompt'])
  self.assertNotIn('last_frame',payload);self.assertFalse(self.plan['nativeEndFrameControl'])
 def test_real_render_keeps_source_duration(self):
  self.plan=self.call('review',direct=True,checks={k:True for k in assembly.REVIEW_KEYS})
  with patch.object(_Handler,'_ffmpeg_binary',return_value=str(Path(__file__).resolve().parents[1]/'runtime/ffmpeg.exe')):
   result=self.call('finalize')
  output=result['results'][0];self.assertAlmostEqual(output['duration'],4,places=2)
  self.assertEqual(output['frames'],96);self.assertEqual(output['reviewStatus'],'whole-film-review-required')
 def test_revised_action_can_repair_same_join_and_keeps_old_candidate(self):
  candidate=self.candidate()
  self.plan['joins'][0]['attempt']={'status':'succeeded','model':self.model['id'],'actionPlan':'低头再抬眼','requestId':'old-request','candidateId':candidate['id']}
  self.plan=assembly.save(self.storage,self.plan)
  calls=[]
  def request(model,url,operation,body=None,**kw):
   if body is None:return {'production_modes':['shot','scene']}
   calls.append(body);return {'id':'revised-task','status':'queued'}
  with patch.object(_Handler,'_request_ai_json',side_effect=request):
   self.plan=self.call('generate',model=self.model['id'],action_plan='手持泡面桶，肩膀带头向右转',request_id='revised-request')
   repeated=self.call('generate',model=self.model['id'],action_plan='手持泡面桶，肩膀带头向右转',request_id='revised-request')
  self.assertEqual(len(calls),1)
  self.assertIn('肩膀带头向右转',calls[0]['prompt'])
  self.assertEqual(len(repeated['joins'][0]['attempts']),1)
  self.assertEqual(repeated['joins'][0]['candidates'][0]['id'],candidate['id'])
 def test_unchanged_terminal_action_never_dispatches(self):
  self.plan['joins'][0]['attempt']={'status':'succeeded','model':self.model['id'],'actionPlan':'持桶 右转','requestId':'first'}
  self.plan=assembly.save(self.storage,self.plan)
  with patch.object(_Handler,'_request_ai_json') as request:
   with self.assertRaisesRegex(StorageError,'动作方案没有修改'):self.call('generate',model=self.model['id'],action_plan=' 持桶   右转 ',request_id='second')
  request.assert_not_called()
 def test_uncertain_receipt_remains_locked_despite_changed_action(self):
  self.plan['joins'][0]['attempt']={'status':'unknown','model':self.model['id'],'actionPlan':'低头','requestId':'first'}
  self.plan=assembly.save(self.storage,self.plan)
  with patch.object(_Handler,'_request_ai_json') as request:
   with self.assertRaisesRegex(StorageError,'回执尚未确认'):self.call('generate',model=self.model['id'],action_plan='持桶右转',request_id='second')
  request.assert_not_called()


if __name__=='__main__':unittest.main()
