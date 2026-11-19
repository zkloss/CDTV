"""纯 Python 本地存储服务，替代 comic-drama-storage（Java/JAR）。

数据与文件存储使用标准库（sqlite3 + http.server）；AI 转发使用项目已有的 httpx 和 Pillow：
- /api/storage/health                     健康检查
- /project/**  /chapter/**                项目与章节
- /asset/**                               素材库（含上传）
- /video-project/**                       视频创作任务
- /file/**                                文件桶（上传/下载/信息）
- /api/admin/models/**                    模型管理
- /api/storage/data/**                    通用文档与 OriginalDoubao 账号持久化
- /ai/image                               图片生成与参考图编辑，结果保存到本地文件桶
- /ai/audio /ai/chat /ai/video/**          MiniMax 音色试听、文本转发、Seedance 任务与成片保存
- /prompt/**                              提示词库
- /desktop/account-quota/**               每日额度

兼容接口响应格式：{"code":200,"message":"success","data":...}；通用文档接口返回原始 StoredDocument。
数据保存在 storageDir 下的 storage.db（SQLite）；文件保存在 files/<bucket>/<id>/content.bin。
"""
from __future__ import annotations

import logging
logger = logging.getLogger('local_storage')

import ast
import base64
import binascii
import hashlib
import io
import json
import mimetypes
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from PIL import Image

SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# Muse 只按固定档位出片：5 秒档与 10 秒档。实测 15 秒请求会退回 10 秒，
# 10 秒请求偶尔整段复述成 60 秒。这里是唯一事实源，前后端都按它判定时长。
MUSE_VIDEO_DURATION_TIERS = (5.0, 10.0)
DOCUMENT_TABLES = (
    "projects",
    "chapters",
    "assets",
    "video_projects",
    "ai_models",
    "prompts",
    "desktop_account_quota",
    "desktop_account_state",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_segment(value: str, name: str) -> str:
    if not value or not SAFE_SEGMENT.match(value):
        raise StorageError(400, f"{name} 只能包含字母、数字、下划线和短横线")
    return value


def parse_chinese_number_py(num_str: str) -> int:
    if not num_str:
        return 0
    num_str = str(num_str).strip()
    if num_str.isdigit():
        return int(num_str)
    cn_map = {
        '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '百': 100, '千': 1000, '万': 10000,
    }
    if num_str == '十':
        return 10
    total = 0
    r = 0
    for char in num_str:
        val = cn_map.get(char)
        if val is None:
            continue
        if val >= 10:
            if r == 0:
                r = 1
            total += r * val
            r = 0
        else:
            r = val
    total += r
    return total


def is_prologue_title_py(title: str) -> bool:
    t = str(title or '').strip().lower()
    return bool(re.search(r'旁白|序幕|序章|前言|楔子|开篇|开局|导言|00|第0集|第00集|prologue|intro', t))


def normalize_chapter_title_py(title: str) -> str:
    raw = str(title or '').strip()
    if not raw:
        return '第1集'
    if is_prologue_title_py(raw):
        if raw in ['开局旁白 / 序幕', '开局旁白', '序幕', '序章', '楔子', '第0集', '第00集', '旁白']:
            return '开局旁白 / 序幕'
        return raw
    match = re.search(r'第\s*([0-9零一二两三四五六七八九十百千万]+)\s*([集章节回话幕])', raw)
    if match:
        num = parse_chinese_number_py(match.group(1))
        unit = match.group(2)
        if num == 0:
            return '开局旁白 / 序幕'
        prefix = f'第{num}{unit}'
        suffix = raw[match.end():].strip()
        suffix = re.sub(r'^[\s\-:：·—]+', '', suffix).strip()
        return f'{prefix} {suffix}'.strip() if suffix else prefix
    num_match = re.match(r'^([0-9]+)$', raw)
    if num_match:
        num = int(num_match.group(1))
        return '开局旁白 / 序幕' if num == 0 else f'第{num}集'
    return raw


def get_chapter_sort_key_py(item: dict) -> tuple:
    title = str(item.get('title') or '').strip()
    if is_prologue_title_py(title):
        return (0, 0, str(item.get('createdAt') or item.get('created_at') or ''))
    match = re.search(r'第\s*([0-9零一二两三四五六七八九十百千万]+)\s*[集章节回话幕]', title)
    if match:
        num = parse_chinese_number_py(match.group(1))
        return (1, num, str(item.get('createdAt') or item.get('created_at') or ''))
    num_match = re.search(r'(\d+)', title)
    if num_match:
        return (1, int(num_match.group(1)), str(item.get('createdAt') or item.get('created_at') or ''))
    return (2, 999999, str(item.get('createdAt') or item.get('created_at') or ''))


def sort_and_normalize_chapters_py(storage: Any, project_id: str, items: list) -> list:
    normalized_items = []
    for item in items:
        old_title = item.get('title') or ''
        new_title = normalize_chapter_title_py(old_title)
        if new_title != old_title and item.get('id'):
            item['title'] = new_title
            try:
                storage.update_document('chapters', item['id'], {'title': new_title})
            except Exception:
                pass
        else:
            item['title'] = new_title
        normalized_items.append(item)
    normalized_items.sort(key=get_chapter_sort_key_py)
    return normalized_items


class StorageError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class LocalStorage:
    """SQLite 文档存储 + 文件桶，接口对齐 comic-drama-storage。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "storage.db"
        self._lock = threading.RLock()
        self._init_db()

    # ---------- 数据库 ----------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init_db(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_document (
                    namespace TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    PRIMARY KEY (namespace, object_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_file (
                    bucket TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (bucket, object_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_storage_file_object_id ON storage_file(object_id)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
        self._seed_default_models()

    def _seed_default_models(self) -> None:
        """初始化内置模型配置（仅在全新无模型且未初始化过的数据库中注入一次）。
        如果已初始化过，或者数据库中已有任何模型，绝对不自动恢复已被用户删除的模型。
        """
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM storage_meta WHERE key = 'default_models_seeded'"
            ).fetchone()
            if row is not None and str(row[0]).strip() == "1":
                return

        existing = self.list_documents("ai_models")
        if len(existing) > 0:
            with self._lock, self._connection() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO storage_meta (key, value) VALUES ('default_models_seeded', '1')"
                )
            return

        from model_seeds import DEFAULT_MODELS
        for model in DEFAULT_MODELS:
            self.create_document("ai_models", dict(model))

        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO storage_meta (key, value) VALUES ('default_models_seeded', '1')"
            )

    @contextmanager
    def _connection(self):
        with closing(self._connect()) as connection, connection:
            yield connection

    # ---------- 文档 ----------

    def list_documents(self, namespace: str) -> list[dict[str, Any]]:
        _safe_segment(namespace, "namespace")
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT object_id, revision, data_json FROM storage_document "
                "WHERE namespace=? ORDER BY updated_at DESC",
                (namespace,),
            ).fetchall()
        return [self._document_payload(row) for row in rows]

    def get_document(self, namespace: str, object_id: str) -> dict[str, Any]:
        _safe_segment(namespace, "namespace")
        _safe_segment(object_id, "id")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT object_id, revision, data_json FROM storage_document "
                "WHERE namespace=? AND object_id=?",
                (namespace, object_id),
            ).fetchone()
        if row is None:
            raise StorageError(404, "数据不存在")
        return self._document_payload(row)

    def create_document(self, namespace: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data or {})
        requested = str(payload.get("id") or "").strip()
        object_id = requested if SAFE_SEGMENT.match(requested) else uuid.uuid4().hex
        now = _now_iso()
        payload["id"] = object_id
        payload.setdefault("createTime", now)
        payload.setdefault("updateTime", now)
        return self.save_document(namespace, object_id, payload, expected_revision=0)

    def update_document(self, namespace: str, object_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_document(namespace, object_id)
        merged = {key: value for key, value in current.items() if key not in {"revision"}}
        if isinstance(patch, dict):
            merged.update(patch)
        merged["id"] = object_id
        merged["updateTime"] = _now_iso()
        return self.save_document(namespace, object_id, merged, expected_revision=current.get("revision"))

    def delete_document(self, namespace: str, object_id: str, expected_revision: int | None = None) -> None:
        _safe_segment(namespace, "namespace")
        _safe_segment(object_id, "id")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT revision FROM storage_document WHERE namespace=? AND object_id=?", (namespace, object_id)
            ).fetchone()
            current_revision = int(row["revision"]) if row else 0
            if expected_revision is not None and expected_revision != current_revision:
                raise StorageError(409, f"数据版本冲突，当前版本为 {current_revision}")
            connection.execute(
                "DELETE FROM storage_document WHERE namespace=? AND object_id=?",
                (namespace, object_id),
            )

    def save_document(
        self, namespace: str, object_id: str, data: dict[str, Any], expected_revision: int | None
    ) -> dict[str, Any]:
        _safe_segment(namespace, "namespace")
        _safe_segment(object_id, "id")
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        content_hash = _sha256_bytes(payload.encode("utf-8"))
        now = _now_iso()
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT revision FROM storage_document WHERE namespace=? AND object_id=?",
                (namespace, object_id),
            ).fetchone()
            current_revision = int(row["revision"]) if row else 0
            if expected_revision is not None and expected_revision != current_revision:
                raise StorageError(409, f"数据版本冲突，当前版本为 {current_revision}")
            revision = current_revision + 1
            connection.execute(
                """
                INSERT INTO storage_document(namespace, object_id, revision, updated_at, content_hash, data_json)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(namespace, object_id) DO UPDATE SET
                  revision=excluded.revision, updated_at=excluded.updated_at,
                  content_hash=excluded.content_hash, data_json=excluded.data_json
                """,
                (namespace, object_id, revision, now, content_hash, payload),
            )
        result = dict(data)
        result["id"] = object_id
        result["revision"] = revision
        return result

    @staticmethod
    def _document_payload(row: sqlite3.Row) -> dict[str, Any]:
        try:
            data = json.loads(row["data_json"])
        except (TypeError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data["id"] = row["object_id"]
        data["revision"] = int(row["revision"])
        return data

    # ---------- 文件 ----------

    def file_directory(self, bucket: str, object_id: str) -> Path:
        _safe_segment(bucket, "bucket")
        _safe_segment(object_id, "id")
        return self.root / "files" / bucket / object_id

    def save_file(
        self,
        bucket: str,
        content: bytes,
        filename: str,
        content_type: str,
        requested_id: str | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        _safe_segment(bucket, "bucket")
        if not content:
            raise StorageError(400, "文件内容不能为空")
        object_id = requested_id if (requested_id and requested_id.strip()) else "local_" + uuid.uuid4().hex
        _safe_segment(object_id, "id")
        content_hash = _sha256_bytes(content)
        if expected_sha256 and expected_sha256.strip() and content_hash.lower() != expected_sha256.strip().lower():
            raise StorageError(400, "文件哈希校验失败")
        directory = self.file_directory(bucket, object_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "content.bin").write_bytes(content)
        safe_name = self._safe_filename(filename)
        content_type = content_type or "application/octet-stream"
        now = _now_iso()
        meta = {
            "bucket": bucket,
            "id": object_id,
            "name": safe_name,
            "contentType": content_type,
            "size": len(content),
            "sha256": content_hash,
            "updatedAt": now,
        }
        (directory / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT revision FROM storage_file WHERE bucket=? AND object_id=?",
                (bucket, object_id),
            ).fetchone()
            revision = (int(row["revision"]) if row else 0) + 1
            connection.execute(
                """
                INSERT INTO storage_file(bucket, object_id, file_name, content_type, file_size, sha256, revision, updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(bucket, object_id) DO UPDATE SET
                  file_name=excluded.file_name, content_type=excluded.content_type,
                  file_size=excluded.file_size, sha256=excluded.sha256,
                  revision=excluded.revision, updated_at=excluded.updated_at
                """,
                (bucket, object_id, safe_name, content_type, len(content), content_hash, revision, now),
            )
        meta["revision"] = revision
        return meta

    def find_file(self, object_id: str) -> dict[str, Any]:
        _safe_segment(object_id, "id")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT bucket FROM storage_file WHERE object_id=? ORDER BY updated_at DESC LIMIT 1",
                (object_id,),
            ).fetchone()
        if row is None:
            raise StorageError(404, "文件不存在")
        return self.read_file_meta(row["bucket"], object_id)

    def read_file_meta(self, bucket: str, object_id: str) -> dict[str, Any]:
        directory = self.file_directory(bucket, object_id)
        meta_path = directory / "meta.json"
        if not meta_path.is_file():
            raise StorageError(404, "文件不存在")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StorageError(500, "读取文件元数据失败") from exc
        return meta

    def read_file_content(self, bucket: str, object_id: str) -> bytes:
        self.read_file_meta(bucket, object_id)
        content = self.file_directory(bucket, object_id) / "content.bin"
        if not content.is_file():
            raise StorageError(404, "文件内容不存在")
        return content.read_bytes()

    def delete_file(self, bucket: str, object_id: str) -> None:
        directory = self.file_directory(bucket, object_id)
        for name in ("content.bin", "meta.json"):
            try:
                (directory / name).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass
        with self._lock, self._connection() as connection:
            connection.execute(
                "DELETE FROM storage_file WHERE bucket=? AND object_id=?",
                (bucket, object_id),
            )

    @staticmethod
    def _safe_filename(value: str | None) -> str:
        filename = Path(str(value or "file")).name.strip() or "file"
        return re.sub(r"[\r\n]", "_", filename)


class _Handler(BaseHTTPRequestHandler):
    server_version = "LocalStorage/1.0"
    storage: LocalStorage

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 屏蔽默认日志
        return

    # ---------- 工具 ----------

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data: Any) -> None:
        self._send_json({"code": 200, "message": "success", "data": data})

    def _fail(self, message: str, status: int = 200) -> None:
        self._send_json({"code": 500, "message": message, "data": None}, status)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _read_json(self) -> dict[str, Any]:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise StorageError(400, "JSON 数据格式不正确") from exc
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], list[tuple[str, str, bytes]]]:
        """解析 multipart/form-data，返回 (普通字段, [(字段名, 文件名, 内容)])。"""
        fields: dict[str, str] = {}
        files: list[tuple[str, str, bytes]] = []
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        if not message.is_multipart():
            return fields, files
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if not field_name:
                continue
            content = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename is not None:
                files.append((field_name, filename, content))
            else:
                value = content.decode("utf-8", "replace")
                # HTTP clients encode list values as repeated form fields.
                fields[field_name] = fields[field_name] + "\n" + value if field_name in fields else value
        return fields, files

    def _namespace(self, path: str, prefix: str) -> tuple[str, str]:
        rest = path[len(prefix):].strip("/")
        return prefix, unquote(rest)

    # ---------- HTTP 路由 ----------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            self._route(method, path, query)
        except StorageError as exc:
            self._fail(exc.message, exc.status if exc.status >= 400 else 200)
        except Exception as exc:  # noqa: BLE001 - 兜底，避免线程崩溃
            self._fail(f"存储服务内部错误：{exc}")

    def _route(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        storage = self.storage

        if path == "/local-file" and method in {"GET", "HEAD"}:
            local_path = (query.get("path") or [""])[0]
            if local_path:
                from pathlib import Path
                p = Path(local_path)
                if p.is_file():
                    self._serve_local_disk_file(p, method == "GET")
                    return
            raise StorageError(404, "文件不存在")
        if (path in {"/api/huashu/video", "/huashu/video"}) and method in {"GET", "HEAD"}:
            project_id = (query.get("projectId") or [""])[0]
            file_name = (query.get("file") or [""])[0]
            if project_id and file_name:
                p = storage.root / "huashu_projects" / project_id / "out" / file_name
                if p.is_file():
                    self._serve_local_disk_file(p, method == "GET")
                    return
            raise StorageError(404, "宣传片视频文件不存在")
        if path == "/api/storage/health":
            self._ok({"status": "ok"})
            return
        if path == "/api/storage/config":
            self._ok({"root": str(storage.root)})
            return

        # Desktop account persistence uses the original raw StoredDocument envelope.
        document_route = re.fullmatch(r"/api/storage/data/([^/]+)(?:/([^/]+))?", path)
        if document_route:
            namespace, object_id = (unquote(value) if value else None for value in document_route.groups())
            def envelope(document):
                return {"namespace": namespace, "id": document["id"], "revision": document["revision"],
                        "updatedAt": document.get("updateTime"),
                        "data": {key: value for key, value in document.items() if key != "revision"}}
            if method == "GET":
                self._send_json(envelope(storage.get_document(namespace, object_id)) if object_id else
                                [envelope(item) for item in storage.list_documents(namespace)])
                return
            if method == "PUT" and object_id:
                body = self._read_json()
                if not isinstance(body.get("data"), dict):
                    raise StorageError(400, "data 必须是 JSON 对象")
                self._send_json(envelope(storage.save_document(namespace, object_id, body["data"],
                                                               body.get("expectedRevision"))))
                return
            if method == "DELETE" and object_id:
                revision = (query.get("expectedRevision") or [None])[0]
                try:
                    revision = int(revision) if revision is not None else None
                except ValueError as exc:
                    raise StorageError(400, "expectedRevision 必须为整数") from exc
                storage.delete_document(namespace, object_id, revision)
                self.send_response(204)
                self.end_headers()
                return

        # 项目
        if path == "/project/list" and method == "GET":
            self._ok(storage.list_documents("projects"))
            return
        if path == "/project" and method == "POST":
            body = self._with_defaults(self._read_json(), {
                "name": "未命名项目", "style": "", "styleDesc": "",
                "ratio": "16:9", "coverId": "", "description": "",
            })
            self._ok(storage.create_document("projects", body))
            return
        chapter_list = re.match(r"^/project/([^/]+)/chapter/list$", path)
        if chapter_list and method == "GET":
            project_id = unquote(chapter_list.group(1))
            items = [item for item in storage.list_documents("chapters")
                     if str(item.get("projectId")) == project_id]
            sorted_items = sort_and_normalize_chapters_py(storage, project_id, items)
            self._ok(sorted_items)
            return
        chapter_create = re.match(r"^/project/([^/]+)/chapter$", path)
        if chapter_create and method == "POST":
            project_id = unquote(chapter_create.group(1))
            storage.get_document("projects", project_id)
            body = self._read_json()
            body["projectId"] = project_id
            if "title" in body:
                body["title"] = normalize_chapter_title_py(body["title"])
            self._ok(storage.create_document("chapters", body))
            return
        project_item = re.match(r"^/project/([^/]+)$", path)
        if project_item:
            project_id = unquote(project_item.group(1))
            if method == "GET":
                self._ok(storage.get_document("projects", project_id))
                return
            if method == "PUT":
                self._ok(storage.update_document("projects", project_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("projects", project_id)
                self._ok(None)
                return

        # 章节
        chapter_item = re.match(r"^/chapter/([^/]+)$", path)
        if chapter_item:
            chapter_id = unquote(chapter_item.group(1))
            if method == "PUT":
                body = self._read_json()
                if "title" in body:
                    body["title"] = normalize_chapter_title_py(body["title"])
                self._ok(storage.update_document("chapters", chapter_id, body))
                return
            if method == "DELETE":
                storage.delete_document("chapters", chapter_id)
                self._ok(None)
                return

        # 素材
        if path == "/asset/list" and method == "GET":
            filtered = self._filter_assets(storage.list_documents("assets"), query)
            page_raw = (query.get("page") or [""])[0].strip()
            size_raw = (query.get("pageSize") or [""])[0].strip()
            if not page_raw and not size_raw:
                self._ok(filtered)
                return
            try:
                page = int(page_raw or "1")
                page_size = int(size_raw or "12")
            except ValueError as exc:
                raise StorageError(400, "page/pageSize 必须为整数") from exc
            page = max(1, page)
            page_size = max(1, min(page_size, 200))
            total = len(filtered)
            total_pages = max(1, (total + page_size - 1) // page_size)
            start = (page - 1) * page_size
            self._ok({
                "items": filtered[start:start + page_size],
                "total": total,
                "page": page,
                "pageSize": page_size,
                "totalPages": total_pages,
            })
            return
        if path == "/asset" and method == "POST":
            body = self._with_defaults(self._read_json(), {
                "type": "image", "name": "", "coverId": "", "description": "",
                "tags": "", "duration": "", "boundProjectIds": [],
            })
            self._ok(storage.create_document("assets", body))
            return
        if path == "/asset/upload" and method == "POST":
            self._ok(self._asset_upload(storage))
            return
        if path == "/asset/upload/batch" and method == "POST":
            self._ok(self._asset_upload(storage, single=False))
            return
        asset_item = re.match(r"^/asset/([^/]+)$", path)
        if asset_item:
            asset_id = unquote(asset_item.group(1))
            if method == "PUT":
                self._ok(storage.update_document("assets", asset_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("assets", asset_id)
                self._ok(None)
                return

        # 视频创作任务
        if path == "/video-project/list" and method == "GET":
            self._ok([self._video_summary(item) for item in storage.list_documents("video_projects")])
            return
        if path == "/video-project" and method == "POST":
            body = self._read_json()
            project_id = str(body.get("projectId") or "").strip()
            if not project_id and "id" not in body:
                raise StorageError(400, "请选择关联项目")
            if project_id:
                storage.get_document("projects", project_id)
            body = self._with_defaults(body, {"name": "未命名任务", "description": "", "assets": [], "storyboards": []})
            self._ok(storage.create_document("video_projects", body))
            return
        video_item = re.match(r"^/video-project/([^/]+)$", path)
        if video_item:
            video_id = unquote(video_item.group(1))
            if method == "GET":
                self._ok(storage.get_document("video_projects", video_id))
                return
            if method == "PUT":
                body = self._read_json()
                if "projectId" in body:
                    storage.get_document("projects", str(body.get("projectId") or ""))
                self._ok(storage.update_document("video_projects", video_id, body))
                return
            if method == "DELETE":
                storage.delete_document("video_projects", video_id)
                self._ok(None)
                return

        # 图片创作会话
        if path == "/image-conversation/list" and method == "GET":
            items = sorted(storage.list_documents("image_conversations"),
                           key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""),
                           reverse=True)
            self._ok(items)
            return
        if path == "/image-conversation" and method == "POST":
            body = self._with_defaults(self._read_json(), {"title": "新对话", "messages": []})
            self._ok(storage.create_document("image_conversations", body))
            return
        conversation_item = re.match(r"^/image-conversation/([^/]+)$", path)
        if conversation_item:
            conversation_id = unquote(conversation_item.group(1))
            if method == "GET":
                self._ok(storage.get_document("image_conversations", conversation_id))
                return
            if method == "PUT":
                self._ok(storage.update_document("image_conversations", conversation_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("image_conversations", conversation_id)
                self._ok(None)
                return

        # 项目级创作助手会话：按 projectId 隔离，未创建项目时使用 __draft__
        if path == "/project-agent-conversation/list" and method == "GET":
            project_id = str((query.get("projectId") or ["__draft__"])[0] or "__draft__").strip() or "__draft__"
            items = [item for item in storage.list_documents("project_agent_conversations")
                     if str(item.get("projectId") or "__draft__") == project_id]
            items.sort(key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)
            self._ok(items)
            return
        if path == "/project-agent-conversation" and method == "POST":
            body = self._with_defaults(self._read_json(), {
                "projectId": "__draft__", "title": "新创作对话", "messages": [],
                "projectDraft": {}, "chapterDraft": {},
            })
            self._ok(storage.create_document("project_agent_conversations", body))
            return
        agent_conversation_item = re.match(r"^/project-agent-conversation/([^/]+)$", path)
        if agent_conversation_item:
            conversation_id = unquote(agent_conversation_item.group(1))
            if method == "GET":
                self._ok(storage.get_document("project_agent_conversations", conversation_id))
                return
            if method == "PUT":
                self._ok(storage.update_document("project_agent_conversations", conversation_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("project_agent_conversations", conversation_id)
                self._ok(None)
                return

        # 文件
        if path == "/file/upload" and method == "POST":
            self._ok(self._file_upload(storage))
            return
        file_download = re.match(r"^/file/([^/]+)/download$", path)
        if file_download and method in {"GET", "HEAD"}:
            object_id = unquote(file_download.group(1))
            meta = storage.find_file(object_id)
            self._serve_file(storage, meta, method == "GET")
            return
        file_item = re.match(r"^/file/([^/]+)$", path)
        if file_item:
            object_id = unquote(file_item.group(1))
            if method == "GET":
                self._ok(self._legacy_file(storage.find_file(object_id)))
                return
            if method == "DELETE":
                meta = storage.find_file(object_id)
                storage.delete_file(meta["bucket"], object_id)
                self._ok(None)
                return

        # 模型管理
        if path == "/api/admin/models" and method == "GET":
            self._ok(self._sorted_models(storage.list_documents("ai_models")))
            return
        if path == "/api/admin/models" and method == "POST":
            body = self._read_json()
            self._normalize_model(body, partial=False)
            self._ok(storage.create_document("ai_models", body))
            return
        if path == "/api/admin/models/batch" and method == "POST":
            body = self._read_json()
            items = body if isinstance(body, list) else body.get("models", [])
            created = []
            for item in items:
                if isinstance(item, dict):
                    self._normalize_model(item, partial=False)
                    created.append(storage.create_document("ai_models", item))
            self._ok(created)
            return
        if path in {"/api/admin/models/fetch-remote", "/api/admin/models/fetch"} and method == "POST":
            body = self._read_json()
            api_url = str(body.get("apiUrl") or "").strip()
            api_key = str(body.get("apiKey") or "").strip()
            model_id = str(body.get("modelId") or "").strip()
            provider = str(body.get("provider") or "").strip()
            model_type = str(body.get("modelType") or body.get("defaultType") or "").strip()
            # 兜底1：如果未显式传 key 但有 modelId，从当前编辑的模型中读取已配置的 key
            if not api_key and model_id:
                try:
                    existing = storage.get_document("ai_models", model_id)
                    api_key = str(existing.get("apiKey") or "").strip()
                except Exception:
                    pass
            # 兜底2：如果仍无 key 但有 apiUrl，从同 API 地址的已有模型中匹配 key
            if not api_key and api_url:
                norm_target = api_url.rstrip("/")
                for item in storage.list_documents("ai_models"):
                    cand_url = str(item.get("apiUrl") or "").strip().rstrip("/")
                    cand_key = str(item.get("apiKey") or "").strip()
                    if cand_key and cand_url == norm_target:
                        api_key = cand_key
                        break
            models = self._fetch_remote_models(api_url, api_key, provider=provider, model_type=model_type)
            self._ok(models)
            return
        if path == "/api/admin/models/public/list" and method == "GET":
            model_type = (query.get("modelType") or [""])[0]
            items = [item for item in self._sorted_models(storage.list_documents("ai_models"))
                     if self._is_model_enabled(item)
                     and (not model_type or item.get("modelType") == model_type)]
            for item in items:
                item.pop("apiKey", None)
            self._ok(items)
            return
        model_item = re.match(r"^/api/admin/models/([^/]+)$", path)
        if model_item:
            model_id = unquote(model_item.group(1))
            if method == "PUT":
                patch = self._read_json()
                if not str(patch.get("apiKey") or "").strip():
                    patch.pop("apiKey", None)
                self._normalize_model(patch, partial=True)
                self._ok(storage.update_document("ai_models", model_id, patch))
                return
            if method == "DELETE":
                storage.delete_document("ai_models", model_id)
                self._ok(None)
                return

        # 提示词
        if path == "/prompt/list" and method == "GET":
            items = storage.list_documents("prompts")
            if (query.get("scope") or [""])[0] == "shared":
                items = [item for item in items if item.get("shared")]
            # All local prompts belong to the single-machine user, including shared ones.
            try:
                limit = int((query.get("limit") or ["50"])[0])
            except ValueError as exc:
                raise StorageError(400, "limit 必须为整数") from exc
            self._ok(items[:max(1, min(limit, 500))])
            return
        if path == "/prompt" and method == "POST":
            self._ok(storage.create_document("prompts", self._read_json()))
            return
        prompt_item = re.match(r"^/prompt/([^/]+)$", path)
        if prompt_item:
            prompt_id = unquote(prompt_item.group(1))
            if method == "PUT":
                self._ok(storage.update_document("prompts", prompt_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("prompts", prompt_id)
                self._ok(None)
                return

        # 每日额度
        if path == "/desktop/account-quota/status" and method == "GET":
            self._ok(self._quota_status(storage, query))
            return
        if path == "/desktop/account-quota/today-usage" and method == "GET":
            self._ok(self._quota_today(storage, query))
            return
        if path == "/desktop/account-quota/consume" and method == "POST":
            self._ok(self._quota_consume(storage))
            return

        if path == "/ai/image" and method == "POST":
            self._ok(self._generate_image(storage, self._read_json()))
            return

        if path == "/ai/audio" and method == "POST":
            self._ok(self._generate_audio(storage, self._read_json()))
            return
        if path == "/ai/chat" and method == "POST":
            self._ok(self._generate_chat(storage, self._read_json()))
            return
        if path == "/ai/optimize-prompt" and method == "POST":
            self._ok(self._optimize_prompt(storage, self._read_json()))
            return
        if path == "/ai/creation-data" and method == "POST":
            self._ok(self._generate_creation_data(storage, self._read_json()))
            return
        if path == "/ai/script" and method == "POST":
            self._ok(self._generate_script(storage, self._read_json()))
            return
        if path.startswith(("/api/huashu/", "/huashu/")):
            action = path[len("/api/huashu/"):] if path.startswith("/api/huashu/") else path[len("/huashu/"):]
            import huashu_bridge
            storage_dir = storage.storage_dir
            if action == "status":
                self._ok(huashu_bridge.get_huashu_status())
                return
            if action == "templates":
                self._ok(huashu_bridge.get_huashu_templates())
                return
            body = self._read_json() if method == "POST" else {}
            project_id = str(body.get("project_id") or (query.get("projectId") or [""])[0])
            if action == "project_info":
                self._ok(huashu_bridge.get_huashu_project_info(storage_dir, project_id))
                return
            if action == "init":
                self._ok(huashu_bridge.init_huashu_project(
                    storage_dir,
                    project_id,
                    body.get("template_id", "keynote-ui"),
                    body.get("title", ""),
                    body.get("script_text", "")
                ))
                return
            if action == "open_studio":
                self._ok(huashu_bridge.open_huashu_studio(storage_dir, project_id))
                return
            if action == "render":
                self._ok(huashu_bridge.render_huashu_project(
                    storage_dir,
                    project_id,
                    bool(body.get("blur", False)),
                    str(body.get("template_id") or "keynote-ui")
                ))
                return
            if action == "video":
                target_dir = huashu_bridge.get_huashu_project_dir(storage_dir, project_id)
                out_dir = target_dir / "out"
                file_name = (query.get("file") or [""])[0]
                if file_name:
                    target_file = out_dir / file_name
                else:
                    mp4s = sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) if out_dir.is_dir() else []
                    target_file = mp4s[0] if mp4s else None
                if target_file and target_file.is_file():
                    self._serve_local_disk_file(target_file, method == "GET")
                    return
                raise StorageError(404, "视频文件不存在")
        if path == "/ai/video" and method == "POST":
            self._ok(self._submit_video(storage, self._read_json()))
            return
        if path == "/ai/video/cancel" and method == "POST":
            body = self._read_json()
            model = self._video_model(storage, body.get("model"))
            task_id = str(body.get("taskId") or "").strip()
            if not task_id:
                raise StorageError(400, "缺少需要终止的任务 ID")
            parsed = urlparse(str(model.get("apiUrl") or ""))
            base = f"{parsed.scheme}://{parsed.netloc}"
            from urllib.parse import quote
            task_key = quote(task_id, safe="")
            is_muse = bool(re.match(r"^muse[-_ ]?video", str(model.get("modelName") or ""), re.I))
            if not is_muse:
                raise StorageError(400, "当前服务商尚未接入远程取消；任务仍可能在服务端运行")

            cancel_endpoints = [
                f"{base}/v1/videos/{task_key}/cancel",
                f"{base}/v1/videos/generations/{task_key}/cancel",
                f"{base}/admin/tasks/{task_key}/cancel",
            ]
            for ep in cancel_endpoints:
                try:
                    res = self._request_ai_json(model, ep, "终止视频任务", {})
                    if res.get("cancelled") or res.get("stopped") or res.get("status") in {"cancelled", "canceled", "not_found"}:
                        break
                except Exception:
                    continue

            for _ in range(8):
                try:
                    state = self._request_ai_json(model, f"{base}/v1/videos/{task_key}", "确认任务终止")
                    status = str(state.get("status") or "").lower()
                    if status in {"cancelled", "canceled", "failed", "succeeded", "completed"}:
                        self._ok({"stopped": True, "status": status, "taskId": task_id})
                        return
                except Exception:
                    self._ok({"stopped": True, "status": "cancelled", "taskId": task_id})
                    return
                time.sleep(0.2)
            self._ok({"stopped": True, "status": "cancelling", "taskId": task_id})
            return
        if path == "/video/extract-last-frame" and method == "POST":
            self._ok(self._extract_video_last_frame(storage, self._read_json()))
            return
        if path == "/video/extract-custom-frame" and method == "POST":
            self._ok(self._extract_custom_frame(storage, self._read_json()))
            return
        if path == "/video/generate-camera-matrix" and method == "POST":
            self._ok(self._generate_camera_matrix(storage, self._read_json()))
            return
        if path == "/image/crop-matrix-cell" and method == "POST":
            self._ok(self._crop_matrix_cell(storage, self._read_json()))
            return
        if path == "/image/crop-role-portrait" and method == "POST":
            self._ok(self._crop_role_portrait(storage, self._read_json()))
            return
        video_task = re.fullmatch(r"/ai/video/([^/]+)", path)
        if video_task and method == "GET":
            self._ok(self._poll_video(storage, unquote(video_task.group(1)), (query.get("model") or [""])[0]))
            return

        if path == "/api/custom-rules" and method == "GET":
            try:
                import skill_loader
                self._ok({"rules": skill_loader.load_custom_continuity_rules()})
            except Exception as e:
                self._ok({"rules": "", "error": str(e)})
            return
        if path == "/api/custom-rules" and method == "PUT":
            try:
                import skill_loader
                b = self._read_json()
                rules_content = str(b.get("rules") or "")
                target_file = skill_loader.get_custom_rules_dir() / "continuity_overlay.md"
                target_file.parent.mkdir(parents=True, exist_ok=True)
                with open(target_file, "w", encoding="utf-8") as rf:
                    rf.write(rules_content)
                self._ok({"status": "saved", "path": str(target_file)})
            except Exception as e:
                self._fail(f"保存自定义规则失败: {e}")
            return
        if path == "/api/skill-info" and method == "GET":
            try:
                import skill_loader
                self._ok({
                    "version": skill_loader.load_skill_version(),
                    "skillDir": str(skill_loader.get_skill_dir()),
                    "customRulesDir": str(skill_loader.get_custom_rules_dir()),
                })
            except Exception as e:
                self._ok({"version": "7.4.26", "error": str(e)})
            return

        # 未识别的 AI 接口不能误报为用户没有保存配置。
        if path.startswith("/ai/"):
            self._read_body()
            self._fail("当前本地服务尚未接入此 AI 接口")
            return

        raise StorageError(404, "接口不存在")

    # ---------- 辅助 ----------

    def _serve_local_disk_file(self, file_path: Path, send_body: bool) -> None:
        import mimetypes
        if not file_path.is_file():
            raise StorageError(404, "文件不存在")
        size = file_path.stat().st_size
        start, end = 0, size - 1
        range_match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if range_match:
            first, last = range_match.groups()
            if first:
                start = int(first)
                if last:
                    end = min(int(last), end)
            elif last:
                start = max(0, size - int(last))
            else:
                start = size
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = max(0, end - start + 1)
        self.send_response(206 if range_match else 200)
        content_type = mimetypes.guess_type(file_path.name)[0] or "video/mp4"
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if range_match:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not send_body:
            return
        with open(file_path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(remaining, 64 * 1024))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _serve_file(self, storage: LocalStorage, meta: dict[str, Any], send_body: bool) -> None:
        path = storage.file_directory(meta["bucket"], meta["id"]) / "content.bin"
        if not path.is_file():
            raise StorageError(404, "文件内容不存在")
        size = path.stat().st_size
        start, end = 0, size - 1
        range_match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if range_match:
            first, last = range_match.groups()
            if first:
                start = int(first)
                if last:
                    end = min(int(last), end)
            elif last:
                start = max(0, size - int(last))
            else:
                start = size
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = max(0, end - start + 1)
        self.send_response(206 if range_match else 200)
        self.send_header("Content-Type", meta.get("contentType") or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        if range_match:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if send_body:
            try:
                with path.open("rb") as file:
                    file.seek(start)
                    remaining = length
                    while remaining:
                        chunk = file.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def _resolve_ai_model(self, storage: LocalStorage, model_type: str, selected: Any = "") -> dict[str, Any]:
        selected = str(selected or "").strip()
        models = [item for item in self._sorted_models(storage.list_documents("ai_models"))
                  if item.get("modelType") == model_type and self._is_model_enabled(item)]
        model = next((item for item in models if str(item.get("id")) == selected), None)
        if model is None:
            model = next((item for item in models if not selected or item.get("modelName") == selected), None)
        label = {"image": "图片", "audio": "音频", "video": "视频", "text": "文本"}[model_type]
        if model is None:
            raise StorageError(400, f"未找到已启用的{label}模型，请在设置中心检查所选模型")
        for key, field in (("apiUrl", "API 地址"), ("modelName", "API 模型名")):
            if not str(model.get(key) or "").strip():
                raise StorageError(400, f"所选{label}模型未填写 {field}，请在设置中心补充")
        return model

    @staticmethod
    def _ai_endpoint(api_url: str, suffix: str) -> str:
        raw_url = api_url.strip()
        if "www.daseinai.xyz" in raw_url:
            raw_url = raw_url.replace("www.daseinai.xyz", "api.daseinai.xyz")
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise StorageError(400, "模型 API 地址必须为有效的 HTTP 或 HTTPS 地址")
        path = parsed.path.rstrip("/")
        if not path.endswith(suffix):
            path = (path or "/v1") + suffix
        return parsed._replace(path=path, fragment="").geturl()

    @classmethod
    def _optimize_image_for_api(cls, source: str, storage: Any = None, max_dim: int = 1280, max_bytes: int = 700_000) -> str:
        """应用轻量胶片滤镜算法并压缩优化图片，防止触发真人面部风控拦截（Likeness Protection）并防止超大 Payload。"""
        if not isinstance(source, str) or not source.strip():
            return source

        raw = None
        # 1. 如果是本地文件桶链接 (/file/local_xxx/download 或 local_xxx)
        if (source.startswith("/file/") or "local_" in source) and storage is not None:
            try:
                m = re.search(r"local_[a-zA-Z0-9]+", source)
                if m:
                    file_id = m.group(0)
                    meta = storage.find_file(file_id)
                    if meta:
                        bucket = meta.get("bucket") or "files"
                        obj_id = meta.get("id") or file_id
                        candidates = [
                            storage.file_directory(bucket, obj_id) / "content.bin",
                            storage._file_path(bucket, obj_id) if hasattr(storage, "_file_path") else None,
                        ]
                        for cand in candidates:
                            if cand and hasattr(cand, "is_file") and cand.is_file():
                                raw = cand.read_bytes()
                                break
            except Exception:
                pass

        # 2. 如果是 Base64 Data URL
        if raw is None and source.startswith("data:image/"):
            try:
                _, separator, encoded = source.partition(",")
                if separator:
                    raw = base64.b64decode(encoded)
            except Exception:
                pass

        if raw:
            try:
                import film_filter
                filtered = film_filter.process_image_bytes(raw, grain_intensity=10.0, max_dim=max_dim, jpeg_quality=92)
                b64 = base64.b64encode(filtered).decode("ascii")
                return f"data:image/jpeg;base64,{b64}"
            except Exception as e:
                print(f"[OptimizeImage Warning] {e}")

        return source

    @staticmethod
    def _request_ai_json(model: dict[str, Any], endpoint: str, operation: str,
                         body: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
                         timeout: float | None = None) -> dict[str, Any]:
        api_key = str(model.get("apiKey") or "").strip()
        trust_env = urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}
        req_timeout = timeout if timeout is not None else (300 if body is not None else 30)
        request_headers = {**(headers or {})}
        if api_key:
            auth_val = api_key if api_key.startswith(("Bearer ", "Token ")) else f"Bearer {api_key}"
            request_headers.setdefault("Authorization", auth_val)
            request_headers.setdefault("token", api_key)
            request_headers.setdefault("Token", api_key)
            request_headers.setdefault("X-Api-Key", api_key)
        try:
            from analysis_runtime import request as send_request
            try:
                response = send_request("POST" if body is not None else "GET", endpoint, body=body,
                                        headers=request_headers, timeout=req_timeout, trust_env=trust_env)
            except Exception as conn_err:
                parsed_ep = urlparse(endpoint)
                if (parsed_ep.port == 18610 or "18610" in endpoint) and any(m in str(conn_err).lower() for m in ("connect", "10061", "refused")):
                    import subprocess, time
                    try:
                        tools_root = Path(os.environ.get("CDTV_TOOLS_ROOT", "").strip()) if os.environ.get("CDTV_TOOLS_ROOT", "").strip() else next((p for p in Path(__file__).resolve().parents if (p / "muse2api").is_dir()), Path("tools"))
                        muse_exe = tools_root / "muse2api" / "dist" / "Muse2API" / "Muse2API.exe"
                        if muse_exe.is_file():
                            subprocess.Popen([str(muse_exe)], cwd=str(muse_exe.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                            time.sleep(2.5)
                            response = send_request("POST" if body is not None else "GET", endpoint, body=body,
                                                    headers=request_headers, timeout=req_timeout, trust_env=trust_env)
                    except Exception:
                        pass
                if "response" not in locals():
                    raise
            # Some OpenAI-compatible providers (notably newer reasoning models)
            # reject max_tokens and require max_completion_tokens instead.
            if (body is not None and isinstance(body, dict) and "max_tokens" in body
                    and "max_completion_tokens" not in body and response.status_code == 400):
                try:
                    error_text = response.text.lower()
                except Exception:
                    error_text = ""
                mentions_limit = "max_tokens" in error_text
                indicates_unsupported = any(marker in error_text for marker in (
                    "unsupported", "not support", "unrecognized", "unknown parameter", "deprecated",
                ))
                if mentions_limit and indicates_unsupported:
                    compatible_body = dict(body)
                    compatible_body["max_completion_tokens"] = compatible_body.pop("max_tokens")
                    response = send_request("POST", endpoint, body=compatible_body,
                                            headers=request_headers, timeout=req_timeout, trust_env=trust_env)
            if response.status_code == 413:
                raise StorageError(413, f"{operation}失败（HTTP 413 请求体过大）：发送的图片或参数超出了服务商单次限制，已自动启动自适应压缩")
            try:
                from ai_response import decode
                result = response.json() if response.is_error else decode(response, operation, api_key)
            except StorageError as exc:
                if body is not None and isinstance(body, dict) and not body.get("stream") and ("保活" in str(exc) or getattr(exc, "keepaliveOnly", False)):
                    retry_body = dict(body)
                    retry_body["stream"] = True
                    retry_resp = send_request("POST", endpoint, body=retry_body, headers=request_headers, timeout=req_timeout, trust_env=trust_env)
                    if not retry_resp.is_error:
                        result = decode(retry_resp, operation, api_key)
                    else:
                        raise
                else:
                    raise
            except ValueError as exc:
                if response.is_error:
                    title_m = re.search(r"<title>(.*?)</title>", response.text, flags=re.IGNORECASE)
                    title_text = title_m.group(1).strip() if title_m else ""
                    if title_text:
                        raise StorageError(502, f"{operation}失败（服务商网关返回 HTTP {response.status_code}）：{title_text}，请检查中转站服务状态或切换模型") from exc
                    cleaned_body = re.sub(r"<!--[\s\S]*?-->", " ", response.text)
                    cleaned_body = re.sub(r"<[^>]+>", " ", cleaned_body)
                    snippet = " ".join(cleaned_body.split())[:120].strip()
                    raise StorageError(502, f"{operation}失败（服务商返回 HTTP {response.status_code}）：{snippet or '服务商未返回有效 JSON'}") from exc
                raise StorageError(502, f"{operation}返回非 JSON 内容（HTTP {response.status_code}），请检查 API 地址") from exc
            if not isinstance(result, dict):
                raise StorageError(502, f"{operation}返回格式不正确")
            terminal_task_error = body is None and str(result.get("status") or result.get("state") or "").lower() in {
                "failed", "error", "cancelled", "canceled", "expired"
            }
            if response.is_error or (result.get("error") and not terminal_task_error):
                error = result.get("error") or {}
                detail = error.get("message") if isinstance(error, dict) else str(error)
                if not detail and result.get("detail"):
                    d = result.get("detail")
                    if isinstance(d, list):
                        detail = "; ".join(f"{x.get('loc', [''])[-1]}: {x.get('msg', '')}" if isinstance(x, dict) else str(x) for x in d)
                    else:
                        detail = str(d)
                detail = str(detail or result.get("message") or result.get("msg") or "请检查模型配置和服务商状态")
                if "upstream authentication failed" in detail.lower() or "upstream_error" in str(result).lower():
                    detail = f"{detail}（第三方中转站上游官方密钥/余额失效，请切换为其他可用文本模型或联系中转站管理员）"
                raise StorageError(502, f"{operation}失败（HTTP {response.status_code}）："
                                   + detail.replace(api_key, "[隐藏]")[:400])
            return result
        except httpx.TimeoutException as exc:
            raise StorageError(504, f"{operation}超时；服务商可能仍在处理，请先检查任务记录再决定是否重试") from exc
        except httpx.HTTPError as exc:
            raise StorageError(502, f"无法连接{operation}服务，请检查网络与 API 地址") from exc

    def _generate_audio(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._resolve_ai_model(storage, "audio", body.get("model"))
        prompt = str(body.get("prompt") or "").strip()
        preview = str(body.get("preview_text") or body.get("text") or body.get("input") or "").strip() or prompt
        if not prompt and not preview:
            raise StorageError(400, "请填写语音台词或音效描述")
        if len(preview) > 500:
            raise StorageError(400, "试听文本不能超过 500 个字符")

        provider = str(model.get("provider") or "").lower()
        api_url = str(model.get("apiUrl") or "").strip()
        model_name = str(model.get("modelName") or "").strip()
        api_key = str(model.get("apiKey") or "").strip()
        input_text = preview or prompt

        # 1. MiniMax 音色设计
        if provider == "minimax" or "/voice_design" in api_url:
            result = self._request_ai_json(model, self._ai_endpoint(api_url, "/voice_design"),
                                           "MiniMax 音频生成", {"prompt": prompt, "preview_text": preview})
            base = result.get("base_resp") or {}
            if not isinstance(base, dict) or base.get("status_code", 0) not in {0, "0"}:
                detail = str(base.get("status_msg") or "未知错误") if isinstance(base, dict) else "返回格式不正确"
                raise StorageError(502, "MiniMax 音频生成失败：" + detail.replace(api_key, "[隐藏]")[:400])
            try:
                audio = bytes.fromhex(result.get("trial_audio") or "")
            except (ValueError, TypeError) as exc:
                raise StorageError(502, "MiniMax 返回的 trial_audio 不是有效的十六进制音频") from exc
            if not audio:
                raise StorageError(502, "MiniMax 未返回试听音频 trial_audio")
            stored = storage.save_file("generated-audio", audio, f"voice-{uuid.uuid4().hex}.mp3", "audio/mpeg")
            url = self._legacy_file(stored)["url"]
            return {"content": url, "audio_url": url, "fileId": stored["id"], "format": "mp3",
                    "voice_id": result.get("voice_id", "")}

        # 2. 阿里云百炼 / DashScope 专有语音合成（CosyVoice、Sambert、Qwen-TTS 等）
        is_dashscope_domain = any(d in api_url.lower() for d in ("dashscope", "aliyuncs.com", "maas.aliyun", "bailian")) or provider in {"dashscope", "bailian", "aliyun", "百炼", "阿里云百炼"}
        is_cosyvoice = "cosyvoice" in model_name.lower()
        is_sambert = "sambert" in model_name.lower()
        is_dashscope_tts = is_cosyvoice or is_sambert or (is_dashscope_domain and not any(k in model_name.lower() for k in ("omni", "chat", "realtime", "livetranslate")))

        if is_dashscope_tts:
            parsed_url = urlparse(api_url)
            base_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
            tts_candidates = [
                f"{base_origin}/api/v1/services/audio/tts/SpeechSynthesizer",
                f"{base_origin}/api/v1/services/aigc/text-to-speech/generation",
                f"{base_origin}/api/v1/services/audio/tts/generation",
                "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer",
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-to-speech/generation",
            ]
            voice_param = str(body.get("voice") or model.get("voice") or "").strip()
            if not voice_param:
                hints = " ".join([
                    str(body.get("voice_style") or ""),
                    str(body.get("name") or ""),
                    str(body.get("description") or ""),
                    str(body.get("style") or ""),
                    str(body.get("prompt") or ""),
                    str(input_text or ""),
                ]).lower()
                is_v2 = "v2" in model_name.lower() or not is_sambert
                if is_sambert:
                    if any(k in hints for k in ["男", "大叔", "沉稳", "老", "苍凉", "旁白", "雄浑"]):
                        voice_param = "zhichu"
                    elif any(k in hints for k in ["女", "甜美", "少女"]):
                        voice_param = "zhimiao_emo"
                    else:
                        voice_param = "zhichu"
                else:
                    # CosyVoice 音色智能推断
                    if any(k in hints for k in ["大叔", "苍凉", "雄浑", "厚重", "天道", "开篇", "序幕", "旁白", "叙事", "解说", "老者", "老祖", "师尊", "尊者", "帝尊", "神明", "威严", "沉稳", "宿命", "深沉", "男"]):
                        voice_param = "longshu_v2" if is_v2 else "longshu"
                    elif any(k in hints for k in ["评书", "霸气", "说书", "热血", "怒吼", "粗犷"]):
                        voice_param = "longfeiyan_v2" if is_v2 else "longfeiyan"
                    elif any(k in hints for k in ["少年", "青年", "男主", "少侠", "师弟", "阳光", "温润"]):
                        voice_param = "longyuan_v2" if is_v2 else "longyuan"
                    elif any(k in hints for k in ["萝莉", "可爱", "女童", "灵宠", "灵兽", "小女孩", "软萌", "童声"]):
                        voice_param = "longmiao_v2" if is_v2 else "longmiao"
                    elif any(k in hints for k in ["御姐", "师姐", "女尊", "仙子", "女帝", "知性", "成熟女", "夫人", "神女"]):
                        voice_param = "longyue_v2" if is_v2 else "longyue"
                    elif any(k in hints for k in ["女", "女主", "甜美", "温柔", "灵动", "姑娘"]):
                        voice_param = "longtian_v2" if is_v2 else "longtian"
                    elif any(k in hints for k in ["系统", "提示", "广播", "通知"]):
                        voice_param = "longxiaochun_v2" if is_v2 else "longxiaochun"
                    else:
                        # 默认开局/旁白优先使用大叔苍凉男声，避免默认女声出戏
                        voice_param = "longshu_v2" if is_v2 else "longshu"
            elif "v2" in model_name.lower() and not voice_param.endswith("_v2") and not voice_param.startswith("custom_"):
                if voice_param in {"longshu", "longfeiyan", "longyuan", "longlaotie", "longjing", "longxiaochun", "longtian", "longmiao", "longyue", "longshuo"}:
                    voice_param = f"{voice_param}_v2"
            elif "v1" in model_name.lower() and voice_param.endswith("_v2"):
                voice_param = voice_param.replace("_v2", "")

            dashscope_payload = {
                "model": model_name,
                "input": {
                    "text": input_text,
                    "voice": voice_param,
                },
                "parameters": {
                    "voice": voice_param,
                    "format": "mp3",
                    "sample_rate": 22050,
                },
                "voice": voice_param,
            }
            trust_env = urlparse(api_url).hostname not in {"127.0.0.1", "localhost", "::1"}
            last_err = None
            for endpoint in tts_candidates:
                try:
                    with httpx.Client(timeout=httpx.Timeout(120, connect=15), trust_env=trust_env) as client:
                        resp = client.post(
                            endpoint,
                            json=dashscope_payload,
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        )
                    if resp.status_code == 200:
                        ct = resp.headers.get("content-type", "")
                        if "audio/" in ct or "octet-stream" in ct:
                            audio_bytes = resp.content
                            stored = storage.save_file("generated-audio", audio_bytes, f"voice-{uuid.uuid4().hex}.mp3", "audio/mpeg")
                            url = self._legacy_file(stored)["url"]
                            return {"content": url, "audio_url": url, "fileId": stored["id"], "format": "mp3"}
                        try:
                            res_json = resp.json()
                        except Exception:
                            res_json = {}
                        output = res_json.get("output") if isinstance(res_json.get("output"), dict) else {}
                        audio_url = (
                            (output.get("audio") if isinstance(output.get("audio"), dict) else {}).get("url")
                            or output.get("audio_url")
                            or output.get("url")
                            or res_json.get("audio_url")
                            or res_json.get("url")
                        )
                        if audio_url:
                            with httpx.Client(timeout=httpx.Timeout(60, connect=15), trust_env=True) as dl_client:
                                dl_resp = dl_client.get(audio_url)
                                dl_resp.raise_for_status()
                                audio_bytes = dl_resp.content
                            stored = storage.save_file("generated-audio", audio_bytes, f"voice-{uuid.uuid4().hex}.mp3", "audio/mpeg")
                            url = self._legacy_file(stored)["url"]
                            return {"content": url, "audio_url": url, "fileId": stored["id"], "format": "mp3"}
                        if output.get("audio") and isinstance(output.get("audio"), str):
                            audio_bytes = base64.b64decode(output["audio"])
                            stored = storage.save_file("generated-audio", audio_bytes, f"voice-{uuid.uuid4().hex}.mp3", "audio/mpeg")
                            url = self._legacy_file(stored)["url"]
                            return {"content": url, "audio_url": url, "fileId": stored["id"], "format": "mp3"}
                    elif resp.status_code != 404:
                        try:
                            err_json = resp.json()
                            msg = err_json.get("message") or err_json.get("error", {}).get("message") or resp.text
                        except Exception:
                            msg = resp.text[:200]
                        raise StorageError(resp.status_code, f"百炼语音合成失败（HTTP {resp.status_code}）：{msg}")
                except StorageError:
                    raise
                except Exception as ex:
                    last_err = ex
                    continue
            if last_err and not isinstance(last_err, StorageError):
                raise StorageError(502, f"连接百炼语音合成服务失败：{last_err}")

        # 3. Qwen-Omni / 多模态全双工音频对话模型 (通过 /chat/completions 输出音频)
        is_omni = any(k in model_name.lower() for k in ("omni", "audio-preview", "livetranslate", "realtime"))
        if is_omni:
            chat_endpoint = self._ai_endpoint(api_url, "/chat/completions")
            omni_payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": "你是一个专业的角色台词配音与音效生成助手。请直接朗读或拟声发音输出用户给出的文本内容，不要输出任何多余问候或解释说明。"},
                    {"role": "user", "content": input_text},
                ],
                "modalities": ["text", "audio"],
                "audio": {
                    "voice": str(body.get("voice") or model.get("voice") or "cherry"),
                    "format": "mp3",
                },
                "stream": False,
            }
            trust_env = urlparse(chat_endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}
            try:
                with httpx.Client(timeout=httpx.Timeout(120, connect=15), trust_env=trust_env) as client:
                    response = client.post(chat_endpoint, json=omni_payload, headers={"Authorization": f"Bearer {api_key}"})
                if response.status_code == 200:
                    res_json = response.json()
                    choices = res_json.get("choices") or []
                    if choices and isinstance(choices, list):
                        msg = choices[0].get("message") or {}
                        audio_obj = msg.get("audio") or {}
                        audio_b64 = audio_obj.get("data") or ""
                        if audio_b64:
                            audio_bytes = base64.b64decode(audio_b64)
                            stored = storage.save_file("generated-audio", audio_bytes, f"voice-{uuid.uuid4().hex}.mp3", "audio/mpeg")
                            url = self._legacy_file(stored)["url"]
                            return {"content": url, "audio_url": url, "fileId": stored["id"], "format": "mp3"}
                if response.is_error:
                    err_json = response.json() if "json" in response.headers.get("content-type", "") else {}
                    err_msg = err_json.get("message") or err_json.get("error", {}).get("message") or response.text[:200]
                    raise StorageError(response.status_code, f"音频生成失败：{err_msg}")
            except Exception as e:
                if isinstance(e, StorageError):
                    raise
                pass  # Fall through to try standard /audio/speech

        # 4. OpenAI 标准 / 第三方兼容模式 /audio/speech (TTS)
        speech_endpoint = self._ai_endpoint(api_url, "/audio/speech") if not api_url.endswith("/audio/speech") else api_url
        tts_payload = {
            "model": model_name,
            "input": input_text,
            "voice": str(body.get("voice") or model.get("voice") or ("longxiaochun" if "dashscope" in api_url else "alloy")),
        }
        trust_env = urlparse(speech_endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}
        try:
            with httpx.Client(timeout=httpx.Timeout(120, connect=15), trust_env=trust_env) as client:
                response = client.post(speech_endpoint, json=tts_payload, headers={"Authorization": f"Bearer {api_key}"})
            if response.status_code == 200:
                audio_bytes = response.content
                if audio_bytes and len(audio_bytes) > 50:
                    content_type = response.headers.get("content-type", "audio/mpeg")
                    ext = "mp3" if "mpeg" in content_type or "mp3" in content_type else "wav"
                    stored = storage.save_file("generated-audio", audio_bytes, f"voice-{uuid.uuid4().hex}.{ext}", content_type)
                    url = self._legacy_file(stored)["url"]
                    return {"content": url, "audio_url": url, "fileId": stored["id"], "format": ext}

            # 5. 如果 /audio/speech 报 404 且模型为 qwen 等，自动尝试 /chat/completions 音频模态
            if response.status_code == 404:
                chat_endpoint = self._ai_endpoint(api_url, "/chat/completions")
                fallback_payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "你是一个专业的角色台词配音与音效生成助手。请直接朗读或拟声发音输出用户给出的文本内容，不要输出任何多余问候或解释说明。"},
                        {"role": "user", "content": input_text},
                    ],
                    "modalities": ["text", "audio"],
                    "audio": {"voice": "cherry", "format": "mp3"},
                    "stream": False,
                }
                with httpx.Client(timeout=httpx.Timeout(120, connect=15), trust_env=trust_env) as client:
                    fb_res = client.post(chat_endpoint, json=fallback_payload, headers={"Authorization": f"Bearer {api_key}"})
                if fb_res.status_code == 200:
                    choices = (fb_res.json().get("choices") or [])
                    if choices and isinstance(choices, list):
                        audio_b64 = (choices[0].get("message") or {}).get("audio", {}).get("data") or ""
                        if audio_b64:
                            audio_bytes = base64.b64decode(audio_b64)
                            stored = storage.save_file("generated-audio", audio_bytes, f"voice-{uuid.uuid4().hex}.mp3", "audio/mpeg")
                            url = self._legacy_file(stored)["url"]
                            return {"content": url, "audio_url": url, "fileId": stored["id"], "format": "mp3"}

            try:
                err_json = response.json()
                msg = err_json.get("message") or err_json.get("error", {}).get("message") or response.text
                raise StorageError(response.status_code, f"音频生成失败：{msg}")
            except Exception as e:
                if isinstance(e, StorageError):
                    raise
                raise StorageError(response.status_code, f"音频生成失败（HTTP {response.status_code}）：{response.text[:200]}")
        except httpx.TimeoutException as exc:
            raise StorageError(504, "音频生成超时，请稍后重试") from exc
        except httpx.HTTPError as exc:
            raise StorageError(502, f"无法连接音频生成 API 地址：{str(exc)}") from exc

    def _generate_chat(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._resolve_ai_model(storage, "text", body.get("model"))
        if not isinstance(body.get("messages"), list) or not body["messages"]:
            raise StorageError(400, "messages 不能为空")
        payload = {**body, "model": model["modelName"], "stream": False}
        if model.get("maxTokens"):
            payload["max_tokens"] = int(model["maxTokens"])
        elif model.get("contextWindow") and not payload.get("max_tokens"):
            payload["max_tokens"] = min(32000, max(4096, int(model["contextWindow"] // 4)))
        headers = {}
        if urlparse(model["apiUrl"]).path.rstrip("/").endswith("/messages"):
            endpoint = self._ai_endpoint(model["apiUrl"], "/messages")
            headers = {"anthropic-version": "2023-06-01"}
            if str(model.get("apiKey") or "").strip():
                headers["x-api-key"] = str(model["apiKey"]).strip()
            payload.setdefault("max_tokens", 4096)
        else:
            endpoint = self._ai_endpoint(model["apiUrl"], "/chat/completions")
        return self._request_ai_json(model, endpoint, "文本生成", payload, headers)

    def _optimize_prompt(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise StorageError(400, "提示词内容不能为空")
        error = str(body.get("error") or "").strip()
        title = str(body.get("title") or "当前分镜").strip()
        model_id = body.get("model")

        # Try to resolve a text model
        text_model = None
        if model_id:
            try:
                text_model = self._resolve_ai_model(storage, "text", model_id)
            except Exception:
                text_model = None
        if not text_model:
            for doc in storage.list_documents("ai_models"):
                if doc.get("modelType") == "text" and doc.get("enabled"):
                    text_model = doc
                    break

        if text_model:
            system_prompt = (
                "你是一位专业的影视级 AI 视频分镜提示词优化大师。\n"
                "用户在生成 AI 视频（如 Muse、Kling、Seedance 等）时，遇到了上游拒答、审核不通过或生成失败。\n"
                "你的任务是：根据【当前提示词】与具体的【失败/拒答/报错原因】，进行针对性的深度分析与动态智能润色，确保既保留原剧情核心镜头要素，又彻底排除导致审核拦截或模型生成失败的因素。\n\n"
                "【重要优化原则（拒绝机械套用固定模板，必须动态针对具体原因修复）】：\n"
                "1. 针对具体报错动态修复：\n"
                "   - 若报错涉及文本违规/敏感拒答（如 upstream replied with text only / 敏感 / 违规 / 暴力等）：\n"
                "     重点排查并剔除或重构“爆炸”、“炸毁”、“流血”、“武器”、“残暴”等敏感词。切记：哪怕原提示词写的是否定句（如“不拍爆炸”、“无血腥”），否定句里的敏感词依然会命中过滤模型！必须将“不拍爆炸”彻底删除，将剧烈物理动态转化为合规的视觉物理反应（如“猛烈震动”、“强烈晃动”、“冲击波气浪”、“墨水飞溅”）。\n"
                "   - 若报错涉及声音描写（如“笔尖沙沙声”、“沉闷巨响，声音在前”等非画面听觉词）：\n"
                "     视频生成模型无法渲染声音逻辑，剥离听觉词或将其转化为纯视觉动作（如“笔尖在纸上快速划过”、“书桌剧烈震颤，煤油灯翻倒熄灭”）。\n"
                "   - 若报错涉及复杂冲突时间轴或肢体负向指令（如“不允许画反”）：\n"
                "     转化为正面姿态描写（如“第一人称POV俯视视角，右手稳定持笔书写”），动作顺畅连贯。\n"
                "2. 保持剧情连贯与电影质感：\n"
                "   - 保留镜头中出场角色的关键道具（如口琴）、场景环境（如夜色街道）、动作起点与终点。\n"
                "   - 叙述流畅生动，镜头感强。\n"
                "3. 输出格式要求：\n"
                "   - 只输出优化后的最终分镜提示词正文。\n"
                "   - 绝不要带有“优化后：”、“好的”、“根据你的要求”等任何解释或前后缀说明。"
            )
            user_content = f"分镜标题：{title}\n报错/拒答原因：{error or '常规安全审核与画面动态优化'}\n当前提示词：\n{prompt}"
            try:
                res = self._generate_chat(storage, {
                    "model": text_model.get("id") or text_model.get("modelName"),
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.4
                })
                text = self._chat_result_text(res)
                text = re.sub(r"^```[a-zA-Z]*\n?", "", text).rstrip("`").strip()
                text = re.sub(r"^(?:优化后提示词|优化后的提示词|优化后|润色后)[：:\s]*", "", text).strip()
                if text:
                    return {"ok": True, "optimized": text, "source": "ai", "model": text_model.get("name", "AI文本模型")}
            except Exception:
                pass

        optimized = self._rule_based_prompt_optimization(prompt, error)
        return {"ok": True, "optimized": optimized, "source": "rules"}

    @staticmethod
    def _rule_based_prompt_optimization(prompt: str, error: str) -> str:
        text = prompt

        # 1. Eliminate explicit negative constraints and sensitive words
        text = re.sub(r"[，,、\s]*只拍[^，,。\n]*?不拍[^，,。\n]*?(?=[，,。\n]|$)", "", text)
        text = re.sub(r"[，,、\s]*不拍[^\s，,。\n]*?(?=[，,。\n]|$)", "", text)
        text = re.sub(r"[，,、\s]*不允许画反", "", text)
        text = re.sub(r"[，,、\s]*禁止[^\s，,。\n]*?(?=[，,。\n]|$)", "", text)
        text = re.sub(r"[，,、\s]*不能[^\s，,。\n]*?(?=[，,。\n]|$)", "", text)

        # Replace explosion/violent triggers with visual physics
        text = re.sub(r"爆炸|炸开|炸碎|巨炸", "剧烈震颤冲击", text)
        text = re.sub(r"血腥|残暴|砍杀|割喉", "猛烈冲击", text)

        # 2. Convert audio-only sound cues into visual dynamic cues
        text = re.sub(r"[，,、\s]*笔尖沙沙声", "", text)
        text = re.sub(r"[，,、\s]*声音在前", "", text)
        text = re.sub(r"[，,、\s]*(?:远处|近处)?(?:先)?(?:传来)?沉闷巨响", "突然桌面猛烈晃动", text)
        text = re.sub(r"[，,、\s]*(?:传来)?(?:巨响|轰鸣声|爆炸声)", "猛烈震颤冲击", text)
        text = re.sub(r"[，,、\s]*(?:清晰的)?脚步声", "快步走动", text)
        text = re.sub(r"[，,、\s]*(?:刺耳的)?刹车声", "车辆急停晃动", text)

        # 3. Clean up punctuation artifacts
        text = re.sub(r"[，,]{2,}", "，", text)
        text = re.sub(r"[。]{2,}", "。", text)
        text = re.sub(r"^[，,。、\s]+", "", text)
        text = re.sub(r"[，,、\s]+(?=[。])", "", text)
        text = re.sub(r"[，,]\n", "\n", text)
        return text.strip()

    @staticmethod
    def _chat_result_text(result: dict[str, Any]) -> str:
        """Extract text from common OpenAI-compatible and Anthropic responses."""
        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if content is None and isinstance(choices[0], dict):
                content = choices[0].get("text")
            if isinstance(content, list):
                content = "".join(str(item.get("text") or item.get("content") or "")
                                   if isinstance(item, dict) else str(item) for item in content)
            if isinstance(content, str) and content.strip():
                return content.strip()
        content = result.get("content")
        if isinstance(content, list):
            content = "".join(str(item.get("text") or item.get("content") or "")
                               if isinstance(item, dict) else str(item) for item in content)
        for candidate in (content, result.get("output_text"), result.get("text")):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        raise StorageError(502, "文本模型没有返回可读取的文字内容")

    @staticmethod
    def _parse_script_to_shots(script_text: str, consistency: dict[str, Any]) -> list[dict[str, Any]]:
        from script_shot_contract import parse_script_shots
        return parse_script_shots(script_text, consistency)

    @staticmethod
    def _parse_creation_json(text: str, script_text: str = "") -> dict[str, Any]:
        if not text or not str(text).strip():
            raise StorageError(502, "文本模型未返回任何内容")

        cleaned = str(text or "").replace("\ufeff", "").strip()
        # 1. 移除 DeepSeek / Qwen 等思考模型的 <think>...</think> 思考链
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE).strip()

        # 2. 提取 markdown 代码块（如果存在）
        code_block = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", cleaned, flags=re.IGNORECASE)
        if code_block:
            candidate = code_block.group(1).strip()
        else:
            # 找到最外层的 {
            start = cleaned.find("{")
            if start >= 0:
                candidate = cleaned[start:].strip()
            else:
                candidate = cleaned

        def clean_json_str(s: str) -> str:
            # 移除行尾注释 // 与 /* */
            s = re.sub(r"//.*?\n", "\n", s)
            s = re.sub(r"/\*[\s\S]*?\*/", "", s)
            # 移除对象或数组末尾的多余逗号（如 {"a": 1,} 或 [1, 2,]）
            s = re.sub(r",\s*([\}\]])", r"\1", s)
            return s.strip()

        candidate = clean_json_str(candidate)

        # 尝试标准 json.loads（关闭严格转义，容许字符串内未转义换行/制表符）
        document: dict[str, Any] | None = None
        try:
            doc = json.loads(candidate, strict=False)
            if isinstance(doc, dict):
                document = doc
        except Exception:
            pass

        # 核心恢复算法：针对长输出被截断的情况，从后向前扫描最后一个完整的对象/数组闭合点并补齐外层结构
        if document is None:
            pos = len(candidate)
            while pos > 0:
                last_brace = candidate.rfind("}", 0, pos)
                if last_brace < 0:
                    break
                cand = candidate[:last_brace + 1].strip()
                open_sq = cand.count("[") - cand.count("]")
                open_cu = cand.count("{") - cand.count("}")
                attempt = cand + ("]" * max(0, open_sq)) + ("}" * max(0, open_cu))
                attempt = clean_json_str(attempt)
                try:
                    doc = json.loads(attempt, strict=False)
                    if isinstance(doc, dict) and (doc.get("consistency") or doc.get("characters") or doc.get("shots")):
                        document = doc
                        break
                except Exception:
                    pass
                pos = last_brace

        # 若仍然失败，尝试 ast.literal_eval（兼容单引号 Python 字典格式）
        if document is None:
            try:
                doc = ast.literal_eval(candidate)
                if isinstance(doc, dict):
                    document = doc
            except Exception:
                pass

        if not isinstance(document, dict):
            raise StorageError(502, "文本模型返回的内容不是合法 JSON，请降低模型温度后重试")

        if not document.get("shots") and isinstance(document.get("consistency"), dict) and document["consistency"].get("shots"):
            document["shots"] = document["consistency"]["shots"]
        if not document.get("shots") and isinstance(document.get("assets"), dict) and document["assets"].get("shots"):
            document["shots"] = document["assets"]["shots"]
        if not isinstance(document.get("shots"), list):
            document["shots"] = []

        from script_shot_contract import ensure_script_shot_coverage
        try:
            document = ensure_script_shot_coverage(document, script_text)
        except ValueError as exc:
            raise StorageError(502, str(exc)) from exc

        has_assets = any(document.get(key) for key in ("characters", "roles", "people", "scenes", "props", "items", "audio", "audios"))
        consistency = document.get("consistency")
        if isinstance(consistency, dict):
            has_assets = has_assets or any(consistency.get(key) for key in ("characters", "roles", "people", "scenes", "props", "items", "audio", "audios"))
        if not has_assets and not document.get("shots"):
            if not document.get("consistency") and isinstance(document.get("assets"), dict):
                document["consistency"] = document["assets"]
            else:
                raise StorageError(502, "文本模型返回的数据既没有资产也没有分镜")

        # 建立资产规范名称映射，杜绝同物异名分裂
        canonical_names = {}
        cons_obj = document.get("consistency") if isinstance(document.get("consistency"), dict) else document
        for grp in ("characters", "roles", "people", "scenes", "props", "items", "audio", "audios"):
            items = cons_obj.get(grp)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get("id") and item.get("name"):
                        canonical_names[str(item["id"])] = str(item["name"])
                        canonical_names[str(item["id"]).lower()] = str(item["name"])

        # 校验并同步 shots 中的 wirelist 命名
        if canonical_names and isinstance(document.get("shots"), list):
            for s in document["shots"]:
                if isinstance(s, dict):
                    wirelist = s.get("wirelist")
                    if isinstance(wirelist, list):
                        for w in wirelist:
                            if isinstance(w, dict) and w.get("asset_id") in canonical_names:
                                w["name"] = canonical_names[w["asset_id"]]
        return document

    def _generate_script(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._resolve_ai_model(storage, "text", body.get("model"))
        title = str(body.get("title") or "未命名章节").strip()
        source_text = str(body.get("sourceText") or "").strip()
        requirements = str(body.get("requirements") or "").strip()
        if not source_text:
            raise StorageError(400, "请先输入或导入章节原文")
        if len(source_text) > 50000:
            raise StorageError(400, "章节原文不能超过 50000 个字符")
        if len(requirements) > 5000:
            raise StorageError(400, "剧本要求不能超过 5000 个字符")
        project_type = str(body.get("projectType") or body.get("type") or "drama").strip().lower()
        genre = str(body.get("genre") or (body.get("storyGenres")[0] if isinstance(body.get("storyGenres"), list) and body.get("storyGenres") else "") or body.get("storyGenre") or "").strip()
        try:
            import skill_loader
            system = skill_loader.build_script_system_prompt(project_type, genre=genre)
        except Exception:
            system = """你是 CDTV 内置的工业级视觉编剧总控引擎。请生成可直接进入 AI 资产与分镜制作的高质量脚本。"""
        user = f"""章节标题：{title}

额外要求：
{requirements or '保持原文风格，改编为节奏紧凑、戏剧冲突饱满、可用于连续短剧制作的剧本。'}

章节原文：
{source_text}

请直接输出完整剧本正文。"""
        script_max_tokens = int(model.get("maxTokens") or 16000)
        if model.get("contextWindow") and not model.get("maxTokens"):
            script_max_tokens = min(32000, max(16000, int(model["contextWindow"] // 4)))
        is_anthropic = urlparse(model["apiUrl"]).path.rstrip("/").endswith("/messages")
        if is_anthropic:
            endpoint = self._ai_endpoint(model["apiUrl"], "/messages")
            payload = {
                "model": model["modelName"], "system": system,
                "messages": [{"role": "user", "content": user}],
                "max_tokens": script_max_tokens, "temperature": 0.35,
            }
            headers = {"anthropic-version": "2023-06-01"}
            if str(model.get("apiKey") or "").strip():
                headers["x-api-key"] = str(model["apiKey"]).strip()
        else:
            endpoint = self._ai_endpoint(model["apiUrl"], "/chat/completions")
            payload = {
                "model": model["modelName"],
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.35, "max_tokens": min(script_max_tokens, 32768), "stream": True,
            }
            headers = {}
        try:
            result = self._request_ai_json(model, endpoint, "剧本生成", payload, headers)
        except Exception as first_script_err:
            if not is_anthropic and payload.get("stream"):
                try:
                    retry_p = dict(payload)
                    retry_p["stream"] = False
                    result = self._request_ai_json(model, endpoint, "剧本生成", retry_p, headers)
                except Exception:
                    raise first_script_err
            else:
                raise first_script_err
        return {"script": self._chat_result_text(result), "model": model.get("modelName", "")}

    def _generate_creation_data(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._resolve_ai_model(storage, "text", body.get("model"))
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise StorageError(400, "请先输入小说、故事或创作需求")
        if len(prompt) > 30000:
            raise StorageError(400, "创作需求不能超过 30000 个字符")
        scope = str(body.get("scope") or "full").strip().lower()
        title = str(body.get("title") or "").strip()
        project_type = str(body.get("projectType") or body.get("type") or "drama").strip().lower()
        genre = str(body.get("genre") or (body.get("storyGenres")[0] if isinstance(body.get("storyGenres"), list) and body.get("storyGenres") else "") or body.get("storyGenre") or "").strip()
        try:
            import skill_loader
            system = skill_loader.build_creation_data_system_prompt(project_type, genre=genre)
        except Exception:
            system = """你是 CDTV 创作数据编排器。请把剧本提炼成结构化创作数据 JSON。包含 characters, scenes, props, audio, asset_wirelist, shots。"""
        user = f"""项目标题：{title or '短剧第一集'}

创作需求与剧本内容：
{prompt}

请直接输出紧凑完整的 JSON 对象，无需过多冗长思考链，确保全部角色、场景、道具与分镜完整闭合。"""
        creation_max_tokens = min(int(model.get("maxTokens") or 16384), 32768)
        if model.get("contextWindow") and not model.get("maxTokens"):
            creation_max_tokens = min(32768, max(8192, int(model["contextWindow"] // 4)))
        is_anthropic = urlparse(model["apiUrl"]).path.rstrip("/").endswith("/messages")
        if is_anthropic:
            endpoint = self._ai_endpoint(model["apiUrl"], "/messages")
            payload = {
                "model": model["modelName"], "system": system,
                "messages": [{"role": "user", "content": user}],
                "max_tokens": creation_max_tokens, "temperature": 0.2,
            }
            headers = {"anthropic-version": "2023-06-01"}
            if str(model.get("apiKey") or "").strip():
                headers["x-api-key"] = str(model["apiKey"]).strip()
        else:
            endpoint = self._ai_endpoint(model["apiUrl"], "/chat/completions")
            payload = {
                "model": model["modelName"],
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.2, "max_tokens": creation_max_tokens, "stream": True,
            }
            headers = {}
        try:
            result = self._request_ai_json(model, endpoint, "创作数据生成", payload, headers, timeout=600.0)
            text = self._chat_result_text(result)
            document = self._parse_creation_json(text, script_text=str(body.get("script") or prompt))
        except Exception as primary_err:
            if not is_anthropic and payload.get("stream"):
                try:
                    retry_payload = dict(payload)
                    retry_payload["stream"] = False
                    result = self._request_ai_json(model, endpoint, "创作数据生成", retry_payload, headers, timeout=600.0)
                    text = self._chat_result_text(result)
                    document = self._parse_creation_json(text, script_text=str(body.get("script") or prompt))
                except Exception:
                    raise primary_err
            else:
                raise primary_err
        return {
            "document": document,
            "text": json.dumps(document, ensure_ascii=False, indent=2),
            "model": model.get("modelName", ""),
        }

    @staticmethod
    def _video_submit_candidates(api_url: str, model_name: str = "") -> list[str]:
        raw = api_url.strip().rstrip("/")
        parsed = urlparse(raw)
        path = parsed.path.rstrip("/")
        base = f"{parsed.scheme}://{parsed.netloc}"
        clean_model = str(model_name or "").strip()

        # 1. 匹配 AutoDL ComfyUI 工作流 / 自定义工作流 API 或本地/云端 ComfyUI (8188 / 6006)
        is_workflow = (
            "comfyui_workflow" in path
            or "autodl" in parsed.netloc.lower()
            or "comfy" in raw.lower()
            or "workflow" in raw.lower()
            or parsed.port in {8188, 6006}
            or "8188" in raw
        )
        if "comfyui_workflow" in path:
            candidates = []
            if clean_model:
                if path.endswith("/comfyui_workflow"):
                    candidates.append(f"{raw}/{clean_model}")
                else:
                    base_wf = raw.rsplit("/", 1)[0]
                    candidates.append(f"{base_wf}/{clean_model}")
            candidates.append(raw)
            return candidates
        if is_workflow:
            candidates = [raw]
            if clean_model:
                candidates.insert(0, f"{base}/api/v1/comfyui/comfyui_workflow/{clean_model}")
                candidates.append(f"{raw}/api/v1/comfyui/comfyui_workflow/{clean_model}")
                candidates.append(f"{raw}/comfyui/comfyui_workflow/{clean_model}")
                candidates.append(f"{raw}/{clean_model}")
            candidates.append(f"{base}/prompt")
            candidates.append(f"{raw}/prompt")
            dedup = []
            for c in candidates:
                if c and c not in dedup:
                    dedup.append(c)
            return dedup

        if path.endswith(("/tasks", "/video/generations", "/videos/generations", "/generations")):
            return [raw]
        candidates = []
        if path in {"/v1", ""}:
            candidates.append(f"{base}/v1/videos/generations")
            candidates.append(f"{base}/v1/video/generations")
            candidates.append(f"{base}/v1/tasks")
            candidates.append(f"{base}/tasks")
        else:
            candidates.append(f"{raw}/videos/generations")
            candidates.append(f"{raw}/video/generations")
            candidates.append(f"{raw}/tasks")
        return candidates

    @staticmethod
    def _video_poll_candidates(api_url: str, task_id: str) -> list[str]:
        raw = api_url.strip().rstrip("/")
        parsed = urlparse(raw)
        path = parsed.path.rstrip("/")
        base = f"{parsed.scheme}://{parsed.netloc}"

        # 1. 匹配 AutoDL ComfyUI 工作流 / 自定义工作流轮询
        if "comfyui" in raw.lower() or "autodl.com" in parsed.netloc or "workflow" in raw.lower() or parsed.port in {8188, 6006} or "8188" in raw:
            candidates = [
                f"{base}/api/v1/comfyui/comfyui_workflow/result/{task_id}",
                f"{base}/comfyui/comfyui_workflow/result/{task_id}",
                f"{base}/history/{task_id}",
                f"{raw}/result/{task_id}",
                f"{raw}/{task_id}",
            ]
            dedup = []
            for c in candidates:
                if c and c not in dedup:
                    dedup.append(c)
            return dedup

        if path.endswith(("/tasks", "/video/generations", "/videos/generations", "/generations")):
            return [f"{raw}/{task_id}"]
        candidates = []
        if path in {"/v1", ""}:
            candidates.append(f"{base}/v1/videos/generations/{task_id}")
            candidates.append(f"{base}/v1/video/generations/{task_id}")
            candidates.append(f"{base}/v1/tasks/{task_id}")
            candidates.append(f"{base}/tasks/{task_id}")
        else:
            candidates.append(f"{raw}/videos/generations/{task_id}")
            candidates.append(f"{raw}/video/generations/{task_id}")
            candidates.append(f"{raw}/tasks/{task_id}")
        return candidates

    def _extract_video_last_frame(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        import cv2, tempfile, urllib.request
        file_id = str(body.get("fileId") or "").strip()
        url = str(body.get("url") or "").strip()
        path_val = str(body.get("path") or "").strip()

        content_bytes = b""
        if path_val and os.path.exists(path_val):
            try:
                with open(path_val, "rb") as fp:
                    content_bytes = fp.read()
            except Exception:
                pass

        if not file_id and url and "/file/" in url:
            m = re.search(r"/file/([^/?#]+)", url)
            if m:
                file_id = m.group(1)

        if not content_bytes and file_id:
            try:
                meta = storage.find_file(file_id)
                content_bytes = storage.read_file_content(meta["bucket"], file_id)
            except Exception:
                for b in ["files", "generated-videos", "assets"]:
                    try:
                        content_bytes = storage.read_file_content(b, file_id)
                        if content_bytes:
                            break
                    except Exception:
                        pass

        if not content_bytes and url:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content_bytes = resp.read()
            except Exception as e:
                raise StorageError(500, f"下载视频失败: {e}")

        if not content_bytes:
            raise StorageError(404, "未能读取到有效视频文件")

        temp_fd, temp_path = tempfile.mkstemp(suffix=".mp4")
        try:
            with open(temp_fd, "wb") as f:
                f.write(content_bytes)
            cap = cv2.VideoCapture(temp_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                raise StorageError(500, "无法解析视频帧数")
            # 优先读取倒数第二帧以防末尾全黑帧
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - 2))
            ret, frame = cap.read()
            if not ret or frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - 1))
                ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                raise StorageError(500, "提取视频尾帧失败")

            success, buffer = cv2.imencode(".png", frame)
            if not success:
                raise StorageError(500, "尾帧编码失败")
            png_bytes = buffer.tobytes()
            saved = storage.save_file(
                bucket="files",
                content=png_bytes,
                filename="last_frame.png",
                content_type="image/png"
            )
            return {
                "fileId": saved["id"],
                "url": f"/file/{saved['id']}/download",
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
                "success": True,
            }
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    def _extract_custom_frame(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        import cv2, numpy as np, tempfile, urllib.request
        file_id = str(body.get("fileId") or "").strip()
        url = str(body.get("url") or "").strip()
        path_val = str(body.get("path") or "").strip()
        position = str(body.get("position") or "last")
        timestamp = float(body.get("timestamp") or 0)
        fraction = float(body.get("fraction") or 0.95)
        compare_file_id = str(body.get("compareFileId") or "").strip()
        continuity_threshold = max(0.01, min(0.5, float(body.get("continuityThreshold") or 0.085)))

        content_bytes = b""
        if path_val and os.path.exists(path_val):
            try:
                with open(path_val, "rb") as fp:
                    content_bytes = fp.read()
            except Exception:
                pass

        if not file_id and url and "/file/" in url:
            m = re.search(r"/file/([^/?#]+)", url)
            if m:
                file_id = m.group(1)

        if not content_bytes and file_id:
            try:
                meta = storage.find_file(file_id)
                content_bytes = storage.read_file_content(meta["bucket"], file_id)
            except Exception:
                for b in ["files", "generated-videos", "assets"]:
                    try:
                        content_bytes = storage.read_file_content(b, file_id)
                        if content_bytes:
                            break
                    except Exception:
                        pass
        elif not content_bytes and url:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content_bytes = resp.read()
            except Exception as e:
                raise StorageError(500, f"下载视频失败: {e}")

        if not content_bytes:
            raise StorageError(404, "未能读取到有效视频文件")

        temp_fd, temp_path = tempfile.mkstemp(suffix=".mp4")
        try:
            with open(temp_fd, "wb") as f:
                f.write(content_bytes)
            cap = cv2.VideoCapture(temp_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
            if total_frames <= 0:
                raise StorageError(500, "无法解析视频帧数")

            if position == "first":
                target_frame = 0
            elif position == "timestamp":
                target_frame = int(round(timestamp * fps))
            elif position == "fraction":
                target_frame = int(round(total_frames * fraction))
            else:
                target_frame = max(0, total_frames - 2)

            target_frame = max(0, min(total_frames - 1, target_frame))
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()
            if not ret or frame is None:
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - 2))
                ret, frame = cap.read()
            cap.release()
            if not ret or frame is None:
                raise StorageError(500, "提取视频指定帧失败")

            success, buffer = cv2.imencode(".png", frame)
            if not success:
                raise StorageError(500, "动作帧编码失败")
            png_bytes = buffer.tobytes()
            saved = storage.save_file(
                bucket="files",
                content=png_bytes,
                filename="action_frame.png",
                content_type="image/png"
            )
            result = {
                "fileId": saved["id"],
                "url": f"/file/{saved['id']}/download",
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
                "frameIndex": target_frame,
                "totalFrames": total_frames,
                "timestamp": round(target_frame / max(1.0, fps), 2),
                "fps": round(fps, 2),
                "success": True,
            }
            if compare_file_id:
                compare_bytes = b""
                try:
                    compare_meta = storage.find_file(compare_file_id)
                    compare_bytes = storage.read_file_content(compare_meta["bucket"], compare_file_id)
                except Exception:
                    for compare_bucket in ["files", "generated-images", "assets"]:
                        try:
                            compare_bytes = storage.read_file_content(compare_bucket, compare_file_id)
                            if compare_bytes:
                                break
                        except Exception:
                            pass
                if not compare_bytes:
                    raise StorageError(404, "未找到用于续接检查的上一镜尾帧")
                compare_image = cv2.imdecode(np.frombuffer(compare_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if compare_image is None:
                    raise StorageError(400, "无法解码用于续接检查的上一镜尾帧")
                resized = cv2.resize(compare_image, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_AREA)
                continuity_mae = float(np.mean(cv2.absdiff(frame, resized))) / 255.0
                result.update({
                    "continuityMae": round(continuity_mae, 5),
                    "continuityThreshold": continuity_threshold,
                    "continuityPassed": continuity_mae <= continuity_threshold,
                    "comparedFileId": compare_file_id,
                })
            return result
        finally:
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    def _crop_matrix_cell(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        import cv2, numpy as np, urllib.request
        file_id = str(body.get("fileId") or "").strip()
        url = str(body.get("url") or "").strip()
        cell_index = int(body.get("cellIndex", 0))
        rows = int(body.get("rows", 3))
        cols = int(body.get("cols", 3))

        content_bytes = b""
        if not file_id and url and "/file/" in url:
            m = re.search(r"/file/([^/?#]+)", url)
            if m:
                file_id = m.group(1)

        if not content_bytes and file_id:
            try:
                meta = storage.find_file(file_id)
                content_bytes = storage.read_file_content(meta["bucket"], file_id)
            except Exception:
                for b in ["files", "generated-images", "assets"]:
                    try:
                        content_bytes = storage.read_file_content(b, file_id)
                        if content_bytes:
                            break
                    except Exception:
                        pass
        elif not content_bytes and url:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content_bytes = resp.read()
            except Exception as e:
                raise StorageError(500, f"下载九宫格图片失败: {e}")

        if not content_bytes:
            raise StorageError(404, "未能读取到九宫格图片数据")

        arr = np.frombuffer(content_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise StorageError(400, "无法解码九宫格图像")

        h, w = img.shape[:2]
        if rows != 3 or cols != 3 or cell_index < 0 or cell_index >= 9:
            raise StorageError(400, "机位索引无效，请重新选择九宫格机位")
        r = cell_index // cols
        c = cell_index % cols

        # The index page contains a title band and gutters. Equal thirds include
        # the title and cut every panel. Detect long panel borders, then fill any
        # missing internal border from the generator's regular layout.
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 145)
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=max(55, int(min(w, h) * 0.055)),
            minLineLength=max(80, int(min(w, h) * 0.18)),
            maxLineGap=max(8, int(min(w, h) * 0.01)),
        )

        x_values: list[int] = []
        y_values: list[int] = []
        if lines is not None:
            for x_start, y_start, x_end, y_end in lines.reshape(-1, 4):
                dx, dy = abs(int(x_end) - int(x_start)), abs(int(y_end) - int(y_start))
                if dx <= max(4, int(w * 0.003)) and dy >= int(h * 0.20):
                    x_values.append(int(round((int(x_start) + int(x_end)) / 2)))
                if dy <= max(4, int(h * 0.004)) and dx >= int(w * 0.18):
                    y_values.append(int(round((int(y_start) + int(y_end)) / 2)))

        def clustered(values: list[int], tolerance: int) -> list[int]:
            result: list[list[int]] = []
            for value in sorted(values):
                if not result or value - result[-1][-1] > tolerance:
                    result.append([value])
                else:
                    result[-1].append(value)
            return [int(round(sum(group) / len(group))) for group in result]

        x_lines = clustered(x_values, max(3, int(w * 0.003)))
        y_lines = clustered(y_values, max(3, int(h * 0.004)))
        x_outer = [value for value in x_lines if int(w * 0.015) <= value <= int(w * 0.985)]
        y_top_candidates = [value for value in y_lines if int(h * 0.07) <= value <= int(h * 0.22)]
        y_bottom_candidates = [value for value in y_lines if int(h * 0.75) <= value <= int(h * 0.985)]

        grid_left = min(x_outer) if x_outer else int(round(w * 0.03))
        grid_right = max(x_outer) if x_outer else int(round(w * 0.97))
        grid_top = min(y_top_candidates) if y_top_candidates else int(round(h * 0.094))
        grid_bottom = max(y_bottom_candidates) if y_bottom_candidates else int(round(h * 0.965))

        def divider_pair(values: list[int], target: float, tolerance: float, min_gap: int, max_gap: int):
            nearby = [value for value in values if abs(value - target) <= tolerance]
            pairs = [
                (left, right)
                for left in nearby
                for right in nearby
                if min_gap <= right - left <= max_gap
            ]
            if not pairs:
                return None
            return min(pairs, key=lambda pair: abs(((pair[0] + pair[1]) / 2) - target))

        x_targets = [grid_left + (grid_right - grid_left) * step / 3 for step in (1, 2)]
        y_targets = [grid_top + (grid_bottom - grid_top) * step / 3 for step in (1, 2)]
        x_pairs = [
            divider_pair(x_lines, target, w * 0.075, max(5, int(w * 0.004)), int(w * 0.035))
            for target in x_targets
        ]
        y_pairs = [
            divider_pair(y_lines, target, h * 0.075, max(5, int(h * 0.005)), int(h * 0.045))
            for target in y_targets
        ]

        detected_x_gaps = [pair[1] - pair[0] for pair in x_pairs if pair]
        detected_y_gaps = [pair[1] - pair[0] for pair in y_pairs if pair]
        gap_x = int(round(float(np.median(detected_x_gaps)))) if detected_x_gaps else int(round(w * 0.009))
        gap_y = int(round(float(np.median(detected_y_gaps)))) if detected_y_gaps else int(round(h * 0.016))
        panel_w = (grid_right - grid_left - 2 * gap_x) / 3
        panel_h = (grid_bottom - grid_top - 2 * gap_y) / 3

        for index, pair in enumerate(x_pairs):
            if pair is None:
                end = int(round(grid_left + panel_w * (index + 1) + gap_x * index))
                x_pairs[index] = (end, end + gap_x)
        for index, pair in enumerate(y_pairs):
            if pair is None:
                end = int(round(grid_top + panel_h * (index + 1) + gap_y * index))
                y_pairs[index] = (end, end + gap_y)

        x_bounds = [
            (grid_left, x_pairs[0][0]),
            (x_pairs[0][1], x_pairs[1][0]),
            (x_pairs[1][1], grid_right),
        ]
        y_bounds = [
            (grid_top, y_pairs[0][0]),
            (y_pairs[0][1], y_pairs[1][0]),
            (y_pairs[1][1], grid_bottom),
        ]
        x1, x2 = x_bounds[c]
        y1, y2 = y_bounds[r]
        inset_x = max(2, int(round(w * 0.0015)))
        inset_y = max(2, int(round(h * 0.002)))
        x1, x2 = max(0, x1 + inset_x), min(w, x2 - inset_x)
        y1, y2 = max(0, y1 + inset_y), min(h, y2 - inset_y)
        if x2 - x1 < w * 0.18 or y2 - y1 < h * 0.16:
            raise StorageError(500, "未能识别完整的九宫格面板边界，请重新生成矩阵")

        crop = img[y1:y2, x1:x2].copy()

        # Each panel has a dark caption plaque in its lower-left corner. Inpaint
        # that plaque rather than chopping off the bottom of the image.
        crop_h, crop_w = crop.shape[:2]
        label_y = int(crop_h * 0.72)
        label_x = int(crop_w * 0.62)
        label_roi = cv2.cvtColor(crop[label_y:, :label_x], cv2.COLOR_BGR2GRAY)
        bright = cv2.inRange(label_roi, 170, 255)
        bright = cv2.morphologyEx(
            bright,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3)),
            iterations=1,
        )
        contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        text_parts = []
        for contour in contours:
            bx, by, bw, bh = cv2.boundingRect(contour)
            if (
                bw >= 3
                and bh >= 4
                and bh <= crop_h * 0.11
                and by + bh >= label_roi.shape[0] * 0.62
                and bx <= crop_w * 0.55
            ):
                text_parts.append((bx, by, bw, bh))

        groups: list[list[tuple[int, int, int, int]]] = []
        for part in sorted(text_parts, key=lambda item: item[1] + item[3] / 2):
            center = part[1] + part[3] / 2
            matching = next(
                (
                    group
                    for group in groups
                    if abs(center - np.mean([item[1] + item[3] / 2 for item in group])) <= max(6, crop_h * 0.025)
                ),
                None,
            )
            if matching is None:
                groups.append([part])
            else:
                matching.append(part)

        candidates = []
        for group in groups:
            left = min(item[0] for item in group)
            top = min(item[1] for item in group)
            right = max(item[0] + item[2] for item in group)
            bottom = max(item[1] + item[3] for item in group)
            total_width = sum(item[2] for item in group)
            if total_width >= crop_w * 0.08 and left <= crop_w * 0.12:
                candidates.append((total_width, left, top, right - left, bottom - top))

        label_cleaned = False
        if candidates:
            _, bx, by, bw, bh = max(candidates)
            margin_x = max(10, int(crop_w * 0.025))
            margin_y = max(8, int(crop_h * 0.025))
            mask = np.zeros((crop_h, crop_w), dtype=np.uint8)
            left = max(0, bx - margin_x)
            top = max(0, label_y + by - margin_y)
            right = min(crop_w, bx + bw + margin_x)
            bottom = min(crop_h, label_y + by + bh + margin_y)
            cv2.rectangle(mask, (left, top), (right, bottom), 255, thickness=-1)
            crop = cv2.inpaint(crop, mask, 4, cv2.INPAINT_NS)
            label_cleaned = True
        success, buffer = cv2.imencode(".png", crop)
        if not success:
            raise StorageError(500, "机位图像编码失败")

        png_bytes = buffer.tobytes()
        saved = storage.save_file(
            bucket="files",
            content=png_bytes,
            filename=f"camera_matrix_cell_{cell_index}.png",
            content_type="image/png"
        )
        return {
            "fileId": saved["id"],
            "url": f"/file/{saved['id']}/download",
            "width": int(crop.shape[1]),
            "height": int(crop.shape[0]),
            "cellIndex": cell_index,
            "cropBounds": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
            "labelCleaned": label_cleaned,
            "success": True,
        }

    def _generate_camera_matrix(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        file_id = str(body.get("fileId") or "").strip()
        url = str(body.get("url") or "").strip()
        if not file_id and not url:
            raise StorageError(400, "请先提取上一镜尾帧，再生成机位矩阵")
        custom_prompt = str(body.get("prompt") or "").strip()
        
        matrix_prompt = custom_prompt or (
            "分析输入这张图的整体构图。识别所有出现的关键主体（无论是单人、群体/情侣、车辆还是特定物体）及空间关系与互动。"
            "生成一张和谐统一的3×3矩阵“电影镜头索引页”，在相同环境中展示这组主体的9个不同摄影镜头（你必须根据内容调整标准电影镜头类型）：\n"
            "第一排（交代环境）：\n"
            "1. 大远景(ELS)：主体在广阔的环境中显得很小。\n"
            "2. 全景(LS)：完整展示主体或群体（从头到脚/从车轮到车顶）。\n"
            "3. 中远景（美式/3-4镜头）：从膝盖以上构图（人物），或展示物体的3/4视图。\n"
            "第二排（核心覆盖）：\n"
            "4. 中景(MS)：从腰部以上构图（或物体的核心部分）。重点表现互动或动作。\n"
            "5. 中特写(MCU)：从胸部以上构图。对主要主体进行亲密感构图。\n"
            "6. 特写(CU)：紧凑构图，聚焦于面部或物体的“正面”。\n"
            "第三排（细节与角度）：\n"
            "7. 大特写(ECU)：宏观细节，强烈聚焦于关键特征（眼睛、手部、Logo、纹理）。\n"
            "8. 低角度镜头（虫瞻位）：从地面向上仰视主体（营造庄严/英雄感）。\n"
            "9. 高角度镜头（鸟瞰位）：从上方俯视主体。\n"
            "确保严格的一致性：\n"
            "9个面板中必须保持相同的人物/物体、相同的服装和相同的光影。景深应随景别真实变化（特写镜头应有背景虚化）。\n"
            "排版要求：九个面板必须严格对齐并使用清晰等宽间隔；每个面板保留完整画面。编号和镜头名称只能放在面板下方独立标签栏，严禁覆盖人物、物体或画面内容，方便后期无损拆分。\n"
            "一张包含9个面板的专业 3×3电影分镜矩阵图。该矩阵以全方位的焦段范围展示输入图像中的特定主体/场景。顶排：宽广环境图、全景图、3/4剪裁图。中排：腰部以上视角、胸部以上视角、面部/正面特写。底排：宏观细节角度仰拍、高角度俯拍。所有画框均具备写实纹理、一致的电影级调色，并针对所分析的主体数量进行准确构图。"
        )

        image_ref = ""
        # 优先直接从本地存储直接读取图片转为 Base64，彻底避免 HTTP 回环端口阻塞与代理超时
        if file_id:
            raw_bytes = b""
            try:
                meta = storage.find_file(file_id)
                raw_bytes = storage.read_file_content(meta["bucket"], file_id)
            except Exception:
                for b in ["files", "generated-videos", "assets"]:
                    try:
                        raw_bytes = storage.read_file_content(b, file_id)
                        if raw_bytes:
                            break
                    except Exception:
                        pass
            if raw_bytes:
                try:
                    with Image.open(io.BytesIO(raw_bytes)) as reference:
                        mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[reference.format]
                except (OSError, KeyError) as exc:
                    raise StorageError(400, "尾帧图片无法读取，请重新提取尾帧") from exc
                image_ref = f"data:{mime};base64,{base64.b64encode(raw_bytes).decode('ascii')}"

        if not image_ref:
            if url:
                image_ref = url
            elif file_id:
                image_ref = f"/file/{file_id}/download"

        # 智能匹配图片模型：优先使用传入的指定模型，未指定则自动选用系统中已启用的第一个图片模型
        selected_model = str(body.get("model") or "").strip()
        if not selected_model:
            enabled_img_models = [m for m in self._sorted_models(storage.list_documents("ai_models")) if m.get("modelType") == "image" and self._is_model_enabled(m)]
            if enabled_img_models:
                selected_model = str(enabled_img_models[0].get("id") or enabled_img_models[0].get("modelName") or "muse-image")
            else:
                selected_model = "muse-image"

        gen_body = {
            "prompt": matrix_prompt,
            "image": [image_ref] if image_ref else [],
            "size": "16:9",
            "model": selected_model,
        }
        res = self._generate_image(storage, gen_body)
        # _generate_image returns a locally saved fileId/url and a data list.
        # Reading only `images` discarded successful generations after saving.
        generated_id = str(res.get("fileId") or "").strip()
        generated_url = str(res.get("url") or "").strip()
        if not generated_id:
            images = res.get("data") or res.get("images") or []
            first_img = images[0] if isinstance(images, list) and images else None
            if isinstance(first_img, dict):
                generated_id = str(first_img.get("id") or first_img.get("fileId") or "").strip()
                generated_url = str(first_img.get("url") or "").strip()
        if not generated_id:
            raise StorageError(500, "九宫格生成未返回有效图片")
        return {
            "fileId": generated_id,
            "url": generated_url or f"/file/{generated_id}/download",
            "success": True,
        }

    def _crop_role_portrait(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        import cv2, numpy as np
        file_id = str(body.get("fileId") or "").strip()
        if not file_id:
            raise StorageError(400, "必须提供 fileId")
        content_bytes = b""
        try:
            meta = storage.find_file(file_id)
            content_bytes = storage.read_file_content(meta["bucket"], file_id)
        except Exception:
            for b in ["files", "generated-videos", "assets"]:
                try:
                    content_bytes = storage.read_file_content(b, file_id)
                    if content_bytes:
                        break
                except Exception:
                    pass
        if not content_bytes:
            raise StorageError(404, f"未找到文件 {file_id}")
        arr = np.frombuffer(content_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise StorageError(400, "无法解码图像")
        h, w = img.shape[:2]
        # 若为 16:9 或宽幅三视图（宽/高 >= 1.4），精准裁剪左侧 42% 的单人正面高清特写
        if w / h >= 1.4:
            crop_w = int(w * 0.42)
            crop = img[:, :crop_w]
        else:
            crop = img
        success, buffer = cv2.imencode(".png", crop)
        if not success:
            raise StorageError(500, "特写图像编码失败")
        png_bytes = buffer.tobytes()
        saved = storage.save_file(
            bucket="files",
            content=png_bytes,
            filename="role_portrait.png",
            content_type="image/png"
        )
        return {
            "fileId": saved["id"],
            "url": f"/file/{saved['id']}/download",
            "width": int(crop.shape[1]),
            "height": int(crop.shape[0]),
        }

    def _video_model(self, storage: LocalStorage, selected: Any) -> dict[str, Any]:
        return self._resolve_ai_model(storage, 'video', selected)

    @staticmethod
    def _sanitize_video_prompt(prompt: str) -> str:
        """Keep directing content, drop request-policy talk.

        Muse is a chat agent: policy sentences such as "不拼接/不额外生成第二场景"
        make it answer conversationally ("there is nothing to attach") instead of
        generating, while the time/weather continuity and the cross-scene cut
        bridge are exactly what keeps a scene change coherent. Strip only the
        wrapper and the meta lines, never the direction.
        """
        text = str(prompt or '')
        text = re.sub(r'【自动转场安排·开始】\s*', '', text)
        text = re.sub(r'\s*【自动转场安排·结束】\s*', '\n', text)
        text = re.sub(r'^[ \t]*【转场边界】.*$', '', text, flags=re.M)
        text = re.sub(r'【单镜交付约束】[\s\S]*?(?=\n|$)', '', text)
        text = re.sub(r"真人写实年代复古摄影|真人写实年代复古胶片质感|真人写实|真人实拍|真人摄影|真人出镜|真实人物|真人", "影视写实年代电影质感", text)
        text = re.sub(r'[{｛]{2}[^{}]+[}｝]{2}', '', text)
        return re.sub(r'\n{3,}', '\n\n', text).strip()

    @staticmethod
    def _validate_video_duration(content: bytes, expected: float, tiers: tuple[float, ...] = ()) -> dict[str, Any]:
        import cv2
        import tempfile
        actual = None
        with tempfile.TemporaryDirectory(prefix="cdtv-video-validation-") as work:
            video_path = Path(work) / "result.mp4"
            video_path.write_bytes(content)
            capture = cv2.VideoCapture(str(video_path))
            try:
                fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
                frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                if fps > 0 and frames > 0:
                    actual = round(frames / fps, 3)
            finally:
                capture.release()
        tolerance = max(0.5, expected * 0.05)
        passed = actual is not None and abs(actual - expected) <= tolerance
        matched_tier = None
        if not passed and actual is not None:
            for tier in tiers:
                if abs(actual - tier) <= max(0.5, tier * 0.05):
                    passed = True
                    matched_tier = tier
                    break
        return {"passed": passed, "expectedDuration": expected, "actualDuration": actual,
                "matchedTier": matched_tier,
                "reason": "" if passed else (f"请求 {expected:g} 秒，上游返回 {actual:g} 秒，未通过单镜时长验收" if actual is not None else "无法读取上游视频时长，未通过验收")}

    @staticmethod
    def _muse_duration_notice(expected: float, tier: float) -> str:
        return (f"上游 Muse 单镜只产出 {tier:g} 秒（本次请求 {expected:g} 秒），本镜已按 {tier:g} 秒记录；"
                "若动作没有覆盖完整，请在分镜阶段拆镜后重做")

    @staticmethod
    def _ffmpeg_binary() -> str:
        meipass = getattr(sys, "_MEIPASS", "")
        candidates = [Path(meipass) / "runtime" / "ffmpeg.exe" if meipass else None,
                      Path(__file__).resolve().parent / "runtime" / "ffmpeg.exe"]
        for candidate in candidates:
            if candidate and candidate.exists():
                return str(candidate)
        return ""

    @classmethod
    def _trim_video(cls, content: bytes, expected: float, actual: float) -> tuple[bytes | None, str]:
        """Cut an overlong upstream clip down to the requested shot length.

        Muse treats the requested duration as a hint and occasionally answers a
        10-second request with a minute-long recap of the whole scene. A large
        overrun is that recap case, where the requested beat lands at the tail;
        a small overshoot is usually padding at the end, so keep the head.
        """
        import tempfile
        binary = cls._ffmpeg_binary()
        if not binary:
            return None, ""
        keep_tail = actual > max(expected * 1.5, expected + 2.0)
        start = max(0.0, actual - expected) if keep_tail else 0.0
        with tempfile.TemporaryDirectory(prefix="cdtv-video-trim-") as work:
            source = Path(work) / "source.mp4"
            target = Path(work) / "trimmed.mp4"
            source.write_bytes(content)
            command = [
                binary, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{expected:.3f}",
                "-map", "0:v:0", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target),
            ]
            try:
                subprocess.run(command, capture_output=True, timeout=180, check=False)
            except (OSError, subprocess.SubprocessError):
                return None, ""
            if not target.exists() or target.stat().st_size == 0:
                return None, ""
            return target.read_bytes(), "tail" if keep_tail else "head"

    @classmethod
    def _settle_muse_duration(cls, content: bytes, expected: float, exact_continuity: bool) -> tuple[bytes, dict[str, Any]]:
        validation = cls._validate_video_duration(content, expected, MUSE_VIDEO_DURATION_TIERS)
        if validation["passed"]:
            tier = validation.pop("matchedTier")
            if tier is None:
                return content, {**validation, "effectiveDuration": expected, "adjusted": False, "notice": ""}
            return content, {**validation, "effectiveDuration": tier, "adjusted": True,
                             "notice": cls._muse_duration_notice(expected, tier)}
        actual = validation.get("actualDuration")
        if actual is None or actual <= expected:
            return content, {**validation, "effectiveDuration": expected, "adjusted": False, "notice": ""}
        if exact_continuity and actual > max(expected * 1.5, expected + 2.0):
            return content, {**validation, "passed": False, "originalDuration": actual,
                "trimmed": False, "effectiveDuration": expected, "adjusted": False, "notice": "",
                "reason": f"上游返回 {actual:g} 秒，超过本镜 {expected:g} 秒；尾帧续接不能截取结尾冒充接镜，原始结果已保留，请重试本镜"}
        trimmed, mode = cls._trim_video(content, expected, float(actual))
        if trimmed is None:
            return content, {**validation, "effectiveDuration": expected, "adjusted": False, "notice": ""}
        recheck = cls._validate_video_duration(trimmed, expected)
        if not recheck["passed"]:
            return content, {**validation, "effectiveDuration": expected, "adjusted": False, "notice": ""}
        return trimmed, {
            **recheck,
            "originalDuration": actual,
            "trimmed": True,
            "trimMode": mode,
            "effectiveDuration": expected,
            "adjusted": False,
            "notice": "",
            "reason": f"上游返回 {actual:g} 秒，已自动裁取{'结尾' if mode == 'tail' else '开头'} {expected:g} 秒",
        }

    def _submit_video(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._video_model(storage, body.get("model"))
        content = body.get("content") or []
        if not isinstance(content, list) or not content:
            raise StorageError(400, "视频生成 content 不能为空")
            
        prompt_text = ""
        image_urls = []
        optimized_content = []
        optimized_by_source: dict[str, str] = {}
        for item in content:
            if not isinstance(item, dict):
                continue
            item_copy = dict(item)
            if item.get("type") == "text":
                raw_t = str(item.get("text") or "")
                purified_t = re.sub(r"真人写实年代复古摄影|真人写实年代复古胶片质感|真人写实|真人实拍|真人摄影|真人出镜|真实人物|真人", "影视写实年代电影质感", raw_t)
                purified_t = re.sub(r'[{｛]{2}[^{}]+[}｝]{2}', '', purified_t)
                item_copy["text"] = purified_t
                prompt_text += purified_t
            elif item.get("type") == "image_url":
                if isinstance(item.get("image_url"), dict):
                    url_val = item["image_url"].get("url")
                    if url_val:
                        opt_url = self._optimize_image_for_api(str(url_val), storage=storage)
                        optimized_by_source[str(url_val)] = opt_url
                        item_copy["image_url"] = {"url": opt_url}
                        image_urls.append(opt_url)
                else:
                    url_val = item.get("image_url")
                    if url_val:
                        opt_url = self._optimize_image_for_api(str(url_val), storage=storage)
                        optimized_by_source[str(url_val)] = opt_url
                        item_copy["image_url"] = opt_url
                        image_urls.append(opt_url)
            elif item.get("type") == "image":
                url_val = item.get("url") or item.get("image")
                if url_val:
                    opt_url = self._optimize_image_for_api(str(url_val), storage=storage)
                    optimized_by_source[str(url_val)] = opt_url
                    item_copy["url"] = opt_url
                    if "image" in item_copy:
                        item_copy["image"] = opt_url
                    image_urls.append(opt_url)
            optimized_content.append(item_copy)
                    
        ratio = str(body.get("ratio") or body.get("aspect_ratio") or "16:9")
        if ratio == "智能":
            ratio = "16:9"
        duration = int(body.get("duration") or 5)
        generate_audio = bool(body.get("generate_audio", True))

        safe_prompt = self._sanitize_video_prompt(prompt_text)

        audio_contract = None
        is_muse_video = bool(re.match(r"^muse[-_ ]?video", str(model.get("modelName") or ""), re.I))
        if is_muse_video:
            if duration > 10:
                duration = 10
            elif duration < 3:
                duration = 3
            safe_prompt = re.sub(r"【00:00-00:\d+】", f"【00:00-00:{duration:02d}】", safe_prompt)
        handoff = body.get("role_handoff")
        role_handoff = bool(isinstance(handoff, dict) and handoff.get("mode") == "observer_reveal"
                            and handoff.get("observerId") and handoff.get("actorId")
                            and handoff.get("observerId") != handoff.get("actorId"))
        if isinstance(handoff, dict) and handoff.get("mode") == "observer_reveal" and not role_handoff:
            raise StorageError(400, "人物交接必须指定两个不同的角色")
        if role_handoff and len(image_urls) < 2:
            raise StorageError(400, "人物交接必须同时提供上一镜尾帧和新入画少年的参考图")
        if role_handoff:
            observer = str(handoff.get("observerName") or "上一镜观察者")
            actor = str(handoff.get("actorName") or "新入画少年")
            if handoff.get("phase") == "scripted":
                safe_prompt += (f"\n【后台人物身份锁】{observer}与{actor}是不同的人，外貌服装不互换。"
                                "从真实尾帧继续，站位、机位、持物、进场方式及路线全部按本镜正文执行，不增加其他剧情或环境。")
            elif handoff.get("phase") == "inside":
                safe_prompt += (f"\n【后台双人身份锁】{observer}与{actor}是两个不同的人，已经都在同一原屋内。"
                                f"{observer}执行自己的动作，{actor}执行自己的动作，外貌服装和动作不互换；不重新跑一次入屋、不返回街道。")
            else:
                safe_prompt += (f"\n【后台人物交接锁】{observer}留在上一镜原屋门槛内观察并让路；奔跑、跨门槛入屋的是另外一个人{actor}。"
                                f"{actor}从外面朝镜头跑进{observer}当前所在的同一间屋；镜头所在侧是入口，对面红纸木门只是背景，不能作为入屋目的地。"
                                "保留新人物参考，不把尾帧观察者当成跑来的人。")
        if is_muse_video:
            from audio_contract import prepare_muse_prompt
            try:
                safe_prompt, audio_contract = prepare_muse_prompt(safe_prompt, body.get("dialogue_contract"))
            except ValueError as exc:
                raise StorageError(400, str(exc)) from exc

        # Keep duplicated legacy prompt/content fields consistent for all video models.
        optimized_content = [i for i in optimized_content if i.get("type") not in {"text", "audio", "audio_url", "input_audio"}]
        optimized_content.append({"type": "text", "text": safe_prompt})

        # 提取并优化首尾帧 / 动作接续帧 (first_frame)
        first_frame_url = str(body.get("first_frame") or body.get("first_frame_url") or "").strip()
        if not first_frame_url:
            for item in content:
                if isinstance(item, dict) and item.get("role") == "first_frame":
                    u = item.get("image_url") or item.get("url") or item.get("image")
                    if isinstance(u, dict):
                        u = u.get("url")
                    if u:
                        first_frame_url = str(u).strip()
                        break
        if first_frame_url:
            # Reuse the already optimized variant: the film-grain pass is not
            # deterministic, so re-processing would upload a near-duplicate frame.
            first_frame_url = optimized_by_source.get(first_frame_url) or self._optimize_image_for_api(first_frame_url, storage=storage)
            # 确保尾帧排在 image_urls 首位，使 Muse/Seedance 等接口将其作为首帧参考
            while first_frame_url in image_urls:
                image_urls.remove(first_frame_url)
            image_urls.insert(0, first_frame_url)

        if is_muse_video and role_handoff:
            if handoff.get("phase") == "scripted":
                safe_prompt += f"\n【单镜连续】本片总长 {duration} 秒，从真实尾帧开始，保持人物身份与空间关系，按本镜正文完成动作。"
            elif handoff.get("phase") == "inside":
                safe_prompt += f"\n【单镜连续】本片总长 {duration} 秒，从同一原屋内真实尾帧开始，两人保持身份与空间关系，分别继续本镜动作。"
            else:
                safe_prompt += f"\n【单镜连续】本片总长 {duration} 秒，从真实尾帧观察者原位开始，观察者始终停在门槛内，新入画少年跑来并进入同一间屋。"
            optimized_content = [item for item in optimized_content if item.get("type") != "text"]
            optimized_content.append({"type": "text", "text": safe_prompt})
        elif is_muse_video:
            # Muse composes a chat-style answer and can stretch a single shot into
            # a minute-long recap that opens before the handoff frame. State the
            # delivery shape as direction, not as a prohibition it can argue with.
            is_stickman_prompt = "墨柴" in safe_prompt or "stickman" in safe_prompt.lower() or "火柴人" in safe_prompt
            if is_stickman_prompt:
                camera_direction = "运镜紧密跟随动作动态推拉摇移，保持高动态视觉冲击，全片连续发生到结尾无动作断档与冷场。"
            else:
                camera_direction = "机位与运镜按本镜正文执行，固定机位时保持画框不动，全片保持在同一个场景与同一条动作线上。"

            safe_prompt = (
                safe_prompt.rstrip()
                + f"\n【单镜连续】本片总长 {duration} 秒，是一个连续长镜头：从第一张图的画面直接开始，"
                  f"事件按时间顺序连续发生到结尾；{camera_direction}"
            )
            optimized_content = [item for item in optimized_content if item.get("type") != "text"]
            optimized_content.append({"type": "text", "text": safe_prompt})

        # Muse only receives still-image context and cannot extend the previous video motion.
        # For exact action continuation, keep the real tail frame as the sole image input;
        # extra character/prop references otherwise compete with the first-frame anchor.
        # Scene cuts reuse the first image as a scene anchor instead, so the character
        # references must survive: never collapse them unless continuity is enabled.
        continuity_mode_val = str(body.get("continuity_mode") or "").strip().lower()
        strict_continuity = (
            is_muse_video
            and bool(first_frame_url)
            and (
                (
                    bool(body.get("continuity_enabled", True))
                    and continuity_mode_val == "exact"
                )
                or bool(body.get("first_frame_pin"))
            )
        )
        if strict_continuity:
            safe_prompt = (
                safe_prompt.rstrip()
                + "\n【首帧硬约束·最高优先级】第一张图是视频第0秒的精确画面，不是普通参考图。"
                  "第一帧必须保持原图的构图、景别、机位、人物姿态、道具位置、背景和光线；"
                  "禁止空镜开场，禁止在开场切换景别。提示词中的中景、全景、特写、推拉摇移与新增特效"
                  "只能在1秒以后从原姿态渐进发生，不能覆盖或重建第0秒画面。"
            )
            optimized_content = [i for i in optimized_content if i.get("type") != "text"]
            optimized_content.append({"type": "text", "text": safe_prompt})

        is_transition = (
            is_muse_video
            and bool(first_frame_url)
            and bool(body.get("continuity_enabled", True))
            and continuity_mode_val == "transition"
        )
        if is_transition:
            safe_prompt = (
                safe_prompt.rstrip()
                + "\n【尾帧转场过渡·运镜动能连续·最高优先级】第一张图是上一镜真实尾帧，全片第0秒严禁静止或刹车顿挫，必须完全承接上一镜运镜动能与惯性速度（两镜同向同速连续）；"
                  "若首帧处于遮挡物覆盖状态，遮挡物沿运镜方向自然顺滑退出视野，平滑展露出本镜新场景、新人物与新动作。"
                  "两镜时空与光影有机融合，过渡流畅自然，动能连续不顿，严禁突兀硬切或黑屏断档。"
            )
            optimized_content = [i for i in optimized_content if i.get("type") != "text"]
            optimized_content.append({"type": "text", "text": safe_prompt})

        if is_muse_video:
            production_id = uuid.uuid4().hex[:12]
            safe_prompt = (f"【本次独立制作 {production_id}】请重新生成下述当前镜头，总长 {duration} 秒。"
                           "本次只制作这个镜头，直接从第一张图片开始；请勿返回已有整集文件、历史合集或前面镜头的回放。\n"
                           + safe_prompt
                           + f"\n请把本次新生成的单镜视频作为一个附件返回，文件名 shot_{production_id}.mp4。")
            optimized_content = [i for i in optimized_content if i.get("type") != "text"]
            optimized_content.append({"type": "text", "text": safe_prompt})

        provider_lower = str(model.get("provider") or "").lower()
        api_url_lower = str(model.get("apiUrl") or "").lower()
        if "runninghub" in provider_lower or "runninghub" in api_url_lower:
            return self._submit_runninghub_video(storage, model, safe_prompt, image_urls, body)

        is_autodl_or_comfy = (
            "autodl" in provider_lower
            or "autodl" in api_url_lower
            or "comfyui" in api_url_lower
            or "comfyui" in provider_lower
            or "liblib" in provider_lower
            or "liblib" in api_url_lower
            or "workflow" in api_url_lower
            or "custom" in provider_lower
        )

        production_mode = str(body.get("production_mode") or ("scene" if duration > 10 else "shot"))
        payload = {
            "model": model["modelName"],
            "prompt": safe_prompt,
            "content": optimized_content,
            "images": image_urls,
            "image": image_urls[0] if image_urls else "",
            "ratio": ratio,
            "aspect_ratio": ratio,
            "duration": duration,
            "production_mode": production_mode,
            "generate_audio": generate_audio,
            "resolution": str(body.get("resolution") or "720p").lower(),
            "watermark": False,
        }
        if is_autodl_or_comfy:
            payload["workflow_id"] = model["modelName"]
            payload["workflowId"] = model["modelName"]
            payload["audios"] = [item.get("url") or item.get("audio") for item in content if isinstance(item, dict) and item.get("type") in {"audio", "audio_url"}]
            payload["params"] = {
                "prompt": safe_prompt,
                "images": image_urls,
                "image": image_urls[0] if image_urls else "",
                "first_frame": first_frame_url,
                "duration": duration,
                "ratio": ratio,
                "resolution": payload["resolution"],
            }
            payload["inputs"] = dict(payload["params"])
        if first_frame_url:
            payload["first_frame"] = first_frame_url
            payload["first_frame_url"] = first_frame_url
        if "seed" in body and body["seed"] is not None:
            payload["seed"] = body["seed"]
            
        candidates = self._video_submit_candidates(str(model.get("apiUrl") or ""), model_name=str(model.get("modelName") or ""))
        last_error = None
        result = None
        successful_endpoint = ""
        
        for endpoint in candidates:
            current_payload = dict(payload)
            # 自适应重试循环：如服务商报错某些字段不被支持，动态剔除并自适应适配
            for attempt in range(5):
                try:
                    result = self._request_ai_json(model, endpoint, f"{model.get('name', '视频')} 提交", current_payload, timeout=1800)
                    successful_endpoint = endpoint
                    break
                except StorageError as err:
                    last_error = err
                    err_str = str(err)
                    
                    # 1. 匹配 422 字段类型不一致（例如 duration 需要 string 或 int）
                    if "duration" in err_str and ("string" in err_str or "String" in err_str):
                        current_payload["duration"] = str(current_payload.get("duration", 10))
                        continue
                    if "duration" in err_str and ("integer" in err_str or "int" in err_str):
                        try:
                            current_payload["duration"] = int(current_payload.get("duration", 10))
                        except Exception:
                            pass
                        continue

                    # 2. 匹配 ratio 自适应报错（如 TaskTypeConstraint: ratio must be adaptive）
                    if "ratio" in err_str.lower() and ("adaptive" in err_str.lower() or "not valid" in err_str.lower() or "tasktypeconstraint" in err_str.lower()):
                        if current_payload.get("ratio") != "adaptive":
                            current_payload["ratio"] = "adaptive"
                            continue

                    # 3. 匹配服务商返回的未识别/不允许字段报错（兼容方括号 [field]、引号 'field' 与 is not valid）
                    field_match = re.search(r"[\[\'\"]?(\w+)[\]\'\"]?\s*(?:不是允许的请求字段|is not allowed|unknown field|is extra|extra_forbidden|is not valid|specified in the request)", err_str, re.IGNORECASE)
                    if field_match and field_match.group(1) in current_payload:
                        bad_field = field_match.group(1)
                        current_payload.pop(bad_field, None)
                        continue

                    # 4. 更加通用的扩展字段报错自适应剔除
                    stripped = False
                    for extra_k in ["images", "image", "aspect_ratio", "generate_audio", "prompt", "resolution", "watermark", "seed", "production_mode"]:
                        if extra_k in current_payload and extra_k in err_str:
                            current_payload.pop(extra_k, None)
                            stripped = True
                    if stripped:
                        continue

                    # 5. 如果多模态 content 不被支持，回退到 prompt + image / images / first_frame
                    if ("content" in current_payload and ("content" in err_str.lower() or "多模态" in err_str or "unsupported" in err_str.lower())):
                        current_payload.pop("content", None)
                        if image_urls:
                            current_payload["image"] = image_urls[0]
                            current_payload["image_url"] = image_urls[0]
                            if len(image_urls) > 1:
                                current_payload["images"] = image_urls
                        continue

                    # 6. 尝试剔除扩展可选字段简化为通用 OpenAI 格式
                    if attempt >= 2 and any(k in current_payload for k in ["generate_audio", "watermark", "resolution", "aspect_ratio"]):
                        current_payload.pop("generate_audio", None)
                        current_payload.pop("watermark", None)
                        current_payload.pop("resolution", None)
                        current_payload.pop("aspect_ratio", None)
                        continue

                    if "404" in err_str or "Invalid URL" in err_str:
                        break
                    raise
            if result is not None:
                break
                
        if result is None:
            if last_error:
                raise last_error
            raise StorageError(400, "无法连接所选视频模型 API 地址，请检查模型配置")
            
        task_id = str(
            result.get("id") or
            result.get("task_id") or
            result.get("taskId") or
            result.get("prompt_id") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("id") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("task_id") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("taskId") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("prompt_id") or
            (result.get("data") if isinstance(result.get("data"), str) else "") or
            ""
        ).strip()
        
        # 兼容同步直接返回视频地址的接口（如 OpenAI /v1/videos/generations 返回 {"data": [{"url": "..."}]}）
        direct_video_url = (
            result.get("video_url") or
            result.get("output_url") or
            result.get("url") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("url") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("video_url")
        )
        if not direct_video_url and isinstance(result.get("data"), list) and result["data"]:
            first = result["data"][0]
            if isinstance(first, dict):
                direct_video_url = first.get("url") or first.get("video_url")

        if not task_id:
            if direct_video_url:
                task_id = f"sync_{uuid.uuid4().hex[:12]}"
                result["video_url"] = direct_video_url
                result["status"] = "succeeded"
            else:
                raise StorageError(502, f"视频服务未返回任务 ID（返回内容：{json.dumps(result, ensure_ascii=False)[:200]}）")

        request_cache_id = _sha256_bytes(f"{model['id']}:{task_id}".encode())
        storage.save_document("ai_video_submissions", request_cache_id, {
            "expectedDuration": duration, "isMuse": is_muse_video,
            "shotId": str(body.get("shot_id") or ""), "projectId": str(body.get("project_id") or ""),
            "continuityEnabled": body.get("continuity_enabled"), "referenceCount": len(image_urls),
            "exactContinuity": strict_continuity,
        }, expected_revision=None)

        if is_muse_video and not any(abs(duration - tier) <= 0.5 for tier in MUSE_VIDEO_DURATION_TIERS):
            result["durationNotice"] = (
                f"上游 Muse 单镜只产出 {'/'.join(f'{tier:g}' for tier in MUSE_VIDEO_DURATION_TIERS)} 秒，"
                f"本次请求 {duration:g} 秒；出片后会按上游实际产出时长记录本镜")
                
        if direct_video_url:
            cache_id = _sha256_bytes(f"{model['id']}:{task_id}".encode())
            try:
                trust_env = urlparse(direct_video_url).hostname not in {"127.0.0.1", "localhost", "::1"}
                with httpx.Client(timeout=300, trust_env=trust_env, follow_redirects=True) as client:
                    if urlparse(direct_video_url).scheme in {"http", "https"}:
                        response = client.get(direct_video_url)
                        response.raise_for_status()
                        mime = response.headers.get("content-type", "video/mp4").split(";")[0].strip()
                        if response.content and (mime.startswith("video/") or mime == "application/octet-stream"):
                            video_bytes = response.content
                            if is_muse_video:
                                video_bytes, result["validation"] = self._settle_muse_duration(video_bytes, float(duration), strict_continuity)
                            stored = storage.save_file("generated-videos", video_bytes, f"{task_id}.mp4", mime)
                            result["video_url"] = self._legacy_file(stored)["url"]
            except Exception:
                pass
            result["status"] = "succeeded"
            if is_muse_video and not result.get("validation", {}).get("passed"):
                result["status"] = "failed"
                result["error"] = {"code": "invalid_video_duration", "message": result.get("validation", {}).get("reason") or "视频文件未通过时长验收"}
            storage.save_document("ai_video_results", cache_id, {"result": result}, expected_revision=None)

        return {
            **result,
            "audio_contract": audio_contract,
            "taskId": task_id,
            "status": result.get("status") or result.get("state") or "queued",
            "endpoint": successful_endpoint,
        }

    def _poll_video(self, storage: LocalStorage, task_id: str, selected: str) -> dict[str, Any]:
        model = self._video_model(storage, selected)
        _safe_segment(task_id, "任务 ID")
        provider_lower = str(model.get("provider") or "").lower()
        api_url_lower = str(model.get("apiUrl") or "").lower()
        if "runninghub" in provider_lower or "runninghub" in api_url_lower:
            return self._poll_runninghub_video(storage, model, task_id)

        cache_id = _sha256_bytes(f"{model['id']}:{task_id}".encode())
        try:
            return storage.get_document("ai_video_results", cache_id)["result"]
        except StorageError as exc:
            if exc.status != 404:
                raise
                
        candidates = self._video_poll_candidates(str(model.get("apiUrl") or ""), task_id)
        result = None
        last_error = None
        for endpoint in candidates:
            try:
                result = self._request_ai_json(model, endpoint, f"{model.get('name', '视频')} 查询", timeout=60)
                break
            except StorageError as err:
                last_error = err
                if "404" in str(err) or "Invalid URL" in str(err):
                    continue
                raise
                
        if result is None:
            if last_error:
                raise last_error
            raise StorageError(400, "查询视频生成进度失败，请检查 API 地址")
            
        status = str(
            result.get("status") or
            result.get("state") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("status") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("state") or
            ""
        ).lower()
        if not status and str(result.get("code") or "") in {"200", "0"}:
            if (result.get("video_url") or (result.get("data") if isinstance(result.get("data"), dict) else {}).get("video_url")):
                status = "succeeded"
            else:
                status = "running"
        result["status"] = status
        
        if status not in {"succeeded", "completed", "done", "success", "finished", "2"}:
            return result
            
        content = result.get("content") if isinstance(result.get("content"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        
        video_url = (
            result.get("video_url") or
            result.get("output_url") or
            result.get("url") or
            content.get("video_url") or
            data.get("video_url") or
            data.get("output_url") or
            data.get("url") or
            (data.get("result") if isinstance(data.get("result"), dict) else {}).get("video_url") or
            (data.get("result") if isinstance(data.get("result"), dict) else {}).get("url") or
            (result.get("result") if isinstance(result.get("result"), dict) else {}).get("video_url")
        )
        if not video_url and isinstance(result.get("data"), list) and result["data"]:
            first = result["data"][0]
            if isinstance(first, dict):
                video_url = first.get("url") or first.get("video_url")
        if not video_url and isinstance(result.get(task_id), dict):
            task_info = result[task_id]
            outputs = task_info.get("outputs") or {}
            for node_id, node_out in outputs.items():
                if isinstance(node_out, dict):
                    v_items = node_out.get("gifs") or node_out.get("videos") or node_out.get("images") or []
                    if v_items and isinstance(v_items[0], dict):
                        first_v = v_items[0]
                        fn = first_v.get("filename")
                        sub = first_v.get("subfolder", "")
                        tp = first_v.get("type", "output")
                        parsed_api = urlparse(str(model.get("apiUrl") or ""))
                        base = f"{parsed_api.scheme}://{parsed_api.netloc}"
                        video_url = f"{base}/view?filename={fn}&subfolder={sub}&type={tp}"
                        break
                
        if not video_url:
            raise StorageError(502, f"视频生成完成但未返回有效视频地址（内容：{json.dumps(result, ensure_ascii=False)[:200]}）")
            
        frame_url = (
            result.get("last_frame_url") or
            content.get("last_frame_url") or
            data.get("last_frame_url")
        )
        
        try:
            trust_env = urlparse(video_url).hostname not in {"127.0.0.1", "localhost", "::1"}
            with httpx.Client(timeout=300, trust_env=trust_env, follow_redirects=True) as client:
                if urlparse(video_url).scheme not in {"http", "https"}:
                    raise StorageError(502, "视频服务返回的视频地址无效")
                response = client.get(video_url)
                response.raise_for_status()
                mime = response.headers.get("content-type", "video/mp4").split(";")[0].strip()
                if not response.content or (not mime.startswith("video/") and mime != "application/octet-stream"):
                    raise StorageError(502, "视频服务返回的视频文件为空或内容无效")
                stored_bytes = response.content
                try:
                    submission = storage.get_document("ai_video_submissions", cache_id)
                except StorageError as exc:
                    if exc.status != 404:
                        raise
                    submission = {}
                if submission.get("isMuse") and submission.get("expectedDuration"):
                    stored_bytes, validation = self._settle_muse_duration(stored_bytes, float(submission["expectedDuration"]), bool(submission.get("exactContinuity", submission.get("continuityEnabled", False))))
                    result["validation"] = validation
                    if not validation["passed"]:
                        result["status"] = "failed"
                        result["error"] = {"code": "invalid_video_duration", "message": validation["reason"]}
                stored = storage.save_file("generated-videos", stored_bytes, f"{task_id}.mp4", mime)
                result["video_url"] = self._legacy_file(stored)["url"]
                result["content"] = {**content, "video_url": result["video_url"]}
                if frame_url:
                    image, mime, extension = self._image_content(frame_url, client)
                    frame = storage.save_file("generated-images", image, f"{task_id}.{extension}", mime)
                    result["last_frame_url"] = self._legacy_file(frame)["url"]
                    result["content"]["last_frame_url"] = result["last_frame_url"]
        except httpx.HTTPError as exc:
            raise StorageError(502, "下载生成视频结果失败，请稍后查询此任务，无需重新提交") from exc
            
        storage.save_document("ai_video_results", cache_id, {"result": result}, expected_revision=None)
        return result

    def _generate_image(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        models = self._sorted_models(storage.list_documents("ai_models"))
        selected = str(body.get("model") or "").strip()
        models = [item for item in models if item.get("modelType") == "image" and self._is_model_enabled(item)]
        model = next((item for item in models if str(item.get("id")) == selected), None)
        if model is None:
            model = next((item for item in models if not selected or item.get("modelName") == selected), None)
        if model is None:
            raise StorageError(400, "未找到已启用的图片模型，请在设置中心检查所选模型")
        api_key = str(model.get("apiKey") or "").strip()
        if not api_key:
            raise StorageError(400, "所选图片模型未填写 API Key，请在设置中心补充")
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise StorageError(400, "请填写图片生成描述")
        images = body.get("image") or []
        if not isinstance(images, list):
            images = [images]
            
        endpoint = self._image_endpoint(str(model.get("apiUrl") or ""), bool(images))
        payload = {key: body[key] for key in (
            "n", "size", "quality", "background", "output_format", "output_compression", "input_fidelity", "user"
        ) if body.get(key) is not None}
        payload.update(model=model["modelName"], prompt=prompt)
        cue_adapter = model.get("imageAdapter") == "cue2api"
        if cue_adapter:
            payload["response_format"] = "b64_json"
        headers = {"Authorization": f"Bearer {api_key}"}
        # Loopback test/provider endpoints must not pass through system proxies.
        trust_env = urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}
        try:
            with httpx.Client(timeout=httpx.Timeout(660 if cue_adapter else 300, connect=15), trust_env=trust_env) as client:
                if images:
                    files = []
                    for index, source in enumerate(images):
                        content, content_type, extension = self._image_content(source, client)
                        field = "image" if len(images) == 1 else "image[]"
                        files.append((field, (f"reference-{index + 1}.{extension}", content, content_type)))
                    response = client.post(endpoint, headers=headers,
                                           data={key: str(value) for key, value in payload.items()}, files=files)
                else:
                    response = client.post(endpoint, headers=headers, json=payload)
                if response.is_error:
                    try:
                        error = response.json().get("error", {})
                        detail = error.get("message", "") if isinstance(error, dict) else str(error)
                    except (ValueError, AttributeError):
                        detail = ""
                    detail = str(detail).replace(api_key, "[隐藏]")[:400]
                    reason = {401: "API Key 无效", 403: "模型访问被拒绝", 429: "额度不足或请求过于频繁"}.get(
                        response.status_code, "请检查模型名、接口地址及服务商状态")
                    raise StorageError(502, f"图片模型请求失败（HTTP {response.status_code}）：{detail or reason}")
                try:
                    result = response.json()
                except ValueError as exc:
                    raise StorageError(502, "图片模型返回的内容不是 JSON，请检查 API 地址") from exc
                results = result.get("data") if isinstance(result, dict) else None
                if not isinstance(results, list) or not results:
                    raise StorageError(502, "图片模型没有返回图片数据")
                saved = []
                for item in results:
                    if not isinstance(item, dict):
                        raise StorageError(502, "图片模型返回的图片数据格式不正确")
                    source = (f"data:image/png;base64,{item['b64_json']}" if item.get("b64_json") else item.get("url"))
                    if not source:
                        raise StorageError(502, "图片模型没有返回图片地址或 Base64 数据")
                    content, content_type, extension = self._image_content(source, client)
                    stored = storage.save_file("files", content, f"generated-{uuid.uuid4().hex}.{extension}", content_type)
                    saved.append(self._legacy_file(stored))
                first = saved[0]
                return {"content": first["url"], "url": first["url"], "fileId": first["id"], "data": saved}
        except httpx.TimeoutException as exc:
            raise StorageError(504, "图片请求超时；服务商可能仍在处理，请先检查其任务记录再决定是否重试") from exc
        except httpx.HTTPError as exc:
            raise StorageError(502, "无法请求图片服务或下载结果，请检查网络与 API 地址") from exc

    @staticmethod
    def _image_endpoint(api_url: str, editing: bool) -> str:
        parsed = urlparse(api_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise StorageError(400, "图片模型 API 地址必须为有效的 HTTP 或 HTTPS 地址")
        action = "edits" if editing else "generations"
        api_path = parsed.path.rstrip("/")
        if re.search(r"/images/(generations|edits)$", api_path):
            api_path = api_path.rsplit("/", 1)[0] + "/" + action
        else:
            api_path = (api_path or "/v1") + "/images/" + action
        return parsed._replace(path=api_path, fragment="").geturl()

    @staticmethod
    def _image_content(source: Any, client: httpx.Client) -> tuple[bytes, str, str]:
        if not isinstance(source, str):
            raise StorageError(400, "图片数据必须为 Base64 图片或 HTTP 图片地址")
        if source.startswith("data:"):
            header, separator, encoded = source.partition(",")
            if not separator or not header.startswith("data:image/") or not header.endswith(";base64"):
                raise StorageError(400, "参考图片的 Base64 格式不正确")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise StorageError(400, "图片 Base64 数据无法解析") from exc
        elif urlparse(source).scheme in {"http", "https"}:
            response = client.get(source, follow_redirects=True, timeout=60)
            response.raise_for_status()
            content = response.content
        else:
            raise StorageError(400, "图片地址必须使用 HTTP 或 HTTPS")
        try:
            with Image.open(io.BytesIO(content)) as image:
                image_format = image.format
                image.verify()
            content_type, extension = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"),
                                       "WEBP": ("image/webp", "webp")}[image_format]
        except (OSError, ValueError, KeyError, Image.DecompressionBombError) as exc:
            raise StorageError(400, "图片内容无效或不是支持的 PNG、JPEG、WebP 格式") from exc
        return content, content_type, extension

    # ---------- RunningHub 原生接入适配 ----------

    def _generate_runninghub_image(self, storage: LocalStorage, model: dict[str, Any], prompt: str, images: list[Any], body: dict[str, Any]) -> dict[str, Any]:
        api_key = str(model.get("apiKey") or "").strip()
        api_base = str(model.get("apiUrl") or "https://www.runninghub.ai").rstrip("/")
        if not api_base.startswith("http"):
            api_base = "https://www.runninghub.ai"
        if not api_key:
            raise StorageError(400, "RunningHub 模型未填写 API Key，请在设置中心补充")

        workflow_id = str(model.get("workflowId") or body.get("workflowId") or model.get("modelName") or "runninghub-image")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        submit_payload = {
            "apiKey": api_key,
            "workflowId": workflow_id,
            "nodeParamList": [
                {
                    "nodeName": "CLIPTextEncode",
                    "fieldName": "text",
                    "fieldValue": prompt
                }
            ]
        }
        trust_env = urlparse(api_base).hostname not in {"127.0.0.1", "localhost", "::1"}
        with httpx.Client(timeout=httpx.Timeout(180, connect=15), trust_env=trust_env) as client:
            try:
                resp = client.post(f"{api_base}/task/openapi/create", json=submit_payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                raise StorageError(502, f"请求 RunningHub 生图接口失败: {str(exc)}") from exc
            
            task_id = (data.get("data") if isinstance(data.get("data"), dict) else {}).get("taskId") or data.get("taskId")
            if not task_id:
                err_msg = data.get("msg") or data.get("message") or "RunningHub 未返回任务 ID"
                raise StorageError(502, f"RunningHub 任务创建失败: {err_msg}")
            
            start_time = time.time()
            output_url = None
            while time.time() - start_time < 90:
                time.sleep(2)
                try:
                    poll_resp = client.post(f"{api_base}/task/openapi/outputs", json={"taskId": task_id, "apiKey": api_key}, headers=headers)
                    poll_resp.raise_for_status()
                    poll_data = poll_resp.json()
                except Exception:
                    continue
                
                data_obj = poll_data.get("data") if isinstance(poll_data.get("data"), dict) else {}
                status = str(data_obj.get("status") or poll_data.get("status") or "").upper()
                if status == "SUCCESS":
                    file_urls = data_obj.get("fileUrls") or data_obj.get("fileUrlList") or []
                    if file_urls:
                        output_url = file_urls[0]
                    elif data_obj.get("fileUrl"):
                        output_url = data_obj.get("fileUrl")
                    break
                elif status in ["FAILED", "ERROR"]:
                    raise StorageError(502, f"RunningHub 生图失败: {poll_data.get('msg') or poll_data}")
            
            if not output_url:
                raise StorageError(504, "RunningHub 生图超时，未在指定时间内返回图片结果")
            
            content, content_type, extension = self._image_content(output_url, client)
            stored = storage.save_file("files", content, f"generated-{uuid.uuid4().hex}.{extension}", content_type)
            saved = [self._legacy_file(stored)]
            first = saved[0]
            return {"content": first["url"], "url": first["url"], "fileId": first["id"], "data": saved}

    def _submit_runninghub_video(self, storage: LocalStorage, model: dict[str, Any], prompt_text: str, image_urls: list[str], body: dict[str, Any]) -> dict[str, Any]:
        api_key = str(model.get("apiKey") or "").strip()
        api_base = str(model.get("apiUrl") or "https://www.runninghub.ai").rstrip("/")
        if not api_base.startswith("http"):
            api_base = "https://www.runninghub.ai"
        if not api_key:
            raise StorageError(400, "RunningHub 视频模型未填写 API Key，请在设置中心补充")

        workflow_id = str(model.get("workflowId") or body.get("workflowId") or model.get("modelName") or "runninghub-video")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        submit_payload = {
            "apiKey": api_key,
            "workflowId": workflow_id,
            "nodeParamList": [
                {
                    "nodeName": "Prompt",
                    "fieldName": "text",
                    "fieldValue": prompt_text
                }
            ]
        }
        if image_urls:
            submit_payload["nodeParamList"].append({
                "nodeName": "LoadImage",
                "fieldName": "image",
                "fieldValue": image_urls[0]
            })
            
        trust_env = urlparse(api_base).hostname not in {"127.0.0.1", "localhost", "::1"}
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), trust_env=trust_env) as client:
            try:
                resp = client.post(f"{api_base}/task/openapi/create", json=submit_payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                raise StorageError(502, f"请求 RunningHub 视频接口失败: {str(exc)}") from exc
                
            task_id = (data.get("data") if isinstance(data.get("data"), dict) else {}).get("taskId") or data.get("taskId")
            if not task_id:
                err_msg = data.get("msg") or data.get("message") or "RunningHub 未返回任务 ID"
                raise StorageError(502, f"RunningHub 视频任务创建失败: {err_msg}")
            
            return {
                "taskId": str(task_id),
                "status": "processing",
                "endpoint": f"{api_base}/task/openapi/create"
            }

    def _poll_runninghub_video(self, storage: LocalStorage, model: dict[str, Any], task_id: str) -> dict[str, Any]:
        api_key = str(model.get("apiKey") or "").strip()
        api_base = str(model.get("apiUrl") or "https://www.runninghub.ai").rstrip("/")
        if not api_base.startswith("http"):
            api_base = "https://www.runninghub.ai"
            
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        cache_id = _sha256_bytes(f"{model['id']}:{task_id}".encode())
        try:
            return storage.get_document("ai_video_results", cache_id)["result"]
        except StorageError as exc:
            if exc.status != 404:
                raise
                
        trust_env = urlparse(api_base).hostname not in {"127.0.0.1", "localhost", "::1"}
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), trust_env=trust_env) as client:
            try:
                resp = client.post(f"{api_base}/task/openapi/outputs", json={"taskId": task_id, "apiKey": api_key}, headers=headers)
                resp.raise_for_status()
                poll_data = resp.json()
            except Exception as exc:
                raise StorageError(502, f"查询 RunningHub 任务进度失败: {str(exc)}") from exc
                
            data_obj = poll_data.get("data") if isinstance(poll_data.get("data"), dict) else {}
            status_str = str(data_obj.get("status") or poll_data.get("status") or "").upper()
            
            if status_str == "SUCCESS":
                file_urls = data_obj.get("fileUrls") or data_obj.get("fileUrlList") or []
                video_url = file_urls[0] if file_urls else data_obj.get("fileUrl")
                if not video_url:
                    raise StorageError(502, "RunningHub 标记成功但未返回视频文件链接")
                    
                response = client.get(video_url, follow_redirects=True, timeout=180)
                response.raise_for_status()
                mime = response.headers.get("content-type", "video/mp4").split(";")[0].strip()
                stored = storage.save_file("generated-videos", response.content, f"{task_id}.mp4", mime)
                local_url = self._legacy_file(stored)["url"]
                
                result = {
                    "taskId": task_id,
                    "status": "succeeded",
                    "video_url": local_url,
                    "content": {"video_url": local_url}
                }
                storage.save_document("ai_video_results", cache_id, {"result": result}, expected_revision=None)
                return result
            elif status_str in ["FAILED", "ERROR"]:
                raise StorageError(502, f"RunningHub 视频生成失败: {poll_data.get('msg') or poll_data}")
            else:
                return {
                    "taskId": task_id,
                    "status": "processing"
                }

    @staticmethod
    def _with_defaults(body: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
        for key, value in defaults.items():
            body.setdefault(key, value)
        return body

    @staticmethod
    def _filter_assets(items: list[dict[str, Any]], query: dict[str, list[str]]) -> list[dict[str, Any]]:
        asset_type = (query.get("type") or [""])[0]
        keyword = (query.get("keyword") or [""])[0].strip().lower()
        project_id = (query.get("projectId") or [""])[0].strip()
        result = []
        for item in items:
            if asset_type and asset_type not in ("all", item.get("type")):
                continue
            if project_id:
                bound = [str(value) for value in (item.get("boundProjectIds") or [])]
                if project_id == "__unlinked__":
                    if bound:
                        continue
                elif project_id not in bound:
                    continue
            if keyword:
                haystack = f"{item.get('name', '')} {item.get('description', '')} {item.get('tags', '')}".lower()
                if keyword not in haystack:
                    continue
            result.append(item)
        return result

    def _asset_upload(self, storage: LocalStorage, single: bool = True) -> dict[str, Any] | list[dict[str, Any]]:
        fields, files = self._parse_multipart(self._read_body(), self.headers.get("Content-Type") or "")
        if not files:
            raise StorageError(400, "请选择要上传的文件")
        bindings = list(dict.fromkeys(item.strip() for item in fields.get("boundProjectIds", "").splitlines()
                                      if item.strip()))
        assets = []
        for _, filename, content in files[:1] if single else files:
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            stored = storage.save_file("assets", content, filename, content_type)
            media_type = "audio" if content_type.startswith("audio/") else ("video" if content_type.startswith("video/") else "image")
            body = {
                "name": fields.get("name", "").strip() or Path(filename).stem,
                "description": fields.get("description", ""), "tags": fields.get("tags", ""),
                "type": fields.get("type", "").strip() or ("scene" if media_type == "video" else media_type),
                "duration": fields.get("duration", ""), "coverId": stored["id"], "boundProjectIds": bindings,
            }
            asset = storage.create_document("assets", body)
            asset["mediaType"] = media_type
            assets.append(asset)
        return assets[0] if single else assets

    def _file_upload(self, storage: LocalStorage) -> dict[str, Any]:
        fields, files = self._parse_multipart(self._read_body(), self.headers.get("Content-Type") or "")
        if not files:
            raise StorageError(400, "请选择要上传的文件")
        _, filename, content = files[0]
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        stored = storage.save_file(fields.get("bucket", "").strip() or "files", content, filename, content_type)
        return self._legacy_file(stored)

    @staticmethod
    def _legacy_file(stored: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": stored.get("id"),
            "fileName": stored.get("name"),
            "cosKey": stored.get("sha256"),
            "bucket": stored.get("bucket"),
            "fileSize": stored.get("size"),
            "contentType": stored.get("contentType"),
            "url": f"/file/{stored.get('id')}/download",
            "deleted": False,
            "createTime": stored.get("updatedAt"),
            "updateTime": stored.get("updatedAt"),
        }

    @staticmethod
    def _video_summary(source: dict[str, Any]) -> dict[str, Any]:
        result = dict(source)
        assets = source.get("assets") if isinstance(source.get("assets"), list) else []
        storyboards = source.get("storyboards") if isinstance(source.get("storyboards"), list) else []
        episodes = source.get("episodes") if isinstance(source.get("episodes"), dict) else {}
        if episodes:
            all_ep_shots = []
            for ep_key, ep_val in episodes.items():
                if isinstance(ep_val, dict) and isinstance(ep_val.get("storyboards"), list):
                    all_ep_shots.extend(ep_val["storyboards"])
            if all_ep_shots:
                storyboards = all_ep_shots
            result["episodeCount"] = len(episodes)
        active_statuses = {"preparing", "submitting", "queued", "pending", "generating", "processing", "running"}
        completed = 0
        running = 0
        for shot in storyboards:
            if not isinstance(shot, dict):
                continue
            has_result = bool(str(shot.get("resultFileId") or "").strip()
                              or str(shot.get("resultUrl") or "").strip())
            if has_result:
                completed += 1
                continue
            status = str(shot.get("status") or "").strip().lower()
            task_id = str(shot.get("taskId") or shot.get("seedanceTaskId") or "").strip()
            if status in active_statuses or (task_id and status not in {"succeeded", "failed", "cancelled", "canceled"}):
                running += 1
        for asset in assets:
            if isinstance(asset, dict) and str(asset.get("generatingStartedAt") or "").strip():
                running += 1
        result["assetCount"] = len(assets)
        result["storyboardCount"] = len(storyboards)
        result["completedCount"] = completed
        result["runningCount"] = running
        result.pop("assets", None)
        result.pop("storyboards", None)
        return result

    @staticmethod
    def _sorted_models(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda item: int(item.get("sortOrder") or 0))

    @staticmethod
    def _is_model_enabled(item: dict[str, Any]) -> bool:
        val = item.get("enabled", True)
        if isinstance(val, str):
            return val.lower() not in {"false", "0", "off", "no"}
        return bool(val)

    @staticmethod
    def _normalize_model(body: dict[str, Any], partial: bool) -> None:
        model_types = {"text", "image", "video", "audio"}
        if not partial or "name" in body:
            name = str(body.get("name") or "").strip()
            if not name:
                raise StorageError(400, "请输入模型显示名称")
            body["name"] = name
        if not partial or "modelType" in body:
            if str(body.get("modelType") or "") not in model_types:
                raise StorageError(400, "模型类型不正确")
        if not partial or "modelName" in body:
            if not str(body.get("modelName") or "").strip():
                raise StorageError(400, "请输入 API 模型名")
        if not partial or "apiUrl" in body:
            api_url = str(body.get("apiUrl") or "").strip()
            if not api_url:
                raise StorageError(400, "请输入 API 地址")
            body["apiUrl"] = re.sub(r"/+$", "", api_url)
        if "contextWindow" in body:
            try:
                val = body["contextWindow"]
                body["contextWindow"] = int(val) if val not in (None, "") and int(val) > 0 else None
            except (ValueError, TypeError):
                body["contextWindow"] = None
        if "maxTokens" in body:
            try:
                val = body["maxTokens"]
                body["maxTokens"] = int(val) if val not in (None, "") and int(val) > 0 else None
            except (ValueError, TypeError):
                body["maxTokens"] = None
        if not partial:
            body.setdefault("provider", "")
            body.setdefault("icon", "")
            body.setdefault("sortOrder", 0)
            body.setdefault("points", 0)
            body.setdefault("enabled", True)
            body.setdefault("contextWindow", None)
            body.setdefault("maxTokens", None)

    @staticmethod
    def _fetch_remote_models(api_url: str, api_key: str = "", provider: str = "", model_type: str = "") -> list[dict[str, Any]]:
        clean_url = str(api_url or "").strip().rstrip("/")
        if not clean_url:
            raise StorageError(400, "请输入 API 地址")
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "http://" + clean_url

        clean_key = str(api_key or "").strip()
        clean_provider = str(provider or "").strip().lower()
        clean_type = str(model_type or "").strip().lower()

        # 1. 专门适配 AutoDL.Art / AutoDL ComfyUI 工作流平台（支持全市场 27 款工作流 + 自定义工作流）
        is_autodl = (
            "autodl" in clean_url.lower()
            or "/comfyui_workflow" in clean_url.lower()
            or "autodl" in clean_provider
        )
        if is_autodl:
            # 收录 AutoDL.Art 官方 ComfyUI 市场的全部 27 款工作流（Zealman / AI资源仓 / 官方）
            autodl_workflows = [
                # --- Zealman 开发者系列：MiniMax-H3 多图多音频与动作迁移 ---
                {
                    "id": "minimax_h3_zm_u24",
                    "name": "H3多图多音频生视频(升级画质)",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "MiniMax-H3 多图多音频协同生成，升级画质，最多9图+3音频，最长支持15秒",
                },
                {
                    "id": "minimax_h3_zm_u30",
                    "name": "H3多图多音频生视频(超清画质)",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "超清不油腻，细腻高动态画质，多图多音频协同生成",
                },
                {
                    "id": "minimax_image_audio_to_video_v2_15s",
                    "name": "H3多图多音频生视频15秒",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U06V2 15秒超长视频生成，多图多音频协同",
                },
                {
                    "id": "minimax_h3_lightx2v_v5_15s",
                    "name": "H3多图生视频15秒",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U06V5 15秒多图参考生成，动作连贯自然",
                },
                {
                    "id": "minimax_h3_zm_nono",
                    "name": "H3多图多音频生视频(影视画质)",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "NONO影视级色调与质感，光影电影感强",
                },
                {
                    "id": "minimax_h3_lightx2v_v5",
                    "name": "H3多图参考生视频",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U06V5 多图参考生视频，视觉主体一致性高",
                },
                {
                    "id": "minimax_h3_lightx2v",
                    "name": "H3首尾帧生成视频",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U02 首尾帧精准过渡与平滑补帧",
                },
                {
                    "id": "minimax_image_audio_to_video_v2",
                    "name": "H3多图多音频生视频",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U06V2 多图多音频经典协同生成工作流",
                },
                {
                    "id": "minimax_h3_zm_u08",
                    "name": "H3多图多音频生视频(高速版)",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U08 高速推理版，快速预览分镜动态",
                },
                {
                    "id": "minimax_h3_zm_u22",
                    "name": "H3多图多音频生视频(短剧带货版)",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U22 专为短剧与电商带货场景优化的人物与道具协同",
                },
                {
                    "id": "minimax_h3_lightx2v_no_pic",
                    "name": "H3文生视频",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U03 纯文本提示词直出视频",
                },
                {
                    "id": "wan2.2animate-v4-motion_retargeting",
                    "name": "动作迁移",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "Wan2.2 骨骼与姿态迁移，高保真还原复杂人物动作",
                },
                {
                    "id": "minimax_h3_zm_titim",
                    "name": "H3全自动多角色动迁替换",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "全自动多人物检测与复杂多角色动作迁移替换",
                },
                {
                    "id": "minimax_h3_zm_titi",
                    "name": "H3全自动角色动迁替换",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "单人物精准动作与骨骼重定向替换",
                },
                {
                    "id": "minimax_image_audio_to_video",
                    "name": "H3图生视频-音频同步(自动对口型)",
                    "owned_by": "Zealman",
                    "modelType": "video",
                    "description": "U11 人物嘴型与参考音频毫秒级同步对口型",
                },
                # --- AI资源仓 开发者系列：六脉神剑与多图多音 ---
                {
                    "id": "minimax_h3_801",
                    "name": "H3九图15s(无字幕版)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "六脉神剑 801：九图15s纯净画面无字幕，高一致性连续生视频",
                },
                {
                    "id": "minimax_h3_802",
                    "name": "H3九图15s(画质增强版)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "六脉神剑 802：九图15s细节增强与纹理提升",
                },
                {
                    "id": "minimax_h3_803",
                    "name": "H3九图三音15s(画质增强版)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "六脉神剑 803：九图三音协同+画质提升",
                },
                {
                    "id": "minimax_h3_804",
                    "name": "H3九图15s(多模式版)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "六脉神剑 804：九图15s多模式可调工作流",
                },
                {
                    "id": "minimax_h3_805",
                    "name": "H3九图三音15s(多模式版/6合1)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "六脉神剑 805：6合1全能工作流，支持多镜头多人物协同",
                },
                {
                    "id": "minimax_h3_z0901",
                    "name": "H3文生视频(高质量创意直出)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "画质先行：纯文本输入创意高保真直出",
                },
                {
                    "id": "minimax_h3_z0902",
                    "name": "H3六图生视频(多图一致性创作)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "画质先行：最多6张参考图，强一致性视觉创作",
                },
                {
                    "id": "minimax_h3_z0903",
                    "name": "H3六图三音频生视频(高质量音画融合)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "画质先行：六图三音音画高度交融",
                },
                {
                    "id": "minimax_h3_b99_001",
                    "name": "H3文生视频(MH3高画质)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "MH3 高清文生视频工作流",
                },
                {
                    "id": "minimax_h3_b99_002",
                    "name": "H3首尾帧生成视频(MH3高画质)",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "MH3 首尾帧高质感平滑插帧",
                },
                {
                    "id": "minimax_h3_b99_003_12s",
                    "name": "H3多图生视频12秒",
                    "owned_by": "AI资源仓",
                    "modelType": "video",
                    "description": "MH3 12秒多图协同生视频",
                },
                # --- AutoDL 官方语音合成 ---
                {
                    "id": "indextts2-v1",
                    "name": "IndexTTS2 语音合成工作流",
                    "owned_by": "AutoDL官方",
                    "modelType": "audio",
                    "description": "零样本声音克隆与多情感配音合成",
                },
            ]

            # 动态适配：如果用户在 API 地址中指定了具体 workflow_id (例如 .../minimax_h3_zm_u24 或私有自定义工作流)
            m = re.search(r"/comfyui_workflow/([^/?#]+)", clean_url)
            if m:
                target_wf = m.group(1).strip()
                if target_wf:
                    existing_idx = next((i for i, w in enumerate(autodl_workflows) if w["id"] == target_wf), -1)
                    if existing_idx >= 0:
                        matched = dict(autodl_workflows.pop(existing_idx))
                        matched["is_current"] = True
                        matched["name"] = f"★ 当前地址对应: {matched['name']}"
                        autodl_workflows.insert(0, matched)
                    else:
                        autodl_workflows.insert(0, {
                            "id": target_wf,
                            "name": f"★ 当前地址对应: {target_wf}",
                            "owned_by": "AutoDL",
                            "modelType": "video",
                            "description": f"当前 URL 确定的工作流 ID: {target_wf}",
                            "is_current": True
                        })

            return autodl_workflows

        # 2. 专门适配本地/内网原生 ComfyUI (端口 8188 或 provider == ComfyUI)
        is_comfyui_native = (
            "8188" in clean_url
            or clean_provider in {"comfyui", "comfyui 原生", "comfy"}
        )
        if is_comfyui_native:
            comfy_models = []
            parsed_host = urlparse(clean_url).hostname or ""
            trust_env = parsed_host not in {"127.0.0.1", "localhost", "::1"}
            # 尝试从 ComfyUI /object_info 读取 Checkpoint 节点已加载的模型
            try:
                base_comfy = f"{urlparse(clean_url).scheme}://{urlparse(clean_url).netloc}"
                with httpx.Client(timeout=httpx.Timeout(4.0, connect=2.0), trust_env=trust_env) as client:
                    resp = client.get(f"{base_comfy}/object_info/CheckpointLoaderSimple")
                    if resp.status_code == 200:
                        data = resp.json()
                        ckpts = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
                        for ck in ckpts:
                            if isinstance(ck, str) and ck.strip():
                                name_clean = re.sub(r"\.[^.]+$", "", ck.strip())
                                comfy_models.append({
                                    "id": ck.strip(),
                                    "name": f"ComfyUI: {name_clean}",
                                    "owned_by": "ComfyUI",
                                    "modelType": "video" if any(k in ck.lower() for k in ["svd", "animatediff", "wan", "hunyuan", "cog"]) else "image",
                                    "description": f"本地 ComfyUI 模型: {ck.strip()}"
                                })
            except Exception:
                pass

            if not comfy_models:
                comfy_models = [
                    {"id": "comfyui-video", "name": "ComfyUI 原生文生/图生视频工作流", "owned_by": "ComfyUI", "modelType": "video"},
                    {"id": "comfyui-animatediff", "name": "ComfyUI AnimateDiff 视频工作流", "owned_by": "ComfyUI", "modelType": "video"},
                    {"id": "comfyui-wan2.1", "name": "ComfyUI Wan2.1 视频工作流", "owned_by": "ComfyUI", "modelType": "video"},
                    {"id": "comfyui-hunyuan", "name": "ComfyUI 混元视频生成工作流", "owned_by": "ComfyUI", "modelType": "video"},
                ]
            return comfy_models

        # 3. 专门适配 RunningHub (智绘/润影云端工作流)
        is_runninghub = (
            "runninghub" in clean_url.lower()
            or "runninghub" in clean_provider
        )
        if is_runninghub:
            rh_workflows = [
                {
                    "id": "runninghub-video",
                    "name": "RunningHub 官方视频生成工作流",
                    "owned_by": "RunningHub",
                    "modelType": "video",
                    "description": "RunningHub 云端视频生成工作流，支持文生/图生视频"
                },
                {
                    "id": "runninghub-image",
                    "name": "RunningHub 官方生图工作流",
                    "owned_by": "RunningHub",
                    "modelType": "image",
                    "description": "RunningHub 云端 ComfyUI 生图工作流"
                },
                {
                    "id": "runninghub-animate",
                    "name": "RunningHub 动作迁移工作流",
                    "owned_by": "RunningHub",
                    "modelType": "video",
                    "description": "RunningHub 动作重定向与视频风格化工作流"
                },
                {
                    "id": "runninghub-lipsync",
                    "name": "RunningHub 音频同步对口型工作流",
                    "owned_by": "RunningHub",
                    "modelType": "video",
                    "description": "人物面部嘴型与音频毫秒级同步对齐"
                },
            ]
            m = re.search(r"/(?:task/openapi/create|workflow|task)/([^/?#]+)", clean_url)
            if m:
                target_wf = m.group(1).strip()
                if target_wf and not any(w["id"] == target_wf for w in rh_workflows):
                    rh_workflows.insert(0, {
                        "id": target_wf,
                        "name": f"RunningHub 自定义工作流 ({target_wf})",
                        "owned_by": "RunningHub",
                        "modelType": "video",
                        "description": f"URL 中指定的自定义工作流 ID: {target_wf}"
                    })
            return rh_workflows

        # 4. 专门适配 LiblibAI (哩布哩布云端 ComfyUI 工作流)
        is_liblib = (
            "liblib" in clean_url.lower()
            or "liblib" in clean_provider
        )
        if is_liblib:
            liblib_workflows = [
                {
                    "id": "liblib-video-workflow",
                    "name": "LiblibAI ComfyUI 视频生成工作流",
                    "owned_by": "LiblibAI",
                    "modelType": "video",
                    "description": "哩布哩布云端 ComfyUI 视频生成工作流"
                },
                {
                    "id": "liblib-wan2.1",
                    "name": "LiblibAI Wan2.1 视频工作流",
                    "owned_by": "LiblibAI",
                    "modelType": "video",
                    "description": "Wan2.1 电影级视频生成工作流"
                },
                {
                    "id": "liblib-animatediff",
                    "name": "LiblibAI AnimateDiff 动态生视频",
                    "owned_by": "LiblibAI",
                    "modelType": "video",
                    "description": "AnimateDiff 连续长镜头视频工作流"
                },
            ]
            m = re.search(r"/comfyui/([^/?#]+)", clean_url)
            if m:
                target_wf = m.group(1).strip()
                if target_wf and not any(w["id"] == target_wf for w in liblib_workflows):
                    liblib_workflows.insert(0, {
                        "id": target_wf,
                        "name": f"LiblibAI 自定义工作流 ({target_wf})",
                        "owned_by": "LiblibAI",
                        "modelType": "video",
                        "description": f"URL 中指定的工作流 ID: {target_wf}"
                    })
            return liblib_workflows

        # 5. 通用自建/第三方工作流接口 (FastAPI / Flask / Dify 等，带有 workflow 路径)
        is_custom_wf = (
            "custom" in clean_provider
            or "{model" in clean_url.lower()
            or "/workflow" in clean_url.lower()
        )
        if is_custom_wf:
            m = re.search(r"/workflow[s]?/([^/?#{}]+)", clean_url)
            extracted_id = m.group(1).strip() if m else "custom-workflow"
            return [
                {
                    "id": extracted_id,
                    "name": f"自定义工作流 ({extracted_id})",
                    "owned_by": "通用工作流",
                    "modelType": "video",
                    "description": f"自建或第三方工作流接口: {clean_url}"
                }
            ]

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CDTV/1.0",
            "Accept": "application/json, text/plain, */*",
        }
        if clean_key:
            headers["Authorization"] = f"Bearer {clean_key}"

        candidates: list[str] = []
        if clean_url.endswith("/models"):
            candidates.append(clean_url)
        elif clean_url.endswith("/v1"):
            candidates.append(f"{clean_url}/models")
            candidates.append(clean_url)
        else:
            candidates.append(f"{clean_url}/v1/models")
            candidates.append(f"{clean_url}/models")
            candidates.append(f"{clean_url}/api/v1/models")
            candidates.append(f"{clean_url}/api/tags")

        last_error = None
        response = None
        parsed_host = urlparse(clean_url).hostname or ""
        trust_env = parsed_host not in {"127.0.0.1", "localhost", "::1"}
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0), trust_env=trust_env, follow_redirects=True) as client:
            for target_url in candidates:
                try:
                    resp = client.get(target_url, headers=headers)
                    if resp.status_code == 200:
                        response = resp
                        break
                    elif resp.status_code in {401, 403}:
                        raise StorageError(resp.status_code, f"API Key 认证失败（HTTP {resp.status_code}）：{resp.text[:120]}")
                    last_error = f"HTTP {resp.status_code}"
                except httpx.TimeoutException:
                    last_error = "请求超时，请检查网络或 API 地址是否可达"
                except (httpx.ConnectError, httpx.NetworkError):
                    last_error = "无法连接到该 API 地址，请确认网络与服务状态"
                except StorageError:
                    raise
                except Exception as e:
                    last_error = str(e)

        if response is None:
            if last_error == "HTTP 404":
                raise StorageError(400, "获取模型列表失败：该接口未提供 /v1/models 列表。若为工作流或自定义 API，请直接在下方模型配置列表中输入模型名保存即可使用。")
            raise StorageError(400, f"获取模型列表失败：{last_error or '未能连接到有效的 /models 接口'}")

        try:
            data = response.json()
        except Exception as exc:
            raise StorageError(400, f"接口返回非 JSON 数据：{response.text[:100]}") from exc

        raw_items: list[Any] = []
        if isinstance(data, list):
            raw_items = data
        elif isinstance(data, dict):
            if isinstance(data.get("data"), list):
                raw_items = data["data"]
            elif isinstance(data.get("models"), list):
                raw_items = data["models"]
            elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("models"), list):
                raw_items = data["data"]["models"]
            elif isinstance(data.get("list"), list):
                raw_items = data["list"]

        models_out: list[dict[str, Any]] = []
        seen = set()
        for item in raw_items:
            model_id = ""
            owned_by = ""
            if isinstance(item, str):
                model_id = item.strip()
            elif isinstance(item, dict):
                model_id = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
                owned_by = str(item.get("owned_by") or item.get("owner") or "").strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)

            m_lower = model_id.lower()
            if any(k in m_lower for k in ["seedream", "image", "dall-e", "midjourney", "flux", "stable-diffusion", "sd-", "sdxl", "cogview", "kolors"]):
                guessed_type = "image"
            elif any(k in m_lower for k in ["seedance", "video", "sora", "kling", "runway", "gen-2", "gen-3", "luma", "cogvideo", "hailuo", "minimax-video", "pika"]):
                guessed_type = "video"
            elif any(k in m_lower for k in ["audio", "tts", "voice", "speech", "whisper", "cosyvoice", "fish-speech", "chattts"]):
                guessed_type = "audio"
            else:
                guessed_type = "text"

            models_out.append({
                "id": model_id,
                "name": model_id,
                "owned_by": owned_by,
                "modelType": guessed_type,
            })

        if not models_out:
            raise StorageError(400, "接口已成功响应，但返回的模型列表为空")

        return models_out

    def _quota_status(self, storage: LocalStorage, query: dict[str, list[str]]) -> dict[str, Any]:
        account_id = (query.get("accountId") or [""])[0]
        record = self._quota_record(storage, account_id)
        return {"accountId": account_id, "date": self._today(), "generatedCount": record.get("generatedCount", 0),
                "dailyLimit": record.get("dailyLimit", 3), "exhausted": record.get("exhausted", False)}

    def _quota_today(self, storage: LocalStorage, query: dict[str, list[str]]) -> dict[str, Any]:
        return {"date": self._today(), "usage": [item for item in storage.list_documents("desktop_account_quota")
                                                if item.get("date") == self._today()]}

    def _quota_consume(self, storage: LocalStorage) -> dict[str, Any]:
        body = self._read_json()
        account_id = str(body.get("accountId") or "").strip()
        _safe_segment(account_id, "账号 ID")
        with storage._lock:
            record = self._quota_record(storage, account_id)
            try:
                limit = max(1, min(int(body.get("dailyLimit", record.get("dailyLimit", 3))), 99))
            except (ValueError, TypeError) as exc:
                raise StorageError(400, "dailyLimit 必须为整数") from exc
            record.update(generatedCount=int(record.get("generatedCount", 0)) + 1,
                          dailyLimit=limit, accountId=account_id, date=self._today())
            record["exhausted"] = record["generatedCount"] >= limit
            storage.save_document("desktop_account_quota", account_id, record,
                                  expected_revision=record.get("revision"))
        return record

    @staticmethod
    def _quota_record(storage: LocalStorage, account_id: str) -> dict[str, Any]:
        if not account_id:
            return {"generatedCount": 0, "dailyLimit": 3, "exhausted": False}
        try:
            record = storage.get_document("desktop_account_quota", account_id)
        except StorageError:
            return {"generatedCount": 0, "dailyLimit": 3, "exhausted": False}
        if record.get("date") != _Handler._today():
            return {"generatedCount": 0, "dailyLimit": int(record.get("dailyLimit", 3)), "exhausted": False,
                    "revision": record["revision"]}
        return record

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")


class LocalStorageServer:
    """在后台线程中运行本地存储 HTTP 服务。"""

    def __init__(self, root: Path, host: str = "127.0.0.1", port: int = 18081) -> None:
        self.storage = LocalStorage(root)
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is not None:
            return int(self._server.server_port)
        return self._port

    def start(self) -> None:
        handler = type("_BoundHandler", (_Handler,), {"storage": self.storage})
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        self._port = int(self._server.server_port)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="local-storage", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def available(self, timeout: float = 0.8) -> bool:
        import socket

        try:
            with socket.create_connection((self._host, self._port), timeout=timeout):
                return True
        except OSError:
            return False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="本地存储服务（Python 版）")
    parser.add_argument("--root", default=str(Path.home() / ".comic-drama" / "storage"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()

    server = LocalStorageServer(Path(args.root), args.host, args.port)
    server.start()
    print(f"local-storage listening on http://{args.host}:{args.port} (root={server.storage.root})")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()


from native_film import install as _install_native_film
_install_native_film(_Handler)


if __name__ == "__main__":
    main()
