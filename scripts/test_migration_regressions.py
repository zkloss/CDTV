"""Python migration contracts. All providers and user storage are isolated fixtures."""
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from PIL import Image

from local_storage import LocalStorageServer


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, body, content_type="application/json", status=200):
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.server.requests.append((self.path, dict(self.headers),
                                     json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        if self.path.endswith("/voice_design"):
            self.respond(self.server.audio)
        elif self.path.endswith("/cancel"):
            self.server.video = {"id": "task-1", "status": "cancelled"}
            self.respond({"cancelled": True})
        elif self.path.endswith("/tasks"):
            self.respond({"id": "task-1", "status": "queued"})
        elif self.path.endswith("/messages"):
            self.respond({"content": [{"type": "text", "text": "测试回复"}]})
        else:
            self.respond({"choices": [{"message": {"content": "测试回复"}}]})

    def do_GET(self):
        self.server.downloads.append((self.path, self.headers.get("Authorization")))
        if self.path.endswith("/task-1"):
            self.respond(self.server.video)
        elif self.path.endswith(".png"):
            self.respond(self.server.png, "image/png")
        else:
            self.respond(self.server.output_video, "video/mp4")


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        cls.thread = threading.Thread(target=cls.provider.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.provider.server_port}"
        image = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(image, "PNG")
        cls.provider.png = image.getvalue()

    @classmethod
    def tearDownClass(cls):
        cls.provider.shutdown()
        cls.provider.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = LocalStorageServer(self.root / "storage", port=0)
        self.server.start()
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{self.server._server.server_port}", trust_env=False)
        self.provider.requests = []
        self.provider.downloads = []
        self.provider.audio = {"voice_id": "voice-1", "trial_audio": b"ID3test-audio\r\n".hex(),
                               "base_resp": {"status_code": 0}}
        self.provider.video = {"id": "task-1", "status": "running"}
        self.provider.output_video = b"\x00\x00\x00\x18ftypmp42fixture\r\n"

    def tearDown(self):
        self.client.close()
        self.server.stop()
        self.temp.cleanup()

    def model(self, model_type, provider, suffix):
        return self.server.storage.create_document("ai_models", {
            "name": "测试模型", "modelType": model_type, "provider": provider, "modelName": "real-api-model",
            "apiUrl": self.url + suffix, "apiKey": "fixture-private-key", "enabled": True,
        })

    def post(self, path, body):
        return self.client.post(path, json=body).json()

    def test_account_document_envelope_and_revision_conflicts(self):
        path = "/api/storage/data/account/account-1"
        created = self.client.put(path, json={"data": {"id": "account-1", "name": "账号"},
                                             "expectedRevision": 0}).json()
        self.assertEqual(created["data"]["name"], "账号")
        self.assertEqual(created["revision"], 1)
        self.assertEqual(self.client.get("/api/storage/data/account").json()[0]["id"], "account-1")
        self.assertEqual(self.client.get(path).json()["namespace"], "account")
        self.assertEqual(self.client.put(path, json={"data": {}, "expectedRevision": 0}).status_code, 409)
        self.assertEqual(self.client.delete(path + "?expectedRevision=0").status_code, 409)
        self.assertEqual(self.client.delete(path + "?expectedRevision=1").status_code, 204)
        self.assertEqual(self.client.get("/api/storage/data/account").json(), [])

    def test_desktop_account_cache_restores_from_database(self):
        from launcher import DesktopApi
        api = DesktopApi.__new__(DesktopApi)
        api._storage_available = lambda: True
        api._storage_request = self.client.request
        with patch.multiple("launcher", DATA_DIR=self.root, ACCOUNTS_FILE=self.root / "accounts.json",
                            SETTINGS_FILE=self.root / "settings.json"), patch("launcher.scan_local_instances_cookies", return_value=[]):
            api._write_accounts([{"id": "first", "name": "第一"}, {"id": "second", "name": "第二", "accountType": "dola"}])
            (self.root / "accounts.json").unlink()
            self.assertEqual([item["id"] for item in api._read_accounts()], ["first", "second"])
            self.assertEqual([item["accountType"] for item in api._read_accounts()], ["doubao", "dola"])
            api._write_accounts([{"id": "second", "name": "改名", "accountType": "dola"}])
            records = self.client.get("/api/storage/data/account").json()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["data"]["name"], "改名")
            self.assertEqual(records[0]["data"]["accountType"], "dola")

    def test_sqlite_connections_close_after_reads_and_writes(self):
        storage = self.server.storage
        connect = storage._connect
        connections = []
        def tracked():
            connection = connect()
            connections.append(connection)
            return connection
        with patch.object(storage, "_connect", side_effect=tracked):
            storage.create_document("projects", {"name": "测试"})
            storage.list_documents("projects")
        for connection in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_file_upload_preserves_binary_crlf_and_custom_bucket(self):
        content = b"\r\n\x00binary\r\n--not-boundary\r\n"
        result = self.client.post("/file/upload", files={"file": ("test.mp4", content, "video/mp4")},
                                  data={"bucket": "custom"}).json()["data"]
        self.assertEqual(result["bucket"], "custom")
        response = self.client.get(result["url"])
        self.assertEqual(response.content, content)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    def test_asset_upload_persists_fields_and_project_bindings(self):
        result = self.client.post("/asset/upload", files={"file": ("orig.png", self.provider.png, "image/png")},
                                  data={"name": "人物一", "description": "描述", "tags": "主角", "type": "role",
                                        "duration": "5", "boundProjectIds": ["project-1", "project-2"]}).json()["data"]
        saved = self.server.storage.get_document("assets", result["id"])
        self.assertEqual(saved["name"], "人物一")
        self.assertEqual(saved["description"], "描述")
        self.assertEqual(saved["tags"], "主角")
        self.assertEqual(saved["type"], "role")
        self.assertEqual(saved["duration"], "5")
        self.assertEqual(saved["boundProjectIds"], ["project-1", "project-2"])

    def test_batch_upload_saves_every_file(self):
        result = self.client.post("/asset/upload/batch", files=[
            ("files", ("a.png", self.provider.png, "image/png")),
            ("files", ("b.mp3", b"ID3audio\r\n", "audio/mpeg")),
        ], data={"tags": "批量"}).json()["data"]
        self.assertEqual(len(result), 2)
        self.assertEqual({item["name"] for item in result}, {"a", "b"})
        self.assertEqual(len(self.server.storage.list_documents("assets")), 2)
        self.assertEqual({item["type"] for item in result}, {"image", "audio"})

    def test_empty_batch_reports_error(self):
        self.assertNotEqual(self.post("/asset/upload/batch", {})["code"], 200)

    def test_file_head_ranges_and_unsatisfiable_range(self):
        content = b"0123456789"
        file = self.server.storage.save_file("files", content, "video.mp4", "video/mp4")
        url = f"/file/{file['id']}/download"
        head = self.client.head(url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertEqual(head.headers["Content-Length"], "10")
        for header, expected in [("bytes=2-5", b"2345"), ("bytes=7-", b"789"), ("bytes=-3", b"789")]:
            response = self.client.get(url, headers={"Range": header})
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response.content, expected)
        invalid = self.client.get(url, headers={"Range": "bytes=20-"})
        self.assertEqual(invalid.status_code, 416)
        self.assertEqual(invalid.headers["Content-Range"], "bytes */10")

    def test_quota_consumes_and_resets_on_new_day(self):
        first = self.post("/desktop/account-quota/consume", {"accountId": "a", "dailyLimit": 5})["data"]
        self.assertEqual(first["generatedCount"], 1)
        self.assertEqual(first["dailyLimit"], 5)
        self.assertEqual(self.client.get("/desktop/account-quota/status?accountId=a").json()["data"]["generatedCount"], 1)
        self.server.storage.update_document("desktop_account_quota", "a", {"date": "2000-01-01"})
        self.assertEqual(self.client.get("/desktop/account-quota/status?accountId=a").json()["data"]["generatedCount"], 0)
        next_day = self.post("/desktop/account-quota/consume", {"accountId": "a"})["data"]
        self.assertEqual(next_day["generatedCount"], 1)
        self.assertEqual(next_day["dailyLimit"], 5)

    def test_concurrent_quota_consumption_is_not_lost(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.post("/desktop/account-quota/consume", {"accountId": "a"}), range(4)))
        self.assertTrue(all(result["code"] == 200 for result in results))
        self.assertEqual(self.client.get("/desktop/account-quota/status?accountId=a").json()["data"]["generatedCount"], 4)

    def test_shared_prompt_filter_and_limit(self):
        self.server.storage.create_document("prompts", {"title": "私有", "shared": False})
        self.server.storage.create_document("prompts", {"title": "共享", "shared": True})
        shared = self.client.get("/prompt/list?scope=shared").json()["data"]
        self.assertEqual([item["title"] for item in shared], ["共享"])
        self.assertEqual(len(self.client.get("/prompt/list?scope=mine").json()["data"]), 2)
        self.assertEqual(len(self.client.get("/prompt/list?limit=1").json()["data"]), 1)

    def test_minimax_audio_decoded_saved_and_previewed(self):
        self.model("audio", "MiniMax", "/v1/voice_design")
        result = self.post("/ai/audio", {"prompt": "温柔女声", "preview_text": "你好"})
        self.assertEqual(result["code"], 200, result)
        data = result["data"]
        self.assertEqual(data["voice_id"], "voice-1")
        response = self.client.get(data["content"])
        self.assertEqual(response.content, b"ID3test-audio\r\n")
        self.assertEqual(response.headers["Content-Type"], "audio/mpeg")
        self.assertEqual(self.provider.requests[0][2], {"prompt": "温柔女声", "preview_text": "你好"})

    def test_audio_error_does_not_save_fake_file(self):
        self.model("audio", "MiniMax", "/v1/voice_design")
        self.provider.audio = {"base_resp": {"status_code": 1004, "status_msg": "余额不足"}}
        result = self.post("/ai/audio", {"prompt": "女声", "preview_text": "你好"})
        self.assertIn("余额不足", result["message"])
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(list((self.server.storage.root / "files").glob("**/content.bin")), [])

    def test_audio_invalid_hex_and_preview_length(self):
        self.model("audio", "MiniMax", "/v1")
        self.provider.audio = {"trial_audio": "invalid"}
        self.assertIn("十六进制", self.post("/ai/audio", {"prompt": "女声", "preview_text": "你好"})["message"])
        self.provider.requests = []
        self.assertIn("500", self.post("/ai/audio", {"prompt": "女声", "preview_text": "a" * 501})["message"])
        self.assertEqual(self.provider.requests, [])

    def test_seedance_submit_and_running_status(self):
        model = self.model("video", "Seedance", "/api/v3/contents/generations/tasks")
        result = self.post("/ai/video", {"model": model["id"], "content": [{"type": "text", "text": "描述"}],
                                         "duration": 5, "generate_audio": False})
        self.assertEqual(result["data"]["taskId"], "task-1")
        self.assertEqual(self.provider.requests[0][2]["model"], "real-api-model")
        self.assertFalse(self.provider.requests[0][2]["generate_audio"])
        status = self.client.get(f"/ai/video/task-1?model={model['id']}").json()["data"]
        self.assertEqual(status["status"], "running")

    def test_muse_exact_continuity_sends_only_real_tail_frame(self):
        model = self.model("video", "muse2api", "/v1/tasks")
        model = self.server.storage.update_document("ai_models", model["id"], {"modelName": "muse-video"})
        first = "data:image/png;base64," + __import__("base64").b64encode(self.provider.png).decode()
        second_image = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(second_image, "PNG")
        second = "data:image/png;base64," + __import__("base64").b64encode(second_image.getvalue()).decode()
        result = self.post("/ai/video", {
            "model": model["id"],
            "continuity_mode": "exact",
            "content": [
                {"type": "image_url", "image_url": {"url": first}, "role": "first_frame"},
                {"type": "image_url", "image_url": {"url": second}, "role": "reference_image"},
                {"type": "text", "text": "对白：无。\n从真实尾帧继续动作"},
            ],
        })
        self.assertEqual(result["code"], 200, result)
        self.assertEqual(result["data"]["taskId"], "task-1")
        payload = self.provider.requests[0][2]
        self.assertEqual(payload["model"], "muse-video")
        self.assertEqual(payload["images"], [payload["first_frame"]])
        content_images = [item for item in payload["content"] if item.get("type") == "image_url"]
        self.assertEqual(len(content_images), 1)
        self.assertEqual(content_images[0]["role"], "first_frame")
        self.assertIn("第一张图是视频第0秒的精确画面", payload["prompt"])
        self.assertIn("禁止空镜开场", payload["prompt"])

    def test_muse_observer_handoff_keeps_tail_and_child_reference(self):
        import base64
        model = self.model("video", "muse2api", "/v1/tasks")
        self.server.storage.update_document("ai_models", model["id"], {"modelName": "muse-video"})
        images = []
        for color in ["blue", "red", "green"]:
            buf = io.BytesIO()
            Image.new("RGB", (8, 8), color).save(buf, "PNG")
            images.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
        result = self.post("/ai/video", {
            "model": model["id"], "continuity_enabled": True, "continuity_mode": "exact", "first_frame_pin": True,
            "role_handoff": {"mode":"observer_reveal", "observerId":"adult", "observerName":"林枫", "actorId":"boy", "actorName":"赵无极"},
            "content": [{"type":"image_url", "image_url":{"url":v}, "role":"first_frame" if i == 0 else "reference_image"} for i,v in enumerate(images)] + [{"type":"text", "text":"对白：无。\n观察者留在原屋门口，少年跑入。"}],
        })
        self.assertEqual(result["code"], 200, result)
        payload = self.provider.requests[0][2]
        self.assertEqual(len(payload["images"]), 3)
        self.assertEqual(payload["images"][0], payload["first_frame"])
        self.assertEqual(len([i for i in payload["content"] if i.get("type") == "image_url"]), 3)
        self.assertIn("林枫留在上一镜原屋门槛内", payload["prompt"])
        self.assertIn("另外一个人赵无极", payload["prompt"])
        self.assertIn("对面红纸木门只是背景", payload["prompt"])
        self.assertIn("【首帧硬约束·最高优先级】", payload["prompt"])

    def test_muse_inside_pair_keeps_separate_identities_without_reentering(self):
        import base64
        model = self.model("video", "muse2api", "/v1/tasks")
        self.server.storage.update_document("ai_models", model["id"], {"modelName": "muse-video"})
        first="data:image/png;base64,"+base64.b64encode(self.provider.png).decode()
        other=io.BytesIO();Image.new("RGB",(8,8),"red").save(other,"PNG")
        second="data:image/png;base64,"+base64.b64encode(other.getvalue()).decode()
        result=self.post("/ai/video",{"model":model["id"],"continuity_enabled":True,"continuity_mode":"exact",
          "role_handoff":{"mode":"observer_reveal","phase":"inside","observerId":"adult","observerName":"林枫","actorId":"boy","actorName":"赵无极"},
          "content":[{"type":"image_url","image_url":{"url":first},"role":"first_frame"},{"type":"image_url","image_url":{"url":second},"role":"reference_image"},{"type":"text","text":"对白：无。"}]})
        self.assertEqual(result["code"],200,result)
        payload=self.provider.requests[0][2]
        self.assertEqual(len(payload["images"]),2)
        self.assertIn("已经都在同一原屋内",payload["prompt"])
        self.assertIn("不重新跑一次入屋",payload["prompt"])
        self.assertNotIn("新入画少年跑来并进入同一间屋",payload["prompt"])

    def test_scripted_handoff_keeps_references_without_other_project_actions(self):
        import base64
        model = self.model("video", "muse2api", "/v1/tasks")
        self.server.storage.update_document("ai_models", model["id"], {"modelName": "muse-video"})
        images = []
        for color in ["blue", "red", "green"]:
            buf = io.BytesIO();Image.new("RGB", (8, 8), color).save(buf, "PNG")
            images.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
        result = self.post("/ai/video", {
            "model": model["id"], "continuity_enabled": True, "continuity_mode": "exact", "first_frame_pin": True,
            "role_handoff": {"mode":"observer_reveal", "phase":"scripted", "observerId":"old", "observerName":"陈守一", "actorId":"young", "actorName":"赵小满"},
            "content": [{"type":"image_url", "image_url":{"url":v}, "role":"first_frame" if i == 0 else "reference_image"} for i,v in enumerate(images)] + [{"type":"text", "text":"对白：无。\n陈守一端正相框，赵小满抱纸箱进前厅放在柜台上。"}],
        })
        self.assertEqual(result["code"], 200, result)
        payload = self.provider.requests[0][2]
        self.assertEqual(len(payload["images"]), 3)
        for bad in ["村道", "红纸木门", "少年", "门槛内观察", "奔跑"]:
            self.assertNotIn(bad, payload["prompt"])
        self.assertIn("陈守一端正相框", payload["prompt"])
        self.assertIn("【首帧硬约束·最高优先级】", payload["prompt"])

    def test_muse_observer_handoff_rejects_missing_child_image(self):
        import base64
        model = self.model("video", "muse2api", "/v1/tasks")
        self.server.storage.update_document("ai_models", model["id"], {"modelName": "muse-video"})
        image="data:image/png;base64,"+base64.b64encode(self.provider.png).decode()
        result = self.post("/ai/video", {"model":model["id"],
            "role_handoff":{"mode":"observer_reveal", "observerId":"adult", "actorId":"boy"},
            "content":[{"type":"image_url", "image_url":{"url":image}, "role":"first_frame"}, {"type":"text", "text":"对白：无。"}]})
        self.assertNotEqual(result["code"],200,result)
        self.assertIn("新入画少年",result["message"])
        self.assertEqual(self.provider.requests,[])

    def test_muse_scene_cut_keeps_directing_and_character_references(self):
        model = self.model("video", "muse2api", "/v1/tasks")
        self.server.storage.update_document("ai_models", model["id"], {"modelName": "muse-video"})
        scene = "data:image/png;base64," + __import__("base64").b64encode(self.provider.png).decode()
        role_image = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(role_image, "PNG")
        role = "data:image/png;base64," + __import__("base64").b64encode(role_image.getvalue()).decode()
        prompt = (
            "【自动转场安排·开始】\n"
            "【时空与天气连续性】时间：白天；天气：晴到少云。\n"
            "【跨场景入镜·4→5】先立住屋外土道与光照，再让人物入画。\n"
            "【转场边界】仅生成当前这一镜，不拼接前后视频。\n"
            "【自动转场安排·结束】\n\n"
            "【镜2-1】远景·快速推进 荒凉村道上，少年奔跑\n对白：无。"
        )
        result = self.post("/ai/video", {
            "model": model["id"], "continuity_enabled": False, "continuity_mode": "exact",
            "content": [
                {"type": "image_url", "image_url": {"url": scene}, "role": "first_frame"},
                {"type": "image_url", "image_url": {"url": role}, "role": "reference_image"},
                {"type": "text", "text": prompt},
            ],
        })
        self.assertEqual(result["code"], 200, result)
        payload = self.provider.requests[0][2]
        self.assertIn("【时空与天气连续性】", payload["prompt"])
        self.assertIn("【跨场景入镜·4→5】", payload["prompt"])
        self.assertNotIn("【转场边界】", payload["prompt"])
        self.assertNotIn("【自动转场安排", payload["prompt"])
        # The scene anchor is a first frame, not an exact tail continuation:
        # both references must survive so the character stays on model.
        self.assertEqual(len(payload["images"]), 2)
        content_images = [item for item in payload["content"] if item.get("type") == "image_url"]
        self.assertEqual(len(content_images), 2)
        self.assertNotIn("第一张图是视频第0秒的精确画面", payload["prompt"])

    def test_muse_handoff_pin_collapses_to_first_frame(self):
        model = self.model("video", "muse2api", "/v1/tasks")
        self.server.storage.update_document("ai_models", model["id"], {"modelName": "muse-video"})
        first = "data:image/png;base64," + __import__("base64").b64encode(self.provider.png).decode()
        second_image = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(second_image, "PNG")
        second = "data:image/png;base64," + __import__("base64").b64encode(second_image.getvalue()).decode()
        prompt = "【接镜点·视线交接】第0秒复现门口画面，随后推出门外。\n【镜2-1】远景·快速推进 荒凉村道上少年奔跑\n对白：无。"
        result = self.post("/ai/video", {
            "model": model["id"], "continuity_enabled": False, "continuity_mode": "matchCut",
            "first_frame_pin": True,
            "content": [
                {"type": "image_url", "image_url": {"url": first}, "role": "first_frame"},
                {"type": "image_url", "image_url": {"url": second}, "role": "reference_image"},
                {"type": "text", "text": prompt},
            ],
        })
        self.assertEqual(result["code"], 200, result)
        payload = self.provider.requests[0][2]
        self.assertEqual(payload["images"], [payload["first_frame"]])
        content_images = [item for item in payload["content"] if item.get("type") == "image_url"]
        self.assertEqual(len(content_images), 1)
        self.assertEqual(content_images[0]["role"], "first_frame")
        self.assertIn("第一张图是视频第0秒的精确画面", payload["prompt"])

    def test_muse_cancel_calls_provider_and_confirms_terminal_state(self):
        model = self.model("video", "muse2api", "/v1")
        self.server.storage.update_document("ai_models", model["id"], {"modelName": "muse-video"})
        result = self.post("/ai/video/cancel", {"model": model["id"], "taskId": "task-1"})
        self.assertEqual(result["code"], 200, result)
        self.assertTrue(result["data"]["stopped"])
        self.assertEqual(result["data"]["status"], "cancelled")
        self.assertEqual(self.provider.requests[0][0], "/admin/tasks/task-1/cancel")
        self.assertEqual(self.provider.downloads[0][0], "/v1/videos/task-1")

    def test_muse_trims_overlong_result_to_requested_duration(self):
        import cv2
        import numpy as np
        fixture = self.root / 'fifty-seconds.mp4'
        writer = cv2.VideoWriter(str(fixture), cv2.VideoWriter_fourcc(*'mp4v'), 2, (64, 48))
        for index in range(100):
            writer.write(np.full((48, 64, 3), index, dtype=np.uint8))
        writer.release()
        self.provider.output_video = fixture.read_bytes()
        model = self.model('video', 'muse2api', '/v1/tasks')
        self.server.storage.update_document('ai_models', model['id'], {'modelName': 'muse-video'})
        submitted = self.post('/ai/video', {'model': model['id'], 'duration': 10, 'continuity_enabled': False,
            'content': [{'type': 'text', 'text': '画面：少年在屋外奔跑。\n对白：无。'}]})
        self.assertEqual(submitted['code'], 200, submitted)
        sent_prompt = self.provider.requests[0][2]['prompt']
        self.assertNotIn('【单镜交付约束】', sent_prompt)
        self.assertIn('【单镜连续】', sent_prompt)
        self.provider.video = {'id':'task-1','status':'succeeded','video_url':self.url+'/result.mp4'}
        result = self.client.get(f"/ai/video/task-1?model={model['id']}").json()['data']
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['validation']['originalDuration'], 50)
        self.assertEqual(result['validation']['expectedDuration'], 10)
        self.assertTrue(result['validation']['trimmed'])
        self.assertEqual(result['validation']['trimMode'], 'tail')
        self.assertAlmostEqual(result['validation']['actualDuration'], 10, delta=0.5)
        self.assertNotIn('error', result)
        self.assertTrue(result['video_url'].startswith('/file/local_'))
        self.assertEqual(self.client.get(f"/ai/video/task-1?model={model['id']}").json()['data'], result)

    def test_muse_keeps_head_when_overrun_is_small(self):
        import cv2
        import numpy as np
        from local_storage import _Handler
        fixture = self.root / 'thirteen-seconds.mp4'
        writer = cv2.VideoWriter(str(fixture), cv2.VideoWriter_fourcc(*'mp4v'), 2, (64, 48))
        for index in range(26):
            writer.write(np.full((48, 64, 3), index, dtype=np.uint8))
        writer.release()
        trimmed, validation = _Handler._settle_muse_duration(fixture.read_bytes(), 10, False)
        self.assertTrue(validation['passed'], validation)
        self.assertTrue(validation['trimmed'])
        self.assertEqual(validation['trimMode'], 'head')
        self.assertAlmostEqual(validation['actualDuration'], 10, delta=0.5)
        self.assertAlmostEqual(_Handler._validate_video_duration(trimmed, 10)['actualDuration'], 10, delta=0.5)

    def test_muse_exact_continuity_rejects_recap_without_cutting_away_start(self):
        import cv2
        import numpy as np
        from local_storage import _Handler
        fixture = self.root / 'recap.mp4'
        writer = cv2.VideoWriter(str(fixture), cv2.VideoWriter_fourcc(*'mp4v'), 2, (64,48))
        for index in range(100):
            writer.write(np.full((48,64,3),index,dtype=np.uint8))
        writer.release()
        original=fixture.read_bytes()
        result,validation=_Handler._settle_muse_duration(original,10,exact_continuity=True)
        self.assertEqual(result,original)
        self.assertFalse(validation['passed'])
        self.assertFalse(validation['trimmed'])
        self.assertIn('尾帧续接不能截取结尾',validation['reason'])

    def test_video_duration_accepts_ten_seconds_and_rejects_unreadable_media(self):
        import cv2
        import numpy as np
        from local_storage import _Handler
        fixture = self.root / 'ten-seconds.mp4'
        writer = cv2.VideoWriter(str(fixture), cv2.VideoWriter_fourcc(*'mp4v'), 2, (64, 48))
        for index in range(20): writer.write(np.full((48,64,3),index,dtype=np.uint8))
        writer.release()
        self.assertTrue(_Handler._validate_video_duration(fixture.read_bytes(),10)['passed'])
        self.assertFalse(_Handler._validate_video_duration(b'not a video',10)['passed'])

    def test_single_line_partial_recognition_keeps_full_speech_window_for_review(self):
        from dubbing_alignment import match_lines
        data = {"transcription": [{"text": "了", "offsets": {"from": 9750, "to": 10000}}],
                "speechWindows": [{"start": 7.81, "end": 8.19}, {"start": 8.84, "end": 10.05}]}
        result = match_lines({"lines": ["穿……穿越了？！"], "roles": ["林枫"]}, data, 10)
        self.assertEqual(result["rows"][0]["start"], 7.81)
        self.assertEqual(result["rows"][0]["end"], 10)
        self.assertFalse(result["rows"][0]["confirmed"])

    def test_dubbing_without_detected_dialogue_does_not_invent_a_start(self):
        from dubbing_alignment import match_lines, validate_rows
        contract = {'lines':['别让那小子跑了！抓住他赏银十两！'],'roles':['乱军甲']}
        result = match_lines(contract, {}, 10)
        self.assertIsNone(result['rows'][0]['start'])
        self.assertFalse(result['rows'][0]['confirmed'])
        with self.assertRaises(ValueError): validate_rows(contract,result['rows'],10)

    def test_dubbing_keeps_intentional_stammer_pause(self):
        from dubbing_alignment import match_lines, attach_pause_plan
        contract = {'lines':['我……我不是'],'roles':['林枫']}
        def recording(offsets, windows):
            return {'transcription':[{'text':'我我不是','tokens':[{'text':word,'offsets':{'from':start,'to':end}} for word,start,end in offsets]}],'speechWindows':windows}
        target = recording([('我',2000,2200),('我不是',4000,5000)],[{'start':2,'end':2.2},{'start':4,'end':5}])
        source = recording([('我',0,200),('我不是',800,1800)],[{'start':0,'end':.2},{'start':.8,'end':1.8}])
        rows = match_lines(contract,target,6)['rows']
        attach_pause_plan(contract,rows,target,source,[{'start':0,'duration':1.8}])
        self.assertTrue(rows[0]['confirmed'])
        self.assertEqual(len(rows[0]['pieces']),2)
        self.assertEqual(rows[0]['pieces'][1]['start'],4)

    def test_dubbing_pause_split_failure_keeps_confirmed_whole_line(self):
        from dubbing_alignment import match_lines, attach_pause_plan
        contract = {'lines': ['配。最后一炉。'], 'roles': ['陈守一']}
        target = {'transcription': [{'text': '配最后一炉', 'tokens': [
            {'text': '配', 'offsets': {'from': 11000, 'to': 11300}},
            {'text': '最后一炉', 'offsets': {'from': 12300, 'to': 13800}}]}],
            'speechWindows': [{'start': 11, 'end': 11.3}, {'start': 12.3, 'end': 13.8}]}
        rows = match_lines(contract, target, 15)['rows']
        self.assertTrue(rows[0]['confirmed'])
        attach_pause_plan(contract, rows, target, {'transcription': []}, [{'start': 0, 'duration': 2.2}])
        self.assertTrue(rows[0]['confirmed'])
        self.assertEqual(rows[0]['pausePlan'], 'whole-line')
        self.assertNotIn('pieces', rows[0])
        self.assertEqual((rows[0]['start'], rows[0]['end']), (11, 13.8))

    def test_dubbing_optional_pause_plan_does_not_confirm_absent_dialogue(self):
        from dubbing_alignment import match_lines, attach_pause_plan
        contract = {'lines': ['配。最后一炉。'], 'roles': ['陈守一']}
        rows = match_lines(contract, {}, 15)['rows']
        attach_pause_plan(contract, rows, {}, {}, [{'start': 0, 'duration': 2.2}])
        self.assertFalse(rows[0]['confirmed'])
        self.assertIsNone(rows[0]['start'])

    def test_dubbing_optional_source_recognition_failure_keeps_video_alignment(self):
        import threading
        from breeze_bridge import BreezeBridge
        import dubbing_alignment as alignment
        contract = {'explicit': True, 'lines': ['这一次终于说完了'], 'roles': ['甲']}
        data = {'transcription': [{'text': '这一次终于说完了', 'offsets': {'from': 2000, 'to': 4000}}],
                'speechWindows': [{'start': 2, 'end': 4}]}
        bridge = BreezeBridge(self.root / 'bridge', lambda *args: {}, fetch=lambda *args: None,
                              ffmpeg='fixture-ffmpeg', tools='fixture-tools')
        bridge.alignment = alignment
        job = {'id': 'fixture', 'status': 'running', 'cancel': threading.Event()}
        with patch.object(alignment, 'media_duration', return_value=10), patch.object(alignment, 'transcribe',
                    side_effect=[data, ValueError('source recognition unavailable')]):
            bridge._align_run(job, 'fixture', {'videoFileId': 'v', 'audioFileId': 'a', 'contract': contract,
                                               'timeline': [{'start': 0, 'duration': 2}]})
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(job['result']['status'], 'matched')
        self.assertTrue(job['result']['rows'][0]['confirmed'])
        self.assertIn('pausePlanWarning', job['result'])

    def test_dubbing_target_recognition_failure_still_requires_review(self):
        import threading
        from breeze_bridge import BreezeBridge
        import dubbing_alignment as alignment
        bridge = BreezeBridge(self.root / 'bridge', lambda *args: {}, fetch=lambda *args: None,
                              ffmpeg='fixture-ffmpeg', tools='fixture-tools')
        bridge.alignment = alignment
        job = {'id': 'fixture', 'status': 'running', 'cancel': threading.Event()}
        with patch.object(alignment, 'media_duration', return_value=10), patch.object(alignment, 'transcribe',
                    side_effect=ValueError('video recognition unavailable')):
            bridge._align_run(job, 'fixture', {'videoFileId': 'v', 'audioFileId': 'a',
                'contract': {'explicit': True, 'lines': ['这一次终于说完了'], 'roles': ['甲']},
                'timeline': [{'start': 0, 'duration': 2}]})
        self.assertEqual(job['result']['status'], 'needs_review')
        self.assertFalse(job['result']['rows'][0]['confirmed'])

    def test_dubbing_shortens_tts_pauses_before_speeding_the_voice(self):
        import array
        from dubbing_alignment import compact_pauses, speech_placement
        rate = 24000
        # 陈守一“配。最后一炉。”：0.26s 人声 + 1.2s 停顿 + 0.56s 人声。
        take = array.array('h', [3000] * int(rate * .26) + [0] * int(rate * 1.2) + [3000] * int(rate * .56))
        out = compact_pauses(take, rate, 1.19)
        self.assertLessEqual(len(out) / rate, 1.195)
        self.assertGreater(len(out) / rate, .9)
        self.assertGreaterEqual(sum(1 for v in out if v), int(rate * .8))
        speed, length = speech_placement(len(out) / rate, 8.81, 10.0)
        self.assertAlmostEqual(speed, 1.0, places=6)
        self.assertAlmostEqual(length, len(out) / rate, places=6)

    def test_dubbing_never_cuts_the_tail_when_take_overruns_last_window(self):
        from dubbing_alignment import speech_placement
        # 《最后的快门》第2镜：陈守一的新老年音色 2.16 秒，原声只剩 8.81–10.00。
        speed, length = speech_placement(2.16, 8.81, 10.0)
        self.assertAlmostEqual(speed, 2.16 / 1.19, places=3)
        self.assertAlmostEqual(length, 1.19, places=3)
        self.assertLessEqual(speed, 2.0)
        # 后方有停顿就顺延，不无谓加速。
        self.assertEqual(speech_placement(2.0, 3.0, 6.0), (1.0, 2.0))
        # 加速到上限仍放不下时明确报错，绝不静默截断。
        with self.assertRaises(ValueError):
            speech_placement(3.0, 9.0, 10.0)

    def test_dialogue_contract_collapses_repeated_composed_block(self):
        from audio_contract import dialogue_contract
        block = ('对白：赵小满（抱箱进门，普通交谈）：“师父，周主任来过了……说这店下个月归街道。'
                 '那暗房的药水，还配吗？”；陈守一（平静，低声）：“配。最后一炉。”')
        contract = dialogue_contract(f'画面：学徒进门。\n{block}\n【提示词】正文\n{block}\n音频提示词：雨声')
        self.assertEqual(contract['lines'], [
            '师父，周主任来过了……说这店下个月归街道。那暗房的药水，还配吗？', '配。最后一炉。'])
        self.assertEqual(contract['roles'], ['赵小满', '陈守一'])
        repeated = dialogue_contract('对白：甲：“走！”；甲：“走！”')
        self.assertEqual(repeated['lines'], ['走！', '走！'])

    def test_alignment_places_short_line_when_asr_hears_a_homophone(self):
        from dubbing_alignment import match_lines
        contract = {'lines': ['师父，周主任来过了……说这店下个月归街道。那暗房的药水，还配吗？', '配。最后一炉。'],
                    'roles': ['赵小满', '陈守一']}
        tokens = [('师傅', 3430, 4300), ('周主人来过了', 4300, 5830), ('说这店下个月回的豆', 5830, 7280),
                  ('搭暗房的药水还配吗', 7280, 8800), ('配', 8800, 9000), ('最后一顿', 9000, 10050)]
        data = {'transcription': [{'text': ''.join(w for w, _, _ in tokens),
                                   'tokens': [{'text': word, 'offsets': {'from': start, 'to': end}}
                                              for word, start, end in tokens]}],
                'speechWindows': [{'start': 3.43, 'end': 10.05}]}
        result = match_lines(contract, data, 10.05)
        self.assertEqual(result['status'], 'matched')
        self.assertTrue(all(row['confirmed'] for row in result['rows']))
        self.assertEqual([row['method'] for row in result['rows']], ['order', 'order'])
        self.assertAlmostEqual(result['rows'][1]['start'], 8.8, delta=.2)
        self.assertIn('按分镜台词顺序', result['recognitionNote'])
        self.assertFalse(match_lines({'lines': ['穿……穿越了？！'], 'roles': ['林枫']},
                                     {'transcription': [{'text': '了', 'offsets': {'from': 9750, 'to': 10000}}],
                                      'speechWindows': [{'start': 7.81, 'end': 8.19}]}, 10)['rows'][0]['confirmed'])

    def test_transcript_review_accepts_minor_homophone_noise_but_flags_missing_line(self):
        from audio_contract import compare_transcript
        contract = {'explicit': True,
                    'lines': ['师父，周主任来过了……说这店下个月归街道。那暗房的药水，还配吗？', '配。最后一炉。'],
                    'text': '师父，周主任来过了……说这店下个月归街道。那暗房的药水，还配吗？\n配。最后一炉。'}
        noisy = compare_transcript(contract, '师父 周主人来过来了 说这店下个月鬼都斗 搭暗房的药水 还配吗 配 最后一路')
        self.assertEqual(noisy['status'], 'close_text')
        self.assertGreaterEqual(noisy['similarity'], .7)
        missing = compare_transcript(contract, '师父 周主任来过了 说这店下个月归街道')
        self.assertEqual(missing['status'], 'needs_review')
        self.assertEqual(missing['lineCoverage'][1], 0)

    def test_seedance_completion_downloads_and_cache_survives_storage_reload(self):
        model = self.model("video", "Seedance", "/api/v3/contents/generations/tasks")
        self.provider.video = {"id": "task-1", "status": "succeeded",
                               "content": {"video_url": self.url + "/video.mp4", "last_frame_url": self.url + "/frame.png"}}
        path = f"/ai/video/task-1?model={model['id']}"
        result = self.client.get(path).json()["data"]
        self.assertTrue(result["video_url"].startswith("/file/local_"))
        self.assertTrue(result["last_frame_url"].startswith("/file/local_"))
        self.assertEqual(result["content"]["video_url"], result["video_url"])
        self.assertEqual(self.client.get(result["last_frame_url"]).content, self.provider.png)
        self.assertIsNone(self.provider.downloads[1][1])
        self.assertIsNone(self.provider.downloads[2][1])
        from local_storage import LocalStorage
        self.server.storage = LocalStorage(self.server.storage.root)
        self.server._server.RequestHandlerClass.storage = self.server.storage
        self.assertEqual(self.client.get(path).json()["data"], result)
        self.assertEqual(len(self.provider.downloads), 3)

    def test_terminal_video_error_returns_task_not_transport_failure(self):
        model = self.model("video", "Seedance", "/api/v3/contents/generations/tasks")
        for status in ["failed", "expired"]:
            self.provider.video = {"status": status, "error": {"message": "任务已失败"}}
            result = self.client.get(f"/ai/video/task-1?model={model['id']}").json()
            self.assertEqual(result["code"], 200)
            self.assertEqual(result["data"]["status"], status)

    def test_chat_forwards_selected_model_without_streaming(self):
        model = self.model("text", "DeepSeek", "")
        result = self.post("/ai/chat", {"model": model["id"], "messages": [{"role": "user", "content": "你好"}], "stream": True})
        self.assertEqual(result["data"]["choices"][0]["message"]["content"], "测试回复")
        request = self.provider.requests[0]
        self.assertEqual(request[0], "/v1/chat/completions")
        self.assertEqual(request[2]["model"], "real-api-model")
        self.assertFalse(request[2]["stream"])

    def test_claude_message_endpoint_and_headers(self):
        model = self.model("text", "teamorouter-claude", "/v1/messages")
        result = self.post("/ai/chat", {"model": model["id"], "messages": [{"role": "user", "content": "你好"}]})
        self.assertEqual(result["data"]["content"][0]["text"], "测试回复")
        request = self.provider.requests[0]
        self.assertEqual(request[0], "/v1/messages")
        self.assertEqual(request[1]["anthropic-version"], "2023-06-01")
        self.assertEqual(request[1]["x-api-key"], "fixture-private-key")
        self.assertEqual(request[2]["max_tokens"], 4096)

    def test_manual_doubao_account_does_not_use_undefined_account(self):
        from launcher import DesktopApi
        api = DesktopApi.__new__(DesktopApi)
        api._lock = threading.Lock()
        api._tasks, api._workers = {}, {}
        api.get_settings = lambda: {"defaultAccountId": "a"}
        api._find_account = lambda _: {"id": "a", "name": "手动账号"}
        api._acquire_account_usage = Mock()
        worker = Mock(visible=True, start_error=None)
        worker.ready = threading.Event()
        worker.ready.set()
        api._ensure_worker = Mock(return_value=worker)
        file = self.root / "reference.png"
        file.write_bytes(self.provider.png)
        with patch("launcher.DATA_DIR", self.root), patch("launcher.GENERATION_TASKS_FILE", self.root / "generation_tasks.json"):
            result = api.start_generation({"attachments": [{"path": str(file), "type": "image"}],
                                           "prompt": "测试", "accountId": "a", "autoAssignAccount": False})
        self.assertEqual(api._tasks[result["taskId"]]["accountName"], "手动账号")
        worker.submit_generation.assert_called_once()

    def test_text_bridge_timeout_allows_provider_processing(self):
        from launcher import DesktopApi
        api = DesktopApi.__new__(DesktopApi)
        api._storage_request = Mock(return_value=httpx.Response(200, json={"code": 200, "data": {}}))
        api.backend_request("POST", "/ai/chat", body={"messages": []})
        self.assertEqual(api._storage_request.call_args.kwargs["timeout"], 330)

    def test_storage_settings_report_restart_without_moving_user_data(self):
        from launcher import DesktopApi
        api = DesktopApi.__new__(DesktopApi)
        old_root = self.server.storage.root
        api._local_storage_server = self.server
        api.get_settings = lambda: {"defaultAccountId": "", "storageDir": str(old_root),
                                   "dailyVideoQuota": 3}
        api._write_settings = Mock()
        api._push_cloud_account_state = Mock()
        self.assertFalse(api.save_settings({"storageDir": str(old_root)})["storageRestartRequired"])
        new_root = self.root / "new-storage"
        self.assertTrue(api.save_settings({"storageDir": str(new_root)})["storageRestartRequired"])
        self.assertEqual(api._local_storage_server.storage.root, old_root)
        self.assertFalse((new_root / "storage.db").exists())


if __name__ == "__main__":
    unittest.main()
