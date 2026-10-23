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

import ast
import base64
import binascii
import hashlib
import io
import json
import mimetypes
import re
import sqlite3
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
            models = self._fetch_remote_models(api_url, api_key)
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
        if path == "/ai/creation-data" and method == "POST":
            self._ok(self._generate_creation_data(storage, self._read_json()))
            return
        if path == "/ai/script" and method == "POST":
            self._ok(self._generate_script(storage, self._read_json()))
            return
        if path == "/ai/video" and method == "POST":
            self._ok(self._submit_video(storage, self._read_json()))
            return
        video_task = re.fullmatch(r"/ai/video/([^/]+)", path)
        if video_task and method == "GET":
            self._ok(self._poll_video(storage, unquote(video_task.group(1)), (query.get("model") or [""])[0]))
            return

        # 未识别的 AI 接口不能误报为用户没有保存配置。
        if path.startswith("/ai/"):
            self._read_body()
            self._fail("当前本地服务尚未接入此 AI 接口")
            return

        raise StorageError(404, "接口不存在")

    # ---------- 辅助 ----------

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
            request_headers.setdefault("Authorization", f"Bearer {api_key}")
        try:
            with httpx.Client(timeout=httpx.Timeout(req_timeout, connect=15),
                              trust_env=trust_env) as client:
                response = client.request("POST" if body is not None else "GET", endpoint, json=body,
                                          headers=request_headers)
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
                    response = client.request("POST", endpoint, json=compatible_body,
                                              headers=request_headers)
            if response.status_code == 413:
                raise StorageError(413, f"{operation}失败（HTTP 413 请求体过大）：发送的图片或参数超出了服务商单次限制，已自动启动自适应压缩")
            try:
                result = response.json()
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
    def _parse_creation_json(text: str) -> dict[str, Any]:
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

        has_assets = any(document.get(key) for key in ("characters", "roles", "people", "scenes", "props", "items", "audio", "audios"))
        consistency = document.get("consistency")
        if isinstance(consistency, dict):
            has_assets = has_assets or any(consistency.get(key) for key in ("characters", "roles", "people", "scenes", "props", "items", "audio", "audios"))
        if not has_assets and not document.get("shots"):
            if not document.get("consistency") and isinstance(document.get("assets"), dict):
                document["consistency"] = document["assets"]
            else:
                raise StorageError(502, "文本模型返回的数据既没有资产也没有分镜")
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
        system = """你是 CDTV 内置的短剧工业级编剧总控引擎（遵循漫剧老李 V7.4.20 sd-script-engine 标准）。
请把用户提供的章节原文或创作要求改编为可直接进入 AI 资产、分镜和视频制作流程的高质量中文短剧剧本。
只输出剧本正文，不要 Markdown 代码围栏，不要解释、前言、总结或分析草稿。

遵循漫剧老李 V7.4.20 工业级编剧门禁：
1. 【多集/多幕智能分流与继承】：
   - 若用户输入包含多集（如第1集~第5集）或小说长段落，必须智能识别分集边界，使用【第X集：集名】标明各集，确保每集拥有承前启后、张弛有度的独立戏剧冲突与高潮；
   - 保持各集间人物身份、外貌识别点、核心世界观完全统一；
2. 【严格分离对白与旁白 · 智能过滤小说冗余（极重要）】：
   - 默认短剧/漫剧赛道：全片以【角色对白、微表情神态、视线流转、肢体动作与现场环境视听】为绝对核心！
   - 彻底过滤并转化小说中的作者内心戏、旁白说明、背景交代或网站无关水词：必须将抽象的心理描写转化为具象可见的微动作、神态变化或角色的台词！
   - 若用户指定或倾向“无旁白”，则严禁输出任何口播旁白（VO），所有信息必须 100% 通过角色对白与表演自然交代；
3. 【对白语气位与 FACS 微表情落地（C16规范）】：
   - 所有角色对白必须严格标注情绪与语气位，格式固定为：角色名（情绪/语气位）："台词内容"；
   - 台词语速控制在每秒 3.5~5 字，长对白必须插入动作顿挫或视线转移；
4. 【动作桥接与场面调度落地】：
   - 必须明确人物身体朝向、空间站位、左右手细微动作与微表情（如皱眉、目光低垂、嘴角收紧等）；
   - 跨场景或姿态变化时必须交代桥接动作，严禁瞬移跳跃；
5. 【充足分镜体量保障】：
   - 单集体量充实饱满，严禁草率压缩收尾，必须足够支撑提炼 12~18 个高质量连续分镜。"""
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
                "temperature": 0.35, "max_tokens": script_max_tokens, "stream": False,
            }
            headers = {}
        result = self._request_ai_json(model, endpoint, "剧本生成", payload, headers)
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
        system = """你是 CDTV 创作数据编排器（融合漫剧老李 V7.4.20 sd-asset-engine、sd-storyboard-engine、sd-feed-engine 全套规范）。
请把用户提供的剧本/故事提炼成 CDTV 工业级结构化创作数据 JSON。
必须只输出合法 JSON 对象，不要 Markdown 代码围栏，不要解释，不要在 JSON 后追加任何文字。不要输出 null 或模板占位符。
必须使用这些顶级字段：schema_version（固定为 2.7）、title、style、consistency、shots。

1. consistency 包含 characters、scenes、props、audio、asset_wirelist 五个数组：
   - characters: 每个元素包含 id（如 char_luming）、name、appearance（开头带美术风格关键词，紧凑描写核心发型服装与面部特征识别点，控制在 50~80 字以内）；
   - scenes: 每个元素包含 id（如 scene_mudhouse）、name、environment（开头带美术风格关键词，精炼描写空间几何与光影，控制在 40~60 字以内）；
   - props: 核心道具数组，每个元素包含 id（如 prop_amulet）、name、appearance（材质、外观特征与颜色）；
   - audio: 提炼本集核心台词配音与关键拟声音效（针对视频模型声音敏感度不足进行强感知建模）：
     * 配音（id 固定 aud_vo_ 开头，category 为 "voice"，voice 填推荐音色代号如 "longshu_v2"）：prompt 严格遵循【六维强感知音频公式】：职业身份+性别+年龄+音高+声音质地+发声特点+原本台词与语调情感（例如：“照相馆老摄影师，男，62岁，低沉中音，沙哑微带沧桑颗粒感，沉缓叹息：‘配。最后一炉。’”）；
     * 音效（id 固定 aud_sfx_ 开头，category 为 "sfx"）：prompt 包含【声源类型+空间质感+力度衰减+环境音效描述】；
   - asset_wirelist: 【V7.4.20 素材接线单】严格按 M1（编号占位）模式，列出图号映射：如 [{"slot": "图1", "asset_id": "char_luming", "name": "陆明", "type": "character", "action": "人物锚定"}, {"slot": "图2", "asset_id": "scene_mudhouse", "name": "破旧泥屋", "type": "scene", "action": "环境底图"}]；

2. shots 数组（极重要门禁，必须 100% 完整覆盖本集全部镜头，绝不偷工减料）：
   - 【严禁偷懒截断/必须完整提取全部镜头】：若剧本中已有明确镜头标号（如【镜1-1】、【镜1-2】...【镜头1】、【分镜1】...），你必须 1:1 完整提取剧本中的全部镜头，镜头数量必须与剧本严格完全一致，绝不允许中途截断、合并或漏戏！若未标注明确镜号，根据剧情自然节奏提炼 12~18 个高精连续分镜，单镜 8~10 秒。
   - 每个 shot 必须包含：
     * id: 镜号（如 shot_01、shot_02...）；
     * title: 镜头标题（如 镜1-1 特写老陈神色）；
     * duration_s: 单镜时长（8~10 秒）；
     * scene_id: 对应的 scene id；
     * references: 引用的 asset id 列表（如 ["char_luming", "scene_mudhouse"]）；
     * wirelist: 当前镜头素材接线单（标注当前镜挂载哪几张图，如 [{"slot": "图1", "name": "陆明", "action": "人物锚定"}]）；
     * visual: 精炼画面内容、角色构图与动作（30~50 字）；
     * camera: 专业运镜（如推镜头、特写、跟随跟拍、俯仰视角等，六要素清晰）；
     * dialogue: 对白数组（格式：角色名（语气）："台词"，若无对白留空数组 []）；
     * audio_prompt: 【六维强感知音频提示词】专为声音不敏感视频模型设计的发声蓝图：【职业身份+性别+年龄+音高+声音质地+发声特点+原本台词/音效描述】（例如：【赵小满】年轻女学徒，女，19岁，清脆中高音，轻盈紧绷，急促喘息：“师父…”；【陈守一】老摄影师，男，62岁，低沉中音，沙哑微带沧桑颗粒感，沉缓叹息：“知道了。”；环境配音包含室内挂钟沉闷滴答与窗外雨声。若无对白则填写关键拟音环境音）；
     * video_prompt: 【漫剧老李 V7.4.20 七段式可投喂提示词】。

3. 【V7.4.20 七段式 video_prompt 组装规范（核心）】：
   - 每个分镜的 video_prompt 必须采用精炼七段式纯净版组装：
     【画风风格】+【场景资产】+【主体角色（挂载 图N 锚定）】+【站位朝向与空间关系】+【动作过程与微表情发酵】+【对白/音效简述（融合角色声音质地与发声特征，如：老摄影师沙哑沧桑低沉应答，背景伴随雨声与挂钟滴答声）】+【画面锁闭项（电影质感、4K、无水印文字）】。
   - 单主体聚焦（C20），清洗掉所有非画面的工作流术语（严禁出现“点位A”、“流程节点”等）；
   - 素材形态遵循 M1 契约：直接使用「图1」、「图2」等编号占位，严禁向用户索要图片；
   - 保持全片同一人物/场景/道具始终复用同一 ID，确保一致性。全词紧凑精悍（70~100 字），确保一口气输出完整闭合的合法 JSON！"""
        user = f"""项目标题：{title or '短剧第一集'}

创作需求与剧本内容：
{prompt}

请直接输出紧凑完整的 JSON 对象。"""
        creation_max_tokens = int(model.get("maxTokens") or 16000)
        if model.get("contextWindow") and not model.get("maxTokens"):
            creation_max_tokens = min(32000, max(16000, int(model["contextWindow"] // 4)))
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
                "temperature": 0.2, "max_tokens": creation_max_tokens, "stream": False,
            }
            headers = {}
        result = self._request_ai_json(model, endpoint, "创作数据生成", payload, headers, timeout=600.0)
        text = self._chat_result_text(result)
        document = self._parse_creation_json(text)
        return {
            "document": document,
            "text": json.dumps(document, ensure_ascii=False, indent=2),
            "model": model.get("modelName", ""),
        }

    @staticmethod
    def _video_submit_candidates(api_url: str) -> list[str]:
        raw = api_url.strip().rstrip("/")
        parsed = urlparse(raw)
        path = parsed.path.rstrip("/")
        base = f"{parsed.scheme}://{parsed.netloc}"
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

    def _video_model(self, storage: LocalStorage, selected: Any) -> dict[str, Any]:
        return self._resolve_ai_model(storage, 'video', selected)

    def _submit_video(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._video_model(storage, body.get("model"))
        content = body.get("content") or []
        if not isinstance(content, list) or not content:
            raise StorageError(400, "视频生成 content 不能为空")
            
        prompt_text = ""
        image_urls = []
        optimized_content = []
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
                        item_copy["image_url"] = {"url": opt_url}
                        image_urls.append(opt_url)
                else:
                    url_val = item.get("image_url")
                    if url_val:
                        opt_url = self._optimize_image_for_api(str(url_val), storage=storage)
                        item_copy["image_url"] = opt_url
                        image_urls.append(opt_url)
            elif item.get("type") == "image":
                url_val = item.get("url") or item.get("image")
                if url_val:
                    opt_url = self._optimize_image_for_api(str(url_val), storage=storage)
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

        safe_prompt = re.sub(r"真人写实年代复古摄影|真人写实年代复古胶片质感|真人写实|真人实拍|真人摄影|真人出镜|真实人物|真人", "影视写实年代电影质感", prompt_text.strip())
        safe_prompt = re.sub(r'[{｛]{2}[^{}]+[}｝]{2}', '', safe_prompt)

        payload = {
            "model": model["modelName"],
            "prompt": safe_prompt,
            "content": optimized_content,
            "images": image_urls,
            "image": image_urls[0] if image_urls else "",
            "ratio": ratio,
            "aspect_ratio": ratio,
            "duration": duration,
            "generate_audio": generate_audio,
            "resolution": str(body.get("resolution") or "720p").lower(),
            "watermark": False,
        }
        if "seed" in body and body["seed"] is not None:
            payload["seed"] = body["seed"]
            
        candidates = self._video_submit_candidates(str(model.get("apiUrl") or ""))
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
                    for extra_k in ["images", "image", "aspect_ratio", "generate_audio", "prompt", "resolution", "watermark", "seed"]:
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
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("id") or
            (result.get("data") if isinstance(result.get("data"), dict) else {}).get("task_id") or
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
                            stored = storage.save_file("generated-videos", response.content, f"{task_id}.mp4", mime)
                            result["video_url"] = self._legacy_file(stored)["url"]
            except Exception:
                pass
            result["status"] = "succeeded"
            storage.save_document("ai_video_results", cache_id, {"result": result}, expected_revision=None)

        return {
            **result,
            "taskId": task_id,
            "status": result.get("status") or result.get("state") or "queued",
            "endpoint": successful_endpoint,
        }

    def _poll_video(self, storage: LocalStorage, task_id: str, selected: str) -> dict[str, Any]:
        model = self._video_model(storage, selected)
        _safe_segment(task_id, "任务 ID")
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
        result["status"] = status
        
        if status not in {"succeeded", "completed", "done", "success"}:
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
            data.get("url")
        )
        if not video_url and isinstance(result.get("data"), list) and result["data"]:
            first = result["data"][0]
            if isinstance(first, dict):
                video_url = first.get("url") or first.get("video_url")
                
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
                stored = storage.save_file("generated-videos", response.content, f"{task_id}.mp4", mime)
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
        headers = {"Authorization": f"Bearer {api_key}"}
        # Loopback test/provider endpoints must not pass through system proxies.
        trust_env = urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}
        try:
            with httpx.Client(timeout=httpx.Timeout(300, connect=15), trust_env=trust_env) as client:
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
    def _fetch_remote_models(api_url: str, api_key: str = "") -> list[dict[str, Any]]:
        clean_url = str(api_url or "").strip().rstrip("/")
        if not clean_url:
            raise StorageError(400, "请输入 API 地址")
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "http://" + clean_url

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CDTV/1.0",
            "Accept": "application/json, text/plain, */*",
        }
        clean_key = str(api_key or "").strip()
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
        return self._port

    def start(self) -> None:
        handler = type("_BoundHandler", (_Handler,), {"storage": self.storage})
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
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


if __name__ == "__main__":
    main()
