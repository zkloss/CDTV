import json
import tempfile
import time
import unittest
import urllib.request
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from local_storage import LocalStorageServer, _Handler

class TestPromptOptimize(unittest.TestCase):
    def test_rule_based_optimization(self):
        prompt = (
            "有黄铜口琴（PROP_01）、煤油灯、墨水瓶，窗外安静夜街。右手拿笔，不允许画反。"
            "0-3秒：右手写字，笔尖沙沙声，灯光暖黄稳定。"
            "3-7秒：远处先传来沉闷巨响，声音在前，书桌剧烈震颤，双手一顿，煤油灯倾倒熄灭，墨水瓶震翻，黑墨水溅满手背和稿纸。只拍震颤结果，不拍爆炸。"
            "7-10秒：右手一把抓起口琴摆紧，起身推开木窗。末帧：双手扶窗框，右手握口琴，推开木窗望向夜街。"
        )
        error = "upstream replied with text only: I checked - there's no final video file to attach..."
        optimized = _Handler._rule_based_prompt_optimization(prompt, error)
        
        self.assertNotIn("爆炸", optimized)
        self.assertNotIn("声音在前", optimized)
        self.assertNotIn("笔尖沙沙声", optimized)
        self.assertNotIn("不允许画反", optimized)
        self.assertIn("口琴", optimized)
        self.assertIn("煤油灯", optimized)
        self.assertIn("墨水瓶", optimized)
        self.assertIn("震颤", optimized)

    def test_http_endpoint_fallback_to_rules(self):
        root = Path(tempfile.mkdtemp())
        server = LocalStorageServer(root, port=18092)
        server.start()
        time.sleep(0.3)
        try:
            url = "http://127.0.0.1:18092/ai/optimize-prompt"
            payload = {
                "prompt": "0-3秒：林远右手写字，笔尖沙沙声。3-5秒：不拍爆炸，只拍震颤结果。",
                "error": "upstream replied with text only: failed",
                "title": "第1镜"
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
            data = raw.get("data") or raw
            self.assertTrue(data.get("ok"))
            self.assertIn("optimized", data)
            self.assertNotIn("爆炸", data["optimized"])
            self.assertNotIn("笔尖沙沙声", data["optimized"])
            self.assertEqual(data.get("source"), "rules")
        finally:
            server.stop()

if __name__ == "__main__":
    unittest.main()
