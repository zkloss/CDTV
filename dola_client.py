# -*- coding: utf-8 -*-
"""
Dola AI (Cici) 逆向客户端通信与流式处理模块
- 支持 Windows DPAPI + AES-256-GCM 解密与 32 字节 Hash 头部过滤
- 官方 stream_call_bot 接口协议 (aid: 495671, bot_id: 7339470689562525703)
- 官方生图与生视频 /chat/completion 接口协议 (Seedance 2.0 / 2.5 / Seedream 4.5 / 5.0)
- 自动扫描 doladuo 各分身及本机 Cici / Chrome 的登录态 Cookie
"""

import asyncio
import base64
import concurrent.futures
import ctypes
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Union
from urllib.parse import urlencode

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DOLA_BASE_URL = "https://www.dola.com"
DOLA_AID = "495671"
DOLA_DEFAULT_BOT_ID = "7339470689562525703"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "text/event-stream, application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Origin": "https://www.dola.com",
    "Referer": "https://www.dola.com/chat/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def run_async(coro):
    """Safely runs an async coroutine even if called from a thread with an active event loop"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


class DATA_BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]


def dpapi_decrypt(encrypted_bytes: bytes) -> bytes:
    blob_in = DATA_BLOB(len(encrypted_bytes), ctypes.create_string_buffer(encrypted_bytes, len(encrypted_bytes)))
    blob_out = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return decrypted
    raise RuntimeError("DPAPI Decrypt failed")


def get_master_key(local_state_path: Path) -> bytes:
    if not local_state_path.exists():
        return b""
    try:
        data = json.loads(local_state_path.read_text("utf-8"))
        encrypted_key = base64.b64decode(data["os_crypt"]["encrypted_key"])
        return dpapi_decrypt(encrypted_key[5:])
    except Exception as e:
        print(f"[MasterKey Error] {e}")
        return b""


def decrypt_cookie_val(encrypted_val: bytes, master_key: bytes) -> str:
    """
    解密 Chromium 124+ AES-GCM 加密 Cookie
    自动剥离前置 32 字节 Hash 头部，防止出现乱码
    """
    if not encrypted_val:
        return ""
    try:
        if encrypted_val.startswith(b"v10") or encrypted_val.startswith(b"v11"):
            nonce = encrypted_val[3:15]
            ciphertext = encrypted_val[15:]
            aesgcm = AESGCM(master_key)
            raw_dec = aesgcm.decrypt(nonce, ciphertext, None)
            if len(raw_dec) > 32:
                return raw_dec[32:].decode("utf-8", errors="ignore")
            return raw_dec.decode("utf-8", errors="ignore")
        else:
            return dpapi_decrypt(encrypted_val).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def parse_cookie_str_to_dict(cookie_str: str) -> Dict[str, str]:
    res = {}
    if not cookie_str:
        return res
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            k, v = item.split("=", 1)
            res[k.strip()] = v.strip()
    return res


def extract_cookies_from_profile(profile_dir: Path) -> Dict[str, str]:
    """从给定的 Chrome / Edge / Cici profile 目录中解密提取所有 Dola / Doubao Cookies"""
    cookie_dict = {}
    local_state_candidates = [
        profile_dir / "Local State",
        profile_dir.parent / "Local State",
    ]
    local_state = next((p for p in local_state_candidates if p.exists()), None)
    master_key = get_master_key(local_state) if local_state else b""

    cookies_db_candidates = [
        profile_dir / "Default" / "Network" / "Cookies",
        profile_dir / "Network" / "Cookies",
        profile_dir / "Default" / "Cookies",
        profile_dir / "Cookies",
    ]
    cookies_db = next((p for p in cookies_db_candidates if p.exists()), None)
    temp_dir = Path(os.environ.get("TEMP", "."))

    if cookies_db and cookies_db.exists():
        temp_db = temp_dir / f"dola_cookie_{uuid.uuid4().hex[:8]}.db"
        try:
            shutil.copyfile(cookies_db, temp_db)
            if temp_db.exists():
                conn = sqlite3.connect(str(temp_db))
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name, value, encrypted_value, host_key FROM cookies "
                    "WHERE host_key LIKE '%dola%' OR host_key LIKE '%cici%' OR host_key LIKE '%doubao%' OR host_key LIKE '%bytedance%'"
                )
                for c_name, c_val, c_enc, c_host in cursor.fetchall():
                    val = c_val or (decrypt_cookie_val(c_enc, master_key) if master_key else "")
                    if val:
                        cookie_dict[c_name] = val
                conn.close()
        except Exception as e:
            print(f"[ExtractCookie] 读取 {profile_dir} 失败: {e}")
        finally:
            temp_db.unlink(missing_ok=True)

    # 兼容已保存的 http_cookies.json 快照
    http_cookies_json = profile_dir / "http_cookies.json"
    if http_cookies_json.exists():
        try:
            cached_data = json.loads(http_cookies_json.read_text(encoding="utf-8"))
            for c in cached_data.get("cookies", []):
                if c.get("name") and c.get("value") and c.get("name") not in cookie_dict:
                    cookie_dict[c["name"]] = c["value"]
        except Exception:
            pass

    return cookie_dict


def scan_local_instances_cookies(doladuo_path: Optional[str] = None) -> List[Dict]:
    """
    扫描 doladuo 各分身及本机目录中的登录态 Cookie 并自动解密
    """
    results = []
    scan_dirs = []
    candidate_roots = []

    # 1. 显式参数与环境变量
    if doladuo_path:
        candidate_roots.append(Path(doladuo_path))
    if os.environ.get("DOLADUO_HOME"):
        candidate_roots.append(Path(os.environ["DOLADUO_HOME"]))
    if os.environ.get("DOLA2API_HOME"):
        candidate_roots.append(Path(os.environ["DOLA2API_HOME"]))

    # 2. 从本地 settings.json 读取自定义配置（若存在）
    try:
        from constants import SETTINGS_FILE
        if SETTINGS_FILE.exists():
            import json as _json
            with open(SETTINGS_FILE, "r", encoding="utf-8") as _f:
                _s = _json.load(_f)
                if _s.get("doladuo_path"):
                    candidate_roots.append(Path(_s["doladuo_path"]))
                if _s.get("dola2api_path"):
                    candidate_roots.append(Path(_s["dola2api_path"]))
    except Exception:
        pass

    # 3. 动态搜索工程祖先目录与当前运行目录（无需硬编码具体盘符与绝对路径）
    search_bases = [Path.cwd()]
    try:
        cur_file = Path(__file__).resolve().parent
        search_bases.append(cur_file)
    except Exception:
        pass

    for b in list(search_bases):
        try:
            for p in b.parents:
                if p not in search_bases:
                    search_bases.append(p)
        except Exception:
            pass

    for base in search_bases:
        candidate_roots.extend([
            base / "doladuo",
            base / "dola2api",
            base / "dola2api" / "dist" / "DolaAPI",
        ])

    candidate_roots.extend([
        Path.home() / "doladuo",
        Path.home() / "dola2api",
    ])

    seen_roots = set()
    seen_names = set()
    for candidate_root in candidate_roots:
        if not candidate_root.exists():
            continue
        try:
            root_key = str(candidate_root.resolve()).lower()
        except Exception:
            root_key = str(candidate_root).lower()
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        
        # 1. 扫描 doladuo instances
        instances_dir = candidate_root / "instances"
        if instances_dir.exists():
            for item in sorted(instances_dir.iterdir(), key=lambda p: p.name.lower()):
                if item.is_dir():
                    ud_candidates = [
                        item / "data" / "User Data",
                        item / "User Data",
                        item,
                    ]
                    for ud_cand in ud_candidates:
                        if ud_cand.exists() and ((ud_cand / "Default" / "Network" / "Cookies").exists() or (ud_cand / "Default" / "Cookies").exists() or (ud_cand / "Local State").exists()):
                            scan_dirs.append((item.name, ud_cand))
                            break

        # 2. 如果存在 accounts.json，直接加载
        acc_file = candidate_root / "accounts.json"
        if acc_file.exists():
            try:
                acc_data = json.loads(acc_file.read_text(encoding="utf-8"))
                for acc in acc_data.get("accounts", []):
                    name = acc.get("name") or "Dola_Account"
                    if acc.get("cookie") and name not in seen_names:
                        results.append({
                            "id": acc.get("id") or str(uuid.uuid4())[:8],
                            "name": name,
                            "cookie": acc.get("cookie"),
                            "summary": acc.get("summary") or name,
                            "status": "active",
                            "source": "dola2api_accounts_json",
                        })
                        seen_names.add(name)
            except Exception:
                pass

    # 3. 扫描本机 Cici 默认安装目录
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        default_ud = Path(local_appdata) / "Cici" / "User Data"
        if default_ud.exists():
            scan_dirs.append(("Default_App", default_ud))

    for name, ud_path in scan_dirs:
        if name in seen_names:
            continue
        cookie_dict = extract_cookies_from_profile(ud_path)
        if cookie_dict:
            cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
            preview_keys = ["sessionid", "ttwid", "passport_auth_status", "uid_tt"]
            preview_parts = []
            for pk in preview_keys:
                if pk in cookie_dict:
                    val_sub = cookie_dict[pk][:12] + "..." if len(cookie_dict[pk]) > 12 else cookie_dict[pk]
                    preview_parts.append(f"{pk}={val_sub}")
            summary = "; ".join(preview_parts) if preview_parts else cookie_str[:60] + "..."

            results.append({
                "id": str(uuid.uuid4())[:8],
                "name": name,
                "cookie": cookie_str,
                "summary": summary,
                "status": "active",
                "source": "doladuo_instance",
            })
            seen_names.add(name)

    def _acc_sort_key(item: dict) -> tuple:
        nm = str(item.get("name") or "")
        m = re.search(r"(\d+)", nm)
        num = int(m.group(1)) if m else 9999
        prefix_pri = 0 if "default" in nm.lower() else (1 if "dola" in nm.lower() else 2)
        return (prefix_pri, num, nm.lower())

    results.sort(key=_acc_sort_key)
    return results


class DolaClient:
    def __init__(self, cookie: str, proxy: Optional[str] = None, timeout: int = 180):
        self.cookie = cookie
        self.proxy = proxy
        self.timeout = timeout
        self.cookie_dict = parse_cookie_str_to_dict(cookie)
        self.client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self.client is None or self.client.is_closed:
            mounts = {}
            if self.proxy:
                mounts["http://"] = httpx.AsyncHTTPTransport(proxy=self.proxy)
                mounts["https://"] = httpx.AsyncHTTPTransport(proxy=self.proxy)

            headers = dict(DEFAULT_HEADERS)
            if self.cookie:
                headers["Cookie"] = self.cookie

            self.client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self.timeout, connect=20.0),
                mounts=mounts if mounts else None,
                follow_redirects=True,
            )
        return self.client

    async def close(self):
        if self.client and not self.client.is_closed:
            try:
                await self.client.aclose()
            except Exception:
                pass

    async def __aenter__(self):
        self._get_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @classmethod
    def check_health_sync(cls, cookie: str, proxy: Optional[str] = None) -> bool:
        async def _run():
            client = cls(cookie, proxy=proxy, timeout=15)
            try:
                return await client.check_health()
            finally:
                await client.close()
        try:
            return run_async(_run())
        except Exception:
            return False

    async def check_health(self) -> bool:
        """检查 Cookie 是否有效并能正常通信"""
        try:
            client = self._get_client()
            params = {
                "aid": DOLA_AID,
                "device_platform": "web",
                "language": "en",
                "region": "US",
                "sys_region": "US",
                "pkg_type": "release_version",
                "version_code": "20800",
                "pc_version": "3.36.11",
                "runtime": "web",
                "runtime_version": "3.5.4",
                "samantha_web": "1",
                "use-olympus-account": "1",
                "web_tab_id": str(uuid.uuid4()),
            }
            if "msToken" in self.cookie_dict:
                params["msToken"] = self.cookie_dict["msToken"]

            inner = {
                "event_type": 1,
                "message": {
                    "conversation_id": "0",
                    "section_id": "0",
                    "local_message_id": str(uuid.uuid4()),
                    "content_type": 1,
                    "content": json.dumps({"text": "1"}, ensure_ascii=False),
                    "reply_id": "",
                    "ext": {
                        "origin": "https://www.dola.com",
                        "stream": "1",
                        "answer_with_suggest": "1",
                        "browser_language": "zh-CN",
                    },
                    "local_conversation_id": "0",
                    "bot_id": DOLA_DEFAULT_BOT_ID,
                    "meta_infos": [],
                }
            }
            encoded = base64.b64encode(json.dumps(inner, ensure_ascii=False).encode("utf-8")).decode("ascii")
            url = f"{DOLA_BASE_URL}/alice/message/stream_call_bot?{urlencode(params)}"
            
            resp = await client.post(url, json={"payload": encoded}, timeout=15.0)
            return resp.status_code == 200 and ("event:json" in resp.text or "event_type" in resp.text)
        except Exception as e:
            print(f"[DolaClient Health Error] {e}")
            return False

    async def get_quota(self) -> Dict:
        """查询 Dola (Cici) 官方生图与生视频 OGF 额度"""
        try:
            client = self._get_client()
            url = f"{DOLA_BASE_URL}/alice/user/get_user_ogf_quota?aid={DOLA_AID}&device_platform=web"
            resp = await client.post(url, json={}, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return {
                    "quota_left": data.get("quota_left", 0),
                    "total_quota": data.get("total_quota", 0)
                }
        except Exception:
            pass
        return {"quota_left": 0, "total_quota": 0}

    def _creation_query_params(self) -> Dict[str, str]:
        device_id = "7686302257139090949"
        region = (self.cookie_dict.get("store-country-code") or "JP").upper()
        params = {
            "aid": "582465",
            "real_aid": "582465",
            "channel": "win",
            "chromium_version": "147.0.7727.149",
            "client_platform": "pc_client",
            "device_id": device_id,
            "device_platform": "web",
            "doubao_device_platform": "desktop",
            "doubao_pc_version": "2.29.10",
            "fp": f"verify_{device_id}",
            "language": "en-US",
            "pc_version": "2.29.10",
            "pkg_type": "release_version",
            "region": region,
            "runtime": "web",
            "runtime_version": "3.37.0",
            "samantha_web": "1",
            "sys_region": region,
            "tea_uuid": device_id,
            "tz_name": "Asia/Shanghai",
            "use-olympus-account": "1",
            "version_code": "20800",
            "web_id": "7686302949128046096",
            "web_platform": "desktop",
            "web_tab_id": str(uuid.uuid4()),
        }
        if self.cookie_dict.get("msToken"):
            params["msToken"] = self.cookie_dict["msToken"]
        return params

    @staticmethod
    def _numeric_id(length: int = 16) -> str:
        return "".join(str(random.randrange(10)) for _ in range(length))

    @staticmethod
    def _normalize_image_model(model: str) -> str:
        value = (model or "").strip().lower().replace("_", "-")
        if "4.5" in value:
            return "Seedream 4.5"
        if value in {"dall-e-2", "dall-e-3", "dola-image"}:
            return "Seedream 5.0 Pro"
        if "5.0" in value or not value:
            return "Seedream 5.0 Pro"
        return "Seedream 4.5"

    @staticmethod
    def _normalize_video_model(model: str) -> str:
        value = (model or "").strip().lower().replace("_", "-")
        if "2.5" in value:
            return "seedance_v2.5"
        if "1.0" in value or "mini" in value:
            return "ic_mini"
        return "seedance_v2.0"

    @staticmethod
    def _normalize_image_style(style: Optional[str]) -> str:
        value = (style or "").strip()
        aliases = {
            "portraits": "skill_image_styles_portrait",
            "portrait": "skill_image_styles_portrait",
            "landscape": "skill_image_styles_landscape",
            "landscapes": "skill_image_styles_landscape",
            "anime": "skill_image_styles_japanese_anime",
            "japanese anime": "skill_image_styles_japanese_anime",
            "3d": "skill_image_styles_3d",
            "cyberpunk": "image_gen_style_cyberpunk",
            "oil painting": "skill_image_styles_oil_painting",
            "watercolor": "skill_image_styles_watercolor",
        }
        lowered = value.lower()
        if lowered in {"", "auto", "none", "vivid", "natural"}:
            return ""
        return aliases.get(lowered, value)

    async def upload_image(self, image_data: Union[str, bytes]) -> Optional[Dict[str, str]]:
        """Upload an image to Dola ByteDance TOS and obtain signed CDN URL & URI."""
        try:
            raw_bytes: bytes = b""
            filename = "reference.png"
            ext = "png"
            if isinstance(image_data, bytes):
                raw_bytes = image_data
            elif isinstance(image_data, str):
                s = image_data.strip()
                if s.startswith("data:image/"):
                    match = re.match(r"^data:image/([a-zA-Z0-9_-]+);base64,(.+)$", s, re.DOTALL)
                    if match:
                        ext = match.group(1).lower()
                        if ext == "jpg":
                            ext = "jpeg"
                        filename = f"reference.{ext}"
                        raw_bytes = base64.b64decode(match.group(2))
                elif s.startswith("http://") or s.startswith("https://"):
                    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as dl_client:
                        resp = await dl_client.get(s)
                        if resp.status_code == 200:
                            raw_bytes = resp.content
                            if ".jpg" in s.lower() or ".jpeg" in s.lower():
                                ext, filename = "jpeg", "reference.jpg"
                elif Path(s).exists():
                    raw_bytes = Path(s).read_bytes()
                    if s.lower().endswith((".jpg", ".jpeg")):
                        ext, filename = "jpeg", "reference.jpg"

            if not raw_bytes:
                return None

            # 校验真实图片魔数以纠正 ext
            if raw_bytes.startswith(b"\x89PNG"):
                ext, filename = "png", "reference.png"
            elif raw_bytes.startswith(b"\xff\xd8"):
                ext, filename = "jpeg", "reference.jpg"

            # 应用本地轻量胶片滤镜算法，破除上游真人面部风控拦截
            try:
                from film_filter import process_image_bytes
                filtered_bytes = process_image_bytes(raw_bytes, grain_intensity=9.5, apply_curve=True)
                if filtered_bytes:
                    raw_bytes = filtered_bytes
                    ext = "jpeg"
                    filename = "reference.jpg"
            except Exception as fe:
                print(f"[FilmFilter Warning] {fe}")

            client = self._get_client()
            params = self._creation_query_params()
            mime_type = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
            files = {"data": (filename, raw_bytes, mime_type)}
            data = {"file_type": ext, "scene": "creation"}
            upload_url = f"{DOLA_BASE_URL}/samantha/pages/upload_image?{urlencode(params)}"
            upload_resp = await client.post(upload_url, files=files, data=data, timeout=20.0)
            if upload_resp.status_code != 200:
                return None
            upload_json = upload_resp.json()
            if upload_json.get("code") != 0 or not upload_json.get("data"):
                return None
            short_uri = upload_json["data"].get("uri")
            if not short_uri:
                return None

            return {
                "uri": short_uri,
                "url": upload_json["data"].get("url") or "",
                "name": filename,
                "format": ext,
            }
        except Exception as e:
            print(f"[UploadImage Error] {e}")
            return None

    def _build_creation_body(
        self,
        prompt: str,
        kind: str,
        model: str,
        ratio: str,
        style: Optional[str] = None,
        duration: int = 10,
        image_attachments: Optional[List[Dict[str, str]]] = None,
    ) -> Dict:
        now_ms = int(time.time() * 1000)
        is_image = kind == "image"
        prefix = "Generate image: " if is_image else "Generated video: "
        reply_format = "Generate image: %s" if is_image else "Generated video: %s"

        if is_image:
            ability_param = {
                "model": self._normalize_image_model(model),
                "input_box_content": {
                    "user_input_content": prompt,
                    "reply_message_format": reply_format,
                },
            }
            if ratio in {"1:1", "2:3", "3:4", "4:3", "9:16", "16:9"}:
                ability_param["ratio"] = ratio
            official_style = self._normalize_image_style(style)
            if official_style:
                ability_param["style"] = official_style
            nested = {"ability_param": ability_param, "ability_type": 1}
            chat_ability = {
                "ability_type": 3,
                "ability_param": json.dumps(nested, ensure_ascii=False, separators=(",", ":")),
            }
            general_task = None
        else:
            ability_param = {
                "model": self._normalize_video_model(model),
                "duration": 5 if int(duration) == 5 else 10,
                "input_box_content": {
                    "user_input_content": prompt,
                    "reply_message_format": reply_format,
                },
            }
            if ratio in {"1:1", "3:4", "4:3", "9:16", "16:9", "21:9"}:
                ability_param["ratio"] = ratio
            chat_ability = {
                "ability_type": 17,
                "ability_param": json.dumps(ability_param, ensure_ascii=False, separators=(",", ":")),
            }
            general_task = {
                "runtime_type": 0,
                "agent_task_param": {},
                "agent_task_param_change": {
                    "runtime_changed": False,
                    "device_changed": False,
                    "sandbox_auth_type_changed": False,
                },
                "project_id": "",
                "need_modify_conversation": False,
            }

        option = {
            "send_message_scene": "",
            "create_time_ms": now_ms,
            "collect_id": "",
            "is_audio": False,
            "answer_with_suggest": False,
            "tts_switch": False,
            "need_deep_think": 0,
            "click_clear_context": False,
            "from_suggest": False,
            "is_regen": False,
            "is_replace": False,
            "is_from_click_option": False,
            "is_from_click_softlink": False,
            "disable_sse_cache": False,
            "select_text_action": "",
            "is_select_text": False,
            "resend_for_regen": False,
            "scene_type": 0,
            "unique_key": str(uuid.uuid4()),
            "start_seq": 0,
            "need_create_conversation": True,
            "conversation_init_option": {"need_ack_conversation": True},
            "regen_query_id": [],
            "edit_query_id": [],
            "regen_instruction": "",
            "no_replace_for_regen": False,
            "message_from": 0,
            "shared_app_name": "",
            "shared_app_id": "",
            "sse_recv_event_options": {"support_chunk_delta": True},
            "support_lazy_fetch_stream": True,
            "is_ai_playground": False,
            "is_old_user": False,
            "recovery_option": {
                "is_recovery": False,
                "req_create_time_sec": now_ms // 1000,
                "append_sse_event_scene": 0,
            },
            "message_storage_type": 0,
            "related_deleted_message_ids": {},
            "connector_info_list": [],
            "model_config": {"model_item_key": "", "model_extra_params": {}},
            "aggregate_params": {
                "mention_skill_list": "[]",
                "mention_plugin_list": "[]",
                "mention_ext": "[{}]",
                "conversation_mode": "",
                "mode_id": "",
                "model_item_key": "",
                "agent_mode": "",
                "reasoning_effort": "",
                "provider_id": "",
            },
        }
        if general_task is not None:
            option["general_task_param"] = general_task

        ext = {
            "answer_with_suggest": "0",
            "collection_id": "",
            "is_finish": "1",
            "conversation_init_option": '{"need_ack_conversation":true}',
            "commerce_credit_config_enable": "0",
        }
        if is_image:
            ext["sub_conv_firstmet_type"] = "1"
        else:
            ext["general_task_param"] = json.dumps(general_task, separators=(",", ":"))

        content_blocks = []
        for img in (image_attachments or []):
            content_blocks.append({
                "block_type": 10052,
                "content": {
                    "attachment_block": {
                        "attachments": [{
                            "type": 1,
                            "identifier": str(uuid.uuid4()),
                            "image": {
                                "name": img.get("name", "reference.jpg"),
                                "uri": img.get("uri", ""),
                                "image_ori": {
                                    "url": img.get("url", ""),
                                    "width": int(img.get("width") or 1024),
                                    "height": int(img.get("height") or 1024),
                                    "format": img.get("format", "jpeg"),
                                    "url_formats": {},
                                },
                            },
                            "parse_state": 0,
                            "review_state": 0,
                        }],
                    },
                    "pc_event_block": "",
                },
                "block_id": str(uuid.uuid4()),
                "parent_id": "",
                "meta_info": [],
                "append_fields": [],
                "is_finish": True,
                "patch_type": 2,
            })

        content_blocks.append({
            "block_type": 10000,
            "content": {
                "text_block": {
                    "text": prefix + prompt,
                    "icon_url": "",
                    "icon_url_dark": "",
                    "summary": "",
                },
                "pc_event_block": "",
            },
            "block_id": str(uuid.uuid4()),
            "parent_id": "",
            "meta_info": [],
            "append_fields": [],
        })

        return {
            "client_meta": {
                "local_conversation_id": "local_" + self._numeric_id(),
                "conversation_id": "",
                "bot_id": DOLA_DEFAULT_BOT_ID,
                "last_section_id": "",
                "last_message_index": None,
                "local_permissions": [
                    {"permission_name": "ACCESS_COARSE_LOCATION", "status": 0},
                    {"permission_name": "ACCESS_FINE_LOCATION", "status": 0},
                    {"permission_name": "ACCESS_BACKGROUND_LOCATION", "status": 0},
                ],
            },
            "messages": [{
                "local_message_id": str(uuid.uuid1()),
                "content_block": content_blocks,
                "message_status": 0,
            }],
            "option": option,
            "chat_ability": chat_ability,
            "user_context": [],
            "ext": ext,
        }

    async def _post_creation_completion(self, body: Dict) -> List[Dict]:
        client = self._get_client()
        url = f"{DOLA_BASE_URL}/chat/completion?{urlencode(self._creation_query_params())}"
        headers = {
            "User-Agent": DEFAULT_HEADERS["User-Agent"] + " SamanthaDola/2.29.10",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Agw-Js-Conv": "str, str",
        }
        events: List[Dict] = []
        async with client.stream("POST", url, json=body, headers=headers, timeout=self.timeout) as resp:
            if resp.status_code != 200:
                raw = (await resp.aread()).decode("utf-8", errors="ignore")
                raise RuntimeError(f"Dola creation upstream HTTP {resp.status_code}: {raw[:500]}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        events.append(obj)
                except json.JSONDecodeError:
                    continue
        return events

    @classmethod
    def _walk_json(cls, value):
        yield value
        if isinstance(value, dict):
            for child in value.values():
                yield from cls._walk_json(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._walk_json(child)
        elif isinstance(value, str):
            try:
                child = json.loads(value)
                if child != value:
                    yield from cls._walk_json(child)
            except (json.JSONDecodeError, TypeError):
                pass

    @classmethod
    def _extract_image_urls(cls, values) -> List[str]:
        images: List[str] = []
        seen_keys = set()
        for node in cls._walk_json(values):
            if not isinstance(node, dict):
                continue
            if "image_ori_raw" not in node and not (node.get("key") and node.get("gen_params")):
                continue
            identity = str(node.get("key") or "")
            selected = ""
            for field in ("image_ori_raw", "image_ori", "image_preview", "image_thumb"):
                item = node.get(field)
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    selected = item["url"]
                    break
            if not selected:
                continue
            identity = identity or selected.split("?", 1)[0]
            if identity not in seen_keys:
                seen_keys.add(identity)
                images.append(selected)
        return images

    @classmethod
    def _extract_video_urls(cls, values) -> List[str]:
        candidates: List[str] = []
        url_pattern = re.compile(r'https?://[^\s"\'<>\\]+')
        for node in cls._walk_json(values):
            if not isinstance(node, str):
                continue
            for match in url_pattern.findall(node):
                url = match.rstrip("),]}")
                lowered = url.lower()
                if any(token in lowered for token in (".mp4", ".mov", ".webm", "video/tos", "mime_type=video_mp4")):
                    if url not in candidates:
                        candidates.append(url)
        best_by_path: Dict[str, str] = {}
        for url in candidates:
            path = url.split("?", 1)[0]
            current = best_by_path.get(path, "")
            if len(url) > len(current):
                best_by_path[path] = url
        return list(best_by_path.values())

    @classmethod
    def _extract_texts_and_errors(cls, values):
        texts: List[str] = []
        errors: List[str] = []

        def append_unique(target: List[str], value) -> None:
            if not isinstance(value, str):
                return
            cleaned = value.strip()
            if cleaned and cleaned not in target:
                target.append(cleaned)

        def append_error(code, message) -> None:
            if code in (None, 0, "0", 200, "200"):
                return
            if not isinstance(message, str):
                return
            cleaned = message.strip()
            if not cleaned or cleaned == str(code):
                return
            append_unique(errors, cleaned)

        for node in cls._walk_json(values):
            if not isinstance(node, dict):
                continue
            text_block = node.get("text_block")
            if isinstance(text_block, dict):
                append_unique(texts, text_block.get("text"))
            append_unique(texts, node.get("brief"))

            append_error(
                node.get("error_code"),
                node.get("error_msg") or node.get("message") or node.get("msg") or node.get("error"),
            )
            code = node.get("code")
            if any(k in node for k in ("message", "msg", "error")):
                append_error(code, node.get("message") or node.get("msg") or node.get("error"))
        return texts, errors

    @staticmethod
    def _video_terminal_failure(texts: List[str], errors: List[str]) -> str:
        combined = [str(item).strip() for item in [*errors, *texts] if str(item).strip()]
        terminal_tokens = (
            "reached the daily limit for video generation",
            "reached the daily free usage limit",
            "daily free usage limit",
            "daily video generation limit",
            "upgrade to the dola plus plan",
            "switch to fast mode",
            "今日视频生成额度已达上限",
            "今日视频额度已用完",
            "something went wrong",
        )
        for item in combined:
            lowered = item.lower()
            if any(token in lowered for token in terminal_tokens):
                return item
        if errors:
            return "; ".join(errors)
        return ""

    @classmethod
    def _friendly_video_failure(cls, texts: List[str], errors: List[str], fallback: str) -> str:
        return cls._video_terminal_failure(texts, errors) or fallback

    @classmethod
    def _extract_conversation_id(cls, values) -> str:
        for node in cls._walk_json(values):
            if isinstance(node, dict):
                value = str(node.get("conversation_id") or "")
                if value.isdigit() and value != "0":
                    return value
        return ""

    @classmethod
    def _extract_video_task_context(cls, values) -> Dict[str, str]:
        context = {"question_id": "", "message_index": "", "section_id": ""}
        for node in cls._walk_json(values):
            if not isinstance(node, dict):
                continue
            if not context["question_id"]:
                value = str(node.get("question_id") or "")
                if value.isdigit() and value != "0":
                    context["question_id"] = value
            if not context["message_index"]:
                value = str(node.get("message_index") or "")
                if value.isdigit():
                    context["message_index"] = value
            if not context["section_id"]:
                value = str(node.get("section_id") or "")
                if value.isdigit() and value != "0":
                    context["section_id"] = value
        return context

    @staticmethod
    def _conversation_messages(conversation) -> List[Dict]:
        if not isinstance(conversation, dict):
            return []
        downlink = conversation.get("downlink_body")
        if not isinstance(downlink, dict):
            return []
        body = downlink.get("pull_singe_chain_downlink_body")
        if not isinstance(body, dict):
            return []
        messages = body.get("messages")
        if not isinstance(messages, list):
            return []
        return [item for item in messages if isinstance(item, dict)]

    @classmethod
    def _select_video_task_messages(
        cls,
        conversation,
        question_id: str = "",
        message_index: str = "",
        section_id: str = "",
        prompt: str = "",
    ) -> List[Dict]:
        messages = cls._conversation_messages(conversation)
        if not messages:
            return []

        resolved_question_id = str(question_id or "")
        if not resolved_question_id:
            if str(message_index or ""):
                for message in messages:
                    if (
                        str(message.get("index_in_conv") or "") == str(message_index)
                        and int(message.get("user_type") or 0) == 1
                    ):
                        resolved_question_id = str(message.get("message_id") or "")
                        break

        if not resolved_question_id and prompt:
            prompt_matches = []
            for message in messages:
                if int(message.get("user_type") or 0) != 1:
                    continue
                raw = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
                if prompt in raw:
                    try:
                        index = int(message.get("index_in_conv") or -1)
                    except (TypeError, ValueError):
                        index = -1
                    prompt_matches.append((index, message))
            if prompt_matches:
                prompt_matches.sort(key=lambda item: item[0], reverse=True)
                resolved_question_id = str(prompt_matches[0][1].get("message_id") or "")

        if not resolved_question_id:
            return []

        selected = []
        for message in messages:
            if section_id:
                message_section = str(message.get("section_id") or "")
                if message_section and message_section != str(section_id):
                    continue
            if (
                str(message.get("message_id") or "") == resolved_question_id
                or str(message.get("bot_reply_message_id") or "") == resolved_question_id
            ):
                selected.append(message)
        return selected

    async def _pull_conversation(self, conversation_id: str) -> Dict:
        client = self._get_client()
        body = {
            "cmd": 3100,
            "uplink_body": {
                "pull_singe_chain_uplink_body": {
                    "conversation_id": str(conversation_id),
                    "anchor_index": 9007199254740991,
                    "conversation_type": 3,
                    "direction": 1,
                    "limit": 20,
                    "ext": {},
                    "filter": {"index_list": []},
                    "evaluate_ab_params": "",
                    "evaluate_common_params": "",
                }
            },
            "sequence_id": str(uuid.uuid4()),
            "channel": 2,
            "version": "1",
        }
        url = f"{DOLA_BASE_URL}/im/chain/single?{urlencode(self._creation_query_params())}"
        headers = {
            "User-Agent": DEFAULT_HEADERS["User-Agent"] + " SamanthaDola/2.29.10",
            "Content-Type": "application/json; encoding=utf-8",
            "Agw-Js-Conv": "str",
        }
        resp = await client.post(url, json=body, headers=headers, timeout=min(max(self.timeout, 30), 60))
        if resp.status_code != 200:
            raise RuntimeError(f"Dola conversation poll HTTP {resp.status_code}")
        return resp.json()

    async def generate_image(
        self,
        prompt: str,
        model: str = "Seedream 4.5",
        ratio: str = "1:1",
        style: Optional[str] = None,
    ) -> Dict:
        """Generate images through the current Dola desktop /chat/completion protocol."""
        official_model = self._normalize_image_model(model)
        body = self._build_creation_body(prompt, "image", official_model, ratio, style=style)
        try:
            events = await self._post_creation_completion(body)
            image_urls = self._extract_image_urls(events)
            texts, errors = self._extract_texts_and_errors(events)
            if image_urls:
                return {
                    "success": True,
                    "model": official_model,
                    "prompt": prompt,
                    "images": [{"url": url, "prompt": prompt} for url in image_urls],
                    "text": "\n".join(texts),
                    "error": "",
                }
            error = "; ".join(errors) or (texts[-1] if texts else "Dola 已响应，但未返回生成图片地址。")
            return {"success": False, "model": official_model, "prompt": prompt, "images": [], "text": "\n".join(texts), "error": error}
        except Exception as exc:
            return {"success": False, "model": official_model, "prompt": prompt, "images": [], "text": "", "error": str(exc)}

    async def generate_video(
        self,
        prompt: str,
        model: str = "seedance_v2.0",
        duration: str = "10",
        ratio: str = "16:9",
        images: Optional[List[str]] = None,
        progress_callback: Optional[callable] = None,
    ) -> Dict:
        """Submit a Dola video task and return only media bound to this request."""
        official_model = self._normalize_video_model(model)
        uploaded_attachments = []
        if images:
            for img in images[:3]:
                if not img:
                    continue
                try:
                    att = await self.upload_image(img)
                    if att:
                        uploaded_attachments.append(att)
                except Exception as upload_err:
                    print(f"[UploadImage Warning] {upload_err}")

        if uploaded_attachments:
            clean_prompt = prompt
            clean_prompt = re.sub(r'\[Image\s*(\d+)\]|<Picture\s*(\d+)>|\[图\s*(\d+)\]', r'参考图\1\2\3', clean_prompt)
            clean_prompt = re.sub(r'【连续性硬约束】[^\n]*\n?', '', clean_prompt)
            clean_prompt = re.sub(r'这些字不要印在画面上[^\n]*\n?', '', clean_prompt)
            clean_prompt = re.sub(r'只以角色定妆图为准[^\n]*\n?', '', clean_prompt)
            clean_prompt = re.sub(r'\n{3,}', '\n\n', clean_prompt).strip()
        else:
            clean_prompt = re.sub(r'一致性引用[：:][^\n]*\n?', '', prompt)
            clean_prompt = re.sub(r'【连续性硬约束】[^\n]*\n?', '', clean_prompt)
            clean_prompt = re.sub(r'<Picture\s*\d+>|\[Image\s*\d+\]|\[图\s*\d+\]', '', clean_prompt)
            clean_prompt = re.sub(r'这些字不要印在画面上[^\n]*\n?', '', clean_prompt)
            clean_prompt = re.sub(r'只以角色定妆图为准[^\n]*\n?', '', clean_prompt)
            clean_prompt = re.sub(r'\n{3,}', '\n\n', clean_prompt).strip() or prompt

        match = re.search(r"\d+", str(duration))
        duration_value = 5 if match and int(match.group()) == 5 else 10
        body = self._build_creation_body(
            clean_prompt, "video", official_model, ratio,
            duration=duration_value, image_attachments=uploaded_attachments,
        )
        try:
            if progress_callback:
                progress_callback(40, "已发送视频生成请求，正在等待 Dola 云端响应")
            events = await self._post_creation_completion(body)
            videos = self._extract_video_urls(events)
            texts, errors = self._extract_texts_and_errors(events)
            conversation_id = self._extract_conversation_id(events)
            task_context = self._extract_video_task_context(events)

            if videos:
                return {
                    "success": True,
                    "model": official_model,
                    "prompt": prompt,
                    "conversation_id": conversation_id,
                    "videos": [{"url": url, "cover_url": "", "prompt": prompt} for url in videos],
                    "text": "\n".join(texts),
                    "error": "",
                }

            terminal_failure = self._video_terminal_failure(texts, errors)
            if terminal_failure:
                return {
                    "success": False,
                    "model": official_model,
                    "prompt": prompt,
                    "conversation_id": conversation_id,
                    "videos": [],
                    "text": "\n".join(texts),
                    "error": terminal_failure,
                }

            if not conversation_id:
                fallback = "Dola 已响应，但未返回视频任务 conversation_id。"
                return {
                    "success": False,
                    "model": official_model,
                    "prompt": prompt,
                    "conversation_id": "",
                    "videos": [],
                    "text": "\n".join(texts),
                    "error": self._friendly_video_failure(texts, errors, fallback),
                }

            deadline = time.monotonic() + max(float(self.timeout), 400.0)
            last_poll_error = ""
            last_texts = list(texts)
            last_errors = list(errors)
            terminal_failure = ""
            matched_task_messages = False
            poll_count = 0
            while time.monotonic() < deadline:
                poll_count += 1
                await asyncio.sleep(min(8.0, max(0.0, deadline - time.monotonic())))
                if progress_callback:
                    sim_progress = min(92, 55 + poll_count * 2)
                    progress_callback(sim_progress, "Dola 云端正在渲染视频，正在轮询获取完成结果...")
                try:
                    conversation = await self._pull_conversation(conversation_id)
                    task_messages = self._select_video_task_messages(
                        conversation,
                        question_id=task_context.get("question_id", ""),
                        message_index=task_context.get("message_index", ""),
                        section_id=task_context.get("section_id", ""),
                        prompt=prompt,
                    )
                    if not task_messages:
                        last_poll_error = "轮询成功，但尚未找到与本次视频任务绑定的消息"
                        continue

                    matched_task_messages = True
                    videos = self._extract_video_urls(task_messages)
                    poll_texts, poll_errors = self._extract_texts_and_errors(task_messages)
                    for item in poll_texts:
                        if item not in last_texts:
                            last_texts.append(item)
                    for item in poll_errors:
                        if item not in last_errors:
                            last_errors.append(item)

                    if videos:
                        return {
                            "success": True,
                            "model": official_model,
                            "prompt": prompt,
                            "conversation_id": conversation_id,
                            "videos": [{"url": url, "cover_url": "", "prompt": prompt} for url in videos],
                            "text": "\n".join(last_texts),
                            "error": "",
                        }

                    terminal_failure = self._video_terminal_failure(poll_texts, poll_errors)
                    if terminal_failure:
                        break
                except Exception as poll_exc:
                    last_poll_error = str(poll_exc)

            if terminal_failure:
                error_message = terminal_failure
            else:
                fallback = f"视频任务已提交（conversation_id={conversation_id}），但等待生成结果超时"
                if not matched_task_messages:
                    fallback += "；未找到与本次任务绑定的消息"
                if last_poll_error:
                    fallback += f"；最后一次轮询状态：{last_poll_error}"
                error_message = self._friendly_video_failure(last_texts, last_errors, fallback)
            return {
                "success": False,
                "model": official_model,
                "prompt": prompt,
                "conversation_id": conversation_id,
                "videos": [],
                "text": "\n".join(last_texts),
                "error": error_message,
            }
        except Exception as exc:
            return {"success": False, "model": official_model, "prompt": prompt, "conversation_id": "", "videos": [], "text": "", "error": str(exc)}
