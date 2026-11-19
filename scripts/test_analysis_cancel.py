"""Cancellation and late-response regressions; loopback only, no external AI."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from local_storage import _Handler, StorageError
from scripts import test_continuity_planner as fixtures
import verified_assembly
import analysis_runtime


class CancelTests(unittest.TestCase):
    call = fixtures.PlannerTests.call
    request = fixtures.PlannerTests.request
    def setUp(self):
        fixtures.PlannerTests.setUp(self)

    def seed(self, status='running'):
        join = self.plan['joins'][0]
        join['actionAnalysis'] = {'id':'keep-old', 'promptVersion':'old-version'}
        join['analysisAttempt'] = {'id':'old-stuck', 'status':status, 'stage':'analyzing', 'startedAt':'2026-11-04T03:46:32Z'}
        self.plan = verified_assembly.save(self.storage, self.plan)

    def cancel(self, attempt_id=None, **kw):
        if not attempt_id:
            attempt_id = self.call('status')['joins'][0]['analysisAttempt']['id']
        return self.call('cancel_analysis', analysis_attempt_id=attempt_id, **kw)

    def start(self, request):
        self.done = threading.Event(); self.outcome = []
        def work():
            try:
                self.outcome.append(self.call('plan_action', analysis_model=self.text['id']))
            except BaseException as exc:
                self.outcome.append(exc)
            finally:
                self.done.set()
        self.thread = threading.Thread(target=work)
        self.thread.start()

    def test_old_orphan_can_stop_without_runtime_and_preserve_everything(self):
        self.seed(); before = self.call('status')
        with patch.object(_Handler, '_request_ai_json') as request:
            stopped = self.cancel('old-stuck'); again = self.cancel('old-stuck')
        request.assert_not_called()
        self.assertEqual(stopped['revision'], again['revision'])
        join = stopped['joins'][0]
        self.assertEqual(join['actionAnalysis'], before['joins'][0]['actionAnalysis'])
        self.assertEqual(stopped['sources'], before['sources'])
        self.assertEqual(join['candidates'], before['joins'][0]['candidates'])
        self.assertEqual(join.get('attempt'), before['joins'][0].get('attempt'))
        self.assertEqual(join['analysisAttempt']['status'], 'cancelled')
        self.assertEqual(join['analysisAttempt']['providerCancellation'], 'unconfirmed')
        self.assertTrue(join['analysisAttempt']['finishedAt'])

    def test_unknown_receipt_is_stoppable(self):
        self.seed('unknown')
        self.assertEqual(self.cancel()['joins'][0]['analysisAttempt']['status'], 'cancelled')

    def test_stale_cancel_cannot_stop_newer_attempt(self):
        self.seed()
        with self.assertRaisesRegex(StorageError, '已经变化'):
            self.cancel('different-attempt')
        self.assertEqual(self.call('status')['joins'][0]['analysisAttempt']['status'], 'running')

    def test_cancel_requires_owner_and_attempt_identity(self):
        self.seed()
        with self.assertRaises(StorageError):
            self.cancel('old-stuck', project_id='other-owner')
        with self.assertRaisesRegex(StorageError, '缺少'):
            self.call('cancel_analysis')

    def test_completed_attempt_cannot_be_cancelled(self):
        self.seed('succeeded')
        with self.assertRaisesRegex(StorageError, '已结束'):
            self.cancel()

    def test_changed_source_does_not_prevent_stopping_wait(self):
        self.seed()
        meta = self.storage.find_file(self.videos[0])
        (self.storage.file_directory(meta['bucket'], meta['id'])/'content.bin').write_bytes(b'changed')
        self.assertEqual(self.cancel()['joins'][0]['analysisAttempt']['status'], 'cancelled')

    def late_reply(self, review=False, new_run=False):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        calls = []
        def request(*args, **kw):
            calls.append(args[2])
            if (args[2] == '衔接动作终态复核') == review:
                entered.set(); release.wait(10)
            return self.request(*args, **kw)
        with patch.object(_Handler, '_request_ai_json', side_effect=request):
            self.start(request)
            self.assertTrue(entered.wait(10))
            cancelled = self.cancel()
            cancelled_id = cancelled['joins'][0]['analysisAttempt']['id']
            if new_run:
                with patch.object(_Handler, '_request_ai_json', side_effect=self.request):
                    fresh = self.call('plan_action', analysis_model=self.text['id'])
                fresh_id = fresh['joins'][0]['actionAnalysis']['id']
            release.set(); self.assertTrue(self.done.wait(10)); self.thread.join()
        self.assertIsInstance(self.outcome[0], dict, self.outcome)
        latest = self.call('status')
        if new_run:
            self.assertEqual(latest['joins'][0]['actionAnalysis']['id'], fresh_id)
            self.assertNotEqual(latest['joins'][0]['analysisAttempt']['id'], cancelled_id)
        else:
            self.assertEqual(latest['joins'][0]['analysisAttempt']['status'], 'cancelled')
            self.assertEqual(len(calls), 2 if review else 1)
            self.assertEqual(latest.get('actionAnalysis'), cancelled.get('actionAnalysis'))
        self.assertNotIn(cancelled_id, analysis_runtime._active)

    def test_late_planning_response_never_starts_review_or_overwrites(self):
        self.late_reply()

    def test_late_review_response_never_becomes_a_new_analysis(self):
        self.late_reply(review=True)

    def test_new_analysis_can_finish_before_old_reply_without_being_overwritten(self):
        self.late_reply(new_run=True)

    def test_real_pending_http_is_interrupted_promptly(self):
        entered, release = threading.Event(), threading.Event()
        class Delayed(BaseHTTPRequestHandler):
            def do_POST(inner):
                inner.rfile.read(int(inner.headers.get('Content-Length', 0)))
                entered.set(); release.wait(10)
                try:
                    inner.send_response(200); inner.end_headers(); inner.wfile.write(b'{}')
                except OSError:
                    pass
            def log_message(*args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Delayed)
        server.daemon_threads = True
        serving = threading.Thread(target=server.serve_forever, daemon=True); serving.start()
        self.storage.save_document('ai_models', self.text['id'], {**self.text, 'apiUrl':f'http://127.0.0.1:{server.server_port}/v1'}, self.text['revision'])
        try:
            self.start(None); self.assertTrue(entered.wait(10))
            started = time.monotonic(); self.cancel()
            self.assertTrue(self.done.wait(2), 'local request still blocked after cancellation')
            self.assertLess(time.monotonic()-started, 2)
            self.assertIsInstance(self.outcome[0], dict, self.outcome)
            self.assertEqual(self.outcome[0]['joins'][0]['analysisAttempt']['status'], 'cancelled')
            self.assertFalse(release.is_set(), 'must stop without a provider reply')
        finally:
            release.set(); self.thread.join(10); server.shutdown(); server.server_close(); serving.join()

    def test_real_http_stage_has_wall_clock_deadline(self):
        # A provider sending heartbeat bytes must not extend the stage forever.
        self.seed()
        analysis_runtime.bind(self.storage, self.plan, self.plan['joins'][0])
        class Slow(BaseHTTPRequestHandler):
            def do_POST(inner):
                inner.rfile.read(int(inner.headers.get('Content-Length', 0)))
                inner.send_response(200); inner.end_headers()
                for _ in range(30):
                    try:inner.wfile.write(b' '); inner.wfile.flush()
                    except OSError:break
                    time.sleep(.03)
            def log_message(*args):pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Slow); server.daemon_threads=True
        serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        try:
            start=time.monotonic()
            with self.assertRaisesRegex(StorageError, '超时'):
                _Handler._request_ai_json({},f'http://127.0.0.1:{server.server_port}','本地测试',{},timeout=.15)
            self.assertLess(time.monotonic()-start, .8)
        finally:
            analysis_runtime._active.pop('old-stuck',None);analysis_runtime._local.run=None
            server.shutdown();server.server_close();serving.join()
