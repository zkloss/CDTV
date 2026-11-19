# -*- coding: utf-8 -*-
"""huashu-motion (花叔商业宣传片) Bridge for CDTV General Video Workspace.

Provides Python API to:
1. Query available commercial launch templates (12 styles).
2. Initialize project scaffolds using `om new <dir> --template <template_id>`.
3. Launch local live-edit Studio (`om studio <dir>`).
4. Render 60fps commercial launch videos via headless Chrome + FFmpeg.
5. All background processes strictly enforce CREATE_NO_WINDOW + SW_HIDE + DEVNULL.
"""
from __future__ import annotations

import os
import sys
import json
import time
import shutil
import sqlite3
import subprocess
import threading
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

_lock = threading.Lock()
_studio_processes: Dict[str, subprocess.Popen] = {}
_render_processes: Dict[str, subprocess.Popen] = {}

TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "keynote-ui",
        "name": "Keynote 发布会 UI 快切",
        "tag": "发布会 / 暗黑质感 / 卡片弹跳 / 数字递增",
        "description": "暗黑发光背景，产品界面高光浮现，毛玻璃卡片弹性推入，核心指标数字跳动。",
        "use": "新产品与新功能发布、版本更新亮点、功能操作教程、关键业务指标展示",
        "duration": 25,
        "icon": "📱",
        "energy": "高能快切",
    },
    {
        "id": "object-3d",
        "name": "3D 空间立体产品展示",
        "tag": "3D摄影棚 / 立体空间 / 环绕运镜 / 旗舰质感",
        "description": "产品置于三维光影摄影棚，三维连续运镜环绕、低角度推近特写与立体Logo。",
        "use": "高端旗舰产品发布、Logo与硬件设备立体展示、强烈空间运镜与大片第一眼抓住眼球",
        "duration": 30,
        "icon": "✨",
        "energy": "旗舰电影感",
    },
    {
        "id": "ui-space",
        "name": "3D 界面层级与飞掠运镜",
        "tag": "界面拆解 / 空间悬浮 / 3D连续运镜",
        "description": "真实产品截图拆解为多层悬浮空间，3D摄像机穿梭飞掠、聚焦弹窗并平滑推至平面。",
        "use": "SaaS软件、移动App、UI交互设计展示、不落俗套的沉浸式界面巡礼",
        "duration": 30,
        "icon": "💻",
        "energy": "空间纵深",
    },
    {
        "id": "kinetic-type",
        "name": "动效大字排版与视觉冲击",
        "tag": "文字冲击 / 节奏踩点 / 核心观点",
        "description": "文字即主角，一拍一页，关键大字重磅撞入画面，荧光笔高亮核心结论，节奏紧凑。",
        "use": "观点输出、三大理由/三步骤、开场炸裂钩子、金句与数据定格",
        "duration": 18,
        "icon": "🔤",
        "energy": "节奏紧凑",
    },
    {
        "id": "vox-collage",
        "name": "Vox 杂志风剪贴画拼贴",
        "tag": "调查解说 / 剪贴画 / 红线关联 / 荧光笔标记",
        "description": "截图与便签贴在纸质桌面上，红线穿针引线串联证据，荧光笔圈出核心数字。",
        "use": "深度商业分析、新闻事件复盘、行业深度调研、带有截图证据链的解说片",
        "duration": 35,
        "icon": "📰",
        "energy": "深度纪实",
    },
    {
        "id": "finance-chart",
        "name": "金融走势与商业增长图表",
        "tag": "经济学人 / 数据图表 / K线走势 / 趋势推演",
        "description": "经济学人级高雅版式，坐标轴展开，数据柱与折线平滑攀升，关键转折点高光注释。",
        "use": "财报业绩汇报、市场份额增长、商业模式闭环、令观众截图分享的关键图表",
        "duration": 20,
        "icon": "📈",
        "energy": "严谨优雅",
    },
    {
        "id": "kurzgesagt",
        "name": "扁平宇宙与科学原理解构",
        "tag": "Kurzgesagt风 / 星球系统 / 层级推近",
        "description": "发光星球作为核心概念，周围环绕卫星节点，镜头层层钻入微观解析其内部机制。",
        "use": "复杂系统运作机制、宏观到微观层级、科技原理、温和理性科学解说",
        "duration": 30,
        "icon": "🪐",
        "energy": "宏观宇宙",
    },
    {
        "id": "math-3b1b",
        "name": "3B1B 科技原理与数学公式",
        "tag": "3Blue1Brown / 纯黑背景 / 公式演变 / 曲线变换",
        "description": "纯黑底色，优雅手写公式演变，函数曲线流动形变，色彩与符号高度映射。",
        "use": "算法机制解构、机器学习原理解析、数学物理公式推演、高精尖硬核技术解密",
        "duration": 25,
        "icon": "📐",
        "energy": "学术极简",
    },
    {
        "id": "whiteboard",
        "name": "极简思维白板手绘草图",
        "tag": "白板手绘 / 因果推导 / 涂鸦箭头",
        "description": "黑色白板笔伴随说话实时书写，涂鸦小图标与逻辑箭头相连，镜头拉远纵观全貌。",
        "use": "逻辑推理、底层原因剖析、因果链条拆解、清晰易懂的讲师解说",
        "duration": 25,
        "icon": "🖊️",
        "energy": "因果连贯",
    },
    {
        "id": "talking-head",
        "name": "口播动态花字与画中画包装",
        "tag": "口播包装 / 动态花字 / 强调角标 / 透明通道",
        "description": "专为口播视频打造的高清动效包装，花字、数字卡片与章节转场精准卡点词频。",
        "use": "真人/数字人口播包装、访谈Vlog花字、横竖屏短视频高级动态字幕与贴纸",
        "duration": 20,
        "icon": "🎙️",
        "energy": "吸睛点缀",
    },
    {
        "id": "storytime",
        "name": "趣味段子与小豆人短剧",
        "tag": "火柴豆人 / 对白气泡 / 反转幽默",
        "description": "萌系火柴豆人坐在房间说话，带对白气泡与电脑切屏，伴随滑稽定格与问号反转。",
        "use": "个人翻车日常、幽默第一人称故事、跟AI对话的搞笑脑洞段子",
        "duration": 20,
        "icon": "😄",
        "energy": "诙谐幽默",
    },
    {
        "id": "blank",
        "name": "极简自由定制底座",
        "tag": "极简起点 / 标题大字 / 自由拓展",
        "description": "轻量标准工程，包含大标题、大数字与尾屏卡片，适合自由写代码定制全新样式。",
        "use": "任何定制需求、极客代码编写、自定义品牌视觉设计",
        "duration": 15,
        "icon": "🛠️",
        "energy": "自由创作",
    },
]


def _get_skill_dir() -> Path:
    here = Path(__file__).resolve().parent
    for base in [here, here.parent, here / "_internal"]:
        candidate = base / "SKILL" / "huashu-motion"
        if (candidate / "cli" / "om.js").is_file():
            return candidate
    # Fallback to local
    return here / "SKILL" / "huashu-motion"


def _get_cli_path() -> Path:
    return _get_skill_dir() / "cli" / "om.js"


def _get_node_exe() -> str:
    found = shutil.which("node")
    if found:
        return found
    for cand in [Path(__file__).resolve().parent / "motion_runtime" / "node.exe", Path("C:/Program Files/nodejs/node.exe")]:
        if cand.is_file():
            return str(cand)
    return "node"


def _get_env_with_runtime() -> dict:
    env = os.environ.copy()
    here = Path(__file__).resolve().parent
    runtime_candidates = [
        here / "runtime",
        here.parent / "runtime",
        here / "_internal" / "runtime",
        here.parent / "CDTV" / "_internal" / "runtime",
    ]
    paths = []
    for rc in runtime_candidates:
        if rc.is_dir() and str(rc.resolve()) not in paths:
            paths.append(str(rc.resolve()))
    if paths:
        env["PATH"] = ";".join(paths) + ";" + env.get("PATH", "")
    return env


def _silent_kwargs() -> dict:
    kwargs = {}
    if sys.platform == "win32":
        CREATE_NO_WINDOW = 0x08000000
        STARTF_USESHOWWINDOW = 0x00000001
        SW_HIDE = 0
        kwargs["creationflags"] = CREATE_NO_WINDOW
        si = subprocess.STARTUPINFO()
        si.dwFlags |= STARTF_USESHOWWINDOW
        si.wShowWindow = SW_HIDE
        kwargs["startupinfo"] = si
    return kwargs


def get_huashu_status() -> dict:
    node_ok = False
    try:
        res = subprocess.run([_get_node_exe(), "-v"], capture_output=True, **_silent_kwargs())
        node_ok = (res.returncode == 0)
    except Exception:
        pass

    cli_path = _get_cli_path()
    cli_ok = cli_path.is_file()

    doctor_report = ""
    ready = False
    if node_ok and cli_ok:
        try:
            res = subprocess.run(
                [_get_node_exe(), str(cli_path), "doctor"],
                env=_get_env_with_runtime(),
                capture_output=True,
                **_silent_kwargs()
            )
            out = res.stdout.decode("utf-8", "ignore")
            doctor_report = out
            ready = (res.returncode == 0 and "Chrome" in out and "FFmpeg" in out)
        except Exception as e:
            doctor_report = str(e)

    return {
        "ready": ready,
        "node": node_ok,
        "cli": cli_ok,
        "version": "0.3.1",
        "doctor": doctor_report,
    }


def get_huashu_templates() -> list:
    return TEMPLATES


def get_huashu_project_dir(storage_dir: Path, project_id: str) -> Path:
    p_dir = storage_dir / "huashu_projects" / str(project_id)
    p_dir.mkdir(parents=True, exist_ok=True)
    return p_dir


def find_project_ai_video(storage_dir: Path, project_id: str) -> Path | None:
    """Find the authentic AI-generated video file that belongs strictly to project_id.
    Prevents cross-project contamination (e.g. accidentally loading stickman/doodle clips from other workspaces)."""
    db_path = storage_dir / "storage.db"
    if not db_path.is_file():
        return None

    video_file_ids = []
    try:
        conn = sqlite3.connect(str(db_path))
        c = conn.cursor()

        # 1. Check projects table document workflow directVideo/sceneVideo history
        row = c.execute("SELECT data_json FROM storage_document WHERE namespace='projects' AND object_id=?", (project_id,)).fetchone()
        if row:
            p_data = json.loads(row[0])
            wf = p_data.get("workflow", {})
            for mode in ["directVideo", "sceneVideo"]:
                m_obj = wf.get(mode, {})
                for h in m_obj.get("history", []):
                    fid = h.get("fileId")
                    url = h.get("url", "")
                    if fid:
                        video_file_ids.append(fid)
                    elif "/file/" in url:
                        parts = url.split("/file/")
                        if len(parts) > 1:
                            extracted = parts[1].split("/")[0]
                            if extracted:
                                video_file_ids.append(extracted)

        # 2. Check ai_video_results / ai_video_submissions specifically for this project_id
        for ns in ["ai_video_results", "ai_video_submissions"]:
            for r in c.execute(f"SELECT data_json FROM storage_document WHERE namespace='{ns}' AND data_json LIKE '%{project_id}%'").fetchall():
                try:
                    d = json.loads(r[0])
                    if d.get("projectId") == project_id:
                        for k in ["fileId", "videoFileId", "outputFileId"]:
                            if d.get(k):
                                video_file_ids.append(d[k])
                        url = d.get("url") or d.get("videoUrl") or ""
                        if "/file/" in url:
                            parts = url.split("/file/")
                            if len(parts) > 1:
                                extracted = parts[1].split("/")[0]
                                if extracted:
                                    video_file_ids.append(extracted)
                except Exception:
                    pass
        conn.close()
    except Exception:
        pass

    gen_dir = storage_dir / "files" / "generated-videos"
    for fid in video_file_ids:
        candidate_dir = gen_dir / fid
        if candidate_dir.is_dir():
            for f in candidate_dir.glob("*.mp4"):
                if f.is_file() and f.stat().st_size > 1000:
                    return f
            c_bin = candidate_dir / "content.bin"
            if c_bin.is_file() and c_bin.stat().st_size > 1000:
                return c_bin

    return None


def _smart_brand_injection(target_dir: Path, title: str, script_text: str, storage_dir: Path, project_id: str) -> None:
    """Dynamically customize the huashu project with project title, brand slogans and hero asset.
    Strictly enforces project isolation: NEVER borrow clips or doodles from other projects."""
    try:
        cli_path = _get_cli_path()
        node_exe = _get_node_exe()
        env = _get_env_with_runtime()

        clean_title = (title or "品牌商业发布").strip()
        sub = "传世沉淀 · 东方匠心"
        c1 = "核心工艺"
        c2 = "非凡气韵"
        accent = "#c5a059"

        combined = f"{title} {script_text}"
        is_maotai = ("茅台" in combined or "白酒" in combined or "酒" in combined)

        if is_maotai:
            clean_title = "贵州茅台 · 传世沉淀"
            sub = "东方酱香典范 · 百年匠心陈酿"
            c1 = "酱香传世"
            c2 = "飞天传世 琼浆玉液"
            accent = "#c5a059"
        elif script_text:
            lines = [l.strip() for l in script_text.splitlines() if l.strip() and not l.strip().startswith("#")]
            if lines:
                sub = lines[0][:24]

        # Prepare variable arguments for om set
        set_args = [
            f"title={clean_title}",
            f"subtitle={sub}",
            f"comment={c1}",
            f"reply={c2}",
            f"accent={accent}"
        ]

        if is_maotai:
            set_args.extend([
                "paper=#161412",
                "body=#28231d",
                "backdrop=#12100e",
                "card=#1e1b18",
                "ink=#f5eedc",
                "highlight=#c5a059",
                "statTint=#382f22",
                "name=贵州茅台",
                "nameTag=国酒典范",
                "role=百年酱香典范 · 传世沉淀",
                "corner=东方国酿",
                "chapter=百年沉淀 · 东方气韵",
                "chapterNo=MAOTAI",
                'stats=[{"value":100,"suffix":"年","label":"东方酱香匠心传世","at":2.5}]',
                'keywords=[{"text":"东方酱香 · 百年陈酿","at":5.5}]'
            ])

        # Assets directory
        assets_dir = target_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        studio_jpg = assets_dir / "studio.jpg"
        target_vid = assets_dir / "talk.mp4"

        # Strictly find AI video belonging exclusively to this project_id
        project_ai_video = find_project_ai_video(storage_dir, project_id)
        if project_ai_video and project_ai_video.is_file():
            shutil.copy2(project_ai_video, target_vid)
            set_args.append("talk=assets/talk.mp4")
            set_args.append("screen=assets/studio.jpg")

            # Extract crisp frame 00:00:03 as studio.jpg for static/3D templates
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                subprocess.run(
                    [ffmpeg, "-y", "-ss", "00:00:03", "-i", str(project_ai_video), "-frames:v", "1", "-update", "1", str(studio_jpg)],
                    capture_output=True,
                    **_silent_kwargs()
                )
        else:
            # If no AI video for this project, purge any foreign talk.mp4 that might have been copied
            if target_vid.is_file():
                try:
                    target_vid.unlink()
                except Exception:
                    pass

        # Filter variables to only those declared in this template
        html_file = target_dir / "index.html"
        supported_ids = set()
        if html_file.is_file():
            try:
                html_txt = html_file.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"data-composition-variables=['\"](.*?)['\"]", html_txt, re.DOTALL)
                if m:
                    raw_v = m.group(1).replace("&quot;", '"')
                    supported_ids = {v.get("id") for v in json.loads(raw_v) if isinstance(v, dict) and "id" in v}
            except Exception:
                pass

        valid_set_args = []
        for arg in set_args:
            k = arg.split("=", 1)[0]
            if not supported_ids or k in supported_ids:
                valid_set_args.append(arg)

        # Apply variables via om set
        if valid_set_args:
            set_cmd = [node_exe, str(cli_path), "set"] + valid_set_args + [str(target_dir)]
            subprocess.run(set_cmd, env=env, capture_output=True, **_silent_kwargs())

    except Exception as e:
        logger.warning("Smart brand injection warning: %s", e)

def init_huashu_project(
    storage_dir: Path,
    project_id: str,
    template_id: str = "keynote-ui",
    title: str = "",
    script_text: str = "",
    force: bool = False
) -> dict:
    target_dir = get_huashu_project_dir(storage_dir, project_id)
    cli_path = _get_cli_path()
    node_exe = _get_node_exe()
    env = _get_env_with_runtime()

    if force and target_dir.exists():
        out_dir = target_dir / "out"
        for item in target_dir.iterdir():
            if item.name != "out":
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    try:
                        item.unlink()
                    except Exception:
                        pass

    # If project doesn't have index.html, initialize it with om new
    if not (target_dir / "index.html").is_file():
        cmd = [node_exe, str(cli_path), "new", str(target_dir), "--template", template_id]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", **_silent_kwargs())
        if res.returncode != 0:
            raise RuntimeError(f"初始化宣传片模版失败: {res.stderr or res.stdout}")
        _smart_brand_injection(target_dir, title, script_text, storage_dir, project_id)
    else:
        # Re-apply brand injection in case title or script was updated
        _smart_brand_injection(target_dir, title, script_text, storage_dir, project_id)

    # Generate offline sound
    try:
        subprocess.run([node_exe, str(cli_path), "sound", str(target_dir)], env=env, capture_output=True, **_silent_kwargs())
    except Exception:
        pass

    return {
        "projectId": project_id,
        "templateId": template_id,
        "path": str(target_dir),
        "hasIndex": (target_dir / "index.html").is_file(),
        "hasSound": (target_dir / "assets" / "sound.wav").is_file(),
    }


def open_huashu_studio(storage_dir: Path, project_id: str) -> dict:
    target_dir = get_huashu_project_dir(storage_dir, project_id)
    cli_path = _get_cli_path()
    node_exe = _get_node_exe()
    env = _get_env_with_runtime()

    if not (target_dir / "index.html").is_file():
        init_huashu_project(storage_dir, project_id)

    with _lock:
        existing = _studio_processes.get(project_id)
        if existing and existing.poll() is None:
            # Already running, just open browser
            url = f"http://127.0.0.1:4173/studio"
            webbrowser.open(url)
            return {"status": "already_running", "url": url}

        # Start om studio in background
        cmd = [node_exe, str(cli_path), "studio", str(target_dir), "--no-open"]
        p = subprocess.Popen(
            cmd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            **_silent_kwargs()
        )
        _studio_processes[project_id] = p

    # Wait briefly for server to bind
    time.sleep(1.2)
    url = f"http://127.0.0.1:4173/studio"
    webbrowser.open(url)
    return {"status": "started", "url": url}


def render_huashu_project(storage_dir: Path, project_id: str, blur: bool = False, template_id: str = "keynote-ui") -> dict:
    target_dir = get_huashu_project_dir(storage_dir, project_id)
    cli_path = _get_cli_path()
    node_exe = _get_node_exe()
    env = _get_env_with_runtime()

    if not (target_dir / "index.html").is_file():
        init_huashu_project(storage_dir, project_id, template_id=template_id or "keynote-ui")
    elif template_id:
        try:
            txt = (target_dir / "index.html").read_text(encoding="utf-8", errors="replace")
            expected_sig = f"huashu-motion · {template_id}"
            expected_sig2 = f"huashu-motion · {template_id.replace('-', ' ')}"
            if expected_sig not in txt and expected_sig2 not in txt:
                init_huashu_project(storage_dir, project_id, template_id=template_id, force=True)
        except Exception:
            pass

    # Refresh sound before render
    subprocess.run(
        [node_exe, str(cli_path), "sound", str(target_dir)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_silent_kwargs()
    )

    # Build render cmd
    cmd = [node_exe, str(cli_path), "render", str(target_dir), "--silent"]
    assets_dir = target_dir / "assets"
    if assets_dir.exists() and any(assets_dir.glob("*.mp4")):
        cmd.extend(["--video", "seek"])
    if blur:
        cmd.append("--blur")

    p = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_silent_kwargs()
    )

    out_dir = target_dir / "out"
    mp4_files = sorted(out_dir.glob("*.mp4"), key=os.path.getmtime, reverse=True) if out_dir.is_dir() else []
    if not mp4_files:
        err_msg = (p.stderr or p.stdout or "").strip()
        raise RuntimeError(f"渲染宣传片失败: {err_msg or f'未生成成片 (退出码 {p.returncode})'}")

    latest_mp4 = mp4_files[0]
    return {
        "status": "succeeded",
        "filePath": str(latest_mp4),
        "fileName": latest_mp4.name,
        "size": latest_mp4.stat().st_size,
        "videoUrl": f"/api/huashu/video?projectId={project_id}&file={latest_mp4.name}",
    }


def get_huashu_project_info(storage_dir: Path, project_id: str) -> dict:
    target_dir = get_huashu_project_dir(storage_dir, project_id)
    out_dir = target_dir / "out"
    mp4_files = sorted(out_dir.glob("*.mp4"), key=os.path.getmtime, reverse=True) if out_dir.is_dir() else []
    latest = mp4_files[0] if mp4_files else None

    return {
        "projectId": project_id,
        "path": str(target_dir),
        "isInitialized": (target_dir / "index.html").is_file(),
        "hasRender": latest is not None,
        "latestVideo": str(latest) if latest else None,
        "latestVideoName": latest.name if latest else None,
        "latestVideoSize": latest.stat().st_size if latest else 0,
        "videoUrl": f"/api/huashu/video?projectId={project_id}&file={latest.name}" if latest else "",
        "modifiedTime": target_dir.stat().st_mtime if target_dir.exists() else 0,
    }
