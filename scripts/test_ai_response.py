import json
import unittest
from unittest.mock import patch
import httpx
from local_storage import _Handler, StorageError
from ai_response import decode


def response(text, content_type='text/event-stream'):
    return httpx.Response(200,text=text,headers={'content-type':content_type})


class ResponseTests(unittest.TestCase):
    def test_normal_json_preserved(self):
        self.assertEqual(decode(response('{"choices":[]}', 'application/json'),'分析'),{'choices':[]})

    def test_actual_keepalive_only_receipt_is_not_json_schema_failure(self):
        with self.assertRaisesRegex(StorageError,'只返回保活') as ctx:
            decode(response(': keepalive\n\n'),'分析')
        self.assertEqual(ctx.exception.error_kind,'transport')
        self.assertTrue(ctx.exception.provider_receipt['keepaliveOnly'])
        self.assertEqual(ctx.exception.provider_receipt['httpStatus'],200)

    def test_openai_stream_joins_split_answer_without_reasoning(self):
        raw=': ping\n\ndata: '+json.dumps({'choices':[{'delta':{'reasoning_content':'do not expose','content':'{"a":'}}]})+'\n\n'
        raw+='data: '+json.dumps({'choices':[{'delta':{'content':'1}'}}]})+'\n\ndata: [DONE]\n\n'
        result=decode(response(raw),'分析')
        self.assertEqual(_Handler._chat_result_text(result),'{"a":1}')

    def test_finish_reason_is_valid_end(self):
        raw='data: {"choices":[{"delta":{"content":"answer"},"finish_reason":"stop"}]}\n\n'
        self.assertEqual(_Handler._chat_result_text(decode(response(raw),'分析')),'answer')

    def test_anthropic_stream(self):
        raw='event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"answer"}}\n\n'
        raw+='event: message_stop\ndata: {"type":"message_stop"}\n\n'
        self.assertEqual(_Handler._chat_result_text(decode(response(raw),'分析')),'answer')

    def test_incomplete_partial_answer_not_used(self):
        with self.assertRaisesRegex(StorageError,'提前断开'):
            decode(response('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'),'分析')

    def test_token_limit_answer_not_used_even_with_done(self):
        with self.assertRaisesRegex(StorageError,'截断'):
            decode(response('data: {"choices":[{"delta":{"content":"partial"},"finish_reason":"length"}]}\n\ndata: [DONE]\n\n'),'分析')

    def test_invalid_stream_and_empty_done_rejected(self):
        for raw in ('data: invalid\n\n','data: [DONE]\n\n',''):
            with self.subTest(raw=raw),self.assertRaises(StorageError):decode(response(raw),'分析')

    def test_html_reports_route_instead_of_model_success(self):
        with self.assertRaisesRegex(StorageError,'返回网页'):
            decode(response('<html>login</html>','text/html'),'分析')

    def test_stream_error_key_redacted(self):
        with self.assertRaises(StorageError) as ctx:
            decode(response('data: {"error":{"message":"bad private-key"}}\n\n'),'分析','private-key')
        self.assertNotIn('private-key',str(ctx.exception))

    def test_handler_accepts_stream_despite_nonstream_request(self):
        with patch('analysis_runtime.request',return_value=response('data: {"choices":[{"delta":{"content":"answer"},"finish_reason":"stop"}]}\n\n')):
            result=_Handler._request_ai_json({},'http://127.0.0.1:1','分析',{'stream':False})
        self.assertEqual(_Handler._chat_result_text(result),'answer')
