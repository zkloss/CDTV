"""Native film boundaries use isolated storage and a recorded provider seam."""
import base64
import tempfile
import unittest
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from local_storage import LocalStorage, StorageError, _Handler
from native_film import validate


class NativeFilmTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = LocalStorage(Path(self.temp.name))
        self.handler = object.__new__(_Handler)
        self.model = self.store.create_document('ai_models', {
            'name':'Muse fixture', 'modelType':'video', 'modelName':'muse-video',
            'apiUrl':'http://127.0.0.1:18631/v1/videos/generations', 'apiKey':'fixture', 'enabled':True})
        self.calls = []
        self.sources = [self.store.save_file('video', data, f'{i}.mp4', 'video/mp4')
                        for i, data in enumerate([b'first-video', b'second-video'])]

    def request(self, model, endpoint, operation, body=None, **kwargs):
        self.calls.append((endpoint, body))
        return {'production_modes':['scene','assemble']} if body is None else {'id':'native-task','status':'queued'}

    def test_scene_preserves_full_script_without_single_shot_policies(self):
        script = '第一场：进门。\n第二场：回答。\n学徒：“师父，最后一炉。”'
        with patch.object(_Handler, '_request_ai_json', side_effect=self.request):
            result = self.handler._submit_video(self.store, {'model':self.model['id'], 'production_mode':'scene', 'prompt':script, 'duration':120})
        payload = self.calls[-1][1]
        self.assertIn(script, payload['prompt'])
        self.assertNotIn('单镜连续', payload['prompt'])
        self.assertNotIn('不输出合集', payload['prompt'])
        self.assertEqual(payload['duration'], 120)
        self.assertEqual(result['production_mode'], 'scene')

    def test_assembly_sends_original_ordered_video_bytes(self):
        with patch.object(_Handler, '_request_ai_json', side_effect=self.request):
            self.handler._submit_video(self.store, {'model':self.model['id'], 'production_mode':'assemble', 'prompt':'前后连接',
                'source_videos':[{'fileId':s['id'], 'title':f'素材{i+1}'} for i,s in enumerate(self.sources)]})
        payload = self.calls[-1][1]
        self.assertEqual([base64.b64decode(v.split(',')[1]) for v in payload['videos']], [b'first-video',b'second-video'])
        self.assertNotIn('duration', payload)
        submission = self.store.list_documents('ai_video_submissions')[0]
        self.assertEqual([s['fileId'] for s in submission['sourceVideos']], [s['id'] for s in self.sources])
        self.assertNotIn('base64', str(submission))

    def test_assembly_boundary_images_and_adaptive_brief_use_real_bundled_runtime(self):
        from native_film import prepare_assembly_uploads
        media = (Path(__file__).resolve().parents[1]/'frontend/native-film-qa.mp4').read_bytes()
        clips = [self.store.save_file('video', media, f'real-{i}.mp4', 'video/mp4') for i in range(2)]
        binary = Path(__file__).resolve().parents[1]/'runtime/ffmpeg.exe'
        with patch.object(_Handler, '_ffmpeg_binary', return_value=str(binary)), \
             patch.object(_Handler, '_request_ai_json', side_effect=self.request), \
             patch('native_film.prepare_assembly_uploads', wraps=prepare_assembly_uploads) as prepare:
            self.handler._submit_video(self.store, {'model':self.model['id'], 'production_mode':'assemble',
                'prompt':'动作接不上时自行补过渡，保留对白',
                'source_videos':[{'fileId':c['id'],'title':f'镜头{i+1}'} for i,c in enumerate(clips)]})
        payload = self.calls[-1][1]
        self.assertEqual(len(payload['images']),4)
        self.assertTrue(all(base64.b64decode(v.split(',')[1]).startswith(b'\xff\xd8') for v in payload['images']))
        self.assertEqual([base64.b64decode(v.split(',')[1]) for v in payload['videos']],[media,media])
        self.assertLess(prepare.call_args.args[2],14*1024*1024)
        self.assertIn('需要自行生成缺失动作或短过渡镜头',payload['prompt'])
        self.assertIn('图1：第1段首帧',payload['prompt'])
        self.assertIn('图4：第2段尾部',payload['prompt'])
        self.assertNotIn('不得重拍、重生成或替换原分镜',payload['prompt'])
        submission=self.store.list_documents('ai_video_submissions')[0]
        self.assertEqual(submission['assemblyPolicy'],'dual-ended-bridges-v2')
        pair=submission['bridgeContracts'][0]
        self.assertEqual((pair['startImageIndex'],pair['endImageIndex']),(2,3))
        self.assertEqual(pair['reviewEdges'],['source_to_bridge','bridge_to_next_source'])
        self.assertIn('补段终点=图3（下一镜真实首帧）',payload['prompt'])
        with patch.object(_Handler,'_validate_video_duration',return_value={'passed':True,'actualDuration':2}):
            report=validate(self.handler,b'new bridge film',submission)
        self.assertIsNone(report['continuityReview']['passed'])
        self.assertEqual(report['continuityReview']['status'],'pending')

    def test_missing_boundary_extractor_keeps_video_assembly_available(self):
        with patch.object(_Handler, '_ffmpeg_binary', return_value=None), \
             patch.object(_Handler, '_request_ai_json', side_effect=self.request):
            self.handler._submit_video(self.store, {'model':self.model['id'], 'production_mode':'assemble',
                'prompt':'补过渡', 'source_videos':[{'fileId':s['id']} for s in self.sources]})
        payload=self.calls[-1][1]
        self.assertEqual(payload['images'],[])
        self.assertEqual(len(payload['videos']),2)
        self.assertNotIn('参考图说明',payload['prompt'])
        self.assertIn('本次未附对应边界图',payload['prompt'])
        pair=self.store.list_documents('ai_video_submissions')[0]['bridgeContracts'][0]
        self.assertIsNone(pair['startImageIndex'])
        self.assertIsNone(pair['endImageIndex'])

    def test_unsupported_bridge_stops_before_generation(self):
        with patch.object(_Handler, '_request_ai_json', return_value={}) as request:
            with self.assertRaises(StorageError):
                self.handler._submit_video(self.store, {'model':self.model['id'], 'production_mode':'scene', 'prompt':'完整剧本'})
        self.assertEqual(request.call_count,1)

    def check_capability_error(self, error, expected):
        with patch.object(_Handler, '_request_ai_json', side_effect=error) as request:
            with self.assertRaises(StorageError) as caught:
                self.handler._submit_video(self.store, {'model':self.model['id'], 'production_mode':'assemble',
                    'prompt':'只组合已有镜头', 'source_videos':[{'fileId':s['id']} for s in self.sources]})
        self.assertEqual(request.call_count,1)
        self.assertIn(expected,str(caught.exception))
        self.assertIn('本次未提交组片任务',str(caught.exception))
        self.assertNotIn('尚未启用',str(caught.exception))

    def test_offline_bridge_is_not_reported_as_unsupported(self):
        import httpx
        error=StorageError(502,'无法连接整场制作能力检查服务')
        error.__cause__=httpx.ConnectError('connection refused')
        self.check_capability_error(error,'未连接到 Muse 桥接（127.0.0.1:18631）')

    def test_capability_timeout_does_not_claim_missing_feature(self):
        self.check_capability_error(StorageError(504,'整场制作能力检查超时'),'能力检查超时')

    def test_capability_unauthorized_names_authentication(self):
        self.check_capability_error(StorageError(502,'能力检查失败（HTTP 401）：unauthorized'),'认证未通过')

    def test_old_bridge_missing_capability_route_names_version(self):
        self.check_capability_error(StorageError(502,'能力检查失败（HTTP 404）：Not Found'),'缺少组片能力接口')

    def test_capability_internal_error_preserves_actual_reason(self):
        self.check_capability_error(StorageError(502,'能力检查失败（HTTP 500）：internal failure'),'HTTP 500')

    def test_mode_and_missing_sources_are_not_silently_dropped(self):
        for mode in ['unknown','assemble']:
            with self.assertRaises(StorageError):
                self.handler._submit_video(self.store, {'model':self.model['id'], 'production_mode':mode, 'prompt':'test'})

    def test_native_result_is_never_trimmed_and_duplicate_source_is_rejected(self):
        import hashlib
        submission = {'productionMode':'assemble', 'expectedDuration':0,
                      'sourceVideos':[{'sha256':hashlib.sha256(b'first').hexdigest()}, {'sha256':'other'}]}
        with patch.object(_Handler, '_validate_video_duration', return_value={'passed':False, 'actualDuration':23.4, 'reason':'target mismatch'}):
            report = validate(self.handler,b'new complete film',submission)
            self.assertTrue(report['passed'])
            self.assertFalse(report['trimmed'])
            self.assertEqual(report['reviewStatus'],'needs_review')
            self.assertFalse(validate(self.handler,b'first',submission)['passed'])
            submission['expectedDuration']=60
            self.assertFalse(validate(self.handler,b'new complete film',submission)['passed'])

    def test_native_poll_downloads_original_bytes_and_reuses_saved_result(self):
        import hashlib
        media = (Path(__file__).resolve().parents[1]/'frontend/native-film-qa.mp4').read_bytes()
        class Media(BaseHTTPRequestHandler):
            count = 0
            def log_message(self, *args): pass
            def do_GET(self):
                Media.count += 1
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Length', str(len(media)))
                self.end_headers()
                self.wfile.write(media)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Media)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        cache = hashlib.sha256(f"{self.model['id']}:native-task".encode()).hexdigest()
        self.store.save_document('ai_video_submissions', cache, {'productionMode':'assemble','expectedDuration':10}, expected_revision=None)
        with patch.object(_Handler, '_request_ai_json', return_value={
                'status':'succeeded','url':f'http://127.0.0.1:{server.server_port}/film.mp4'}):
            result = self.handler._poll_video(self.store, 'native-task', self.model['id'])
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['validation']['trimmed'])
            fid = result['video_url'].split('/')[2]
            meta = self.store.find_file(fid)
            self.assertEqual(self.store.read_file_content(meta['bucket'], fid), media)
            self.assertEqual(self.handler._poll_video(self.store, 'native-task', self.model['id']), result)
            self.assertEqual(Media.count, 1)


if __name__ == '__main__':
    unittest.main()
